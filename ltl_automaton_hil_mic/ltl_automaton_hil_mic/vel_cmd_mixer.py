"""ROS 2 velocity-command mixed-initiative controller."""

import rclpy
from geometry_msgs.msg import Twist
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import ClosestState, TrapCheck
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
        self.human_command = None
        self.last_human_input = None
        self._safety_check_in_flight = False
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
        self.current_state = clone_ts_state(message.ts_state)

    def _human_callback(self, message):
        self.human_command = VelocityCommandPolicy._clone(message)
        self.last_human_input = self._now_seconds()

    def _navigation_callback(self, navigation):
        navigation = VelocityCommandPolicy._clone(navigation)
        human_is_recent = (
            self.human_command is not None
            and self.last_human_input is not None
            and self._now_seconds() - self.last_human_input < self.timeout
        )
        if not human_is_recent or self.current_state is None:
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
        human = VelocityCommandPolicy._clone(self.human_command)
        self._safety_check_in_flight = True
        future = self.closest_client.call_async(ClosestState.Request())
        future.add_done_callback(
            lambda completed: self._closest_result(
                completed, source_state, human, navigation
            )
        )

    def _closest_result(self, future, source_state, human, navigation):
        try:
            response = future.result()
        except Exception as error:
            self.get_logger().error(f"closest_region failed: {error}")
            self._publish_and_finish(navigation)
            return
        if not response.closest_state:
            self._publish_and_finish(self.policy.mix(human, navigation))
            return

        potential_state = clone_ts_state(source_state)
        index = potential_state.state_dimension_names.index(
            self.state_dimension_name
        )
        potential_state.states[index] = response.closest_state
        request = TrapCheck.Request(ts_state=potential_state)
        trap_future = self.trap_client.call_async(request)
        trap_future.add_done_callback(
            lambda completed: self._trap_result(
                completed,
                response.metric,
                source_state,
                human,
                navigation,
            )
        )

    def _trap_result(
        self,
        future,
        distance,
        source_state,
        human,
        navigation,
    ):
        try:
            response = future.result()
        except Exception as error:
            self.get_logger().error(f"check_for_trap failed: {error}")
            self._publish_and_finish(navigation)
            return
        if self.current_state != source_state:
            self.get_logger().warning(
                "Using navigation command because the TS state changed."
            )
            self._publish_and_finish(navigation)
            return
        if not response.is_connected:
            self.get_logger().warning(
                "Using navigation command because the closest region is "
                "not connected."
            )
            self._publish_and_finish(navigation)
            return
        trap_distance = distance if response.is_trap else None
        self._publish_and_finish(
            self.policy.mix(human, navigation, trap_distance)
        )

    def _publish_and_finish(self, command):
        self._safety_check_in_flight = False
        self.publisher.publish(command)


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
