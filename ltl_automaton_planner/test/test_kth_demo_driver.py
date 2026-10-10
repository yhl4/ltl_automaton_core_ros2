"""Tests for deterministic KTH demo state transitions."""

import math
from types import MethodType
from types import SimpleNamespace

import rclpy
import pytest
import ltl_automaton_planner.kth_demo_driver as kth_demo_driver
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rcl_interfaces.srv import SetParametersAtomically

from ltl_automaton_planner.kth_demo_driver import KthDemoDriver
from ltl_automaton_planner.kth_demo_driver import next_state_for_action


@pytest.mark.parametrize(
    "state, action, expected",
    [
        (("r1", "unloaded"), "goto_r2", ("r2", "unloaded")),
        (("r1", "loaded"), "goto_r3", ("r3", "loaded")),
        (("r3", "loaded"), "goto_r1", ("r1", "loaded")),
        (("r2", "unloaded"), "pick", ("r2", "loaded")),
        (("r2", "loaded"), "drop", ("r2", "unloaded")),
    ],
)
def test_next_state_for_action(state, action, expected):
    """Apply each supported action without changing unrelated dimensions."""
    assert next_state_for_action(state, action) == expected


@pytest.mark.parametrize(
    "state, action",
    [
        (("r1", "unloaded"), "pick"),
        (("r2", "loaded"), "pick"),
        (("r2", "unloaded"), "drop"),
        (("r1", "unloaded"), "unknown"),
    ],
)
def test_next_state_for_action_rejects_invalid_transition(state, action):
    """Reject actions that violate the KTH example transition guards."""
    with pytest.raises(ValueError):
        next_state_for_action(state, action)


def test_published_state_messages_own_dimension_and_state_lists(monkeypatch):
    """Keep each published ROS state independent of later message edits."""
    original_dimensions = list(kth_demo_driver.STATE_DIMENSIONS)
    driver = None
    context = None
    try:
        driver, context, _ = _construct_driver(monkeypatch, 0.25)
        published = []
        driver.state_publisher = SimpleNamespace(publish=published.append)
        first_input = ("r1", "unloaded")
        second_input = ("r2", "loaded")

        driver._publish_state(first_input)
        driver._publish_state(second_input)

        assert len(published) == 2
        first, second = published
        assert list(first.ts_state.states) == list(first_input)
        assert list(second.ts_state.states) == list(second_input)
        assert list(first.ts_state.state_dimension_names) == original_dimensions
        assert list(second.ts_state.state_dimension_names) == original_dimensions
        assert first.ts_state.states is not second.ts_state.states
        assert (
            first.ts_state.state_dimension_names
            is not second.ts_state.state_dimension_names
        )

        first.ts_state.states[0] = "changed"
        first.ts_state.state_dimension_names[0] = "changed_dimension"
        assert list(second.ts_state.states) == list(second_input)
        assert list(second.ts_state.state_dimension_names) == original_dimensions
        assert kth_demo_driver.STATE_DIMENSIONS == original_dimensions
        assert first_input == ("r1", "unloaded")
        assert second_input == ("r2", "loaded")

        driver._publish_state(("r3", "unloaded"))
        third = published[-1]
        assert list(third.ts_state.state_dimension_names) == original_dimensions
        assert third.ts_state.state_dimension_names is not second.ts_state.state_dimension_names
    finally:
        kth_demo_driver.STATE_DIMENSIONS[:] = original_dimensions
        if driver is not None:
            _close_driver(driver, context)


