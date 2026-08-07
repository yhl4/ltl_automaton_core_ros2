"""ROS 2 monitor mapping six joint positions to TS regions."""

import math
from pathlib import Path

import rclpy
from ltl_automaton_planner_core.configuration.transition_system import (
    import_ts_from_file,
)
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import JointState
from std_msgs.msg import String


class Region6DJointspaceModel:
    """ROS-independent six-dimensional spherical-region monitor."""

    def __init__(self, region_dict):
        self.region_dict = region_dict
        self.state = None

    def is_in_region(self, position, region, hysteresis=0.0):
        if len(position) < 6:
            raise ValueError("JointState must contain at least six positions.")
        attr = self.region_dict["nodes"][region]["attr"]
        center = attr["position"]
        distance = math.sqrt(
            sum((position[index] - center[index]) ** 2 for index in range(6))
        )
        return distance < attr["radius"] + hysteresis

    def _find(self, position, names):
        for name in names:
            if self.is_in_region(position, name):
                self.state = name
                return name
        return None

    def update(self, position):
        """Return the current region and whether the transition was connected."""
        if self.state:
            found = self._find(
                position,
                self.region_dict["nodes"][self.state]["connected_to"],
            )
            if found:
                return found, True
        previous = self.state
        found = self._find(position, self.region_dict["nodes"])
        return found, previous is None


class Region6DJointspaceMonitor(Node):
    """Publish a 6D joint-space region from JointState feedback."""

    def __init__(self):
        super().__init__("region_6d_jointspace_monitor")
        self.declare_parameter("transition_system_path", "")
        path = self.get_parameter("transition_system_path").value
        if not path:
            raise ValueError("transition_system_path must be set.")
        ts_dict = import_ts_from_file(Path(path).read_text(encoding="utf-8"))
        self.model = Region6DJointspaceModel(
            ts_dict["state_models"]["6d_jointspace_region"]
        )
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.publisher = self.create_publisher(String, "current_region", qos)
        self.create_subscription(
            JointState, "feedback/joint_state", self._joint_state_callback, 10
        )

    def _joint_state_callback(self, message):
        previous = self.model.state
        try:
            region, connected = self.model.update(message.position)
        except ValueError as error:
            self.get_logger().error(str(error))
            return
        if region is not None and region != previous:
            if previous is not None and not connected:
                self.get_logger().warning(
                    f"Unallowable TS transition from {previous} to {region}."
                )
            self.publisher.publish(String(data=region))


def main(args=None):
    """Run the 6D joint-space monitor."""
    rclpy.init(args=args)
    node = Region6DJointspaceMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
