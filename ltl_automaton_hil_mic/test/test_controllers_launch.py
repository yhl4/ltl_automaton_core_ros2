"""Launch-level tests for both ROS 2 mixed-initiative controllers."""

import time
import unittest

from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Twist
from launch import LaunchDescription
from launch_ros.actions import Node
import launch_testing
import launch_testing.actions
import launch_testing.asserts
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import ClosestState, TrapCheck
import pytest
import rclpy
from std_msgs.msg import Bool


@pytest.mark.launch_test
def generate_test_description():
    """Launch both controllers against test-provided safety services."""
    package_share = get_package_share_directory("ltl_automaton_hil_mic")
    bool_controller = Node(
        package="ltl_automaton_hil_mic",
        executable="bool_cmd_hil_mic",
        parameters=[
            {
                "transition_system_path": (
                    package_share + "/config/example_bool_ts.yaml"
                ),
                "state_dimension_name": "load",
                "monitored_action": "pick",
            }
        ],
    )
    velocity_controller = Node(
        package="ltl_automaton_hil_mic",
        executable="vel_cmd_hil_mic",
        parameters=[
            {
                "state_dimension_name": "2d_pose_region",
                "ds": 1.0,
                "epsilon": 1.0,
                "deadband": 0.05,
                "timeout": 60.0,
            }
        ],
    )
    return (
        LaunchDescription(
            [
                bool_controller,
                velocity_controller,
                launch_testing.actions.ReadyToTest(),
            ]
        ),
        {
            "bool_controller": bool_controller,
            "velocity_controller": velocity_controller,
        },
    )


