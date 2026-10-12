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
from ltl_automaton_execution.fake_runtime import FakePlant
from ltl_automaton_execution.fake_runtime import FakeStateAbstraction
from ltl_automaton_execution.fake_runtime import FakeStateObserver
from ltl_automaton_planner.planner_node import PlannerNode


HOUSEHOLD_TS = (
    Path(__file__).parents[2]
    / "ltl_automaton_planner"
    / "config"
    / "demo_d1_household_ts.yaml"
)
DIMENSIONS = ["2d_pose_region", "gripper_state"]
NEUTRAL = "(b0 || ! b0)"
CYCLE_TS = """
state_dim: [region]
state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to: {r2: goto_r2}
      r2:
        connected_to: {r1: goto_r1}
actions:
  goto_r1: {guard: '1', weight: 1.0}
  goto_r2: {guard: '1', weight: 1.0}
"""
SELF_LOOP_TS = """
state_dim: [region]
state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to: {r1: wait}
actions:
  wait: {guard: '1', weight: 1.0}
"""


class InstrumentedObserver:
    """Record the observer boundary while delegating fake observation."""

    def __init__(self, plant):
        self._observer = FakeStateObserver(plant)
        self.states = []

    def start(self, on_observation):
        def record(observation):
            self.states.append(tuple(observation.state.states))
            on_observation(observation)

        self._observer.start(record)

    def stop(self):
        self._observer.stop()


class InstrumentedAbstraction:
    """Record successful fake abstractions before ROS publication."""

    def __init__(self):
        self._abstraction = FakeStateAbstraction()
        self.states = []

    def abstract(self, observation):
        state = self._abstraction.abstract(observation)
        if state is not None:
            self.states.append(tuple(state.states))
        return state


class RealExecutionHarness:
    """Spin public Core and execution contracts without private assertions."""

    def __init__(self):
        self.context = Context()
        self.execution_paused = False
        rclpy.init(context=self.context)
        self.planner = PlannerNode(context=self.context)
        self.plant = FakePlant()
        self.plant_states = []
        self.plant.add_listener(
            lambda observation: self.plant_states.append(
                tuple(observation.state.states)
            )
        )
        self.state_observer = InstrumentedObserver(self.plant)
        self.state_abstraction = InstrumentedAbstraction()
        self.execution = ExecutionManagerNode(
            context=self.context,
            fake_plant=self.plant,
            state_observer=self.state_observer,
            state_abstraction=self.state_abstraction,
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

    def load(self, yaml_content=None):
        assert self.load_client.wait_for_service(timeout_sec=3.0)
        request = LoadTransitionSystem.Request()
        request.transition_system_yaml = (
            HOUSEHOLD_TS.read_text(encoding="utf-8")
            if yaml_content is None else yaml_content
        )
        future = self.load_client.call_async(request)
        assert self.wait(future.done)
        assert future.result().success

    def plan(self, initial, hard_task, dimensions=DIMENSIONS, soft_task=NEUTRAL):
        assert self.action_client.wait_for_server(timeout_sec=3.0)
        goal = PlanLTL.Goal()
        goal.hard_task = hard_task
        goal.soft_task = soft_task
        goal.initial_state.state_dimension_names = dimensions
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

    def pause_execution(self):
        """Stop scheduling new fake steps and drain already published truth."""
        self.executor.remove_node(self.execution)
        self.execution_paused = True
        assert self.wait(lambda: len(self.states) == len(self.plant_states))

    def resume_execution(self):
        self.executor.add_node(self.execution)
        self.execution_paused = False

    def stop(self):
        self.executor.remove_node(self.driver)
        if not self.execution_paused:
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


def _wait_steps(harness, generation, minimum):
    return harness.wait(lambda: any(
        item.planning_generation == generation and item.execution_step_seq >= minimum
        for item in harness.observations
    ))


def _assert_observation_pipeline(harness):
    assert harness.plant_states
    assert harness.plant_states == harness.state_observer.states
    assert harness.state_observer.states == harness.state_abstraction.states
    assert harness.state_abstraction.states == harness.states


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
        assert _wait_steps(harness, 1, 8)
        harness.pause_execution()
        _assert_observation_pipeline(harness)

        second = harness.plan(("k0", "empty"), "<>(b0)")
        assert second.success
        assert second.error_code == PlanLTL.Result.ERROR_NONE
        harness.resume_execution()
        assert harness.wait(
            lambda: any(
                observation.planning_generation == 2
                for observation in harness.observations
            )
        )
        assert harness.wait(lambda: harness.states[-1] == ("b0", "empty"))
        assert _wait_steps(harness, 2, 8)
        harness.pause_execution()
        _assert_observation_pipeline(harness)
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
        assert _wait_steps(harness, 1, 10)
        harness.pause_execution()
        _assert_observation_pipeline(harness)
    finally:
        harness.stop()


def test_real_dds_two_state_accepting_cycle_keeps_dispatching():
    """Execute beyond the four steps previously suppressed by fingerprints."""
    harness = RealExecutionHarness()
    try:
        harness.load(CYCLE_TS)
        assert harness.plan(
            ("r1",), "([]<> r1) && ([]<> r2)", ["region"], "(r1 || !r1)",
        ).success
        assert _wait_steps(harness, 1, 10)
        harness.pause_execution()
        assert harness.states.count(("r1",)) >= 4
        assert harness.states.count(("r2",)) >= 4
        assert {item.planning_generation for item in harness.observations} == {1}
        sequences = [item.execution_step_seq for item in harness.observations]
        assert sequences == sorted(sequences)
        _assert_observation_pipeline(harness)
    finally:
        harness.stop()


def test_real_dds_same_state_self_loop_uses_new_steps():
    """Repeated state and action still execute with advancing command steps."""
    harness = RealExecutionHarness()
    try:
        harness.load(SELF_LOOP_TS)
        assert harness.plan(("r1",), "[] r1", ["region"], "(r1 || !r1)").success
        assert _wait_steps(harness, 1, 8)
        harness.pause_execution()
        assert len(harness.states) >= 8
        assert set(harness.states) == {("r1",)}
        assert {item.next_action for item in harness.observations} == {"wait"}
        _assert_observation_pipeline(harness)
    finally:
        harness.stop()
