"""ROS 2 execution manager for generation-bearing formal commands."""

from functools import partial
import math
from time import monotonic

import rclpy
from rclpy.clock import Clock
from rclpy.clock import ClockType
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy

from ltl_automaton_msgs.msg import PlanningExecutionObservation
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot
from ltl_automaton_execution.accepted_run_resolver import AcceptedRunResolver
from ltl_automaton_execution.execution import ExecutionManager
from ltl_automaton_execution.fake_runtime import FakeBackend
from ltl_automaton_execution.fake_runtime import FakePlant
from ltl_automaton_execution.fake_runtime import FakeStateAbstraction
from ltl_automaton_execution.fake_runtime import FakeStateObserver
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
        self.declare_parameter("snapshot_request_timeout", 5.0)
        self._snapshot_request_timeout = float(
            self.get_parameter("snapshot_request_timeout").value
        )
        if (
            not math.isfinite(self._snapshot_request_timeout)
            or self._snapshot_request_timeout <= 0.0
        ):
            raise ValueError(
                "snapshot_request_timeout must be finite and positive."
            )
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
        self._snapshot_requests = {}
        self._latest_observation = None
        self._execution_timers = set()
        self._shutting_down = False
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
        self._pending_snapshot_observation = None
        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self._snapshot_retry_timer = self.create_timer(
            0.1,
            self._retry_snapshot_discovery,
            clock=self._steady_clock,
        )
        self._snapshot_retry_timer.cancel()
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
            int(message.execution_step_seq),
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
        if self._shutting_down:
            return
        self._expire_snapshot_requests()
        observation = self._observation_from_message(message)
        if not self._manager.observe_authority(observation):
            return
        identity = (
            observation.planner_instance_id,
            observation.planning_generation,
        )
        self._latest_observation = observation
        self._pending_snapshot_observation = None
        if self._expected_schema_instance not in (
            None,
            observation.planner_instance_id,
        ):
            self._expected_dimensions = None
            self._expected_schema_instance = None
        if not observation.has_next_action:
            self._cancel_snapshot_requests()
            self._snapshot_retry_timer.cancel()
            return
        self._cancel_snapshot_requests(identity)
        if self._manager.in_flight:
            self._pending_snapshot_observation = observation
            self._ensure_snapshot_retry_timer()
            return
        snapshot = self._snapshots.get(identity)
        if snapshot is not None:
            self._manager.dispatch(observation, snapshot)
            return
        if identity in self._snapshot_requests:
            self._ensure_snapshot_retry_timer()
            return
        if not self._snapshot_client.service_is_ready():
            self.get_logger().warning("Planning snapshot service is unavailable.")
            self._pending_snapshot_observation = observation
            self._ensure_snapshot_retry_timer()
            return
        context = {
            "future": None,
            "deadline": monotonic() + self._snapshot_request_timeout,
        }
        self._snapshot_requests[identity] = context
        try:
            future = self._snapshot_client.call_async(
                GetPlanningGraphSnapshot.Request()
            )
            if future is None:
                raise RuntimeError("Planning snapshot request returned no Future.")
            context["future"] = future
            future.add_done_callback(
                partial(self._on_snapshot, observation, identity, context)
            )
        except Exception as error:
            self._detach_snapshot_request(identity, context)
            self._retain_failed_snapshot_observation(identity)
            self.get_logger().warning(
                f"Planning snapshot request failed: {error}"
            )
            return
        self._ensure_snapshot_retry_timer()

    def _detach_snapshot_request(
        self, identity, context, future=None, cancel=True
    ):
        """Detach one matching snapshot request before cancelling it."""
        if self._snapshot_requests.get(identity) is not context:
            return False
        current_future = context.get("future")
        if future is not None and current_future is not future:
            return False
        self._snapshot_requests.pop(identity, None)
        if cancel and current_future is not None:
            try:
                current_future.cancel()
            except Exception:
                pass
        return True

    def _cancel_snapshot_requests(self, keep_identity=None):
        """Cancel requests outside the current authority identity."""
        for identity, context in list(self._snapshot_requests.items()):
            if keep_identity is None or identity != keep_identity:
                self._detach_snapshot_request(identity, context)

    def _ensure_snapshot_retry_timer(self):
        """Keep the retry timer active without extending an active deadline."""
        if self._snapshot_retry_timer.is_canceled():
            self._snapshot_retry_timer.reset()

    def _expire_snapshot_requests(self):
        """Cancel timed-out snapshot requests and retain their latest command."""
        now = monotonic()
        for identity, context in list(self._snapshot_requests.items()):
            if now >= context["deadline"]:
                if self._detach_snapshot_request(identity, context):
                    self._retain_failed_snapshot_observation(identity)

    def _retry_snapshot_discovery(self):
        """Retain the latest command while waiting for ROS service discovery."""
        if self._shutting_down:
            return
        self._expire_snapshot_requests()
        observation = self._pending_snapshot_observation
        if observation is None or not self._manager.is_current(observation):
            self._pending_snapshot_observation = None
            if not self._snapshot_requests:
                self._snapshot_retry_timer.cancel()
            else:
                self._ensure_snapshot_retry_timer()
        elif self._manager.in_flight:
            self._ensure_snapshot_retry_timer()
        elif (
            (observation.planner_instance_id, observation.planning_generation)
            in self._snapshots
            or self._snapshot_client.service_is_ready()
        ):
            self._on_observation(observation)
        else:
            self._ensure_snapshot_retry_timer()

    def _on_snapshot(self, observation, identity, context, future):
        if self._shutting_down:
            return
        if monotonic() >= context["deadline"]:
            if self._detach_snapshot_request(identity, context, future):
                self._retain_failed_snapshot_observation(identity)
            return
        if not self._detach_snapshot_request(
            identity, context, future, cancel=False
        ):
            return
        try:
            response = future.result()
        except Exception as error:
            self._retain_failed_snapshot_observation(identity)
            self.get_logger().warning(
                f"Planning snapshot request failed: {error}"
            )
            return
        if response is None:
            self._retain_failed_snapshot_observation(identity)
            self.get_logger().warning(
                "Planning snapshot request returned no response."
            )
            return
        if not response.success:
            self._retain_failed_snapshot_observation(identity)
            self.get_logger().warning(
                "Planning snapshot request failed: "
                f"{response.message or 'unsuccessful response'}"
            )
            return
        try:
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
        latest_observation = self._latest_observation
        latest_identity = None
        if latest_observation is not None:
            latest_identity = (
                latest_observation.planner_instance_id,
                latest_observation.planning_generation,
            )
        if (
            latest_observation is None
            or latest_identity != identity
            or not self._manager.is_current(latest_observation)
        ):
            self.get_logger().warning(
                "Planning authority changed before latest "
                "snapshot observation."
            )
            return
        try:
            expected_dimensions = self._snapshot_dimensions(snapshot)
        except ValueError as error:
            self.get_logger().warning(f"Planning snapshot rejected: {error}")
            return
        # In-flight steps already hold their resolved states; only current
        # authority needs a graph cache.
        self._snapshots.clear()
        self._snapshots[identity] = snapshot
        self._expected_dimensions = expected_dimensions
        self._expected_schema_instance = snapshot.planner_instance_id
        if latest_observation.has_next_action:
            if self._manager.in_flight:
                self._pending_snapshot_observation = latest_observation
                self._snapshot_retry_timer.reset()
            else:
                self._manager.dispatch(latest_observation, snapshot)

    def _retain_failed_snapshot_observation(self, identity):
        """Retry only the latest valid command for a failed request."""
        if self._shutting_down:
            return
        observation = self._latest_observation
        if observation is None:
            return
        latest_identity = (
            observation.planner_instance_id,
            observation.planning_generation,
        )
        if (
            latest_identity != identity
            or not observation.has_next_action
            or not self._manager.is_current(observation)
        ):
            return
        self._pending_snapshot_observation = observation
        self._ensure_snapshot_retry_timer()

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
        if not isinstance(abstracted, SymbolicState):
            self.get_logger().warning(
                "State abstraction produced malformed symbolic state."
            )
            return
        state = abstracted
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
        if self._shutting_down:
            return None
        self._shutting_down = True
        self._pending_snapshot_observation = None
        self._cancel_snapshot_requests()
        self._snapshot_retry_timer.cancel()
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
