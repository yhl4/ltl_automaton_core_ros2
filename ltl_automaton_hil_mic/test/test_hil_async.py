"""Exercise HIL callback ordering with real nodes and controlled futures."""

from contextlib import contextmanager
import math
from pathlib import Path
from types import SimpleNamespace

from geometry_msgs.msg import Twist
from ltl_automaton_hil_mic import bool_cmd_mixer as bool_module
from ltl_automaton_hil_mic import vel_cmd_mixer as velocity_module
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import ClosestState, TrapCheck
from rclpy.parameter import Parameter
import pytest
import rclpy
from std_msgs.msg import Bool
from time import monotonic as real_monotonic


class DeferredFuture:
    """Hold completed callbacks so tests can deliver them after cancellation."""

    def __init__(self):
        """Initialize a reply with no queued completion."""
        self.callbacks = []
        self.response = None
        self.error = None
        self.cancelled = False

    def add_done_callback(self, callback):
        """Queue a callback for explicit delivery."""
        self.callbacks.append(callback)

    def result(self):
        """Return the recorded response or raise its recorded failure."""
        if self.error is not None:
            raise self.error
        return self.response

    def cancel(self):
        """Record cancellation without removing an already queued callback."""
        self.cancelled = True

    def complete(self, response=None, error=None):
        """Complete and deliver callbacks in the test's chosen order."""
        self.response = response
        self.error = error
        for callback in self.callbacks:
            callback(self)


class ControlledClient:
    """Return controlled futures or fail the next request synchronously."""

    def __init__(self):
        """Initialize an available client with no requests."""
        self.futures = []
        self.fail_next = False

    def service_is_ready(self):
        """Keep discovery available to isolate request and callback faults."""
        return True

    def call_async(self, request):
        """Record each submitted request's future."""
        del request
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("injected request failure")
        future = DeferredFuture()
        self.futures.append(future)
        return future


def velocity(value):
    """Create a one-axis command whose selected value is easy to verify."""
    message = Twist()
    message.linear.x = value
    return message


def state(kind, changed=False):
    """Create a valid source or alternate state for the selected controller."""
    message = TransitionSystemStateStamped()
    message.ts_state.state_dimension_names = [
        "load" if kind == "bool" else "2d_pose_region",
    ]
    message.ts_state.states = [
        ("loaded" if changed else "empty")
        if kind == "bool" else ("r2" if changed else "r1"),
    ]
    return message


def duplicate_dimension_state(kind):
    """Create a state with two values under the same dimension name."""
    message = TransitionSystemStateStamped()
    dimension = "load" if kind == "bool" else "2d_pose_region"
    message.ts_state.state_dimension_names = [dimension, dimension]
    message.ts_state.states = (
        ["empty", "loaded"] if kind == "bool" else ["r1", "r2"]
    )
    return message


@contextmanager
def controller_runtime(
    kind, monkeypatch, safety_check_timeout=1.0, patch_monotonic=True
):
    """Create a real controller while controlling its service completions."""
    config = Path(__file__).resolve().parents[1] / "config/example_bool_ts.yaml"
    rclpy.init(args=[
        "--ros-args", "-p", f"transition_system_path:={config}",
        "-p", f"safety_check_timeout:={safety_check_timeout}",
        "-p", "timeout:=2.0",
        "-p", "max_linear_x_vel:=1.0", "-p", "deadband:=0.05",
        "-p", "ds:=1.0", "-p", "epsilon:=1.0",
    ])
    module = bool_module if kind == "bool" else velocity_module
    clock = [10.0]
    if patch_monotonic:
        monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    node = module.BoolCommandMixer() if kind == "bool" else module.VelocityCommandMixer()
    messages = []
    monkeypatch.setattr(node, "publisher", SimpleNamespace(publish=messages.append))
    trap = ControlledClient()
    closest = ControlledClient()
    monkeypatch.setattr(node, "trap_client", trap)
    if kind == "velocity":
        monkeypatch.setattr(node, "closest_client", closest)
        monkeypatch.setattr(node, "_now_seconds", lambda: clock[0])
    node._state_callback(state(kind))
    value = SimpleNamespace(
        node=node, kind=kind, clock=clock, messages=messages,
        trap=trap, closest=closest,
    )
    try:
        yield value
    finally:
        if not node._closed:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


