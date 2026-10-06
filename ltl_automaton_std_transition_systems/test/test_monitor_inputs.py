"""Check rejected monitor inputs with real ROS nodes and recorded publication."""

from pathlib import Path
from types import SimpleNamespace

from geometry_msgs.msg import Pose
from ltl_automaton_msgs.srv import ClosestState
from ltl_automaton_std_transition_systems.region_2d_pose_monitor import Region2DPoseMonitor
from ltl_automaton_std_transition_systems.region_6d_jointspace_monitor import (
    Region6DJointspaceMonitor,
)
import pytest
import rclpy
from rclpy.parameter import Parameter
from sensor_msgs.msg import JointState
from std_msgs.msg import String


@pytest.fixture(params=["pose", "joint"])
def monitor(request, monkeypatch):
    """Instantiate each monitor from its real example configuration."""
    kind = request.param
    filename = "example_2d_pose_ts.yaml" if kind == "pose" else "example_6d_jointspace_ts.yaml"
    path = Path(__file__).resolve().parents[1] / "config" / filename
    rclpy.init(args=["--ros-args", "-p", f"transition_system_path:={path}"])
    node = Region2DPoseMonitor() if kind == "pose" else Region6DJointspaceMonitor()
    messages = []
    publisher = SimpleNamespace(publish=lambda message: messages.append(message.data))
    monkeypatch.setattr(node, "region_publisher" if kind == "pose" else "publisher", publisher)
    try:
        yield SimpleNamespace(node=node, kind=kind, messages=messages)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def pose(x=0.5):
    """Create a valid unit-orientation pose at a selected cell center."""
    message = Pose()
    message.position.x = x
    message.position.y = 0.5
    message.orientation.w = 1.0
    return message


@pytest.mark.parametrize("invalid", ["nonfinite", "missing"])
def test_invalid_feedback_preserves_last_valid_input_and_allows_recovery(monitor, invalid):
    """Reject invalid feedback without publishing or replacing valid geometry."""
    node = monitor.node
    if monitor.kind == "pose":
        first = pose()
        node._pose_callback(first)
        node._station_callback(String(data="s0"))
        bad = pose()
        if invalid == "nonfinite":
            bad.position.x = float("nan")
        else:
            bad.orientation.w = 0.0
        node._pose_callback(bad)
        assert node.current_pose is first
        response = node._closest_callback(ClosestState.Request(), ClosestState.Response())
        assert response.closest_state == "s0"
        assert response.metric == pytest.approx(-0.15)
        assert node.model.state == "r1"
        assert monitor.messages == ["r1"]
        node._pose_callback(pose(1.5))
        assert monitor.messages == ["r1", "r2"]
    else:
        node._joint_state_callback(JointState(position=[0.0] * 6))
        position = [float("nan")] * 6 if invalid == "nonfinite" else [0.0] * 5
        node._joint_state_callback(JointState(position=position))
        assert node.model.state == "q1"
        assert monitor.messages == ["q1"]
        node._joint_state_callback(JointState(position=[1.0] * 6))
        assert monitor.messages == ["q1", "q2"]


@pytest.mark.parametrize("invalid", [10**400, -(10**400)], ids=["positive", "negative"])
def test_6d_monitor_rejects_oversized_python_input_and_recovers(monkeypatch, invalid):
    """Use a controlled Python input; oversized integers cannot be ROS float64."""
    path = Path(__file__).resolve().parents[1] / "config" / "example_6d_jointspace_ts.yaml"
    rclpy.init(args=["--ros-args", "-p", f"transition_system_path:={path}"])
    node = Region6DJointspaceMonitor()
    messages = []
    publisher = SimpleNamespace(publish=lambda message: messages.append(message.data))
    monkeypatch.setattr(node, "publisher", publisher)
    try:
        node._joint_state_callback(JointState(position=[0.0] * 6))
        for index in (0, 5):
            position = [0.0] * 6
            position[index] = invalid
            node._joint_state_callback(SimpleNamespace(position=position))
            assert node.model.state == "q1"
            assert messages == ["q1"]
        node._joint_state_callback(JointState(position=[1.0] * 6))
        assert node.model.state == "q2"
        assert messages == ["q1", "q2"]
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_monitor_startup_parameters_reject_runtime_writes(monitor):
    """Reject model and subscription changes instead of reporting unused values."""
    node = monitor.node
    original_path = node.get_parameter("transition_system_path").value
    assert node.describe_parameter("transition_system_path").read_only
    result = node.set_parameters([
        Parameter("transition_system_path", value="/tmp/unloaded_transition_system.yaml"),
    ])[0]
    assert not result.successful
    assert node.get_parameter("transition_system_path").value == original_path
    if monitor.kind == "pose":
        assert node.describe_parameter("pose_message_type").read_only
        result = node.set_parameters([
            Parameter("pose_message_type", value="geometry_msgs/msg/PoseStamped"),
        ])[0]
        assert not result.successful
        assert node.get_parameter("pose_message_type").value == "geometry_msgs/msg/Pose"
        node._pose_callback(pose())
        assert monitor.messages == ["r1"]
    else:
        node._joint_state_callback(JointState(position=[0.0] * 6))
        assert monitor.messages == ["q1"]
    assert node.set_parameters([Parameter("use_sim_time", value=True)])[0].successful
