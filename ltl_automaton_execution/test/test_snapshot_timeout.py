"""Check snapshot deadlines independently of ROS time and late replies."""

from time import monotonic
from types import SimpleNamespace

import pytest
import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter

from ltl_automaton_execution import execution_node as execution_module
from ltl_automaton_execution.execution_node import ExecutionManagerNode
from test_execution_node import RecordingAbstraction, RecordingBackend, RecordingObserver
from test_execution_node import _observation, _successful_response


class DeferredSnapshotFuture:
    """Deliver queued replies even after a synchronous cancel callback."""

    def __init__(self):
        """Initialize an unfinished service request."""
        self.callbacks = []
        self.response = None
        self.error = None
        self.cancelled = False
        self.exception_fetched = False

    def add_done_callback(self, callback):
        """Retain completion callbacks for controlled delivery."""
        self.callbacks.append(callback)

    def result(self):
        """Return the reply or raise the injected service error."""
        if self.error is not None:
            raise self.exception()
        return self.response

    def exception(self):
        """Return the error while marking it as retrieved."""
        self.exception_fetched = True
        return self.error

    def cancel(self):
        """Invoke cancellation callbacks immediately, retaining late replies."""
        self.cancelled = True
        for callback in tuple(self.callbacks):
            callback(self)

    def complete(self, response=None, error=None):
        """Deliver a service reply after any earlier cancellation."""
        self.response = response
        self.error = error
        self.exception_fetched = False
        for callback in tuple(self.callbacks):
            callback(self)


class ControlledSnapshotClient:
    """Return a fresh pending request with controllable completion."""

    def __init__(self):
        """Initialize an available snapshot service."""
        self.futures = []
        self.failure = None

    def service_is_ready(self):
        """Keep discovery available to isolate request deadlines."""
        return True

    def call_async(self, _request):
        """Create a pending request or inject a submission-boundary failure."""
        if self.failure == "none":
            return None
        future = DeferredSnapshotFuture()
        if self.failure == "callback":
            def reject_callback(_callback):
                raise RuntimeError("Cannot register completion callback.")
            future.add_done_callback = reject_callback
        self.futures.append(future)
        return future


@pytest.fixture
def snapshot_runtime(monkeypatch):
    """Use a real Node with a controlled monotonic deadline and service."""
    now = [100.0]
    monkeypatch.setattr(execution_module, "monotonic", lambda: now[0])
    context = Context()
    rclpy.init(context=context)
    backend = RecordingBackend()
    node = ExecutionManagerNode(
        backend=backend, state_observer=RecordingObserver(), context=context,
        parameter_overrides=[Parameter("snapshot_request_timeout", value=0.5)],
    )
    client = ControlledSnapshotClient()
    node._snapshot_client = client
    try:
        yield SimpleNamespace(node=node, client=client, backend=backend, now=now)
    finally:
        node.destroy_node()
        rclpy.shutdown(context=context)


@pytest.mark.parametrize("late_error", [False, True])
def test_timeout_retries_latest_step_and_ignores_old_reply(
    snapshot_runtime, late_error,
):
    """An old reply cannot clear or dispatch the replacement request."""
    runtime = snapshot_runtime
    runtime.node._on_observation(_observation(1))
    old = runtime.client.futures[0]
    latest = _observation(1, sequence=1)
    latest.possible_product_node_ids = [2]
    latest.next_action = "wait"
    runtime.node._on_observation(latest)
    assert len(runtime.client.futures) == 1

    runtime.now[0] = 100.5
    runtime.node._retry_snapshot_discovery()
    assert old.cancelled
    assert len(runtime.client.futures) == 2
    assert runtime.backend.calls == []

    old.complete(
        _successful_response(),
        RuntimeError("Late service failure.") if late_error else None,
    )
    if late_error:
        assert old.exception_fetched
    runtime.node._retry_snapshot_discovery()
    assert len(runtime.client.futures) == 2
    assert runtime.backend.calls == []
    runtime.client.futures[1].complete(_successful_response())
    assert len(runtime.backend.calls) == 1
    step = runtime.backend.calls[0][0]
    assert (step.execution_step_seq, step.action) == (1, "wait")
    assert step.source_product_node_ids == (2,)


@pytest.mark.parametrize("late_error", [False, True])
def test_expired_success_cannot_dispatch_before_timer_runs(
    snapshot_runtime, late_error,
):
    """Check the deadline in a response callback despite delayed scheduling."""
    runtime = snapshot_runtime
    runtime.node._on_observation(_observation(1))
    runtime.now[0] = 100.5
    if late_error:
        runtime.client.futures[0].complete(
            error=RuntimeError("Expired service failure.")
        )
    else:
        runtime.client.futures[0].complete(_successful_response())
    assert runtime.backend.calls == []
    assert runtime.client.futures[0].cancelled
    if late_error:
        assert runtime.client.futures[0].exception_fetched
    runtime.node._retry_snapshot_discovery()
    assert len(runtime.client.futures) == 2
    runtime.client.futures[1].complete(_successful_response())
    assert len(runtime.backend.calls) == 1


