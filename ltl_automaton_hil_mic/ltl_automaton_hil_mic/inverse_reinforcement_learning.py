"""Optional demonstration recording for transactional beta learning."""

from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool

from ltl_automaton_msgs.msg import LTLState, LTLStateArray, LTLStateRuns, PlannerStatus

from .trap_detection import flatten_state_dimensions


def _state_values(state):
    if isinstance(state, (tuple, list)):
        return [value for part in state for value in _state_values(part)]
    return [str(state)]


class IRLPlugin:
    """Record one generation's teaching runs and request isolated learning."""

    def __init__(self, ltl_planner, args=None):
        args = args or {}
        self.max_run_buffer_size = args.get("max_run_buffer_size", 100)
        if (
            isinstance(self.max_run_buffer_size, bool)
            or not isinstance(self.max_run_buffer_size, int)
            or self.max_run_buffer_size <= 0
        ):
            raise ValueError("max_run_buffer_size must be a positive integer.")
        self._initial_planner = ltl_planner
        self.node = None
        self.possible_runs = set()
        self.learning_trigger = False
        self._recording_identity = None
        self.publisher = None
        self.subscription = None

    @property
    def ltl_planner(self):
        """Read the host's current committed planner after replacement."""
        return getattr(self.node, "ltl_planner", self._initial_planner)

    def set_node(self, node):
        """Attach the ROS 2 planner host."""
        self.node = node

    def init(self):
        """Initialize teaching from current execution belief."""
        if self.node is None or not callable(getattr(self.node, "start_irl_replan", None)):
            raise RuntimeError("IRLPlugin requires a transactional planner host.")
        self._sync_authority()

    def set_sub_and_pub(self):
        """Preserve the original trigger and diagnostic run topics."""
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.publisher = self.node.create_publisher(LTLStateRuns, "possible_runs", qos)
        self.subscription = self.node.create_subscription(
            Bool, "irl_trigger", self.learning_trigger_callback, 10,
        )

    def _sync_authority(self):
        identity = (self.node._planner_instance_id, self.node._planning_generation)
        if identity != self._recording_identity:
            self.learning_trigger = False
            self._recording_identity = identity
            self._reset_possible_runs()
            return True
        return False

    def _reset_possible_runs(self):
        product = getattr(self.ltl_planner, "product", None)
        current = getattr(self.ltl_planner, "curr_ts_state", None)
        states = getattr(product, "possible_states", set())
        self.possible_runs = {(state,) for state in states if state[0] == current}

    def learning_trigger_callback(self, message):
        """Start recording on True and request learning on a falling edge."""
        self._sync_authority()
        requested = bool(message.data)
        if requested and not self.learning_trigger:
            if self.node._planner_state != PlannerStatus.ACTIVE:
                self.node.get_logger().warning("IRL recording requires an active plan.")
                return
            self._reset_possible_runs()
            if not self.possible_runs:
                self.node.get_logger().warning("IRL has no current Product belief to record.")
                return
            self.learning_trigger = True
            self.node.get_logger().info("IRL teaching started.")
        elif not requested and self.learning_trigger:
            self.learning_trigger = False
            self._learn_and_replan()
            self._reset_possible_runs()

    def update_possible_runs(self, previous_runs, ts_state):
        """Extend teaching paths with actual Product successors."""
        product = self.ltl_planner.product
        successors_by_endpoint = {}
        possible_runs = set()
        for run in previous_runs:
            if not run or run[-1] not in product:
                continue
            endpoint = run[-1]
            if endpoint not in successors_by_endpoint:
                successors_by_endpoint[endpoint] = tuple(
                    successor
                    for successor in product.successors(endpoint)
                    if successor[0] == ts_state
                )
            for successor in successors_by_endpoint[endpoint]:
                possible_runs.add(run + (successor,))
        return possible_runs

    def run_at_ts_update(self, ts_state):
        """Record accepted TS feedback without changing active planning state."""
        if self._sync_authority() or not self.learning_trigger:
            self._reset_possible_runs()
            return
        self.possible_runs = self.update_possible_runs(self.possible_runs, ts_state)
        if not self.possible_runs:
            self.node.get_logger().warning("IRL teaching has no consistent Product path.")
            return
        self.publish_possible_runs()
        if sum(len(run) for run in self.possible_runs) > self.max_run_buffer_size:
            self.learning_trigger = False
            self._learn_and_replan()
            self._reset_possible_runs()

    def _learn_and_replan(self):
        accepted = self.node.start_irl_replan(self.possible_runs, self._recording_identity)
        if not accepted:
            self.node.get_logger().warning("IRL learning request was not accepted.")
        return accepted

    def publish_possible_runs(self):
        """Publish diagnostic teaching paths using the existing message schema."""
        dimensions = flatten_state_dimensions(
            self.ltl_planner.product.graph["ts"].graph["ts_state_format"],
        )
        message = LTLStateRuns()
        for run in sorted(self.possible_runs, key=repr):
            run_message = LTLStateArray()
            for product_state in run:
                state = LTLState()
                state.ts_state.states = _state_values(product_state[0])
                state.ts_state.state_dimension_names = dimensions
                state.buchi_state = str(product_state[1])
                run_message.ltl_states.append(state)
            message.runs.append(run_message)
        self.publisher.publish(message)
