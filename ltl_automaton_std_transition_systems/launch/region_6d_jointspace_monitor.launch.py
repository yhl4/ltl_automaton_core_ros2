"""Launch the standard 6D joint-space region monitor."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Create the 6D monitor launch description."""
    return LaunchDescription(
        [
            DeclareLaunchArgument("transition_system_path"),
            Node(
                package="ltl_automaton_std_transition_systems",
                executable="region_6d_jointspace_monitor",
                name="region_6d_jointspace_monitor",
                output="screen",
                parameters=[
                    {
                        "transition_system_path": LaunchConfiguration(
                            "transition_system_path"
                        )
                    }
                ],
            ),
        ]
    )
