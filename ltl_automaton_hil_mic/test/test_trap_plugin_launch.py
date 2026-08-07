"""Launch-level test for the TrapDetection planner plugin."""

import time
import unittest

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import launch_testing
import launch_testing.actions
import launch_testing.asserts
from ltl_automaton_msgs.msg import (
    LTLPlan,
    LTLStateRuns,
    TransitionSystemState,
    TransitionSystemStateStamped,
)
from ltl_automaton_msgs.srv import TrapCheck
import pytest
import rclpy
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool


@pytest.mark.launch_test
def generate_test_description():
    """Launch the real planner with the installed trap plugin config."""
    planner_share = get_package_share_directory("ltl_automaton_planner")
    plugin_share = get_package_share_directory("ltl_automaton_hil_mic")
    planner = Node(
        package="ltl_automaton_planner",
        executable="planner_node",
        name="trap_plugin_test_planner",
        parameters=[
            {
                "transition_system_path": (
                    planner_share + "/config/kth_example_ts.yaml"
                ),
                "hard_task": (
                    "([]<> (r1 && loaded)) && "
                    "([]<> (r1 && unloaded)) && ([] ! r3)"
                ),
                "soft_task": "(r2 || ! r2)",
                "plugin_config_path": (
                    plugin_share + "/config/trap_detection_plugin.yaml"
                ),
            }
        ],
    )
    return (
        LaunchDescription(
            [
                planner,
                launch_testing.actions.ReadyToTest(),
            ]
        ),
        {"planner": planner},
    )


class TestTrapPluginService(unittest.TestCase):
    """Check safe, trap, and disconnected service responses."""

    @classmethod
    def setUpClass(cls):
        """Create a ROS 2 client node."""
        rclpy.init()
        cls.node = rclpy.create_node("trap_plugin_service_test")
        cls.client = cls.node.create_client(TrapCheck, "check_for_trap")

    @classmethod
    def tearDownClass(cls):
        """Destroy the client node and ROS 2 context."""
        cls.node.destroy_node()
        rclpy.shutdown()

    def _call(self, region, load):
        request = TrapCheck.Request(
            ts_state=TransitionSystemState(
                states=[load, region],
                state_dimension_names=["turtlebot_load", "2d_pose_region"],
            )
        )
        future = self.client.call_async(request)
        deadline = time.monotonic() + 8.0
        while not future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
        self.assertTrue(future.done())
        return future.result()

    def test_plugins_against_real_planner(self):
        """Classify traps, then record one live IRL Product transition."""
        self.assertTrue(self.client.wait_for_service(timeout_sec=15.0))

        safe = self._call("r2", "unloaded")
        self.assertTrue(safe.is_connected)
        self.assertFalse(safe.is_trap)

        trap = self._call("r3", "unloaded")
        self.assertTrue(trap.is_connected)
        self.assertTrue(trap.is_trap)

        disconnected = self._call("r2", "loaded")
        self.assertFalse(disconnected.is_connected)
        self.assertFalse(disconnected.is_trap)

        self._record_irl_run()

    def _record_irl_run(self):
        """Record a live Product transition and publish its possible runs."""
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        runs = []
        plans = []
        subscription = self.node.create_subscription(
            LTLStateRuns,
            "possible_runs",
            runs.append,
            qos,
        )
        plan_subscription = self.node.create_subscription(
            LTLPlan,
            "prefix_plan",
            plans.append,
            qos,
        )
        trigger_publisher = self.node.create_publisher(Bool, "irl_trigger", 10)
        state_publisher = self.node.create_publisher(
            TransitionSystemStateStamped,
            "ts_state",
            10,
        )
        deadline = time.monotonic() + 8.0
        while (
            trigger_publisher.get_subscription_count() < 1
            or state_publisher.get_subscription_count() < 1
        ) and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
        self.assertGreaterEqual(trigger_publisher.get_subscription_count(), 1)
        self.assertGreaterEqual(state_publisher.get_subscription_count(), 1)

        trigger_publisher.publish(Bool(data=True))
        rclpy.spin_once(self.node, timeout_sec=0.2)
        state_message = TransitionSystemStateStamped()
        state_message.header.stamp.sec = 1
        state_message.ts_state.states = ["r2", "unloaded"]
        state_message.ts_state.state_dimension_names = [
            "2d_pose_region",
            "turtlebot_load",
        ]
        state_publisher.publish(state_message)
        deadline = time.monotonic() + 8.0
        while not runs and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
        self.assertTrue(runs)
        self.assertTrue(runs[-1].runs)
        last_state = runs[-1].runs[0].ltl_states[-1].ts_state
        self.assertEqual(last_state.states, ["r2", "unloaded"])
        self.assertTrue(plans)
        rclpy.spin_once(self.node, timeout_sec=0.2)
        plan_count = len(plans)
        trigger_publisher.publish(Bool(data=False))
        deadline = time.monotonic() + 15.0
        while len(plans) <= plan_count and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
        self.assertGreater(len(plans), plan_count)
        self.node.destroy_subscription(subscription)
        self.node.destroy_subscription(plan_subscription)


@launch_testing.post_shutdown_test()
class TestTrapPluginShutdown(unittest.TestCase):
    """Check that the plugin-hosting planner exits cleanly."""

    def test_exit_code(self, proc_info, planner):
        """Require the standard launch-testing shutdown exit codes."""
        launch_testing.asserts.assertExitCodes(
            proc_info,
            process=planner,
            allowable_exit_codes=[0, -2],
        )