@pytest.fixture(params=["bool", "velocity"])
def runtime(request, monkeypatch):
    """Run common safety checks against each controller."""
    with controller_runtime(request.param, monkeypatch) as value:
        yield value


@pytest.fixture
def velocity_runtime(monkeypatch):
    """Run velocity-specific checks without empty Boolean test cases."""
    with controller_runtime("velocity", monkeypatch) as value:
        yield value


def start_check(runtime, finish_closest=True):
    """Start a human query, optionally advance velocity to its trap stage."""
    if runtime.kind == "bool":
        runtime.node._human_callback(Bool(data=True))
    else:
        runtime.node._human_callback(velocity(0.3))
        runtime.node._navigation_callback(velocity(0.1))
        if finish_closest:
            runtime.closest.futures[-1].complete(
                ClosestState.Response(closest_state="r2", metric=0.5),
            )


def test_departure_and_return_rejects_old_trap_decision(runtime):
    """An A-B-A state history must not authorize a decision captured at A."""
    start_check(runtime)
    runtime.node._state_callback(state(runtime.kind, changed=True))
    runtime.node._state_callback(state(runtime.kind))
    runtime.trap.futures[-1].complete(TrapCheck.Response(is_connected=True))
    if runtime.kind == "bool":
        assert runtime.messages == []
    else:
        assert [message.linear.x for message in runtime.messages] == [0.1]


def test_duplicate_state_still_permits_current_decision(runtime):
    """Repeated identical symbolic state does not invalidate a pending query."""
    start_check(runtime)
    runtime.node._state_callback(state(runtime.kind))
    runtime.trap.futures[-1].complete(TrapCheck.Response(is_connected=True))
    if runtime.kind == "bool":
        assert [message.data for message in runtime.messages] == [True]
    else:
        assert [message.linear.x for message in runtime.messages] == [0.3]


def test_duplicate_dimensions_without_state_are_rejected_and_recover(runtime):
    """Reject duplicate dimensions before caching, then recover normally."""
    runtime.node.current_state = None
    runtime.node._state_callback(duplicate_dimension_state(runtime.kind))
    assert runtime.node.current_state is None
    assert runtime.trap.futures == []
    if runtime.kind == "velocity":
        assert runtime.closest.futures == []

    runtime.node._state_callback(state(runtime.kind))
    start_check(runtime, finish_closest=False)
    if runtime.kind == "bool":
        assert len(runtime.trap.futures) == 1
    else:
        assert len(runtime.closest.futures) == 1


def test_duplicate_dimensions_preserve_pending_query_and_recover(runtime):
    """Reject a duplicate update without invalidating an active query."""
    start_check(runtime, finish_closest=False)
    expected_state = runtime.node.current_state
    expected_revision = runtime.node._state_revision
    trap_count = len(runtime.trap.futures)
    closest_count = len(runtime.closest.futures)

    runtime.node._state_callback(duplicate_dimension_state(runtime.kind))
    assert runtime.node.current_state == expected_state
    assert runtime.node._state_revision == expected_revision
    assert len(runtime.trap.futures) == trap_count
    assert len(runtime.closest.futures) == closest_count

    if runtime.kind == "bool":
        runtime.trap.futures[-1].complete(TrapCheck.Response(is_connected=True))
        assert [message.data for message in runtime.messages] == [True]
    else:
        runtime.closest.futures[-1].complete(
            ClosestState.Response(closest_state="r2", metric=0.5)
        )
        runtime.trap.futures[-1].complete(
            TrapCheck.Response(is_connected=True)
        )
        assert [message.linear.x for message in runtime.messages] == [0.3]

    runtime.node._state_callback(state(runtime.kind, changed=True))
    assert runtime.node.current_state.states == (
        ["loaded"] if runtime.kind == "bool" else ["r2"]
    )


