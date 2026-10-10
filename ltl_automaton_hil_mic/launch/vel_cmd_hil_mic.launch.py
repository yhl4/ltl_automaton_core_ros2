"""Launch the velocity mixed-initiative controller."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Create the velocity mixer launch description."""
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "state_dimension_name", default_value="2d_pose_region"
            ),
            DeclareLaunchArgument("safety_check_timeout", default_value="1.0"),
            Node(
                package="ltl_automaton_hil_mic",
                executable="vel_cmd_hil_mic",
                parameters=[
                    {
                        "state_dimension_name": LaunchConfiguration(
                            "state_dimension_name"
                        ),
                        "safety_check_timeout": ParameterValue(
                            LaunchConfiguration("safety_check_timeout"),
                            value_type=float,
                        ),
                    }
                ],
            ),
        ]
    )
