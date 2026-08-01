cmake_minimum_required(VERSION 3.8)

project(ltl_automaton_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/TransitionSystemState.msg"
  "msg/TransitionSystemStateStamped.msg"
  "msg/LTLPlan.msg"
  "msg/LTLState.msg"
  "msg/LTLStateArray.msg"
  "msg/LTLStateRuns.msg"
  "srv/TrapCheck.srv"
  "srv/ClosestState.srv"
  "srv/TaskPlanning.srv"
  DEPENDENCIES
    std_msgs
)

ament_export_dependencies(rosidl_default_runtime)

ament_package()