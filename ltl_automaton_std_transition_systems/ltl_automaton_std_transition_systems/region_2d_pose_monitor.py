"""ROS 2 monitor mapping planar poses to transition-system regions."""

import math
from pathlib import Path

import rclpy
from geometry_msgs.msg import (
    Pose,
    PoseStamped,
    PoseWithCovariance,
    PoseWithCovarianceStamped,
)
from ltl_automaton_msgs.srv import ClosestState
from ltl_automaton_planner_core.configuration.transition_system import (
    import_ts_from_file,
)
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String


POSE_TYPES = {
    "geometry_msgs/msg/Pose": Pose,
    "geometry_msgs/msg/PoseStamped": PoseStamped,
    "geometry_msgs/msg/PoseWithCovariance": PoseWithCovariance,
    "geometry_msgs/msg/PoseWithCovarianceStamped": PoseWithCovarianceStamped,
}


def _pose_from_message(message):
    if isinstance(message, Pose):
        return message
    if isinstance(message, PoseStamped):
        return message.pose
    if isinstance(message, PoseWithCovariance):
        return message.pose
    if isinstance(message, PoseWithCovarianceStamped):
        return message.pose.pose
    raise TypeError(f"Unsupported pose message: {type(message).__name__}")


class Region2DPoseModel:
    """ROS-independent region membership and hysteresis logic."""

    def __init__(self, region_dict):
        self.region_dict = region_dict
        self.state = None
        self.station_access_request = ""
        self.stations = [
            name
            for name, data in region_dict["nodes"].items()
            if data["attr"]["type"] == "station"
        ]
        self.squares = [
            name
            for name, data in region_dict["nodes"].items()
            if data["attr"]["type"] == "square"
        ]

    def is_in_square(self, pose, square, hysteresis=0.0):
        attr = self.region_dict["nodes"][square]["attr"]
        half = float(attr["length"]) / 2.0 + hysteresis
        return (
            abs(attr["pose"][0][0] - pose.position.x) < half
            and abs(attr["pose"][0][1] - pose.position.y) < half
        )

    @staticmethod
    def _yaw(pose):
        quaternion = pose.orientation
        sin_yaw = 2.0 * (
            quaternion.w * quaternion.z + quaternion.x * quaternion.y
        )
        cos_yaw = 1.0 - 2.0 * (
            quaternion.y * quaternion.y + quaternion.z * quaternion.z
        )
        return math.atan2(sin_yaw, cos_yaw)

    def is_in_station(
        self, pose, station, dist_hysteresis=0.0, angle_hysteresis=0.0
    ):
        attr = self.region_dict["nodes"][station]["attr"]
        distance = math.hypot(
            attr["pose"][0][0] - pose.position.x,
            attr["pose"][0][1] - pose.position.y,
        )
        angle = abs(
            math.atan2(
                math.sin(attr["pose"][1][0] - self._yaw(pose)),
                math.cos(attr["pose"][1][0] - self._yaw(pose)),
            )
        )
        threshold = attr.get("angle_threshold", attr.get("angle_tolerance"))
        if threshold is None:
            raise ValueError(f"Station {station!r} has no angle threshold.")
        return (
            distance < attr["radius"] + dist_hysteresis
            and angle < threshold + angle_hysteresis
        )

    def _find_region(self, pose, region_names):
        names = list(region_names)
        for name in names:
            if (
                name in self.stations
                and self.station_access_request == name
                and self.is_in_station(pose, name)
            ):
                self.state = name
                return name
        for name in names:
            if name in self.squares and self.is_in_square(pose, name):
                self.state = name
                return name
        return None

    def update(self, pose):
        """Update the region and return its name, or None when outside the TS."""
        nodes = self.region_dict["nodes"]
        if self.state:
            connected = nodes[self.state]["connected_to"]
            if self.state in self.stations:
                attr = nodes[self.state]["attr"]
                still_inside = self.is_in_station(
                    pose,
                    self.state,
                    attr["dist_hysteresis"],
                    attr["angle_hysteresis"],
                )
                if still_inside and self.station_access_request == self.state:
                    return self.state
                found = self._find_region(pose, connected)
                if found:
                    return found
            else:
                stations = [name for name in connected if name in self.stations]
                found = self._find_region(pose, stations)
                if found:
                    return found
                attr = nodes[self.state]["attr"]
                if self.is_in_square(pose, self.state, attr["hysteresis"]):
                    return self.state
                squares = [name for name in connected if name in self.squares]
                found = self._find_region(pose, squares)
                if found:
                    return found
        return self._find_region(pose, nodes)

    def closest_region(self, pose):
        """Return the closest connected region and boundary distance."""
        if not self.state:
            return None, None
        closest = None
        closest_distance = math.inf
        nodes = self.region_dict["nodes"]
        for name in nodes[self.state]["connected_to"]:
            if name == self.state:
                continue
            attr = nodes[name]["attr"]
            if attr["type"] == "station":
                distance = math.hypot(
                    attr["pose"][0][0] - pose.position.x,
                    attr["pose"][0][1] - pose.position.y,
                ) - attr["radius"]
            else:
                half = attr["length"] / 2.0
                dx = max(abs(attr["pose"][0][0] - pose.position.x) - half, 0.0)
                dy = max(abs(attr["pose"][0][1] - pose.position.y) - half, 0.0)
                distance = math.hypot(dx, dy)
            if distance < closest_distance:
                closest = name
                closest_distance = distance
        return closest, closest_distance if closest is not None else None


class Region2DPoseMonitor(Node):
    """Publish a planar TS region from a configurable geometry pose type."""

    def __init__(self):
        super().__init__("region_2d_pose_monitor")
        self.declare_parameter("transition_system_path", "")
        self.declare_parameter("pose_message_type", "geometry_msgs/msg/Pose")
        path = self.get_parameter("transition_system_path").value
        if not path:
            raise ValueError("transition_system_path must be set.")
        ts_dict = import_ts_from_file(Path(path).read_text(encoding="utf-8"))
        self.model = Region2DPoseModel(
            ts_dict["state_models"]["2d_pose_region"]
        )
        self.current_pose = None
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.region_publisher = self.create_publisher(String, "current_region", qos)
        pose_type_name = self.get_parameter("pose_message_type").value
        if pose_type_name not in POSE_TYPES:
            raise ValueError(f"Unsupported pose_message_type: {pose_type_name}")
        self.create_subscription(
            POSE_TYPES[pose_type_name],
            "agent_2d_region_pose",
            self._pose_callback,
            10,
        )
        self.create_subscription(
            String, "station_access_request", self._station_callback, 10
        )
        self.create_service(ClosestState, "closest_region", self._closest_callback)

    def _pose_callback(self, message):
        self.current_pose = _pose_from_message(message)
        previous = self.model.state
        region = self.model.update(self.current_pose)
        if region is not None and region != previous:
            self.region_publisher.publish(String(data=region))

    def _station_callback(self, message):
        self.model.station_access_request = message.data

    def _closest_callback(self, request, response):
        del request
        if self.current_pose is not None:
            region, distance = self.model.closest_region(self.current_pose)
            if region is not None:
                response.closest_state = region
                response.metric = distance
        return response


def main(args=None):
    """Run the 2D pose monitor."""
    rclpy.init(args=args)
    node = Region2DPoseMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