def test_synchronous_request_failure_allows_next_check(runtime):
    """A failed submission must not leave the controller permanently busy."""
    client = runtime.trap if runtime.kind == "bool" else runtime.closest
    client.fail_next = True
    start_check(runtime, finish_closest=False)
    assert not client.futures
    start_check(runtime, finish_closest=False)
    assert len(client.futures) == 1


@pytest.mark.parametrize("failure", [None, RuntimeError("injected response failure")])
def test_failed_trap_response_allows_next_check(runtime, failure):
    """Missing or failed replies cannot publish a human command or block retry."""
    start_check(runtime)
    runtime.trap.futures[-1].complete(error=failure)
    if runtime.kind == "bool":
        assert runtime.messages == []
    else:
        assert [message.linear.x for message in runtime.messages] == [0.1]
    start_check(runtime)
    assert len(runtime.trap.futures) == 2


def test_timeout_releases_query_and_old_reply_cannot_release_new_one(runtime):
    """Expire an unanswered query and preserve the identity of its successor."""
    start_check(runtime, finish_closest=False)
    client = runtime.trap if runtime.kind == "bool" else runtime.closest
    old = client.futures[-1]
    runtime.clock[0] += 1.1
    runtime.node._check_safety_timeout()
    assert old.cancelled
    start_check(runtime, finish_closest=False)
    assert len(client.futures) == 2
    response = TrapCheck.Response(is_connected=True) if runtime.kind == "bool" else (
        ClosestState.Response(closest_state="r2", metric=0.5)
    )
    old.complete(response)
    if runtime.kind == "bool":
        assert runtime.messages == []
    else:
        assert [message.linear.x for message in runtime.messages] == [0.1]
        assert not runtime.trap.futures
    start_check(runtime, finish_closest=False)
    assert len(client.futures) == 2


def test_destroyed_node_ignores_pending_reply(runtime):
    """A completion queued before teardown cannot publish after teardown."""
    start_check(runtime)
    old = runtime.trap.futures[-1]
    runtime.node.destroy_node()
    assert old.cancelled
    old.complete(TrapCheck.Response(is_connected=True))
    assert runtime.messages == []


@pytest.mark.parametrize("is_trap, expected", [(True, 0.8), (False, 0.9)])
def test_velocity_reply_uses_latest_commands(velocity_runtime, is_trap, expected):
    """Resolve an old query against the newest human and navigation commands."""
    runtime = velocity_runtime
    start_check(runtime)
    runtime.node._human_callback(velocity(0.9))
    runtime.node._navigation_callback(velocity(0.8))
    runtime.trap.futures[-1].complete(
        TrapCheck.Response(is_connected=True, is_trap=is_trap),
    )
    assert [message.linear.x for message in runtime.messages] == [0.8, expected]


def test_velocity_human_expiry_uses_latest_navigation(velocity_runtime):
    """A fresh query does not revive a human input that has since expired."""
    runtime = velocity_runtime
    runtime.node.timeout = 0.2
    start_check(runtime)
    runtime.node._navigation_callback(velocity(0.8))
    runtime.clock[0] += 0.3
    runtime.trap.futures[-1].complete(TrapCheck.Response(is_connected=True))
    assert [message.linear.x for message in runtime.messages] == [0.8, 0.8]


