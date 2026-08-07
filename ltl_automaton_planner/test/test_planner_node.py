"""Tests for ROS2 planner-node state conversion helpers."""

import hashlib
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
)

from ltl_automaton_msgs.msg import (
    PlannerStatus,
    TransitionSystemStateStamped,
)
from ltl_automaton_msgs.srv import LoadTransitionSystem
from ltl_automaton_planner.planner_node import (
    PlannerNode,
    initial_states_from_message,
    load_plugin_specs,
)


VALID_TS_A = """
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

VALID_TS_B = """
state_dim:
  - region
state_models:
  region:
    initial: r3
    nodes:
      r3:
        connected_to:
          r3: stay_r3
actions:
  stay_r3:
    guard: "1"
    weight: 1.5
""".lstrip()


@pytest.fixture
def planner_runtime():
    """Create an isolated single-threaded planner service runtime."""
    context = Context()
    rclpy.init(context=context)
    planner = PlannerNode(context=context)
    client_node = rclpy.create_node(
        "planner_lifecycle_test",
        context=context,
    )
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(planner)
    executor.add_node(client_node)
    runtime = SimpleNamespace(
        context=context,
        planner=planner,
        client_node=client_node,
        executor=executor,
    )

    try:
        yield runtime
    finally:
        executor.remove_node(client_node)
        executor.remove_node(planner)
        client_node.destroy_node()
        planner.destroy_node()
        executor.shutdown()
        rclpy.shutdown(context=context)


def call_load_transition_system(runtime, yaml_content):
    """Call the real ROS service and return its generated response."""
    client = runtime.client_node.create_client(
        LoadTransitionSystem,
        "load_transition_system",
    )
    assert client.wait_for_service(timeout_sec=2.0)

    request = LoadTransitionSystem.Request()
    request.transition_system_yaml = yaml_content
    future = client.call_async(request)
    runtime.executor.spin_until_future_complete(
        future,
        timeout_sec=3.0,
    )
    runtime.client_node.destroy_client(client)

    assert future.done()
    assert future.result() is not None
    return future.result()


def wait_for_message(runtime, messages, timeout=3.0):
    """Spin the isolated runtime until a subscription receives a message."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline and not messages:
        runtime.executor.spin_once(timeout_sec=0.1)

    return bool(messages)


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


def test_initial_status_reaches_a_late_subscriber(planner_runtime):
    """Retain the initial lifecycle state for a late DDS subscriber."""
    statuses = []
    status_qos = QoSProfile(
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    subscription = planner_runtime.client_node.create_subscription(
        PlannerStatus,
        "planner_status",
        statuses.append,
        status_qos,
    )

    assert wait_for_message(planner_runtime, statuses)
    assert statuses[-1].state == PlannerStatus.UNINITIALIZED
    assert planner_runtime.planner._planner_state == (
        PlannerStatus.UNINITIALIZED
    )

    planner_runtime.client_node.destroy_subscription(subscription)


def test_successful_load_activates_ts_and_ready_state(planner_runtime):
    """Load and validate YAML through the real ROS service."""
    response = call_load_transition_system(
        planner_runtime,
        VALID_TS_A,
    )

    assert response.success
    assert response.active_ts_sha256 == hashlib.sha256(
        VALID_TS_A.encode("utf-8")
    ).hexdigest()
    assert planner_runtime.planner._planner_state == PlannerStatus.READY
    assert set(
        planner_runtime.planner._active_transition_system.nodes
    ) == {("r1",), ("r2",)}


@pytest.mark.parametrize(
    "invalid_yaml",
    [
        "state_dim: [",
        "state_dim: [region]\nstate_models: []\nactions: {}\n",
    ],
)
def test_invalid_load_preserves_active_ts(planner_runtime, invalid_yaml):
    """Keep the previous TS, hash, and status after invalid input."""
    first_response = call_load_transition_system(
        planner_runtime,
        VALID_TS_A,
    )
    active_ts = planner_runtime.planner._active_transition_system

    response = call_load_transition_system(
        planner_runtime,
        invalid_yaml,
    )

    assert not response.success
    assert response.message
    assert response.active_ts_sha256 == first_response.active_ts_sha256
    assert planner_runtime.planner._active_transition_system is active_ts
    assert planner_runtime.planner._active_ts_sha256 == (
        first_response.active_ts_sha256
    )
    assert planner_runtime.planner._planner_state == PlannerStatus.READY


def test_ready_transition_system_can_be_replaced(planner_runtime):
    """Replace TS A atomically with TS B while the planner is READY."""
    first_response = call_load_transition_system(
        planner_runtime,
        VALID_TS_A,
    )
    first_ts = planner_runtime.planner._active_transition_system

    second_response = call_load_transition_system(
        planner_runtime,
        VALID_TS_B,
    )

    assert second_response.success
    assert second_response.active_ts_sha256 != (
        first_response.active_ts_sha256
    )
    assert planner_runtime.planner._active_transition_system is not first_ts
    assert set(
        planner_runtime.planner._active_transition_system.nodes
    ) == {("r3",)}
    assert planner_runtime.planner._planner_state == PlannerStatus.READY


@pytest.mark.parametrize(
    "rejected_state",
    [PlannerStatus.PLANNING, PlannerStatus.ACTIVE],
)
def test_load_is_rejected_while_busy_or_active(
    planner_runtime,
    rejected_state,
):
    """Reject TS replacement without changing any active state."""
    first_response = call_load_transition_system(
        planner_runtime,
        VALID_TS_A,
    )
    active_ts = planner_runtime.planner._active_transition_system
    active_planner = object()
    planner_runtime.planner.ltl_planner = active_planner
    planner_runtime.planner._set_planner_status(
        rejected_state,
        "Test rejection state.",
    )

    response = call_load_transition_system(
        planner_runtime,
        VALID_TS_B,
    )

    assert not response.success
    assert response.active_ts_sha256 == first_response.active_ts_sha256
    assert planner_runtime.planner._active_transition_system is active_ts
    assert planner_runtime.planner.ltl_planner is active_planner
    assert planner_runtime.planner._planner_state == rejected_state
