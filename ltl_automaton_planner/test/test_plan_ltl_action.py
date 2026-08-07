"""Integration tests for the transactional PlanLTL action wrapper."""

from threading import Event
import time
from types import SimpleNamespace

from action_msgs.msg import GoalStatus
import pytest
import rclpy
from rclpy.action import ActionClient
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
)

from ltl_automaton_msgs.action import PlanLTL
from ltl_automaton_msgs.msg import (
    LTLPlan,
    PlannerStatus,
    TransitionSystemStateStamped,
)
from ltl_automaton_msgs.srv import LoadTransitionSystem, TaskPlanning
import ltl_automaton_planner.planner_node as planner_module
from ltl_automaton_planner.planner_node import PlannerNode


VALID_TS = """
state_dim:
  - region
state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to:
          r2: goto_r2
      r2:
        connected_to:
          r2: stay_r2
actions:
  goto_r2:
    guard: "1"
    weight: 2.0
  stay_r2:
    guard: "1"
    weight: 1.0
""".lstrip()

CYCLE_TS = """
state_dim:
  - region
state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to:
          r2: goto_r2
      r2:
        connected_to:
          r1: goto_r1
actions:
  goto_r2:
    guard: "1"
    weight: 1.0
  goto_r1:
    guard: "1"
    weight: 1.0
""".lstrip()

DIVERGENCE_TS = """
state_dim:
  - region
state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to:
          r2: goto_r2
      r2:
        connected_to:
          r2: stay_r2
      r3:
        connected_to:
          r2: recover_r2
actions:
  goto_r2:
    guard: "1"
    weight: 1.0
  stay_r2:
    guard: "1"
    weight: 1.0
  recover_r2:
    guard: "1"
    weight: 1.0
""".lstrip()


@pytest.fixture
def action_runtime():
    """Run planner and action client in one real single-threaded executor."""
    context = Context()
    rclpy.init(context=context)
    planner = PlannerNode(context=context)
    client_node = rclpy.create_node(
        "plan_ltl_action_test",
        context=context,
    )
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(planner)
    executor.add_node(client_node)
    action_client = ActionClient(
        client_node,
        PlanLTL,
        "plan_ltl",
    )
    state_publisher = client_node.create_publisher(
        TransitionSystemStateStamped,
        "ts_state",
        10,
    )
    runtime = SimpleNamespace(
        context=context,
        planner=planner,
        client_node=client_node,
        executor=executor,
        action_client=action_client,
        state_publisher=state_publisher,
        stamp=0,
        planner_destroyed=False,
    )

    assert action_client.wait_for_server(timeout_sec=2.0)

    try:
        yield runtime
    finally:
        executor.remove_node(client_node)
        executor.remove_node(planner)
        action_client.destroy()
        client_node.destroy_node()

        if not runtime.planner_destroyed:
            planner.destroy_node()

        executor.shutdown()
        rclpy.shutdown(context=context)


