"""Launch the simulator-agnostic fake execution manager."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "snapshot_request_timeout", default_value="5.0"
        ),
        Node(
            package="ltl_automaton_execution",
            executable="execution_node",
            name="ltl_execution_manager",
            output="screen",
            parameters=[
                {
                    "snapshot_request_timeout": ParameterValue(
                        LaunchConfiguration("snapshot_request_timeout"),
                        value_type=float,
                    )
                }
            ],
        ),
    ])