def _construct_driver(
    monkeypatch, step_delay, max_steps=8, calls=None, extra_parameters=None
):
    """Construct the demo with isolated ROS context and entity spies."""
    context = Context()
    rclpy.init(context=context)
    if calls is None:
        calls = []
    captured = {}
    original_init = Node.__init__
    if extra_parameters is None:
        extra_parameters = []

    def patched_init(node, node_name, *args, **kwargs):
        kwargs["context"] = context
        kwargs["parameter_overrides"] = [
            Parameter("step_delay", value=step_delay),
            Parameter("max_steps", value=max_steps),
        ] + list(extra_parameters)
        original_init(node, node_name, *args, **kwargs)
        captured["node"] = node

        def generic_spy(_node, *spy_args, **spy_kwargs):
            calls.append(("entity", spy_args[0] if spy_args else None))
            return object()

        original_create_timer = node.create_timer

        def timer_spy(_node, timer_period_sec, *timer_args, **timer_kwargs):
            calls.append(("timer", timer_period_sec))
            return original_create_timer(
                timer_period_sec, *timer_args, **timer_kwargs
            )

        node.create_publisher = MethodType(generic_spy, node)
        node.create_subscription = MethodType(generic_spy, node)
        node.create_client = MethodType(generic_spy, node)
        node.create_timer = MethodType(timer_spy, node)

    monkeypatch.setattr(Node, "__init__", patched_init)
    try:
        return KthDemoDriver(), context, calls
    except Exception:
        node = captured.get("node")
        if node is not None:
            node.destroy_node()
        rclpy.shutdown(context=context)
        raise


def _close_driver(driver, context):
    """Destroy the isolated node and ROS context used by a parameter test."""
    driver.destroy_node()
    rclpy.shutdown(context=context)


@pytest.mark.parametrize(
    "step_delay, expected",
    [
        (0.0, "Parameter 'step_delay' must be positive."),
        (-1.0, "Parameter 'step_delay' must be positive."),
        (-math.inf, "Parameter 'step_delay' must be positive."),
        (math.nan, "step_delay must be finite."),
        (math.inf, "step_delay must be finite."),
        (1e10, "step_delay is outside the ROS timer range."),
    ],
)
def test_step_delay_rejected_before_ros_entities(monkeypatch, step_delay, expected):
    """Reject invalid timer periods before creating demo ROS entities."""
    calls = []
    with pytest.raises(ValueError, match=f"^{expected}$") as error:
        _construct_driver(monkeypatch, step_delay, calls=calls)
    assert str(error.value) == expected
    assert calls == []
    if step_delay == 1e10:
        assert isinstance(error.value.__cause__, OverflowError)


def test_max_steps_error_precedes_step_delay_range_check(monkeypatch):
    """Keep the existing max_steps diagnostic precedence."""
    calls = []
    with pytest.raises(ValueError, match="Parameter 'max_steps' must be positive"):
        _construct_driver(monkeypatch, math.nan, max_steps=0, calls=calls)
    assert calls == []


@pytest.mark.parametrize(
    "step_delay, expected_nanoseconds",
    [(0.25, 250000000), (1e-12, 0)],
)
def test_valid_step_delay_preserves_timer_value(monkeypatch, step_delay, expected_nanoseconds):
    """Keep valid values, including ROS sub-nanosecond truncation, unchanged."""
    driver, context, calls = _construct_driver(monkeypatch, step_delay)
    try:
        timer_calls = [value for kind, value in calls if kind == "timer"]
        assert timer_calls == [step_delay]
        assert driver.step_timer.timer_period_ns == expected_nanoseconds
    finally:
        _close_driver(driver, context)


def test_startup_overrides_populate_all_cached_configuration(monkeypatch):
    """Apply all startup-only overrides before caching the demo configuration."""
    driver, context, calls = _construct_driver(
        monkeypatch,
        0.25,
        max_steps=12,
        extra_parameters=[
            Parameter("scenario", value="full"),
            Parameter("replanning_after_steps", value=6),
            Parameter("replanning_hard_task", value="<> r1"),
            Parameter("replanning_soft_task", value="[]!r1"),
        ],
    )
    try:
        expected = {
            "scenario": "full",
            "step_delay": 0.25,
            "max_steps": 12,
            "replanning_after_steps": 6,
            "replanning_hard_task": "<> r1",
            "replanning_soft_task": "[]!r1",
        }
        for name, value in expected.items():
            assert driver.get_parameter(name).value == value
            assert driver.describe_parameter(name).read_only
            assert getattr(driver, name) == value
        assert driver.step_timer.timer_period_ns == 250000000
        assert [value for kind, value in calls if kind == "timer"] == [0.25]
    finally:
        _close_driver(driver, context)


