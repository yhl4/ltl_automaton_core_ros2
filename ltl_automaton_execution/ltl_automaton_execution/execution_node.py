"""ROS 2 execution manager for generation-bearing formal commands."""

from functools import partial

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy

from ltl_automaton_msgs.msg import PlanningExecutionObservation
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot
from ltl_automaton_execution.accepted_run_resolver import AcceptedRunResolver
from ltl_automaton_execution.execution_manager import ExecutionManager
from ltl_automaton_execution.fake_backend import FakeBackend
from ltl_automaton_execution.fake_plant import FakePlant
from ltl_automaton_execution.fake_state_abstraction import FakeStateAbstraction
from ltl_automaton_execution.fake_state_observer import FakeStateObserver
from ltl_automaton_execution.models import AcceptedRun
from ltl_automaton_execution.models import ExecutionObservation
from ltl_automaton_execution.models import PlanningSnapshot
from ltl_automaton_execution.models import ProductEdge
from ltl_automaton_execution.models import ProductNode
from ltl_automaton_execution.models import SymbolicState


COMMAND_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)


class ExecutionManagerNode(Node):
    """Compose formal execution with independent observed state feedback."""

    def __init__(
        self,
        *,
        backend=None,
        state_observer=None,
        state_abstraction=None,
        fake_plant=None,
        execution_delay_sec=None,
        **kwargs,
    ):
        super().__init__("ltl_execution_manager", **kwargs)
        self.declare_parameter("execution_delay_sec", 0.5)
        delay = (
            self.get_parameter("execution_delay_sec").value
            if execution_delay_sec is None else execution_delay_sec
        )
        self._fake_plant = fake_plant or FakePlant()
        selected_backend = backend or FakeBackend(
            self._fake_plant, self._schedule, delay
        )
        self._state_observer = state_observer or FakeStateObserver(
            self._fake_plant
        )
        self._state_abstraction = state_abstraction or FakeStateAbstraction()
        self._manager = ExecutionManager(
            AcceptedRunResolver(),
            selected_backend,
            self.get_logger().warning,
        )
        self._snapshots = {}
        self._snapshot_requests = set()
        self._execution_timers = set()
        self._expected_dimensions = None
        self._expected_schema_instance = None
        self._state_publisher = self.create_publisher(
            TransitionSystemStateStamped,
            "ts_state",
            10,
        )
        self._snapshot_client = self.create_client(
            GetPlanningGraphSnapshot,
            "get_planning_graph_snapshot",
        )
        self._observation_subscription = self.create_subscription(
            PlanningExecutionObservation,
            "planning_execution_observation",
            self._on_observation,
            COMMAND_QOS,
        )
        self._state_observer.start(self._on_state_observation)

    def _schedule(self, delay, callback):
        holder = {}

        def fire():
            timer = holder["timer"]
            timer.cancel()
            self._execution_timers.discard(timer)
            callback()

        timer = self.create_timer(max(float(delay), 0.001), fire)
        holder["timer"] = timer
        self._execution_timers.add(timer)
        return True

    @staticmethod
    def _observation_from_message(message):
        return ExecutionObservation(
            message.planner_instance_id,
            int(message.planning_generation),
            tuple(message.possible_product_node_ids),
            bool(message.has_next_action),
            message.next_action,
        )

    @staticmethod
    def _snapshot_from_message(message):
        metadata = message.metadata
        if not metadata.available:
            raise ValueError(
                metadata.unavailable_reason or "Planning snapshot is unavailable."
            )
        nodes = tuple(
            ProductNode(
                int(node.id),
                SymbolicState(
                    tuple(node.ts_state.state_dimension_names),
                    tuple(node.ts_state.states),
                ),
            )
            for node in message.product_nodes
        )
        edges = tuple(
            ProductEdge(
                int(edge.source_id),
                int(edge.target_id),
                edge.action,
            )
            for edge in message.product_edges
        )
        return PlanningSnapshot(
            metadata.planner_instance_id,
            int(metadata.planning_generation),
            nodes,
            edges,
            AcceptedRun(
                tuple(message.accepted_run.prefix_product_node_ids),
                tuple(message.accepted_run.suffix_product_node_ids),
            ),
        )

    def _on_observation(self, message):
        observation = self._observation_from_message(message)
        if not self._manager.observe_authority(observation):
            return
        if self._expected_schema_instance not in (
            None,
            observation.planner_instance_id,
        ):
            self._expected_dimensions = None
            self._expected_schema_instance = None
        if not observation.has_next_action:
            return
        if self._manager.in_flight:
            return
        identity = (
            observation.planner_instance_id,
            observation.planning_generation,
        )
        snapshot = self._snapshots.get(identity)
        if snapshot is not None:
            self._manager.dispatch(observation, snapshot)
            return
        if identity in self._snapshot_requests:
            return
        if not self._snapshot_client.service_is_ready():
            self.get_logger().warning("Planning snapshot service is unavailable.")
            return
        self._snapshot_requests.add(identity)
        future = self._snapshot_client.call_async(
            GetPlanningGraphSnapshot.Request()
        )
        future.add_done_callback(
            partial(self._on_snapshot, observation, identity)
        )

    def _on_snapshot(self, observation, identity, future):
        self._snapshot_requests.discard(identity)
        try:
            response = future.result()
            if response is None or not response.success:
                raise ValueError(
                    response.message if response is not None
                    else "Planning snapshot request returned no response."
                )
            snapshot = self._snapshot_from_message(response.snapshot)
        except Exception as error:
            self.get_logger().warning(f"Planning snapshot rejected: {error}")
            return
        snapshot_identity = (
            snapshot.planner_instance_id,
            snapshot.planning_generation,
        )
        if snapshot_identity != identity:
            self.get_logger().warning(
                "Planning snapshot identity does not match the observation."
            )
            return
        if not self._manager.is_current(observation):
            self.get_logger().warning(
                "Planning authority changed before snapshot acceptance."
            )
            return
        try:
            expected_dimensions = self._snapshot_dimensions(snapshot)
        except ValueError as error:
            self.get_logger().warning(f"Planning snapshot rejected: {error}")
            return
        self._snapshots[identity] = snapshot
        self._expected_dimensions = expected_dimensions
        self._expected_schema_instance = snapshot.planner_instance_id
        self._manager.dispatch(observation, snapshot)

    @staticmethod
    def _snapshot_dimensions(snapshot):
        if not snapshot.product_nodes:
            raise ValueError("Planning snapshot has no Product nodes.")
        dimensions = snapshot.product_nodes[0].ts_state.dimension_names
        for node in snapshot.product_nodes[1:]:
            if node.ts_state.dimension_names != dimensions:
                raise ValueError(
                    "Planning snapshot has inconsistent TS dimension order."
                )
        return dimensions

    def _on_state_observation(self, observation):
        try:
            abstracted = self._state_abstraction.abstract(observation)
        except Exception as error:
            self.get_logger().warning(f"State abstraction failed: {error}")
            return
        if abstracted is None:
            self.get_logger().warning("State abstraction rejected observation.")
            return
        try:
            state = SymbolicState(
                tuple(abstracted.dimension_names),
                tuple(abstracted.states),
            )
        except (AttributeError, TypeError, ValueError) as error:
            self.get_logger().warning(
                f"State abstraction produced malformed state: {error}"
            )
            return
        if self._expected_dimensions is not None:
            if set(state.dimension_names) != set(self._expected_dimensions):
                self.get_logger().warning(
                    "Observed TS dimensions do not match the active snapshot."
                )
                return
            values = dict(zip(state.dimension_names, state.states))
            state = SymbolicState(
                self._expected_dimensions,
                tuple(values[name] for name in self._expected_dimensions),
            )
        self._publish_state(state)

    def _publish_state(self, state):
        message = TransitionSystemStateStamped()
        message.header.stamp = self.get_clock().now().to_msg()
        message.ts_state.state_dimension_names = list(state.dimension_names)
        message.ts_state.states = list(state.states)
        self._state_publisher.publish(message)

    def destroy_node(self):
        """Stop observation delivery before releasing ROS entities."""
        self._state_observer.stop()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ExecutionManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