@pytest.mark.parametrize("stage", ["closest", "trap"])
def test_velocity_clock_reversal_rejects_pending_reply(
    velocity_runtime, monkeypatch, stage
):
    """Negative input age cannot authorize either stage's delayed safety reply."""
    runtime = velocity_runtime
    ros_time = [10.0]
    monkeypatch.setattr(runtime.node, "_now_seconds", lambda: ros_time[0])
    start_check(runtime, finish_closest=stage == "trap")
    runtime.node._navigation_callback(velocity(0.8))
    future = (
        runtime.closest.futures[-1] if stage == "closest"
        else runtime.trap.futures[-1]
    )
    ros_time[0] = 5.0
    response = (
        ClosestState.Response() if stage == "closest"
        else TrapCheck.Response(is_connected=True)
    )
    future.complete(response)
    assert [message.linear.x for message in runtime.messages] == [0.8, 0.8]
    assert runtime.node.human_command is None
    assert runtime.node.last_human_input is None
    assert runtime.node._safety_request_context is None
    assert not runtime.node._safety_check_in_flight


@pytest.mark.parametrize("invalid_time", [5.0, 12.0])
def test_velocity_invalid_age_cannot_revive_cached_input(
    velocity_runtime, monkeypatch, invalid_time
):
    """Once invalidated, a sample stays absent even if ROS time returns to its window."""
    runtime = velocity_runtime
    ros_time = [10.0]
    monkeypatch.setattr(runtime.node, "_now_seconds", lambda: ros_time[0])
    runtime.node._human_callback(velocity(0.3))
    ros_time[0] = invalid_time
    runtime.node._navigation_callback(velocity(0.1))
    assert not runtime.closest.futures
    assert runtime.node.human_command is None
    ros_time[0] = 10.1
    runtime.node._navigation_callback(velocity(0.2))
    assert not runtime.closest.futures
    assert [message.linear.x for message in runtime.messages] == [0.1, 0.2]
    runtime.node._human_callback(velocity(0.4))
    runtime.node._navigation_callback(velocity(0.2))
    assert len(runtime.closest.futures) == 1
    runtime.closest.futures[-1].complete(ClosestState.Response())
    assert [message.linear.x for message in runtime.messages] == [0.1, 0.2, 0.4]


@pytest.mark.parametrize("timeout", [0.0, 2.0])
def test_velocity_zero_ros_time_respects_freshness_window(
    velocity_runtime, monkeypatch, timeout
):
    """Time zero is a valid receipt time, while a zero timeout disables human input."""
    runtime = velocity_runtime
    runtime.node.timeout = timeout
    monkeypatch.setattr(runtime.node, "_now_seconds", lambda: 0.0)
    runtime.node._human_callback(velocity(0.3))
    runtime.node._navigation_callback(velocity(0.1))
    if timeout == 0.0:
        assert not runtime.closest.futures
        assert [message.linear.x for message in runtime.messages] == [0.1]
    else:
        assert len(runtime.closest.futures) == 1
        runtime.closest.futures[-1].complete(ClosestState.Response())
        assert [message.linear.x for message in runtime.messages] == [0.3]


def test_velocity_empty_closest_after_state_change_uses_navigation(velocity_runtime):
    """Even the no-neighbor branch must reject stale source-state safety data."""
    runtime = velocity_runtime
    start_check(runtime, finish_closest=False)
    runtime.node._state_callback(state("velocity", changed=True))
    runtime.node._navigation_callback(velocity(0.8))
    runtime.closest.futures[-1].complete(ClosestState.Response())
    assert [message.linear.x for message in runtime.messages] == [0.8, 0.8]
    assert not runtime.trap.futures


def test_velocity_trap_submission_failure_uses_navigation(velocity_runtime):
    """Release the two-stage query when its second request fails to start."""
    runtime = velocity_runtime
    start_check(runtime, finish_closest=False)
    runtime.node._navigation_callback(velocity(0.8))
    runtime.trap.fail_next = True
    runtime.closest.futures[-1].complete(
        ClosestState.Response(closest_state="r2", metric=0.5),
    )
    assert [message.linear.x for message in runtime.messages] == [0.8, 0.8]
    start_check(runtime, finish_closest=False)
    assert len(runtime.closest.futures) == 2


