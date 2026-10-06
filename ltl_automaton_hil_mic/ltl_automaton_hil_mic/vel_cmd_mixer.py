"""ROS 2 velocity-command mixed-initiative controller."""

import math
from time import monotonic

import rclpy
from geometry_msgs.msg import Twist
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import ClosestState, TrapCheck
from rclpy.clock import Clock, ClockType
from rclpy.node import Node

from .policies import (
    VelocityCommandPolicy,
    clone_ts_state,
    validate_ts_state,
)


SUPPORTED_STATE_DIMENSIONS = {
    "2d_pose_region",
    "3d_pose_region",
    "2d_point_region",
    "3d_point_region",
}


class VelocityCommandMixer(Node):
    """Blend human and navigation velocities according to nearby traps."""

    def __init__(self):
        super().__init__("vel_cmd_hil_mic")
        defaults = {
            "epsilon": 1.5,
            "ds": 1.2,
            "deadband": 0.2,
            "timeout": 0.2,
            "safety_check_timeout": 1.0,
            "max_linear_x_vel": 0.5,
            "max_linear_y_vel": 0.5,
            "max_linear_z_vel": 0.5,
            "max_angular_x_vel": 2.0,
            "max_angular_y_vel": 2.0,
            "max_angular_z_vel": 2.0,
            "state_dimension_name": "2d_pose_region",
        }
        for name, value in defaults.items():
            self.declare_parameter(name, value)

        self.state_dimension_name = self.get_parameter(
            "state_dimension_name"
        ).value
        if self.state_dimension_name not in SUPPORTED_STATE_DIMENSIONS:
            raise ValueError(
                f"Unsupported state dimension {self.state_dimension_name!r}."
            )
        self.timeout = float(self.get_parameter("timeout").value)
        if self.timeout < 0.0:
            raise ValueError("timeout must be non-negative.")
        self.safety_check_timeout = float(
            self.get_parameter("safety_check_timeout").value
        )
        if (
            not math.isfinite(self.safety_check_timeout)
            or self.safety_check_timeout <= 0.0
        ):
            raise ValueError("safety_check_timeout must be finite and positive.")
        self.policy = VelocityCommandPolicy(
            safety_distance=float(self.get_parameter("ds").value),
            epsilon=float(self.get_parameter("epsilon").value),
            deadband=float(self.get_parameter("deadband").value),
            max_linear=tuple(
                float(self.get_parameter(f"max_linear_{axis}_vel").value)
                for axis in ("x", "y", "z")
            ),
            max_angular=tuple(
                float(self.get_parameter(f"max_angular_{axis}_vel").value)
                for axis in ("x", "y", "z")
            ),
        )
        self.current_state = None
        self._state_revision = 0
        self.human_command = None
        self.last_human_input = None
        self._latest_navigation_command = None
        self._safety_check_in_flight = False
        self._safety_request_context = None
        self._closed = False
        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self._safety_timeout_timer = self.create_timer(
            0.1, self._check_safety_timeout, clock=self._steady_clock
        )
        self.publisher = self.create_publisher(Twist, "cmd_vel", 50)
        self.closest_client = self.create_client(
            ClosestState, "closest_region"
        )
        self.trap_client = self.create_client(TrapCheck, "check_for_trap")
        self.create_subscription(
            TransitionSystemStateStamped,
            "ts_state",
            self._state_callback,
            50,
        )
        self.create_subscription(Twist, "key_vel", self._human_callback, 50)
        self.create_subscription(
            Twist, "nav_vel", self._navigation_callback, 50
        )

    def _now_seconds(self):
        return self.get_clock().now().nanoseconds / 1_000_000_000.0

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

    def _human_callback(self, message):
        self.human_command = VelocityCommandPolicy._clone(message)
        self.last_human_input = self._now_seconds()

    def _human_is_recent(self):
        return (
            self.human_command is not None
            and self.last_human_input is not None
            and self._now_seconds() - self.last_human_input < self.timeout
        )

    def _latest_navigation(self):
        if self._latest_navigation_command is None:
            return Twist()
        return VelocityCommandPolicy._clone(self._latest_navigation_command)

    def _query_is_current(self, context):
        return (
            self.current_state is not None
            and self.current_state == context["source_state"]
            and self._state_revision == context["source_revision"]
            and self._human_is_recent()
        )

    def _clear_safety_request(self, context, cancel=True):
        if self._safety_request_context is not context:
            return False
        self._safety_request_context = None
        self._safety_check_in_flight = False
        future = context.get("future")
        if cancel and future is not None:
            try:
                future.cancel()
            except Exception:
                pass
        return True

    def _publish_latest_navigation(self, context):
        if not self._clear_safety_request(context):
            return
        self.publisher.publish(self._latest_navigation())

    def _publish_policy_result(self, context, distance=None):
        if not self._query_is_current(context):
            self._publish_latest_navigation(context)
            return
        human = VelocityCommandPolicy._clone(self.human_command)
        navigation = self._latest_navigation()
        if not self._clear_safety_request(context, cancel=False):
            return
        self.publisher.publish(self.policy.mix(human, navigation, distance))

    def _navigation_callback(self, navigation):
        navigation = VelocityCommandPolicy._clone(navigation)
        self._latest_navigation_command = VelocityCommandPolicy._clone(
            navigation
        )
        if not self._human_is_recent() or self.current_state is None:
            self.publisher.publish(navigation)
            return
        if self._safety_check_in_flight:
            self.publisher.publish(navigation)
            return
        if not (
            self.closest_client.service_is_ready()
            and self.trap_client.service_is_ready()
        ):
            self.get_logger().warning(
                "Using navigation command while safety services are unavailable."
            )
            self.publisher.publish(navigation)
            return

        source_state = clone_ts_state(self.current_state)
        context = {
            "future": None,
            "deadline": monotonic() + self.safety_check_timeout,
            "source_state": source_state,
            "source_revision": self._state_revision,
        }
        self._safety_request_context = context
        self._safety_check_in_flight = True
        try:
            future = self.closest_client.call_async(ClosestState.Request())
            if future is None:
                raise RuntimeError("closest_region returned no Future.")
            context["future"] = future
            future.add_done_callback(
                lambda completed: self._closest_result(completed, context)
            )
        except Exception as error:
            self.get_logger().error(f"closest_region failed: {error}")
            self._publish_latest_navigation(context)

    def _check_safety_timeout(self):
        if self._closed:
            return
        context = self._safety_request_context
        if context is not None and monotonic() >= context["deadline"]:
            self._publish_latest_navigation(context)

    def _closest_result(self, future, context):
        if (
            self._closed
            or self._safety_request_context is not context
            or context.get("future") is not future
        ):
            return
        if monotonic() >= context["deadline"]:
            self._publish_latest_navigation(context)
            return
        try:
            response = future.result()
        except Exception as error:
            self.get_logger().error(f"closest_region failed: {error}")
            self._publish_latest_navigation(context)
            return
        if response is None or not self._query_is_current(context):
            if response is None:
                self.get_logger().error("closest_region returned no response.")
            else:
                self.get_logger().warning(
                    "Using navigation command because the safety query is stale."
                )
            self._publish_latest_navigation(context)
            return
        if not response.closest_state:
            self._publish_policy_result(context)
            return

        potential_state = clone_ts_state(context["source_state"])
        index = potential_state.state_dimension_names.index(
            self.state_dimension_name
        )
        potential_state.states[index] = response.closest_state
        request = TrapCheck.Request(ts_state=potential_state)
        try:
            trap_future = self.trap_client.call_async(request)
            if trap_future is None:
                raise RuntimeError("check_for_trap returned no Future.")
            context["future"] = trap_future
            trap_future.add_done_callback(
                lambda completed: self._trap_result(
                    completed, response.metric, context
                )
            )
        except Exception as error:
            self.get_logger().error(f"check_for_trap failed: {error}")
            self._publish_latest_navigation(context)

    def _trap_result(
        self,
        future,
        distance,
        context,
    ):
        if (
            self._closed
            or self._safety_request_context is not context
            or context.get("future") is not future
        ):
            return
        if monotonic() >= context["deadline"]:
            self._publish_latest_navigation(context)
            return
        try:
            response = future.result()
        except Exception as error:
            self.get_logger().error(f"check_for_trap failed: {error}")
            self._publish_latest_navigation(context)
            return
        if response is None:
            self.get_logger().error("check_for_trap returned no response.")
            self._publish_latest_navigation(context)
            return
        if not self._query_is_current(context):
            self.get_logger().warning(
                "Using navigation command because the safety query is stale."
            )
            self._publish_latest_navigation(context)
            return
        if not response.is_connected:
            self.get_logger().warning(
                "Using navigation command because the closest region is "
                "not connected."
            )
            self._publish_latest_navigation(context)
            return
        trap_distance = distance if response.is_trap else None
        self._publish_policy_result(context, trap_distance)

    def destroy_node(self):
        """Cancel safety work before destroying the ROS node."""
        self._closed = True
        context = self._safety_request_context
        if context is not None:
            self._clear_safety_request(context)
        timer = getattr(self, "_safety_timeout_timer", None)
        if timer is not None:
            timer.cancel()
        super().destroy_node()


def main(args=None):
    """Run the velocity command mixer."""
    rclpy.init(args=args)
    node = VelocityCommandMixer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
