"""ROS 2 Boolean-command mixed-initiative controller."""

import math
from pathlib import Path
from time import monotonic

import rclpy
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import TrapCheck
from ltl_automaton_planner_core.configuration.transition_system import (
    import_ts_from_file,
)
from rclpy.node import Node
from rclpy.clock import Clock, ClockType
from std_msgs.msg import Bool

from .policies import BoolCommandPolicy, clone_ts_state, validate_ts_state


class BoolCommandMixer(Node):
    """Permit a human Boolean command only when its next TS state is safe."""

    def __init__(self):
        super().__init__("bool_cmd_hil_mic")
        self.declare_parameter("transition_system_path", "")
        self.declare_parameter("state_dimension_name", "load")
        self.declare_parameter("monitored_action", "pick")

        path = self.get_parameter("transition_system_path").value
        if not path:
            raise ValueError("transition_system_path must be set.")
        transition_system = import_ts_from_file(
            Path(path).read_text(encoding="utf-8")
        )
        self.state_dimension_name = self.get_parameter(
            "state_dimension_name"
        ).value
        self.policy = BoolCommandPolicy(
            transition_system,
            self.state_dimension_name,
            self.get_parameter("monitored_action").value,
        )
        self.current_state = None
        self._state_revision = 0
        self._trap_check_in_flight = False
        self._trap_request_context = None
        self._closed = False
        self.declare_parameter("safety_check_timeout", 1.0)
        self.safety_check_timeout = float(
            self.get_parameter("safety_check_timeout").value
        )
        if not math.isfinite(self.safety_check_timeout) or self.safety_check_timeout <= 0.0:
            raise ValueError("safety_check_timeout must be finite and positive.")
        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self._safety_timeout_timer = self.create_timer(
            0.1, self._check_safety_timeout, clock=self._steady_clock
        )
        self.publisher = self.create_publisher(Bool, "mix_cmd", 50)
        self.trap_client = self.create_client(TrapCheck, "check_for_trap")
        self.create_subscription(
            TransitionSystemStateStamped,
            "ts_state",
            self._state_callback,
            50,
        )
        self.create_subscription(Bool, "key_cmd", self._human_callback, 50)
        self.create_subscription(
            Bool, "planner_cmd", self._planner_callback, 50
        )

    def _state_callback(self, message):
        try:
            validate_ts_state(message.ts_state, self.state_dimension_name)
        except ValueError as error:
            self.get_logger().warning(str(error))
            return
        state = clone_ts_state(message.ts_state)
        if self.current_state != state:
            self._state_revision += 1
            self.current_state = state

    def _planner_callback(self, message):
        self.publisher.publish(message)

    def _human_callback(self, message):
        if not message.data:
            return
        if self.current_state is None:
            self.get_logger().warning("Ignoring human command before TS state.")
            return
        if self._trap_check_in_flight:
            self.get_logger().warning(
                "Ignoring human command while a safety check is in progress."
            )
            return
        try:
            potential_state = self.policy.potential_state(self.current_state)
        except ValueError as error:
            self.get_logger().warning(str(error))
            return
        if not self.trap_client.service_is_ready():
            self.get_logger().warning(
                "Ignoring human command while check_for_trap is unavailable."
            )
            return
        request = TrapCheck.Request(ts_state=potential_state)
        source_state = clone_ts_state(self.current_state)
        context = {
            "future": None,
            "deadline": monotonic() + self.safety_check_timeout,
            "source_state": source_state,
            "source_revision": self._state_revision,
        }
        self._trap_request_context = context
        self._trap_check_in_flight = True
        try:
            future = self.trap_client.call_async(request)
        except Exception as error:
            self.get_logger().error(f"check_for_trap failed: {error}")
            self._clear_trap_request(context)
            return
        if future is None:
            self.get_logger().error("check_for_trap returned no Future.")
            self._clear_trap_request(context)
            return
        context["future"] = future
        try:
            future.add_done_callback(
                lambda completed: self._trap_result(completed, context)
            )
        except Exception as error:
            self.get_logger().error(f"check_for_trap failed: {error}")
            self._clear_trap_request(context)

    def _clear_trap_request(self, context, cancel=True):
        if self._trap_request_context is not context:
            return False
        self._trap_request_context = None
        self._trap_check_in_flight = False
        future = context.get("future")
        if cancel and future is not None:
            try:
                future.cancel()
            except Exception:
                pass
        return True

    def _check_safety_timeout(self):
        if self._closed:
            return
        context = self._trap_request_context
        if context is not None and monotonic() >= context["deadline"]:
            self._clear_trap_request(context)

    def _trap_result(self, future, context):
        if (
            self._closed
            or self._trap_request_context is not context
            or context.get("future") is not future
        ):
            return
        if monotonic() >= context["deadline"]:
            self._clear_trap_request(context)
            return
        try:
            response = future.result()
        except Exception as error:
            self.get_logger().error(f"check_for_trap failed: {error}")
            self._clear_trap_request(context, cancel=False)
            return
        self._clear_trap_request(context, cancel=False)
        if response is None:
            self.get_logger().error("check_for_trap returned no response.")
            return
        if (
            self.current_state != context["source_state"]
            or self._state_revision != context["source_revision"]
        ):
            self.get_logger().warning(
                "Discarding human command because the TS state changed."
            )
            return
        if response.is_connected and not response.is_trap:
            self.publisher.publish(Bool(data=True))
        else:
            self.get_logger().warning(
                "Human command rejected because its result is unsafe."
            )

    def destroy_node(self):
        """Cancel safety work before destroying the ROS node."""
        self._closed = True
        context = self._trap_request_context
        if context is not None:
            self._clear_trap_request(context)
        timer = getattr(self, "_safety_timeout_timer", None)
        if timer is not None:
            timer.cancel()
        super().destroy_node()


def main(args=None):
    """Run the Boolean command mixer."""
    rclpy.init(args=args)
    node = BoolCommandMixer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
