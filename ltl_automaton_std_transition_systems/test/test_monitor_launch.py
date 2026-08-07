"""Launch-level communication test for the ROS 2 2D region monitor."""

import time
import unittest

from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Pose
from launch import LaunchDescription
from launch_ros.actions import Node
import launch_testing
import launch_testing.actions
import launch_testing.asserts
from ltl_automaton_msgs.srv import ClosestState
import pytest
import rclpy
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from std_msgs.msg import String


@pytest.mark.launch_test
def generate_test_description():
    """Launch the monitor with its installed example TS."""
    package_share = get_package_share_directory(
        "ltl_automaton_std_transition_systems"
    )
    monitor = Node(
        package="ltl_automaton_std_transition_systems",
        executable="region_2d_pose_monitor",
        parameters=[
            {
                "transition_system_path": (
                    package_share + "/config/example_2d_pose_ts.yaml"
                ),
                "pose_message_type": "geometry_msgs/msg/Pose",
            }
        ],
    )
    joint_monitor = Node(
        package="ltl_automaton_std_transition_systems",
        executable="region_6d_jointspace_monitor",
        parameters=[
            {
                "transition_system_path": (
                    package_share + "/config/example_6d_jointspace_ts.yaml"
                )
            }
        ],
        remappings=[
            ("feedback/joint_state", "joint_feedback"),
            ("current_region", "joint_current_region"),
        ],
    )
    return (
        LaunchDescription(
            [
                monitor,
                joint_monitor,
                launch_testing.actions.ReadyToTest(),
            ]
        ),
        {"monitor": monitor, "joint_monitor": joint_monitor},
    )


class TestMonitorCommunication(unittest.TestCase):
    """Exercise pose monitoring, station access, and closest-state service."""

    @classmethod
    def setUpClass(cls):
        """Create a ROS 2 node for the test workflow."""
        rclpy.init()
        cls.node = rclpy.create_node("region_monitor_launch_test")

    @classmethod
    def tearDownClass(cls):
        """Destroy the test node and ROS 2 context."""
        cls.node.destroy_node()
        rclpy.shutdown()

    def _spin_until(self, predicate, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            rclpy.spin_once(self.node, timeout_sec=0.1)
        return predicate()

    def _publish_until(self, publisher, message, predicate):
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            publisher.publish(message)
            if self._spin_until(predicate, timeout=0.2):
                return True
        return predicate()

    def test_pose_station_and_closest_region_contract(self):
        """Verify the public ROS interfaces against the example TS."""
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        regions = []
        subscription = self.node.create_subscription(
            String,
            "current_region",
            lambda message: regions.append(message.data),
            qos,
        )
        pose_publisher = self.node.create_publisher(
            Pose, "agent_2d_region_pose", 10
        )
        station_publisher = self.node.create_publisher(
            String, "station_access_request", 10
        )
        client = self.node.create_client(ClosestState, "closest_region")

        pose = Pose()
        pose.position.x = 0.5
        pose.position.y = 0.5
        pose.orientation.w = 1.0
        self.assertTrue(
            self._publish_until(
                pose_publisher, pose, lambda: regions and regions[-1] == "r1"
            )
        )

        self.assertTrue(client.wait_for_service(timeout_sec=5.0))
        future = client.call_async(ClosestState.Request())
        self.assertTrue(self._spin_until(future.done))
        response = future.result()
        self.assertEqual(response.closest_state, "s0")
        self.assertAlmostEqual(response.metric, -0.15)

        station_publisher.publish(String(data="s0"))
        self._spin_until(lambda: False, timeout=0.2)
        self.assertTrue(
            self._publish_until(
                pose_publisher, pose, lambda: regions and regions[-1] == "s0"
            )
        )
        self.node.destroy_subscription(subscription)

    def test_joint_state_region_contract(self):
        """Verify the 6D monitor publishes connected joint-space regions."""
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        regions = []
        subscription = self.node.create_subscription(
            String,
            "joint_current_region",
            lambda message: regions.append(message.data),
            qos,
        )
        publisher = self.node.create_publisher(
            JointState, "joint_feedback", 10
        )
        self.assertTrue(
            self._publish_until(
                publisher,
                JointState(position=[0.0] * 6),
                lambda: regions and regions[-1] == "q1",
            )
        )
        self.assertTrue(
            self._publish_until(
                publisher,
                JointState(position=[1.0] * 6),
                lambda: regions and regions[-1] == "q2",
            )
        )
        self.node.destroy_subscription(subscription)


@launch_testing.post_shutdown_test()
class TestMonitorShutdown(unittest.TestCase):
    """Check that the monitor exits cleanly with launch shutdown."""

    def test_exit_code(self, proc_info, monitor, joint_monitor):
        """Require the standard launch-testing shutdown exit codes."""
        launch_testing.asserts.assertExitCodes(
            proc_info,
            process=monitor,
            allowable_exit_codes=[0, -2],
        )
        launch_testing.asserts.assertExitCodes(
            proc_info,
            process=joint_monitor,
            allowable_exit_codes=[0, -2],
        )
