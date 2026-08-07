"""Launch the standard 2D pose region monitor."""

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Create the 2D monitor launch description."""
    default_ts = (
        get_package_share_directory("ltl_automaton_std_transition_systems")
        + "/config/example_2d_pose_ts.yaml"
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "transition_system_path", default_value=default_ts
            ),
            DeclareLaunchArgument(
                "pose_message_type",
                default_value="geometry_msgs/msg/Pose",
            ),
            Node(
                package="ltl_automaton_std_transition_systems",
                executable="region_2d_pose_monitor",
                name="region_2d_pose_monitor",
                output="screen",
                parameters=[
                    {
                        "transition_system_path": LaunchConfiguration(
                            "transition_system_path"
                        ),
                        "pose_message_type": LaunchConfiguration(
                            "pose_message_type"
                        ),
                    }
                ],
            ),
        ]
    )
