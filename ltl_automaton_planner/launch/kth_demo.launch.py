"""Launch the KTH ROS2 closed-loop LTL planner demonstration."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import (
    LaunchConfiguration,
    PathJoinSubstitution,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    """Create the KTH planner and optional demo-driver launch description."""
    default_ts_path = PathJoinSubstitution(
        [
            FindPackageShare("ltl_automaton_planner"),
            "config",
            "kth_example_ts.yaml",
        ]
    )

    planner = Node(
        package="ltl_automaton_planner",
        executable="planner_node",
        name="ltl_planner",
        output="screen",
        parameters=[
            {
                "transition_system_path": ParameterValue(
                    LaunchConfiguration("transition_system_path"),
                    value_type=str,
                ),
                "hard_task": ParameterValue(
                    LaunchConfiguration("hard_task"),
                    value_type=str,
                ),
                "soft_task": ParameterValue(
                    LaunchConfiguration("soft_task"),
                    value_type=str,
                ),
                "beta": ParameterValue(
                    LaunchConfiguration("beta"),
                    value_type=float,
                ),
                "gamma": ParameterValue(
                    LaunchConfiguration("gamma"),
                    value_type=float,
                ),
            }
        ],
    )

    driver = Node(
        package="ltl_automaton_planner",
        executable="kth_demo_driver",
        name="kth_demo_driver",
        output="screen",
        condition=IfCondition(
            LaunchConfiguration("start_driver")
        ),
        parameters=[
            {
                "scenario": ParameterValue(
                    LaunchConfiguration("scenario"),
                    value_type=str,
                ),
                "step_delay": ParameterValue(
                    LaunchConfiguration("step_delay"),
                    value_type=float,
                ),
                "max_steps": ParameterValue(
                    LaunchConfiguration("max_steps"),
                    value_type=int,
                ),
            }
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "transition_system_path",
                default_value=default_ts_path,
            ),
            DeclareLaunchArgument(
                "hard_task",
                default_value=(
                    "([]<> (r1 && loaded)) && "
                    "([]<> (r1 && unloaded))"
                ),
            ),
            DeclareLaunchArgument(
                "soft_task",
                default_value="[]!r3",
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
                "scenario",
                default_value="normal",
            ),
            DeclareLaunchArgument(
                "start_driver",
                default_value="false",
            ),
            DeclareLaunchArgument(
                "step_delay",
                default_value="1.0",
            ),
            DeclareLaunchArgument(
                "max_steps",
                default_value="8",
            ),
            planner,
            driver,
        ]
    )