def test_readonly_runtime_updates_are_atomic_and_use_sim_time_remains_dynamic(
    monkeypatch,
):
    """Reject cached-configuration writes while allowing use_sim_time changes."""
    driver, context, calls = _construct_driver(monkeypatch, 0.25, max_steps=8)
    readonly = {
        "scenario": "full",
        "step_delay": 0.5,
        "max_steps": 12,
        "replanning_after_steps": 6,
        "replanning_hard_task": "<> r1",
        "replanning_soft_task": "[]!r1",
    }
    names = tuple(readonly)
    try:
        before_parameters = {
            name: driver.get_parameter(name).value for name in names
        }
        before_cached = {
            name: getattr(driver, name) for name in names
        }
        before_timer = driver.step_timer.timer_period_ns

        for name, value in readonly.items():
            result = driver.set_parameters([Parameter(name, value=value)])[0]
            assert not result.successful
            assert driver.describe_parameter(name).read_only
            assert driver.get_parameter(name).value == before_parameters[name]
            assert getattr(driver, name) == before_cached[name]
            assert driver.step_timer.timer_period_ns == before_timer

        result = driver.set_parameters_atomically(
            [
                Parameter("use_sim_time", value=True),
                Parameter("scenario", value="full"),
            ]
        )
        assert not result.successful
        assert driver.get_parameter("use_sim_time").value is False
        assert {
            name: driver.get_parameter(name).value for name in names
        } == before_parameters
        assert {name: getattr(driver, name) for name in names} == before_cached
        assert driver.step_timer.timer_period_ns == before_timer

        result = driver.set_parameters(
            [Parameter("use_sim_time", value=True)]
        )[0]
        assert result.successful
        assert driver.get_parameter("use_sim_time").value is True
    finally:
        _close_driver(driver, context)


def test_public_parameter_service_enforces_readonly_and_allows_use_sim_time(
    monkeypatch,
):
    """Exercise the native atomic parameter service boundary."""
    driver, context, calls = _construct_driver(monkeypatch, 0.25, max_steps=8)
    executor = SingleThreadedExecutor(context=context)
    client = Node.create_client(
        driver,
        SetParametersAtomically,
        "kth_demo_driver/set_parameters_atomically",
    )
    executor.add_node(driver)
    try:
        assert driver.get_parameter("use_sim_time").value is False
        before_cache = {
            "step_delay": driver.step_delay,
            "timer_ns": driver.step_timer.timer_period_ns,
        }

        mixed = SetParametersAtomically.Request()
        mixed.parameters = [
            Parameter("use_sim_time", value=True).to_parameter_msg(),
            Parameter("step_delay", value=0.5).to_parameter_msg(),
        ]
        assert client.wait_for_service(timeout_sec=2.0)
        future = client.call_async(mixed)
        executor.spin_until_future_complete(future, timeout_sec=2.0)
        assert future.done()
        assert not future.result().result.successful
        assert driver.describe_parameter("step_delay").read_only
        assert driver.get_parameter("step_delay").value == 0.25
        assert driver.get_parameter("use_sim_time").value is False
        assert driver.step_delay == before_cache["step_delay"]
        assert driver.step_timer.timer_period_ns == before_cache["timer_ns"]

        dynamic = SetParametersAtomically.Request()
        dynamic.parameters = [
            Parameter("use_sim_time", value=True).to_parameter_msg(),
        ]
        future = client.call_async(dynamic)
        executor.spin_until_future_complete(future, timeout_sec=2.0)
        assert future.done()
        assert future.result().result.successful
        assert driver.get_parameter("use_sim_time").value is True
    finally:
        driver.destroy_client(client)
        executor.remove_node(driver)
        executor.shutdown()
        driver.destroy_node()
        rclpy.shutdown(context=context)