def test_velocity_query_stages_share_one_deadline(velocity_runtime):
    """Starting trap lookup does not restart the closest-query time budget."""
    runtime = velocity_runtime
    start_check(runtime, finish_closest=False)
    runtime.clock[0] += 0.8
    runtime.closest.futures[-1].complete(
        ClosestState.Response(closest_state="r2", metric=0.5),
    )
    runtime.node._navigation_callback(velocity(0.8))
    runtime.clock[0] += 0.3
    runtime.trap.futures[-1].complete(TrapCheck.Response(is_connected=True))
    assert [message.linear.x for message in runtime.messages] == [0.8, 0.8]


@pytest.mark.parametrize("kind", ["bool", "velocity"])
def test_real_steady_timer_cancels_unanswered_query(kind, monkeypatch):
    """A real steady timer releases an unanswered safety query."""
    with controller_runtime(
        kind,
        monkeypatch,
        safety_check_timeout=0.05,
        patch_monotonic=False,
    ) as runtime:
        start_check(runtime, finish_closest=False)
        client = runtime.trap if kind == "bool" else runtime.closest
        old = client.futures[-1]
        if kind == "velocity":
            runtime.node._navigation_callback(velocity(0.8))

        deadline = real_monotonic() + 1.0
        while not old.cancelled and real_monotonic() < deadline:
            rclpy.spin_once(runtime.node, timeout_sec=0.01)

        assert old.cancelled
        if kind == "bool":
            assert runtime.messages == []
        else:
            assert [message.linear.x for message in runtime.messages] == [0.8, 0.8]

        start_check(runtime, finish_closest=False)
        assert len(client.futures) == 2


def test_invalid_human_cancels_pending_query_and_valid_input_can_retry(velocity_runtime):
    """Invalid human input cannot become a saturated command or revive old work."""
    runtime = velocity_runtime
    start_check(runtime, finish_closest=False)
    old = runtime.closest.futures[-1]
    runtime.node._human_callback(velocity(float("nan")))
    assert old.cancelled
    assert runtime.node.human_command is None
    assert [message.linear.x for message in runtime.messages] == [0.1]
    start_check(runtime, finish_closest=False)
    old.complete(ClosestState.Response(closest_state="r2", metric=0.5))
    assert not runtime.trap.futures
    assert len(runtime.closest.futures) == 2
    runtime.closest.futures[-1].complete(ClosestState.Response())
    assert [message.linear.x for message in runtime.messages] == [0.1, 0.3]


def test_invalid_navigation_preserves_valid_cache_and_allows_retry(velocity_runtime):
    """A malformed navigation sample cannot replace the valid fallback."""
    runtime = velocity_runtime
    start_check(runtime, finish_closest=False)
    old = runtime.closest.futures[-1]
    runtime.node._navigation_callback(velocity(float("inf")))
    assert old.cancelled
    assert [message.linear.x for message in runtime.messages] == [0.1]
    assert runtime.node._latest_navigation_command.linear.x == 0.1
    runtime.node._navigation_callback(velocity(0.2))
    assert len(runtime.closest.futures) == 2
    runtime.closest.futures[-1].complete(ClosestState.Response())
    assert [message.linear.x for message in runtime.messages] == [0.1, 0.3]


def test_invalid_first_navigation_falls_back_to_zero(velocity_runtime):
    """Before any valid navigation sample, rejection publishes finite zero velocity."""
    runtime = velocity_runtime
    navigation = velocity(0.1)
    navigation.angular.z = float("nan")
    runtime.node._navigation_callback(navigation)
    assert runtime.messages == [Twist()]
    assert runtime.node._latest_navigation_command is None
    assert not runtime.closest.futures


