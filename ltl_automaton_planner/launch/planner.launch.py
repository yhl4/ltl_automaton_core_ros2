"""Launch the ROS2 LTL planner node."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Create the planner launch description."""
    default_ts_path = PathJoinSubstitution(
        [
            FindPackageShare("ltl_automaton_planner"),
            "config",
            "minimal_ts.yaml",
        ]
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "transition_system_path",
                default_value=default_ts_path,
            ),
            DeclareLaunchArgument(
                "hard_task",
                default_value="<> r2",
            ),
            DeclareLaunchArgument(
                "soft_task",
                default_value="(r2 || ! r2)",
            ),
            DeclareLaunchArgument(
                "beta",
                default_value="1000.0",
            ),
            DeclareLaunchArgument(
                "gamma",
                default_value="10.0",
            ),
            DeclareLaunchArgument(
                "initial_ts_state_from_agent",
                default_value="false",
            ),
            DeclareLaunchArgument(
                "replan_on_unplanned_move",
                default_value="true",
            ),
            DeclareLaunchArgument(
                "check_timestamp",
                default_value="true",
            ),
            DeclareLaunchArgument(
                "plugin_config_path",
                default_value="",
            ),
            Node(
                package="ltl_automaton_planner",
                executable="planner_node",
                name="ltl_planner",
                output="screen",
                parameters=[
                    {
                        "transition_system_path": LaunchConfiguration(
                            "transition_system_path"
                        ),
                        "hard_task": LaunchConfiguration("hard_task"),
                        "soft_task": LaunchConfiguration("soft_task"),
                        "beta": ParameterValue(
                            LaunchConfiguration("beta"),
                            value_type=float,
                        ),
                        "gamma": ParameterValue(
                            LaunchConfiguration("gamma"),
                            value_type=float,
                        ),
                        "initial_ts_state_from_agent": ParameterValue(
                            LaunchConfiguration(
                                "initial_ts_state_from_agent"
                            ),
                            value_type=bool,
                        ),
                        "replan_on_unplanned_move": ParameterValue(
                            LaunchConfiguration(
                                "replan_on_unplanned_move"
                            ),
                            value_type=bool,
                        ),
                        "check_timestamp": ParameterValue(
                            LaunchConfiguration("check_timestamp"),
                            value_type=bool,
                        ),
                        "plugin_config_path": ParameterValue(
                            LaunchConfiguration("plugin_config_path"),
                            value_type=str,
                        ),
                    }
                ],
            ),
        ]
    )
