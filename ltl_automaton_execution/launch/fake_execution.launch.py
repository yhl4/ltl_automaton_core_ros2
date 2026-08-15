"""Launch the simulator-agnostic fake execution manager."""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package="ltl_automaton_execution",
            executable="execution_node",
            name="ltl_execution_manager",
            output="screen",
        ),
    ])