class TestControllerCommunication(unittest.TestCase):
    """Exercise controller topics and safety-service decisions end to end."""

    @classmethod
    def setUpClass(cls):
        """Create test services and one ROS 2 communication node."""
        rclpy.init()
        cls.node = rclpy.create_node("hil_mic_launch_test")
        cls.trap_states = set()
        cls.connected = True
        cls.closest_state = "r2"
        cls.closest_distance = 3.0
        cls.trap_request_count = 0
        cls.trap_service = cls.node.create_service(
            TrapCheck, "check_for_trap", cls._trap_callback
        )
        cls.closest_service = cls.node.create_service(
            ClosestState, "closest_region", cls._closest_callback
        )

    @classmethod
    def tearDownClass(cls):
        """Destroy the test node and ROS 2 context."""
        cls.node.destroy_node()
        rclpy.shutdown()

    @classmethod
    def _trap_callback(cls, request, response):
        cls.trap_request_count += 1
        response.is_connected = cls.connected
        response.is_trap = any(
            state in cls.trap_states for state in request.ts_state.states
        )
        return response

    @classmethod
    def _closest_callback(cls, request, response):
        del request
        response.closest_state = cls.closest_state
        response.metric = cls.closest_distance
        return response

    def _spin_until(self, predicate, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self.node, timeout_sec=0.05)
        return predicate()

    def _publish_until(self, publisher, message, predicate, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            publisher.publish(message)
            if self._spin_until(predicate, timeout=0.2):
                return True
        return predicate()

    @staticmethod
    def _state_message():
        message = TransitionSystemStateStamped()
        message.ts_state.states = ["empty", "r1"]
        message.ts_state.state_dimension_names = ["load", "2d_pose_region"]
        return message

    def test_boolean_planner_passthrough_and_human_safety_gate(self):
        """Allow safe human commands and reject trap-producing commands."""
        values = []
        subscription = self.node.create_subscription(
            Bool, "mix_cmd", lambda message: values.append(message.data), 50
        )
        state_publisher = self.node.create_publisher(
            TransitionSystemStateStamped, "ts_state", 50
        )
        planner_publisher = self.node.create_publisher(
            Bool, "planner_cmd", 50
        )
        human_publisher = self.node.create_publisher(Bool, "key_cmd", 50)

        self.assertTrue(
            self._spin_until(
                lambda: state_publisher.get_subscription_count() >= 2
                and planner_publisher.get_subscription_count() >= 1
                and human_publisher.get_subscription_count() >= 1
            )
        )
        state_publisher.publish(self._state_message())
        self._spin_until(lambda: False, timeout=0.2)
        self.assertTrue(
            self._publish_until(
                planner_publisher,
                Bool(data=True),
                lambda: values and values[-1] is True,
            )
        )

        type(self).trap_states = set()
        previous_count = len(values)
        previous_requests = self.trap_request_count
        human_publisher.publish(Bool(data=True))
        self.assertTrue(
            self._spin_until(
                lambda: (
                    self.trap_request_count > previous_requests
                    and len(values) > previous_count
                )
            )
        )
        self._spin_until(lambda: False, timeout=0.3)
        values.clear()

        type(self).trap_states = {"loaded"}
        previous_requests = self.trap_request_count
        human_publisher.publish(Bool(data=True))
        self.assertTrue(
            self._spin_until(
                lambda: self.trap_request_count > previous_requests
            )
        )
        self._spin_until(lambda: False, timeout=0.2)
        self.assertEqual(values, [])
        self.node.destroy_subscription(subscription)

    def test_velocity_human_trap_buffer_and_unconnected_fallback(self):
        """Verify human, blended, and safe navigation output modes."""
        values = []
        subscription = self.node.create_subscription(
            Twist, "cmd_vel", lambda message: values.append(message.linear.x), 50
        )
        state_publisher = self.node.create_publisher(
            TransitionSystemStateStamped, "ts_state", 50
        )
        human_publisher = self.node.create_publisher(Twist, "key_vel", 50)
        navigation_publisher = self.node.create_publisher(
            Twist, "nav_vel", 50
        )
        self.assertTrue(
            self._spin_until(
                lambda: state_publisher.get_subscription_count() >= 2
                and human_publisher.get_subscription_count() >= 1
                and navigation_publisher.get_subscription_count() >= 1
            )
        )
        human = Twist()
        human.linear.x = 0.4
        navigation = Twist()
        navigation.linear.x = 0.1
        state_publisher.publish(self._state_message())
        human_publisher.publish(human)
        self._spin_until(lambda: False, timeout=0.2)

        type(self).connected = True
        type(self).trap_states = set()
        type(self).closest_distance = 3.0
        self.assertTrue(
            self._publish_until(
                navigation_publisher,
                navigation,
                lambda: values and abs(values[-1] - 0.4) < 1e-6,
            )
        )

        type(self).trap_states = {"r2"}
        type(self).closest_distance = 0.5
        self.assertTrue(
            self._publish_until(
                navigation_publisher,
                navigation,
                lambda: values and abs(values[-1] - 0.1) < 1e-6,
            )
        )

        type(self).closest_distance = 1.5
        self.assertTrue(
            self._publish_until(
                navigation_publisher,
                navigation,
                lambda: values and abs(values[-1] - 0.25) < 1e-6,
            )
        )

        type(self).connected = False
        self.assertTrue(
            self._publish_until(
                navigation_publisher,
                navigation,
                lambda: values and abs(values[-1] - 0.1) < 1e-6,
            )
        )
        self.node.destroy_subscription(subscription)


@launch_testing.post_shutdown_test()
class TestControllerShutdown(unittest.TestCase):
    """Check both controllers exit cleanly with launch shutdown."""

    def test_exit_codes(
        self,
        proc_info,
        bool_controller,
        velocity_controller,
    ):
        """Require the standard launch-testing shutdown exit codes."""
        launch_testing.asserts.assertExitCodes(
            proc_info,
            process=bool_controller,
            allowable_exit_codes=[0, -2],
        )
        launch_testing.asserts.assertExitCodes(
            proc_info,
            process=velocity_controller,
            allowable_exit_codes=[0, -2],
        )