def test_duplicate_observations_do_not_extend_request_deadline(snapshot_runtime):
    """Repeated retained commands must not keep a hung request alive."""
    runtime = snapshot_runtime
    runtime.node._on_observation(_observation(1))
    runtime.now[0] = 100.4
    runtime.node._on_observation(_observation(1))
    assert len(runtime.client.futures) == 1
    runtime.now[0] = 100.5
    runtime.node._on_observation(_observation(1))
    runtime.node._retry_snapshot_discovery()
    assert runtime.client.futures[0].cancelled
    assert len(runtime.client.futures) == 2


@pytest.mark.parametrize("replacement", ["no-action", "generation", "instance"])
def test_changed_authority_cancels_unneeded_request(snapshot_runtime, replacement):
    """No-action and new graph authority suppress retries of old commands."""
    runtime = snapshot_runtime
    runtime.node._on_observation(_observation(1))
    old = runtime.client.futures[0]
    if replacement == "no-action":
        latest = _observation(1, sequence=1)
        latest.has_next_action = False
    elif replacement == "generation":
        latest = _observation(2)
    else:
        latest = _observation(1, instance="planner-b")
    runtime.node._on_observation(latest)
    assert old.cancelled
    old.complete(_successful_response())
    runtime.node._retry_snapshot_discovery()
    assert runtime.backend.calls == []
    expected_requests = 1 if replacement == "no-action" else 2
    assert len(runtime.client.futures) == expected_requests
    assert len(runtime.node._snapshot_requests) == expected_requests - 1


@pytest.mark.parametrize("failure", ["none", "callback"])
def test_invalid_request_future_releases_retry(snapshot_runtime, failure):
    """Missing Future and callback-registration errors leave no request lock."""
    runtime = snapshot_runtime
    runtime.client.failure = failure
    runtime.node._on_observation(_observation(1))
    assert not runtime.node._snapshot_requests
    if failure == "callback":
        assert runtime.client.futures[0].cancelled
    runtime.client.failure = None
    runtime.node._retry_snapshot_discovery()
    runtime.client.futures[-1].complete(_successful_response())
    assert len(runtime.backend.calls) == 1


def test_new_instance_without_action_clears_observation_schema(snapshot_runtime):
    """An old graph must not reject independent observations after restart."""
    runtime = snapshot_runtime
    runtime.node._on_observation(_observation(1))
    runtime.client.futures[0].complete(_successful_response())
    latest = _observation(1, instance="planner-b")
    latest.has_next_action = False
    runtime.node._on_observation(latest)
    states = []
    runtime.node._state_abstraction = RecordingAbstraction()
    runtime.node._state_publisher = SimpleNamespace(publish=states.append)
    runtime.node._on_state_observation(
        execution_module.SymbolicState(("new_region",), ("x1",))
    )
    assert len(states) == 1
    assert list(states[0].ts_state.state_dimension_names) == ["new_region"]


@pytest.mark.parametrize("repeat_observation", [False, True])
def test_steady_timer_retries_while_ros_clock_is_paused(repeat_observation):
    """Expire a hung request with no feedback or repeated retained commands."""
    context = Context()
    rclpy.init(context=context)
    backend = RecordingBackend()
    node = ExecutionManagerNode(
        backend=backend, state_observer=RecordingObserver(), context=context,
        parameter_overrides=[
            Parameter("snapshot_request_timeout", value=0.05),
            Parameter("use_sim_time", value=True),
        ],
    )
    client = ControlledSnapshotClient()
    node._snapshot_client = client
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(node)
    try:
        assert node.get_clock().now().nanoseconds == 0
        node._on_observation(_observation(1))
        deadline = monotonic() + 2.0
        while len(client.futures) < 2 and monotonic() < deadline:
            if repeat_observation:
                node._on_observation(_observation(1))
            executor.spin_once(timeout_sec=0.02)
        assert client.futures[0].cancelled
        assert len(client.futures) == 2
        assert node.get_clock().now().nanoseconds == 0
        client.futures[1].complete(_successful_response())
        assert len(backend.calls) == 1
    finally:
        executor.remove_node(node)
        node.destroy_node()
        executor.shutdown()
        rclpy.shutdown(context=context)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf"), -float("inf")])
def test_snapshot_timeout_must_be_finite_and_positive(timeout):
    """Reject deadline configurations that cannot expire correctly."""
    context = Context()
    rclpy.init(context=context)
    try:
        with pytest.raises(ValueError, match="snapshot_request_timeout"):
            ExecutionManagerNode(
                context=context,
                parameter_overrides=[Parameter("snapshot_request_timeout", value=timeout)],
            )
    finally:
        rclpy.shutdown(context=context)