def spin_until(runtime, predicate, timeout=4.0):
    """Spin until a deterministic condition is true or timeout expires."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if predicate():
            return True

        runtime.executor.spin_once(timeout_sec=0.05)

    return predicate()


def load_transition_system(runtime, yaml_content):
    """Load TS YAML through the real ROS service."""
    client = runtime.client_node.create_client(
        LoadTransitionSystem,
        "load_transition_system",
    )
    assert client.wait_for_service(timeout_sec=2.0)
    request = LoadTransitionSystem.Request()
    request.transition_system_yaml = yaml_content
    future = client.call_async(request)
    assert spin_until(runtime, future.done)
    response = future.result()
    runtime.client_node.destroy_client(client)
    assert response is not None
    return response


def make_goal(
    state="r1",
    hard_task="<> r2",
    soft_task="(r2 || ! r2)",
):
    """Build the frozen action goal for a one-dimensional TS."""
    goal = PlanLTL.Goal()
    goal.hard_task = hard_task
    goal.soft_task = soft_task
    goal.initial_state.states = [state]
    goal.initial_state.state_dimension_names = ["region"]
    goal.beta = 1000.0
    goal.gamma = 10.0
    return goal


def send_goal(runtime, goal):
    """Send one goal and return its transport-level goal handle."""
    future = runtime.action_client.send_goal_async(goal)
    assert spin_until(runtime, future.done)
    return future.result()


def action_result(runtime, goal_handle, timeout=8.0):
    """Wait for the generated action result response."""
    future = goal_handle.get_result_async()
    assert spin_until(runtime, future.done, timeout=timeout)
    return future.result()


def publish_state(runtime, state):
    """Publish one uniquely stamped state feedback message."""
    assert spin_until(
        runtime,
        lambda: runtime.state_publisher.get_subscription_count() > 0,
    )
    runtime.stamp += 1
    message = TransitionSystemStateStamped()
    message.header.stamp.nanosec = runtime.stamp
    message.ts_state.states = [state]
    message.ts_state.state_dimension_names = ["region"]
    runtime.state_publisher.publish(message)


def activate(runtime, yaml_content=VALID_TS, goal=None):
    """Load a TS and create the first active plan through the action."""
    assert load_transition_system(runtime, yaml_content).success
    goal_handle = send_goal(runtime, goal or make_goal())
    assert goal_handle.accepted
    response = action_result(runtime, goal_handle)
    assert response.status == GoalStatus.STATUS_SUCCEEDED
    assert response.result.success
    return response.result


def block_candidate(monkeypatch):
    """Hold candidate search open with explicit test synchronization."""
    started = Event()
    release = Event()
    original = planner_module.compute_candidate_plan

    def controlled_compute(request):
        started.set()

        if not release.wait(timeout=8.0):
            return planner_module.PlanningOutcome(
                PlanLTL.Result.ERROR_INTERNAL,
                "Controlled candidate was not released.",
            )

        return original(request)

    monkeypatch.setattr(
        planner_module,
        "compute_candidate_plan",
        controlled_compute,
    )
    return started, release


def test_ready_action_success_returns_plan_and_activates(action_runtime):
    """Return real prefix/suffix data and activate a READY planner."""
    result = activate(action_runtime)

    assert result.error_code == PlanLTL.Result.ERROR_NONE
    assert list(result.prefix_plan.action_sequence) == [
        "goto_r2",
        "stay_r2",
    ]
    assert list(result.suffix_plan.action_sequence) == [
        "stay_r2",
        "stay_r2",
    ]
    assert result.total_cost > 0.0
    assert result.planning_time >= 0.0
    assert action_runtime.planner._planner_state == PlannerStatus.ACTIVE


def test_uninitialized_goal_is_rejected_at_transport(action_runtime):
    """Reject an unready goal without manufacturing an action result."""
    goal_handle = send_goal(action_runtime, make_goal())
    assert not goal_handle.accepted


def test_no_accepting_plan_aborts_with_specific_error(action_runtime):
    """Map a normal empty search result to ERROR_NO_ACCEPTING_PLAN."""
    assert load_transition_system(action_runtime, VALID_TS).success
    goal_handle = send_goal(
        action_runtime,
        make_goal(hard_task="<> r3"),
    )
    response = action_result(action_runtime, goal_handle)

    assert response.status == GoalStatus.STATUS_ABORTED
    assert not response.result.success
    assert response.result.error_code == (
        PlanLTL.Result.ERROR_NO_ACCEPTING_PLAN
    )
    assert action_runtime.planner._planner_state == PlannerStatus.READY


def test_invalid_and_stale_initial_states_do_not_start_worker(
    action_runtime,
    monkeypatch,
):
    """Return structured failures before starting expensive planning."""
    calls = []
    original_compute = planner_module.compute_candidate_plan

    def unexpected_compute(request):
        calls.append(request)
        raise AssertionError("Candidate worker should not run.")

    monkeypatch.setattr(
        planner_module,
        "compute_candidate_plan",
        unexpected_compute,
    )
    assert load_transition_system(action_runtime, VALID_TS).success

    invalid_goal = make_goal(state="missing")
    invalid_handle = send_goal(action_runtime, invalid_goal)
    invalid_response = action_result(action_runtime, invalid_handle)
    assert invalid_response.status == GoalStatus.STATUS_ABORTED
    assert invalid_response.result.error_code == (
        PlanLTL.Result.ERROR_INVALID_GOAL
    )

    # Restore the real function for one successful activation.
    monkeypatch.setattr(
        planner_module,
        "compute_candidate_plan",
        original_compute,
    )
    activate(action_runtime, goal=make_goal())
    monkeypatch.setattr(
        planner_module,
        "compute_candidate_plan",
        unexpected_compute,
    )

    stale_handle = send_goal(action_runtime, make_goal(state="r2"))
    stale_response = action_result(action_runtime, stale_handle)
    assert stale_response.status == GoalStatus.STATUS_ABORTED
    assert stale_response.result.error_code == (
        PlanLTL.Result.ERROR_NOT_READY
    )
    assert calls == []


def test_worker_keeps_control_plane_responsive(
    action_runtime,
    monkeypatch,
):
    """Reject concurrent operations while the candidate is still blocked."""
    assert load_transition_system(action_runtime, VALID_TS).success
    started, release = block_candidate(monkeypatch)
    first_handle = send_goal(action_runtime, make_goal())
    assert first_handle.accepted
    assert spin_until(action_runtime, started.is_set)
    assert not release.is_set()

    statuses = []
    status_qos = QoSProfile(
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    status_subscription = action_runtime.client_node.create_subscription(
        PlannerStatus,
        "planner_status",
        statuses.append,
        status_qos,
    )
    assert spin_until(
        action_runtime,
        lambda: (
            bool(statuses)
            and statuses[-1].state == PlannerStatus.PLANNING
        ),
    )
    assert not release.is_set()

    second_future = action_runtime.action_client.send_goal_async(make_goal())
    assert spin_until(action_runtime, second_future.done)
    assert not second_future.result().accepted
    assert not release.is_set()

    load_client = action_runtime.client_node.create_client(
        LoadTransitionSystem,
        "load_transition_system",
    )
    load_request = LoadTransitionSystem.Request()
    load_request.transition_system_yaml = VALID_TS
    load_future = load_client.call_async(load_request)
    assert spin_until(action_runtime, load_future.done)
    assert not load_future.result().success
    assert not release.is_set()

    replanning_client = action_runtime.client_node.create_client(
        TaskPlanning,
        "replanning",
    )
    replanning_request = TaskPlanning.Request()
    replanning_request.hard_task = "<> r2"
    replanning_request.soft_task = "(r2 || ! r2)"
    replanning_future = replanning_client.call_async(replanning_request)
    assert spin_until(action_runtime, replanning_future.done)
    assert not replanning_future.result().success
    assert not release.is_set()

    cancel_future = first_handle.cancel_goal_async()
    assert spin_until(action_runtime, cancel_future.done)
    assert len(cancel_future.result().goals_canceling) == 0
    assert not release.is_set()

    release.set()
    response = action_result(action_runtime, first_handle)
    assert response.status == GoalStatus.STATUS_SUCCEEDED
    action_runtime.client_node.destroy_client(load_client)
    action_runtime.client_node.destroy_client(replanning_client)
    action_runtime.client_node.destroy_subscription(status_subscription)


def test_expected_execution_makes_candidate_stale_without_rollback(
    action_runtime,
    monkeypatch,
):
    """Keep old-current cursor and publications after an A-to-B move."""
    activate(action_runtime)
    old_planner = action_runtime.planner.ltl_planner
    prefix_messages = []
    command_qos = QoSProfile(
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    subscription = action_runtime.client_node.create_subscription(
        LTLPlan,
        "prefix_plan",
        prefix_messages.append,
        command_qos,
    )
    assert spin_until(action_runtime, lambda: bool(prefix_messages))

    started, release = block_candidate(monkeypatch)
    goal_handle = send_goal(action_runtime, make_goal())
    assert spin_until(action_runtime, started.is_set)
    publish_state(action_runtime, "r2")
    assert spin_until(
        action_runtime,
        lambda: old_planner.curr_ts_state == ("r2",),
    )
    assert spin_until(
        action_runtime,
        lambda: len(prefix_messages) >= 2,
    )
    publication_count = len(prefix_messages)

    release.set()
    response = action_result(action_runtime, goal_handle)
    assert response.status == GoalStatus.STATUS_ABORTED
    assert response.result.error_code == PlanLTL.Result.ERROR_NOT_READY
    assert action_runtime.planner.ltl_planner is old_planner
    assert old_planner.curr_ts_state == ("r2",)
    assert action_runtime.planner._canonical_ts_state == ("r2",)
    assert len(prefix_messages) == publication_count
    action_runtime.client_node.destroy_subscription(subscription)


def test_return_to_initial_state_allows_commit_and_duplicate_is_ignored(
    action_runtime,
    monkeypatch,
):
    """Allow A-to-B-to-A and do not treat duplicate A as execution."""
    cycle_goal = make_goal(hard_task="[]<> r1")
    activate(action_runtime, CYCLE_TS, cycle_goal)
    old_planner = action_runtime.planner.ltl_planner
    started, release = block_candidate(monkeypatch)
    goal_handle = send_goal(action_runtime, cycle_goal)
    assert spin_until(action_runtime, started.is_set)

    publish_state(action_runtime, "r1")
    action_runtime.executor.spin_once(timeout_sec=0.1)
    assert old_planner.curr_ts_state == ("r1",)

    first_expected = action_runtime.planner._expected_next_state()
    assert first_expected == ("r2",)
    publish_state(action_runtime, first_expected[0])
    assert spin_until(
        action_runtime,
        lambda: old_planner.curr_ts_state == first_expected,
    )
    second_expected = action_runtime.planner._expected_next_state()
    assert second_expected == ("r1",)
    publish_state(action_runtime, second_expected[0])
    assert spin_until(
        action_runtime,
        lambda: action_runtime.planner._canonical_ts_state == ("r1",),
    )

    release.set()
    response = action_result(action_runtime, goal_handle)
    assert response.status == GoalStatus.STATUS_SUCCEEDED
    assert response.result.success
    assert action_runtime.planner.ltl_planner is not old_planner


def test_unexpected_state_defers_recovery_until_candidate_finishes(
    action_runtime,
    monkeypatch,
):
    """Never run candidate search and state recovery concurrently."""
    activate(action_runtime, DIVERGENCE_TS)
    active_planner = action_runtime.planner.ltl_planner
    recovery_calls = []
    original_recovery = active_planner.replan_from_ts_state

    def counted_recovery(state):
        recovery_calls.append(state)
        return original_recovery(state)

    active_planner.replan_from_ts_state = counted_recovery
    started, release = block_candidate(monkeypatch)
    goal_handle = send_goal(action_runtime, make_goal())
    assert spin_until(action_runtime, started.is_set)
    publish_state(action_runtime, "r3")
    assert spin_until(
        action_runtime,
        lambda: action_runtime.planner._pending_divergence == ("r3",),
    )
    assert recovery_calls == []
    assert active_planner.curr_ts_state == ("r1",)

    release.set()
    response = action_result(action_runtime, goal_handle)
    assert response.status == GoalStatus.STATUS_ABORTED
    assert response.result.error_code == PlanLTL.Result.ERROR_NOT_READY
    assert recovery_calls == [("r3",)]
    assert active_planner.curr_ts_state == ("r3",)
    assert action_runtime.planner._pending_divergence is None


def test_shutdown_does_not_wait_for_or_commit_blocked_worker(
    action_runtime,
    monkeypatch,
):
    """Destroy the node without joining an unfinished daemon worker."""
    assert load_transition_system(action_runtime, VALID_TS).success
    started, release = block_candidate(monkeypatch)
    goal_handle = send_goal(action_runtime, make_goal())
    assert goal_handle.accepted
    assert spin_until(action_runtime, started.is_set)
    worker = action_runtime.planner._planning_worker
    assert worker is not None and worker.is_alive() and worker.daemon

    action_runtime.planner.destroy_node()
    action_runtime.planner_destroyed = True
    assert action_runtime.planner._shutting_down
    assert action_runtime.planner._planning_token is None
    release.set()
    worker.join(timeout=3.0)
    assert not worker.is_alive()
    assert action_runtime.planner.ltl_planner is None
