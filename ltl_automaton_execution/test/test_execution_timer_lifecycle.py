"""Check execution delay validation and native one-shot timer cleanup."""

from types import SimpleNamespace

import pytest
import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter

from ltl_automaton_execution.execution_node import ExecutionManagerNode
from ltl_automaton_execution.fake_runtime import FakePlant
from ltl_automaton_execution.models import SymbolicState
from test_execution_node import DelayedSnapshotClient, RecordingBackend
from test_execution_node import _observation, _spin_until, _successful_response


@pytest.fixture
def timer_runtime():
    """Use a real ROS executor, timers and the default fake backend."""
    context = Context()
    rclpy.init(context=context)
    plant = FakePlant(SymbolicState(("region", "load"), ("r1", "empty")))
    node = ExecutionManagerNode(
        context=context, fake_plant=plant,
        parameter_overrides=[Parameter("execution_delay_sec", value=0.25)],
    )
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(node)
    try:
        yield SimpleNamespace(node=node, plant=plant, executor=executor)
    finally:
        executor.remove_node(node)
        node.destroy_node()
        executor.shutdown()
        rclpy.shutdown(context=context)


def test_completed_steps_destroy_their_native_timers(timer_runtime):
    """Finished one-shot callbacks must not accumulate in Node.timers."""
    runtime = timer_runtime
    baseline = len(tuple(runtime.node.timers))
    fired = []
    for index in range(3):
        assert runtime.node._schedule(0.001, lambda value=index: fired.append(value))
    assert len(tuple(runtime.node.timers)) == baseline + 3
    assert _spin_until(runtime.executor, lambda: len(fired) == 3)
    assert sorted(fired) == [0, 1, 2]
    assert not runtime.node._execution_timers
    assert len(tuple(runtime.node.timers)) == baseline


def test_callback_failure_still_releases_timer_and_propagates(timer_runtime):
    """Preserve callback errors while releasing resources for the next step."""
    runtime = timer_runtime
    baseline = len(tuple(runtime.node.timers))
    fired = []

    def fail():
        fired.append("failed")
        raise RuntimeError("Injected execution callback failure.")

    assert runtime.node._schedule(0.001, fail)
    with pytest.raises(RuntimeError, match="Injected execution callback failure"):
        _spin_until(runtime.executor, lambda: bool(fired))
    assert not runtime.node._execution_timers
    assert len(tuple(runtime.node.timers)) == baseline
    assert runtime.node._schedule(0.001, lambda: fired.append("next"))
    assert _spin_until(runtime.executor, lambda: len(fired) == 2)
    assert fired == ["failed", "next"]
    assert len(tuple(runtime.node.timers)) == baseline


def test_fake_feedback_publish_failure_releases_dispatch_and_timer(timer_runtime):
    """Keep publication errors visible and allow a later observed step to run."""
    runtime = timer_runtime
    client = DelayedSnapshotClient()
    runtime.node._snapshot_client = client
    publisher = runtime.node._state_publisher
    diagnostics = []
    runtime.node._manager._diagnostic = diagnostics.append

    def fail(_message):
        raise RuntimeError("Injected TS feedback publication failure.")

    runtime.node._state_publisher = SimpleNamespace(publish=fail)
    baseline = len(tuple(runtime.node.timers))
    first = _observation(1)
    runtime.node._on_observation(first)
    client.future.set_result(_successful_response())
    assert runtime.node._manager.in_flight
    with pytest.raises(RuntimeError, match="Injected TS feedback publication failure"):
        _spin_until(runtime.executor, lambda: not runtime.node._manager.in_flight)
    assert not runtime.node._manager.in_flight
    assert not runtime.node._execution_timers
    assert len(tuple(runtime.node.timers)) == baseline
    assert runtime.plant.current_state.states == ("r2", "empty")
    assert "Injected TS feedback publication failure" in diagnostics[-1]
    runtime.node._on_observation(first)
    assert not runtime.node._execution_timers
    runtime.node._state_publisher = publisher
    latest = _observation(1, sequence=1)
    latest.possible_product_node_ids = [2]
    latest.next_action = "wait"
    runtime.node._on_observation(latest)
    assert runtime.node._manager.in_flight
    assert _spin_until(runtime.executor, lambda: not runtime.node._manager.in_flight)
    assert len(tuple(runtime.node.timers)) == baseline


def test_teardown_clears_pending_steps_and_ignores_queued_callback(timer_runtime):
    """A cancelled fake step cannot later mutate the plant through its callback."""
    runtime = timer_runtime
    client = DelayedSnapshotClient()
    runtime.node._snapshot_client = client
    runtime.node._on_observation(_observation(1))
    client.future.set_result(_successful_response())
    timer, = runtime.node._execution_timers
    queued_callback = timer.callback
    original = runtime.plant.current_state
    runtime.node.destroy_node()
    assert not runtime.node._execution_timers
    assert not tuple(runtime.node.timers)
    queued_callback()
    assert runtime.plant.current_state == original
    assert not runtime.node._schedule(0.001, lambda: runtime.plant.set_state(
        SymbolicState(("region", "load"), ("r2", "empty")),
    ))
    assert runtime.plant.current_state == original


def test_zero_delay_keeps_the_existing_one_millisecond_timer(timer_runtime):
    """Keep zero-delay dispatch asynchronous and preserve its existing minimum."""
    runtime = timer_runtime
    fired = []
    baseline = len(tuple(runtime.node.timers))
    assert runtime.node._schedule(0.0, lambda: fired.append(True))
    timer, = runtime.node._execution_timers
    assert timer.timer_period_ns == 1_000_000
    assert not fired
    assert _spin_until(runtime.executor, lambda: bool(fired))
    assert fired == [True]
    assert len(tuple(runtime.node.timers)) == baseline


@pytest.mark.parametrize("delay", [float("nan"), float("inf"), -float("inf"), -1.0, 1e10])
def test_default_node_rejects_invalid_delay_at_startup(delay):
    """Invalid default-backend delays fail before a command is dispatched."""
    context = Context()
    rclpy.init(context=context)
    try:
        with pytest.raises(ValueError, match="execution_delay_sec"):
            ExecutionManagerNode(
                context=context,
                parameter_overrides=[Parameter("execution_delay_sec", value=delay)],
            )
    finally:
        rclpy.shutdown(context=context)


def test_custom_backend_keeps_its_independent_scheduler_contract():
    """The default ROS timer range must not constrain a supplied backend."""
    context = Context()
    rclpy.init(context=context)
    backend = RecordingBackend()
    node = ExecutionManagerNode(
        context=context, backend=backend,
        parameter_overrides=[Parameter("execution_delay_sec", value=1e10)],
    )
    try:
        assert node._manager._backend is backend
        assert node.get_parameter("execution_delay_sec").value == 1e10
        assert not node._execution_timers
    finally:
        node.destroy_node()
        rclpy.shutdown(context=context)