@pytest.mark.parametrize(
    "closest_state, metric",
    [
        ("r2", float("nan")),
        ("r2", float("inf")),
        ("r2", -float("inf")),
        ("", float("nan")),
    ],
)
def test_invalid_closest_metric_uses_latest_navigation_and_releases_query(
    velocity_runtime, closest_state, metric
):
    """Invalid safety distance cannot activate human gain or block another query."""
    runtime = velocity_runtime
    start_check(runtime, finish_closest=False)
    runtime.node._navigation_callback(velocity(0.8))
    runtime.closest.futures[-1].complete(
        ClosestState.Response(closest_state=closest_state, metric=metric),
    )
    assert [message.linear.x for message in runtime.messages] == [0.8, 0.8]
    assert not runtime.trap.futures
    assert all(math.isfinite(message.linear.x) for message in runtime.messages)
    start_check(runtime, finish_closest=False)
    assert len(runtime.closest.futures) == 2


@pytest.mark.parametrize("value, all_axes", [(1e200, False), (1.5e308, True)])
def test_large_finite_human_velocity_is_bounded_without_callback_error(
    velocity_runtime, value, all_axes
):
    """The magnitude check must not overflow before manual speed limits apply."""
    runtime = velocity_runtime
    human = velocity(value)
    if all_axes:
        human.linear.y = value
        human.linear.z = value
    runtime.node._human_callback(human)
    runtime.node._navigation_callback(velocity(0.1))
    runtime.closest.futures[-1].complete(ClosestState.Response())
    assert [message.linear.x for message in runtime.messages] == [1.0]
    assert runtime.messages[0].linear.y == (0.5 if all_axes else 0.0)
    assert runtime.messages[0].linear.z == (0.5 if all_axes else 0.0)


def test_destroyed_velocity_node_ignores_new_input_callbacks(velocity_runtime):
    """New input callbacks cannot publish even a fallback after destruction."""
    runtime = velocity_runtime
    runtime.node.destroy_node()
    runtime.node._human_callback(velocity(float("nan")))
    runtime.node._navigation_callback(velocity(float("nan")))
    assert runtime.messages == []


@pytest.mark.parametrize("timeout", [".nan", ".inf", "-.inf"])
def test_velocity_node_rejects_nonfinite_human_timeout(timeout):
    """A non-finite freshness window must be rejected during initialization."""
    rclpy.init(args=["--ros-args", "-p", f"timeout:={timeout}"])
    node = None
    try:
        with pytest.raises(ValueError, match="finite"):
            node = velocity_module.VelocityCommandMixer()
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


def test_hil_startup_parameters_reject_runtime_writes(runtime):
    """Do not report limits, model selection, or deadlines that were not applied."""
    node = runtime.node
    if runtime.kind == "bool":
        names = [
            "transition_system_path", "state_dimension_name", "monitored_action",
            "safety_check_timeout",
        ]
        assert node.policy.monitored_action == "pick"
    else:
        names = [
            "epsilon", "ds", "deadband", "timeout", "safety_check_timeout",
            "state_dimension_name",
            *[f"max_{kind}_{axis}_vel" for kind in ("linear", "angular")
              for axis in ("x", "y", "z")],
        ]
        assert node.policy.max_linear[0] == 1.0
        assert node.timeout == 2.0
    for name in names:
        original = node.get_parameter(name).value
        replacement = original + 0.5 if isinstance(original, float) else "changed"
        assert node.describe_parameter(name).read_only
        result = node.set_parameters([Parameter(name, value=replacement)])[0]
        assert not result.successful
        assert node.get_parameter(name).value == original
    assert node.set_parameters([Parameter("use_sim_time", value=True)])[0].successful
    result = node.set_parameters_atomically([
        Parameter("safety_check_timeout", value=0.1),
        Parameter("use_sim_time", value=False),
    ])
    assert not result.successful
    assert node.get_parameter("use_sim_time").value is True
