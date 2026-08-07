import math

from geometry_msgs.msg import Twist
from ltl_automaton_msgs.msg import TransitionSystemState
import pytest

from ltl_automaton_hil_mic.policies import (
    BoolCommandPolicy,
    VelocityCommandPolicy,
    validate_ts_state,
)


def _twist(linear_x=0.0, angular_z=0.0):
    command = Twist()
    command.linear.x = linear_x
    command.angular.z = angular_z
    return command


def _bool_ts():
    return {
        "state_models": {
            "load": {
                "nodes": {
                    "empty": {"connected_to": {"loaded": "pick"}},
                    "loaded": {"connected_to": {"empty": "drop"}},
                }
            }
        }
    }


def test_bool_policy_resolves_action_without_mutating_source():
    policy = BoolCommandPolicy(_bool_ts(), "load", "pick")
    source = TransitionSystemState(
        states=["r1", "empty"],
        state_dimension_names=["2d_pose_region", "load"],
    )

    result = policy.potential_state(source)

    assert result.states == ["r1", "loaded"]
    assert source.states == ["r1", "empty"]


def test_bool_policy_rejects_missing_action():
    policy = BoolCommandPolicy(_bool_ts(), "load", "pick")
    source = TransitionSystemState(
        states=["loaded"], state_dimension_names=["load"]
    )

    with pytest.raises(ValueError, match="unavailable"):
        policy.potential_state(source)


def test_state_validation_rejects_malformed_or_missing_dimension():
    with pytest.raises(ValueError, match="count"):
        validate_ts_state(
            TransitionSystemState(
                states=["r1"], state_dimension_names=["region", "load"]
            ),
            "load",
        )
    with pytest.raises(ValueError, match="does not contain"):
        validate_ts_state(
            TransitionSystemState(
                states=["r1"], state_dimension_names=["region"]
            ),
            "load",
        )


def test_velocity_policy_bounds_and_deadband():
    policy = VelocityCommandPolicy(deadband=0.2)
    navigation = _twist(0.1)

    assert policy.mix(_twist(0.1), navigation).linear.x == pytest.approx(0.1)
    assert policy.mix(_twist(2.0), navigation).linear.x == pytest.approx(0.5)


def test_velocity_policy_safety_zones_and_smooth_buffer():
    policy = VelocityCommandPolicy(
        safety_distance=1.0,
        epsilon=1.0,
        deadband=0.05,
    )
    human = _twist(0.4)
    navigation = _twist(0.1)

    assert policy.mix(human, navigation, 0.5).linear.x == pytest.approx(0.1)
    assert policy.mix(human, navigation, 2.5).linear.x == pytest.approx(0.4)
    assert policy.human_gain(1.5) == pytest.approx(0.5)
    assert policy.mix(human, navigation, 1.5).linear.x == pytest.approx(0.25)
    assert policy.magnitude(_twist(0.0, 0.3)) == pytest.approx(0.3)
    assert math.isfinite(policy.human_gain(1.5))


@pytest.mark.parametrize(
    "arguments, error",
    [
        ({"safety_distance": -1.0}, "safety"),
        ({"epsilon": 0.0}, "epsilon"),
        ({"deadband": -0.1}, "deadband"),
    ],
)
def test_velocity_policy_rejects_invalid_parameters(arguments, error):
    with pytest.raises(ValueError, match=error):
        VelocityCommandPolicy(**arguments)
