"""Validate the generated ROS 2 planning contract types."""

from ltl_automaton_msgs.action import PlanLTL
from ltl_automaton_msgs.msg import PlannerStatus
from ltl_automaton_msgs.srv import LoadTransitionSystem


def test_planner_status_contract():
    """Expose only the approved lifecycle constants and fields."""
    message = PlannerStatus()

    assert message.get_fields_and_field_types() == {
        "state": "uint8",
        "message": "string",
    }
    assert PlannerStatus.UNINITIALIZED == 0
    assert PlannerStatus.READY == 1
    assert PlannerStatus.PLANNING == 2
    assert PlannerStatus.ACTIVE == 3


def test_load_transition_system_contract():
    """Generate the approved transition-system loading service."""
    request = LoadTransitionSystem.Request()
    response = LoadTransitionSystem.Response()

    assert list(request.get_fields_and_field_types()) == [
        "transition_system_yaml",
    ]
    assert list(response.get_fields_and_field_types()) == [
        "success",
        "message",
        "active_ts_sha256",
    ]


def test_plan_ltl_contract():
    """Generate the approved planning action goal, result, and feedback."""
    goal = PlanLTL.Goal()
    result = PlanLTL.Result()
    feedback = PlanLTL.Feedback()

    assert list(goal.get_fields_and_field_types()) == [
        "hard_task",
        "soft_task",
        "initial_state",
        "beta",
        "gamma",
    ]
    assert list(result.get_fields_and_field_types()) == [
        "success",
        "error_code",
        "message",
        "prefix_plan",
        "suffix_plan",
        "total_cost",
        "planning_time",
    ]
    assert list(feedback.get_fields_and_field_types()) == ["message"]

    assert PlanLTL.Result.ERROR_NONE == 0
    assert PlanLTL.Result.ERROR_INVALID_GOAL == 1
    assert PlanLTL.Result.ERROR_NOT_READY == 2
    assert PlanLTL.Result.ERROR_NO_ACCEPTING_PLAN == 3
    assert PlanLTL.Result.ERROR_INTERNAL == 4
