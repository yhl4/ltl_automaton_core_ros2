"""Launch the Boolean mixed-initiative controller."""

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Create the Boolean mixer launch description."""
    default_ts = (
        get_package_share_directory("ltl_automaton_hil_mic")
        + "/config/example_bool_ts.yaml"
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "transition_system_path", default_value=default_ts
            ),
            DeclareLaunchArgument(
                "state_dimension_name", default_value="load"
            ),
            DeclareLaunchArgument("monitored_action", default_value="pick"),
            Node(
                package="ltl_automaton_hil_mic",
                executable="bool_cmd_hil_mic",
                parameters=[
                    {
                        "transition_system_path": LaunchConfiguration(
                            "transition_system_path"
                        ),
                        "state_dimension_name": LaunchConfiguration(
                            "state_dimension_name"
                        ),
                        "monitored_action": LaunchConfiguration(
                            "monitored_action"
                        ),
                    }
                ],
            ),
        ]
    )
