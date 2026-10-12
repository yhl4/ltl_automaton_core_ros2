"""Launch the experimental CMR planner and optional existing fake executor."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    namespace = LaunchConfiguration("namespace")
    return LaunchDescription([
        DeclareLaunchArgument("namespace", default_value="cmr"),
        DeclareLaunchArgument("arm", default_value="AP"),
        DeclareLaunchArgument("query_id", default_value="D2"),
        DeclareLaunchArgument("family_prior_json", default_value=""),
        DeclareLaunchArgument("initial_state_json", default_value=""),
        DeclareLaunchArgument("records_directory", default_value=""),
        DeclareLaunchArgument("with_fake_executor", default_value="false"),
        Node(
            package="ltl_automaton_cmr", executable="cmr_node",
            name="cmr_planner", namespace=namespace, output="screen",
            parameters=[{
                name: ParameterValue(LaunchConfiguration(name), value_type=str)
                for name in ("arm", "query_id", "family_prior_json",
                             "initial_state_json", "records_directory")
            }],
        ),
        Node(
            package="ltl_automaton_execution", executable="execution_node",
            name="cmr_execution_manager", namespace=namespace, output="screen",
            condition=IfCondition(LaunchConfiguration("with_fake_executor")),
        ),
    ])
