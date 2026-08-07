"""Tests for ROS2 planner-node state conversion helpers."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_planner.planner_node import (
    PlannerNode,
    initial_states_from_message,
    load_plugin_specs,
)


def make_state_message(states, dimensions):
    """Build a stamped TS-state message for helper tests."""
    message = TransitionSystemStateStamped()
    message.ts_state.states = states
    message.ts_state.state_dimension_names = dimensions
    return message


def test_initial_states_follow_dimension_names():
    """Map agent values by dimension instead of message ordering."""
    message = make_state_message(
        ["loaded", "r2"],
        ["load", "region"],
    )

    assert initial_states_from_message(message) == {
        "load": "loaded",
        "region": "r2",
    }


@pytest.mark.parametrize(
    "states, dimensions, error",
    [
        ([], [], "empty transition-system state"),
        (["r1"], [], "does not match"),
        (["r1", "r2"], ["region", "region"], "must be unique"),
    ],
)
def test_invalid_initial_state_messages_are_rejected(
    states,
    dimensions,
    error,
):
    """Keep waiting when an agent publishes a malformed initial state."""
    message = make_state_message(states, dimensions)

    with pytest.raises(ValueError, match=error):
        initial_states_from_message(message)


def test_load_plugin_specs_preserves_ros1_contract(tmp_path: Path):
    """Load class, module path, and argument mappings from YAML."""
    config_path = tmp_path / "plugins.yaml"
    config_path.write_text(
        """
plugins:
  ExamplePlugin:
    path: example_package.example_plugin
    args:
      threshold: 3
""".lstrip(),
        encoding="utf-8",
    )

    assert load_plugin_specs(config_path) == {
        "ExamplePlugin": {
            "path": "example_package.example_plugin",
            "args": {"threshold": 3},
        }
    }


@pytest.mark.parametrize(
    "content, error",
    [
        ("plugins: []\n", "must be a mapping"),
        ("plugins:\n  ExamplePlugin: {}\n", "requires a module 'path'"),
        (
            "plugins:\n  ExamplePlugin:\n    path: example.module\n"
            "    args: invalid\n",
            "'args' must be a mapping",
        ),
    ],
)
def test_invalid_plugin_specs_are_rejected(tmp_path: Path, content, error):
    """Reject malformed plugin files before importing any modules."""
    config_path = tmp_path / "plugins.yaml"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        load_plugin_specs(config_path)


def test_plugin_lifecycle_and_state_hook(tmp_path: Path, monkeypatch):
    """Initialize a configured plugin and run its TS-update hook."""
    config_path = tmp_path / "plugins.yaml"
    config_path.write_text(
        """
plugins:
  ExamplePlugin:
    path: example.module
    args:
      threshold: 3
""".lstrip(),
        encoding="utf-8",
    )
    events = []

    class ExamplePlugin:
        def __init__(self, planner, args):
            events.append(("construct", planner, args))

        def set_node(self, node):
            events.append(("set_node", node))

        def init(self):
            events.append(("init",))

        def set_sub_and_pub(self):
            events.append(("set_sub_and_pub",))

        def run_at_ts_update(self, state):
            events.append(("update", state))

    monkeypatch.setattr(
        "ltl_automaton_planner.planner_node.importlib.import_module",
        lambda module_path: SimpleNamespace(ExamplePlugin=ExamplePlugin),
    )

    class Logger:
        def info(self, message):
            events.append(("info", message))

        def error(self, message):
            events.append(("error", message))

    host = SimpleNamespace(
        _plugins_initialized=False,
        plugins={},
        ltl_planner=object(),
        get_parameter=lambda name: SimpleNamespace(value=str(config_path)),
        get_logger=lambda: Logger(),
    )

    PlannerNode._initialize_plugins(host)
    PlannerNode._run_plugins(host, ("r2",))

    assert "ExamplePlugin" in host.plugins
    assert ("construct", host.ltl_planner, {"threshold": 3}) in events
    assert ("set_node", host) in events
    assert ("init",) in events
    assert ("set_sub_and_pub",) in events
    assert ("update", ("r2",)) in events


def test_plugin_can_refresh_planner_outputs():
    """Expose one public refresh hook for replanning plugins."""
    events = []
    host = SimpleNamespace(
        _publish_possible_states=lambda: events.append("states"),
        _publish_plan=lambda: events.append("plan"),
        _publish_next_move=lambda: events.append("next"),
    )

    PlannerNode.refresh_planner_outputs(host)

    assert events == ["states", "plan", "next"]
