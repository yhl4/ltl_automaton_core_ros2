"""Launch-level tests for the read-only TrapDetection planner plugin."""

import time
import unittest

from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
import launch_testing
import launch_testing.actions
import launch_testing.asserts
from ltl_automaton_msgs.msg import (
    PlanningExecutionObservation,
    TransitionSystemState,
)
from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot, TrapCheck
from ltl_automaton_msgs.action import PlanLTL
import pytest
import rclpy
from rclpy.action import ActionClient
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy


@pytest.mark.launch_test
def generate_test_description():
    """Launch the planner with only the read-only trap plugin enabled."""
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
                    "([]<> (r1 && loaded)) && ([]<> (r1 && unloaded)) "
                    "&& ([] ! r3)"
                ),
                "soft_task": "(r2 || ! r2)",
                "plugin_config_path": (
                    plugin_share + "/config/trap_detection_plugin.yaml"
                ),
            }
        ],
    )
    return (
        LaunchDescription([planner, launch_testing.actions.ReadyToTest()]),
        {"planner": planner},
    )


class TestTrapPluginService(unittest.TestCase):
    """Trap diagnosis must not change the committed planning identity."""

    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("trap_plugin_service_test")
        cls.client = cls.node.create_client(TrapCheck, "check_for_trap")
        cls.snapshot_client = cls.node.create_client(
            GetPlanningGraphSnapshot,
            "get_planning_graph_snapshot",
        )
        cls.action_client = ActionClient(cls.node, PlanLTL, "plan_ltl")
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        cls.observations = []
        cls.observation_subscription = cls.node.create_subscription(
            PlanningExecutionObservation,
            "planning_execution_observation",
            cls.observations.append,
            qos,
        )

    @classmethod
    def tearDownClass(cls):
        cls.action_client.destroy()
        cls.node.destroy_node()
        rclpy.shutdown()

    def _spin_until(self, predicate, timeout=8.0):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
        self.assertTrue(predicate())

    def _call_trap(self, region, load):
        request = TrapCheck.Request(
            ts_state=TransitionSystemState(
                states=[load, region],
                state_dimension_names=[
                    "turtlebot_load",
                    "2d_pose_region",
                ],
            )
        )
        future = self.client.call_async(request)
        self._spin_until(future.done)
        return future.result()

    def _snapshot(self):
        future = self.snapshot_client.call_async(
            GetPlanningGraphSnapshot.Request()
        )
        self._spin_until(future.done)
        self.assertTrue(future.result().success)
        return future.result().snapshot

    def _replace_task(self, snapshot, hard_task):
        self.assertTrue(self.action_client.wait_for_server(timeout_sec=3.0))
        initial_id = snapshot.accepted_run.prefix_product_node_ids[0]
        initial = next(node.ts_state for node in snapshot.product_nodes if node.id == initial_id)
        goal = PlanLTL.Goal(
            hard_task=hard_task, soft_task=snapshot.metadata.soft_task,
            initial_state=initial, beta=1000.0, gamma=10.0,
        )
        goal_future = self.action_client.send_goal_async(goal)
        self._spin_until(goal_future.done)
        handle = goal_future.result()
        self.assertTrue(handle.accepted)
        result_future = handle.get_result_async()
        self._spin_until(result_future.done)
        result = result_future.result()
        self.assertEqual(result.status, GoalStatus.STATUS_SUCCEEDED)
        self.assertTrue(result.result.success)

    def test_replacement_plan_changes_trap_diagnosis(self):
        """Classify against the newly committed task without stale graph reuse."""
        self._spin_until(lambda: self.client.service_is_ready())
        self._spin_until(lambda: self.snapshot_client.service_is_ready())
        before = self._snapshot()
        self.assertFalse(self._call_trap("r2", "unloaded").is_trap)
        try:
            self._replace_task(before, "[] !r2")
            after = self._snapshot()
            self.assertGreater(
                after.metadata.planning_generation, before.metadata.planning_generation,
            )
            diagnosed = self._call_trap("r2", "unloaded")
            self.assertTrue(diagnosed.is_connected)
            self.assertTrue(diagnosed.is_trap)
        finally:
            self._replace_task(before, before.metadata.hard_task)

    def test_trap_diagnosis_preserves_formal_identity(self):
        self._spin_until(
            lambda: self.client.wait_for_service(timeout_sec=0.0)
        )
        self._spin_until(
            lambda: self.snapshot_client.wait_for_service(timeout_sec=0.0)
        )
        self._spin_until(lambda: bool(self.observations))

        before = self._snapshot()
        before_observation = self.observations[-1]
        self.assertTrue(self._call_trap("r2", "unloaded").is_connected)
        self.assertTrue(self._call_trap("r3", "unloaded").is_trap)
        self.assertFalse(self._call_trap("r2", "loaded").is_connected)

        after = self._snapshot()
        after_observation = self.observations[-1]
        self.assertEqual(
            after.metadata.planner_instance_id,
            before.metadata.planner_instance_id,
        )
        self.assertEqual(
            after.metadata.planning_generation,
            before.metadata.planning_generation,
        )
        self.assertEqual(
            after.metadata.active_ts_sha256,
            before.metadata.active_ts_sha256,
        )
        self.assertEqual(after.accepted_run, before.accepted_run)
        self.assertEqual(
            after_observation.planner_instance_id,
            before_observation.planner_instance_id,
        )
        self.assertEqual(
            after_observation.planning_generation,
            before_observation.planning_generation,
        )


@launch_testing.post_shutdown_test()
class TestTrapPluginShutdown(unittest.TestCase):
    def test_exit_code(self, proc_info, planner):
        launch_testing.asserts.assertExitCodes(
            proc_info,
            process=planner,
            allowable_exit_codes=[0, -2],
        )
