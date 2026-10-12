"""In-process ROS2 integration test for IRL preference learning."""

from pathlib import Path
import math
import tempfile
import time
import unittest

from action_msgs.msg import GoalStatus
from ltl_automaton_msgs.action import PlanLTL
from ltl_automaton_msgs.msg import (
    LTLStateRuns,
    PlanningExecutionObservation,
    TransitionSystemState,
    TransitionSystemStateStamped,
)
from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot
from ltl_automaton_planner.planner_node import PlannerNode
import rclpy
from rclpy.action import ActionClient
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from std_msgs.msg import Bool


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TS_PATH = Path(tempfile.gettempdir()) / "ltl_irl_preference_ts.yaml"
TS_PATH.write_text(
    """state_dim:
  - region
state_models:
  region:
    initial: hub
    nodes:
      hub:
        connected_to:
          bad: to_bad
          good: to_good
      bad:
        connected_to:
          hub: bad_return
      good:
        connected_to:
          hub: good_return
actions:
  to_bad:
    guard: "1"
    weight: 0.0
  to_good:
    guard: "1"
    weight: 4.0
  bad_return:
    guard: "1"
    weight: 0.0
  good_return:
    guard: "1"
    weight: 0.0
""",
    encoding="utf-8",
)


class TestIRLPreferenceDDS(unittest.TestCase):
    """Exercise the real PlannerNode and IRL plugin in one ROS context."""

    def setUp(self):
        self.context = rclpy.context.Context()
        rclpy.init(context=self.context)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.planner = None
        self.client_node = None

        try:
            self.planner = PlannerNode(
                context=self.context,
                parameter_overrides=[
                    Parameter("transition_system_path", value=str(TS_PATH)),
                    Parameter("hard_task", value="[]<> hub"),
                    Parameter("soft_task", value="[] !bad"),
                    Parameter("beta", value=1.0),
                    Parameter("gamma", value=1.0),
                    Parameter(
                        "plugin_config_path",
                        value=str(PACKAGE_ROOT / "config" / "irl_plugin.yaml"),
                    ),
                    Parameter("replan_on_unplanned_move", value=False),
                    Parameter("check_timestamp", value=True),
                ],
            )
            self.client_node = rclpy.create_node(
                "irl_preference_test_client",
                context=self.context,
            )
            self.executor.add_node(self.planner)
            self.executor.add_node(self.client_node)
        except Exception:
            self._destroy_nodes()
            raise

    def tearDown(self):
        self._destroy_nodes()

    def _destroy_nodes(self):
        if self.executor is not None:
            self.executor.shutdown()
        if self.client_node is not None:
            self.client_node.destroy_node()
            self.client_node = None
        if self.planner is not None:
            self.planner.destroy_node()
            self.planner = None
        if self.context is not None and self.context.ok():
            rclpy.shutdown(context=self.context)

    def _spin_until(self, predicate, timeout=30.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            self.executor.spin_once(timeout_sec=0.1)
        return predicate()

    def _feedback(self, state, stamp_base, offset):
        message = TransitionSystemStateStamped()
        message.header.stamp.sec = stamp_base.sec + offset
        message.header.stamp.nanosec = stamp_base.nanosec
        message.ts_state = TransitionSystemState(
            states=[state],
            state_dimension_names=["region"],
        )
        return message

    def _plan(self, action_client):
        self.assertTrue(action_client.wait_for_server(timeout_sec=5.0))
        goal = PlanLTL.Goal(
            hard_task="[]<> hub",
            soft_task="[] !bad",
            initial_state=TransitionSystemState(
                states=["hub"],
                state_dimension_names=["region"],
            ),
            beta=1.0,
            gamma=1.0,
        )
        goal_future = action_client.send_goal_async(goal)
        self.assertTrue(self._spin_until(goal_future.done))
        goal_handle = goal_future.result()
        self.assertTrue(goal_handle.accepted)
        result_future = goal_handle.get_result_async()
        self.assertTrue(self._spin_until(result_future.done))
        result = result_future.result()
        self.assertEqual(result.status, GoalStatus.STATUS_SUCCEEDED)
        self.assertTrue(result.result.success, result.result.message)

    def test_teaching_preference_commits_new_beta(self):
        """A good demonstration raises beta and preserves the old planner."""
        qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        observations = []
        run_messages = []
        state_publisher = self.client_node.create_publisher(
            TransitionSystemStateStamped,
            "/ts_state",
            10,
        )
        trigger_publisher = self.client_node.create_publisher(
            Bool,
            "/irl_trigger",
            qos,
        )
        self.client_node.create_subscription(
            PlanningExecutionObservation,
            "/planning_execution_observation",
            observations.append,
            qos,
        )
        self.client_node.create_subscription(
            LTLStateRuns,
            "/possible_runs",
            run_messages.append,
            qos,
        )
        action_client = ActionClient(
            self.client_node,
            PlanLTL,
            "/plan_ltl",
        )
        snapshot_client = self.client_node.create_client(
            GetPlanningGraphSnapshot,
            "/get_planning_graph_snapshot",
        )

        self.assertTrue(
            self._spin_until(
                lambda: self.planner.ltl_planner is not None
                and self.planner._planner_state != 0
            )
        )
        self._plan(action_client)
        self.assertTrue(
            self._spin_until(
                lambda: observations
                and observations[-1].planning_generation >= 2
            )
        )
        initial_generation = observations[-1].planning_generation
        initial_instance = observations[-1].planner_instance_id
        plugin = self.planner.plugins["IRLPlugin"]
        old_planner = self.planner.ltl_planner

        self.assertEqual(old_planner.beta, 1.0)
        self.assertEqual(old_planner.hard_spec, "[]<> hub")
        self.assertEqual(old_planner.soft_spec, "[] !bad")
        self.assertTrue(
            self._spin_until(
                lambda: trigger_publisher.get_subscription_count() > 0
                and state_publisher.get_subscription_count() > 0
            )
        )
        trigger_publisher.publish(Bool(data=True))
        self.assertTrue(
            self._spin_until(lambda: plugin.learning_trigger)
        )

        stamp_base = self.planner.get_clock().now().to_msg()
        state_publisher.publish(self._feedback("good", stamp_base, 10))
        self.assertTrue(
            self._spin_until(
                lambda: any(
                    len(run) >= 2
                    for run in plugin.possible_runs
                )
            )
        )
        state_publisher.publish(self._feedback("hub", stamp_base, 20))
        self.assertTrue(
            self._spin_until(
                lambda: any(
                    len(run) >= 3
                    for run in plugin.possible_runs
                )
            )
        )
        teaching_run = next(
            run for run in plugin.possible_runs if len(run) >= 3
        )
        self.assertTrue(plugin.learning_trigger)
        self.assertEqual(teaching_run[0][0], ("hub",))
        self.assertEqual(teaching_run[1][0], ("good",))
        self.assertEqual(teaching_run[2][0], ("hub",))
        self.assertTrue(
            all(
                old_planner.product.has_edge(source, target)
                for source, target in zip(teaching_run, teaching_run[1:])
            )
        )

        old_beta = old_planner.beta
        old_initial = set(old_planner.product.graph["initial"])
        old_possible_states = set(old_planner.product.possible_states)
        old_edges = {
            (source, target): dict(attributes)
            for source, target, attributes in old_planner.product.edges(
                data=True
            )
        }
        old_run = old_planner.run
        trigger_publisher.publish(Bool(data=False))
        self.assertTrue(
            self._spin_until(
                lambda: self.planner._planning_generation
                > initial_generation
            )
        )
        new_planner = self.planner.ltl_planner
        self.assertIsNot(new_planner, old_planner)
        self.assertGreater(new_planner.beta, 1.0)
        self.assertTrue(math.isfinite(new_planner.beta))
        self.assertEqual(new_planner.hard_spec, "[]<> hub")
        self.assertEqual(new_planner.soft_spec, "[] !bad")
        self.assertIsNotNone(new_planner.run)
        self.assertTrue(math.isfinite(new_planner.run.totalcost))
        self.assertEqual(old_planner.beta, old_beta)
        self.assertEqual(old_planner.beta, 1.0)
        self.assertIs(old_planner.run, old_run)
        self.assertEqual(set(old_planner.product.graph["initial"]), old_initial)
        self.assertEqual(set(old_planner.product.possible_states), old_possible_states)
        self.assertEqual(
            {
                (source, target): dict(attributes)
                for source, target, attributes in old_planner.product.edges(
                    data=True
                )
            },
            old_edges,
        )

        self.assertTrue(
            self._spin_until(
                lambda: observations
                and observations[-1].planning_generation
                > initial_generation
            )
        )
        committed = observations[-1]
        self.assertEqual(committed.planner_instance_id, initial_instance)
        self.assertEqual(committed.execution_step_seq, 0)
        self.assertTrue(snapshot_client.wait_for_service(timeout_sec=5.0))
        snapshot_future = snapshot_client.call_async(
            GetPlanningGraphSnapshot.Request()
        )
        self.assertTrue(self._spin_until(snapshot_future.done))
        snapshot_response = snapshot_future.result()
        self.assertTrue(snapshot_response.success, snapshot_response.message)
        snapshot = snapshot_response.snapshot
        self.assertTrue(snapshot.metadata.available)
        self.assertEqual(snapshot.metadata.planning_generation, committed.planning_generation)
        self.assertEqual(snapshot.metadata.hard_task, "[]<> hub")
        self.assertEqual(snapshot.metadata.soft_task, "[] !bad")
        self.assertTrue(snapshot.accepted_run.suffix_product_node_ids)
        for edge in snapshot.product_edges:
            self.assertAlmostEqual(
                edge.total_weight,
                edge.transition_cost
                + new_planner.beta * edge.soft_task_distance,
            )


if __name__ == "__main__":
    unittest.main()
