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
  "msg/PlannerStatus.msg"
  "srv/TrapCheck.srv"
  "srv/ClosestState.srv"
  "srv/TaskPlanning.srv"
  "srv/LoadTransitionSystem.srv"
  "action/PlanLTL.action"
  DEPENDENCIES
    std_msgs
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(
    test_generated_interfaces
    test/test_generated_interfaces.py
  )
endif()

ament_export_dependencies(rosidl_default_runtime)

ament_package()
