"""Tests for deterministic KTH demo state transitions."""

import math
from types import MethodType

import rclpy
import pytest
from rclpy.context import Context
from rclpy.node import Node
from rclpy.parameter import Parameter

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


def _construct_driver(monkeypatch, step_delay, max_steps=8, calls=None):
    """Construct the demo with isolated ROS context and entity spies."""
    context = Context()
    rclpy.init(context=context)
    if calls is None:
        calls = []
    captured = {}
    original_init = Node.__init__

    def patched_init(node, node_name, *args, **kwargs):
        kwargs["context"] = context
        kwargs["parameter_overrides"] = [
            Parameter("step_delay", value=step_delay),
            Parameter("max_steps", value=max_steps),
        ]
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
