"""ROS 2 plugin for demonstration-driven soft-task weighting."""

from copy import deepcopy

from ltl_automaton_msgs.msg import LTLState, LTLStateArray, LTLStateRuns
from ltl_automaton_planner_core.ltl_tools.discrete_plan import (
    dijkstra_plan_networkX,
)
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool

from .trap_detection import flatten_state_dimensions


class IRLPlugin:
    """Record Product runs, learn beta, and replan transactionally."""

    def __init__(self, ltl_planner, args=None):
        args = args or {}
        self.ltl_planner = ltl_planner
        self.max_run_buffer_size = int(args.get("max_run_buffer_size", 100))
        if self.max_run_buffer_size <= 0:
            raise ValueError("max_run_buffer_size must be positive.")
        self.node = None
        self.possible_runs = set()
        self.learning_trigger = False
        self.publisher = None
        self.subscription = None

    def set_node(self, node):
        """Attach the ROS 2 planner node hosting this plugin."""
        self.node = node

    def init(self):
        """Initialize run histories from the current Product belief."""
        if self.node is None:
            raise RuntimeError("IRLPlugin requires set_node(node).")
        self._reset_possible_runs()
        self.node.get_logger().info(
            "IRL plugin initialized with a maximum run buffer of "
            f"{self.max_run_buffer_size} states."
        )

    def set_sub_and_pub(self):
        """Create the learning trigger and debug run interfaces."""
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.publisher = self.node.create_publisher(
            LTLStateRuns,
            "possible_runs",
            qos,
        )
        self.subscription = self.node.create_subscription(
            Bool,
            "irl_trigger",
            self.learning_trigger_callback,
            10,
        )

    def run_at_ts_update(self, ts_state):
        """Extend teaching histories or track the current Product belief."""
        if not self.learning_trigger:
            self._reset_possible_runs()
            return
        self.possible_runs = self.update_possible_runs(
            self.possible_runs,
            ts_state,
        )
        state_count = sum(len(run) for run in self.possible_runs)
        if state_count == 0:
            self.node.get_logger().warning(
                "IRL plugin has no Product run consistent with the TS update."
            )
            return
        if state_count > self.max_run_buffer_size:
            self.node.get_logger().warning(
                "IRL run buffer limit reached; learning and replanning."
            )
            self._learn_and_replan()
            self.learning_trigger = False
            self._reset_possible_runs()
            return
        self.publish_possible_runs()

    def learning_trigger_callback(self, message):
        """Start recording on a rising edge and learn on a falling edge."""
        requested = bool(message.data)
        if requested and not self.learning_trigger:
            self.learning_trigger = True
            self._reset_possible_runs()
            self.node.get_logger().info("IRL knowledge acquisition started.")
            return
        if not requested and self.learning_trigger:
            self.learning_trigger = False
            self._learn_and_replan()
            self._reset_possible_runs()

    def _reset_possible_runs(self):
        product = self.ltl_planner.product
        current_states = getattr(product, "possible_states", set())
        if not current_states:
            current_states = product.graph.get("initial", set())
        self.possible_runs = {(state,) for state in current_states}

    def update_possible_runs(self, previous_runs, ts_state):
        """Extend every history with successors matching a TS observation."""
        updated_runs = set()
        for run in previous_runs:
            for successor in self.ltl_planner.product.successors(run[-1]):
                if successor[0] == ts_state:
                    updated_runs.add(run + (successor,))
        return updated_runs

    def publish_possible_runs(self):
        """Publish recorded Product histories using the existing message API."""
        message = LTLStateRuns()
        raw_dimensions = self.ltl_planner.product.graph["ts"].graph[
            "ts_state_format"
        ]
        dimensions = flatten_state_dimensions(raw_dimensions)
        for run in sorted(self.possible_runs, key=repr):
            run_message = LTLStateArray()
            for product_state in run:
                state_message = LTLState()
                ts_state = product_state[0]
                if isinstance(ts_state, tuple):
                    state_message.ts_state.states = [
                        str(value) for value in ts_state
                    ]
                else:
                    state_message.ts_state.states = [str(ts_state)]
                state_message.ts_state.state_dimension_names = dimensions
                state_message.buchi_state = str(product_state[1])
                run_message.ltl_states.append(state_message)
            message.runs.append(run_message)
        self.publisher.publish(message)

    def compute_path_cost(self, path):
        """Return transition and soft-task cost accumulated on a path."""
        transition_cost = 0.0
        soft_cost = 0.0
        product = self.ltl_planner.product
        for source, target in zip(path, path[1:]):
            edge = product[source][target]
            transition_cost += edge["transition_cost"]
            soft_cost += edge["soft_task_dist"]
        return transition_cost, soft_cost

    def select_least_violating_run(self, possible_runs):
        """Select the teaching run with the smallest soft-task distance."""
        if not possible_runs:
            raise ValueError("Cannot learn beta from an empty run set.")
        return min(
            possible_runs,
            key=lambda path: self.compute_path_cost(path)[1],
        )

    def _margin_suffix(self, optimal_path, beta):
        product = deepcopy(self.ltl_planner.product)
        product.update_beta(beta)
        optimal_edges = set(zip(optimal_path, optimal_path[1:]))
        for source, target in product.edges():
            product[source][target]["weight"] += 1.0
            if (source, target) in optimal_edges:
                product[source][target]["weight"] -= 1.0
        run, _ = dijkstra_plan_networkX(product, self.ltl_planner.gamma)
        if run is None:
            raise RuntimeError("IRL margin planning found no accepting run.")
        return tuple(run.suffix)

    @staticmethod
    def _path_match(first, second):
        return sum(left == right for left, right in zip(first, second))

    def learn_beta(self, possible_runs):
        """Learn a non-negative beta with the legacy margin objective."""
        optimal_path = self.select_least_violating_run(possible_runs)
        optimal_soft_cost = self.compute_path_cost(optimal_path)[1]
        beta = float(self.ltl_planner.beta)
        beta_sequence = []
        match_scores = []
        for iteration in range(20):
            marginal_path = self._margin_suffix(optimal_path, beta)
            marginal_soft_cost = self.compute_path_cost(marginal_path)[1]
            gradient = optimal_soft_cost - marginal_soft_cost
            step = 1.0 if iteration < 10 else 1.0 / (iteration + 1)
            updated_beta = max(0.0, beta - step * gradient)
            beta_sequence.append(updated_beta)
            match_scores.append(self._path_match(optimal_path, marginal_path))
            if abs(updated_beta - beta) <= 0.3:
                beta = updated_beta
                break
            beta = updated_beta
        return beta, beta_sequence, match_scores

    def _restore_beta(self, beta):
        self.ltl_planner.beta = beta
        if self.ltl_planner.product is not None:
            self.ltl_planner.product.update_beta(beta)

    def _learn_and_replan(self):
        if not self.possible_runs:
            self.node.get_logger().warning(
                "IRL learning skipped because no teaching runs were recorded."
            )
            return False
        old_beta = float(self.ltl_planner.beta)
        try:
            learned_beta, beta_sequence, match_scores = self.learn_beta(
                self.possible_runs
            )
            self.ltl_planner.beta = learned_beta
            replanned = self.ltl_planner.replan_task(
                self.ltl_planner.hard_spec,
                self.ltl_planner.soft_spec,
                self.ltl_planner.curr_ts_state,
            )
        except Exception as error:
            self._restore_beta(old_beta)
            self.node.get_logger().error(f"IRL learning failed: {error}")
            return False
        if not replanned:
            self._restore_beta(old_beta)
            self.node.get_logger().warning(
                "IRL replanning failed; restored the previous beta."
            )
            return False
        self.node.get_logger().info(
            f"IRL updated beta from {old_beta} to {learned_beta}; "
            f"sequence={beta_sequence}, matches={match_scores}."
        )
        self.node.refresh_planner_outputs()
        return True
