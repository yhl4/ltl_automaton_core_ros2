"""Launch-level communication test for the ROS2 planner node."""

import time
import unittest

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import launch_testing
import launch_testing.actions
import launch_testing.asserts
import pytest
import rclpy
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import String

from ltl_automaton_msgs.msg import (
    LTLPlan,
    LTLStateArray,
    PlannerStatus,
    TransitionSystemStateStamped,
)
from ltl_automaton_msgs.srv import (
    GetPlanningGraphSnapshot,
    LoadTransitionSystem,
    TaskPlanning,
)


@pytest.mark.launch_test
def generate_test_description():
    """Launch the planner with its installed minimal TS configuration."""
    package_share = get_package_share_directory(
        "ltl_automaton_planner"
    )
    planner = Node(
        package="ltl_automaton_planner",
        executable="planner_node",
        name="ltl_planner",
        parameters=[
            {
                "transition_system_path": (
                    package_share + "/config/minimal_ts.yaml"
                ),
                "hard_task": "<> r2",
                "soft_task": "(r2 || ! r2)",
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


class TestPlannerCommunication(unittest.TestCase):
    """Exercise initial output, state feedback, and task replanning."""

    @classmethod
    def setUpClass(cls):
        """Create one ROS2 test node for the communication workflow."""
        rclpy.init()
        cls.node = rclpy.create_node("planner_launch_test")

    @classmethod
    def tearDownClass(cls):
        """Destroy the test node and shut down its ROS2 context."""
        cls.node.destroy_node()
        rclpy.shutdown()

    def _spin_until(self, predicate, timeout=8.0):
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if predicate():
                return True

            rclpy.spin_once(self.node, timeout_sec=0.1)

        return predicate()

    def test_planner_topics_feedback_and_service(self):
        """Verify the public planner communication contract end to end."""
        command_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        next_moves = []
        prefix_plans = []
        suffix_plans = []
        possible_states = []
        planner_statuses = []

        subscriptions = [
            self.node.create_subscription(
                String,
                "next_move_cmd",
                lambda message: next_moves.append(message.data),
                command_qos,
            ),
            self.node.create_subscription(
                LTLPlan,
                "prefix_plan",
                prefix_plans.append,
                command_qos,
            ),
            self.node.create_subscription(
                LTLPlan,
                "suffix_plan",
                suffix_plans.append,
                command_qos,
            ),
            self.node.create_subscription(
                LTLStateArray,
                "possible_ltl_states",
                possible_states.append,
                command_qos,
            ),
            self.node.create_subscription(
                PlannerStatus,
                "planner_status",
                planner_statuses.append,
                command_qos,
            ),
        ]

        self.assertTrue(
            self._spin_until(
                lambda: (
                    next_moves
                    and prefix_plans
                    and suffix_plans
                    and possible_states
                    and planner_statuses
                )
            )
        )
        self.assertEqual(
            planner_statuses[-1].state,
            PlannerStatus.ACTIVE,
        )
        self.assertEqual(next_moves[-1], "goto_r2")
        self.assertEqual(
            list(prefix_plans[-1].action_sequence),
            ["goto_r2", "stay_r2"],
        )
        self.assertEqual(
            list(suffix_plans[-1].action_sequence),
            ["stay_r2", "stay_r2"],
        )
        self.assertEqual(
            list(possible_states[-1].ltl_states[0].ts_state.states),
            ["r1"],
        )

        snapshot_client = self.node.create_client(
            GetPlanningGraphSnapshot,
            "get_planning_graph_snapshot",
        )
        self.assertTrue(
            snapshot_client.wait_for_service(timeout_sec=5.0)
        )
        first_snapshot_future = snapshot_client.call_async(
            GetPlanningGraphSnapshot.Request()
        )
        rclpy.spin_until_future_complete(
            self.node,
            first_snapshot_future,
            timeout_sec=8.0,
        )
        first_snapshot = first_snapshot_future.result()
        self.assertIsNotNone(first_snapshot)
        self.assertTrue(first_snapshot.success)
        self.assertEqual(
            first_snapshot.snapshot.metadata.planning_generation,
            1,
        )
        self.assertEqual(
            first_snapshot.snapshot.metadata.product_node_count,
            len(first_snapshot.snapshot.product_nodes),
        )
        product_ids = {
            node.id for node in first_snapshot.snapshot.product_nodes
        }
        self.assertTrue(
            set(
                first_snapshot
                .snapshot
                .accepted_run
                .prefix_product_node_ids
            ).issubset(product_ids)
        )
        self.assertTrue(
            set(
                first_snapshot
                .snapshot
                .accepted_run
                .suffix_product_node_ids
            ).issubset(product_ids)
        )

        state_publisher = self.node.create_publisher(
            TransitionSystemStateStamped,
            "ts_state",
            10,
        )
        self.assertTrue(
            self._spin_until(
                lambda: state_publisher.get_subscription_count() > 0
            )
        )

        state_message = TransitionSystemStateStamped()
        state_message.header.stamp = self.node.get_clock().now().to_msg()
        state_message.ts_state.states = ["r2"]
        state_message.ts_state.state_dimension_names = ["region"]
        state_publisher.publish(state_message)

        self.assertTrue(
            self._spin_until(
                lambda: next_moves and next_moves[-1] == "stay_r2"
            )
        )
        self.assertEqual(
            list(possible_states[-1].ltl_states[0].ts_state.states),
            ["r2"],
        )

        cursor_snapshot_future = snapshot_client.call_async(
            GetPlanningGraphSnapshot.Request()
        )
        rclpy.spin_until_future_complete(
            self.node,
            cursor_snapshot_future,
            timeout_sec=8.0,
        )
        self.assertEqual(
            cursor_snapshot_future.result().snapshot,
            first_snapshot.snapshot,
        )

        replanning_client = self.node.create_client(
            TaskPlanning,
            "replanning",
        )
        self.assertTrue(replanning_client.wait_for_service(timeout_sec=5.0))

        request = TaskPlanning.Request()
        request.hard_task = "<> r2"
        request.soft_task = "(r2 || ! r2)"
        future = replanning_client.call_async(request)
        rclpy.spin_until_future_complete(
            self.node,
            future,
            timeout_sec=8.0,
        )

        self.assertTrue(future.done())
        self.assertIsNotNone(future.result())
        self.assertTrue(future.result().success)

        replanned_snapshot_future = snapshot_client.call_async(
            GetPlanningGraphSnapshot.Request()
        )
        rclpy.spin_until_future_complete(
            self.node,
            replanned_snapshot_future,
            timeout_sec=8.0,
        )
        replanned_snapshot = replanned_snapshot_future.result()
        self.assertTrue(replanned_snapshot.success)
        self.assertEqual(
            replanned_snapshot.snapshot.metadata.planning_generation,
            2,
        )
        self.assertEqual(
            replanned_snapshot.snapshot.metadata.hard_task,
            request.hard_task,
        )

        load_client = self.node.create_client(
            LoadTransitionSystem,
            "load_transition_system",
        )
        self.assertTrue(load_client.wait_for_service(timeout_sec=5.0))

        load_request = LoadTransitionSystem.Request()
        load_request.transition_system_yaml = "state_dim: []\n"
        load_future = load_client.call_async(load_request)
        rclpy.spin_until_future_complete(
            self.node,
            load_future,
            timeout_sec=5.0,
        )

        self.assertTrue(load_future.done())
        self.assertIsNotNone(load_future.result())
        self.assertFalse(load_future.result().success)
        self.assertTrue(load_future.result().active_ts_sha256)
        self.assertEqual(
            planner_statuses[-1].state,
            PlannerStatus.ACTIVE,
        )

        for subscription in subscriptions:
            self.node.destroy_subscription(subscription)

        self.node.destroy_publisher(state_publisher)
        self.node.destroy_client(replanning_client)
        self.node.destroy_client(load_client)
        self.node.destroy_client(snapshot_client)


@launch_testing.post_shutdown_test()
class TestPlannerShutdown(unittest.TestCase):
    """Verify that launch teardown stops the planner cleanly."""

    def test_exit_code(self, proc_info):
        """Require a successful planner process exit."""
        launch_testing.asserts.assertExitCodes(proc_info)
