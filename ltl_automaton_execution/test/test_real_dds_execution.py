"""Real Core plus FakeBackend execution-loop regressions."""

from pathlib import Path
import time

from action_msgs.msg import GoalStatus
import rclpy
from rclpy.action import ActionClient
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor

from ltl_automaton_msgs.action import PlanLTL
from ltl_automaton_msgs.msg import PlanningExecutionObservation
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import LoadTransitionSystem
from ltl_automaton_execution.execution_node import COMMAND_QOS
from ltl_automaton_execution.execution_node import ExecutionManagerNode
from ltl_automaton_planner.planner_node import PlannerNode


HOUSEHOLD_TS = (
    Path(__file__).parents[2]
    / "ltl_automaton_planner"
    / "config"
    / "demo_d1_household_ts.yaml"
)
DIMENSIONS = ["2d_pose_region", "gripper_state"]
NEUTRAL = "(b0 || ! b0)"


class RealExecutionHarness:
    """Spin public Core and execution contracts without private assertions."""

    def __init__(self):
        self.context = Context()
        rclpy.init(context=self.context)
        self.planner = PlannerNode(context=self.context)
        self.execution = ExecutionManagerNode(
            context=self.context,
            execution_delay_sec=0.005,
        )
        self.driver = rclpy.create_node(
            "real_fake_execution_test",
            context=self.context,
        )
        self.executor = SingleThreadedExecutor(context=self.context)
        for node in (self.planner, self.execution, self.driver):
            self.executor.add_node(node)
        self.action_client = ActionClient(self.driver, PlanLTL, "plan_ltl")
        self.load_client = self.driver.create_client(
            LoadTransitionSystem,
            "load_transition_system",
        )
        self.states = []
        self.observations = []
        self.state_subscription = self.driver.create_subscription(
            TransitionSystemStateStamped,
            "ts_state",
            self._record_state,
            10,
        )
        self.observation_subscription = self.driver.create_subscription(
            PlanningExecutionObservation,
            "planning_execution_observation",
            self.observations.append,
            COMMAND_QOS,
        )

    def _record_state(self, message):
        self.states.append(tuple(message.ts_state.states))

    def wait(self, predicate, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            self.executor.spin_once(timeout_sec=0.02)
        return predicate()

    def load(self):
        assert self.load_client.wait_for_service(timeout_sec=3.0)
        request = LoadTransitionSystem.Request()
        request.transition_system_yaml = HOUSEHOLD_TS.read_text(
            encoding="utf-8"
        )
        future = self.load_client.call_async(request)
        assert self.wait(future.done)
        assert future.result().success

    def plan(self, initial, hard_task):
        assert self.action_client.wait_for_server(timeout_sec=3.0)
        goal = PlanLTL.Goal()
        goal.hard_task = hard_task
        goal.soft_task = NEUTRAL
        goal.initial_state.state_dimension_names = DIMENSIONS
        goal.initial_state.states = list(initial)
        goal.beta = 1000.0
        goal.gamma = 10.0
        goal_future = self.action_client.send_goal_async(goal)
        assert self.wait(goal_future.done)
        goal_handle = goal_future.result()
        assert goal_handle.accepted
        result_future = goal_handle.get_result_async()
        assert self.wait(result_future.done, timeout=20.0)
        response = result_future.result()
        assert response.status == GoalStatus.STATUS_SUCCEEDED
        return response.result

    def stop(self):
        self.executor.remove_node(self.driver)
        self.executor.remove_node(self.execution)
        self.executor.remove_node(self.planner)
        self.action_client.destroy()
        self.driver.destroy_node()
        self.execution.destroy_node()
        self.planner.destroy_node()
        self.executor.shutdown()
        rclpy.shutdown(context=self.context)


def _subsequence(sequence, expected):
    iterator = iter(sequence)
    return all(any(item == wanted for item in iterator) for wanted in expected)


def _wait_stable(harness, quiet_duration=0.2, timeout=2.0):
    count = len(harness.states)
    quiet_since = time.monotonic()
    deadline = quiet_since + timeout
    while time.monotonic() < deadline:
        harness.executor.spin_once(timeout_sec=0.02)
        if len(harness.states) != count:
            count = len(harness.states)
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= quiet_duration:
            return True
    return False


def test_real_dds_t1_and_current_state_closure():
    """T1 executes automatically and a later plan starts from executed k0."""
    harness = RealExecutionHarness()
    try:
        harness.load()
        first = harness.plan(("l0", "empty"), "<>(k0)")
        assert first.success
        assert harness.wait(lambda: ("k0", "empty") in harness.states)
        progression = [("l0", "empty"), *harness.states]
        assert _subsequence(progression, [
            ("l0", "empty"),
            ("d0", "empty"),
            ("n1", "empty"),
            ("k0", "empty"),
        ])
        assert harness.wait(
            lambda: harness.observations
            and harness.observations[-1].planning_generation == 1
        )
        assert _wait_stable(harness)

        second = harness.plan(("k0", "empty"), "<>(b0)")
        assert second.success
        assert second.error_code == PlanLTL.Result.ERROR_NONE
        assert harness.wait(
            lambda: any(
                observation.planning_generation == 2
                for observation in harness.observations
            )
        )
    finally:
        harness.stop()


def test_real_dds_t3_executes_navigation_pick_and_place():
    """T3 uses the same resolver/backend seam for motion and interaction."""
    harness = RealExecutionHarness()
    try:
        harness.load()
        result = harness.plan(
            ("l0", "empty"),
            "<>(holding && <>(empty))",
        )
        assert result.success
        assert harness.wait(lambda: ("bp0", "empty") in harness.states)
        progression = [("l0", "empty"), *harness.states]
        assert _subsequence(progression, [
            ("lp0", "empty"),
            ("lp0", "holding"),
            ("bp0", "holding"),
            ("bp0", "empty"),
        ])
        assert _wait_stable(harness)
    finally:
        harness.stop()
