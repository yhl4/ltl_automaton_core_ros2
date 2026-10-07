import math
from decimal import Decimal, localcontext
from types import SimpleNamespace

from geometry_msgs.msg import Twist
from ltl_automaton_msgs.msg import TransitionSystemState
import pytest

from ltl_automaton_hil_mic.policies import (
    BoolCommandPolicy,
    VelocityCommandPolicy,
    validate_ts_state,
)


class UnhashableString(str):
    """Represent a valid string value whose hash is intentionally disabled."""

    __hash__ = None


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
    for names, states in (
        (["load", "load"], ["empty", "loaded"]),
        (["region", "region", "load"], ["r1", "r2", "empty"]),
    ):
        with pytest.raises(
            ValueError, match="TS state dimension names must be unique"
        ):
            validate_ts_state(
                SimpleNamespace(
                    states=states,
                    state_dimension_names=names,
                ),
                "load",
            )
    valid_unhashable = UnhashableString("load")
    validate_ts_state(
        SimpleNamespace(
            states=["empty"], state_dimension_names=[valid_unhashable]
        ),
        "load",
    )
    with pytest.raises(
        ValueError, match="TS state dimension names must be unique"
    ):
        validate_ts_state(
            SimpleNamespace(
                states=["r1", "r2"],
                state_dimension_names=[
                    UnhashableString("load"),
                    UnhashableString("load"),
                ],
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


@pytest.mark.parametrize(
    "arguments",
    [
        {"safety_distance": float("nan")},
        {"epsilon": float("nan")},
        {"epsilon": float("inf")},
        {"deadband": float("nan")},
    ],
)
def test_velocity_policy_rejects_nonfinite_parameters(arguments):
    with pytest.raises(ValueError, match="finite"):
        VelocityCommandPolicy(**arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {"max_linear": (0.5, 0.5)},
        {"max_angular": (1.0, 1.0, 1.0, 1.0)},
        {"max_linear": (-0.5, 0.5, 0.5)},
        {"max_angular": (1.0, float("nan"), 1.0)},
        {"max_linear": (float("inf"), 0.5, 0.5)},
    ],
)
def test_velocity_policy_requires_three_finite_nonnegative_axis_limits(arguments):
    with pytest.raises(ValueError):
        VelocityCommandPolicy(**arguments)


def test_velocity_policy_allows_zero_axis_limits():
    policy = VelocityCommandPolicy(max_linear=(0.0, 0.0, 0.0))
    assert policy.bound(_twist(2.0)).linear.x == 0.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_velocity_policy_rejects_invalid_human_instead_of_commanding_limit(value):
    policy = VelocityCommandPolicy()
    for operation in (policy.bound, policy.magnitude):
        with pytest.raises(ValueError, match="finite"):
            operation(_twist(value))
    with pytest.raises(ValueError, match="finite"):
        policy.mix(_twist(value), _twist(0.1))


def test_velocity_policy_rejects_invalid_navigation_even_at_full_human_gain():
    navigation = _twist(0.1)
    navigation.angular.y = float("nan")
    with pytest.raises(ValueError, match="finite"):
        VelocityCommandPolicy().mix(_twist(0.4), navigation, 3.0)


@pytest.mark.parametrize("distance", [float("nan"), float("inf"), -float("inf")])
def test_velocity_policy_rejects_nonfinite_distance(distance):
    policy = VelocityCommandPolicy()
    with pytest.raises(ValueError, match="finite"):
        policy.human_gain(distance)
    with pytest.raises(ValueError, match="finite"):
        policy.mix(_twist(0.4), _twist(0.1), distance)


def test_velocity_policy_magnitude_avoids_square_overflow():
    policy = VelocityCommandPolicy()
    assert policy.magnitude(_twist(1e200)) == 1e200
    assert policy.mix(_twist(1e200), _twist(0.1)).linear.x == 0.5
    command = _twist(3.0)
    command.linear.y = 4.0
    assert policy.magnitude(command) == 5.0


def test_velocity_policy_bounds_finite_components_even_when_norm_overflows():
    policy = VelocityCommandPolicy()
    command = _twist(1.5e308)
    command.linear.y = 1.5e308
    command.linear.z = 1.5e308
    assert math.isinf(policy.magnitude(command))
    result = policy.mix(command, _twist(0.1))
    assert (result.linear.x, result.linear.y, result.linear.z) == (0.5, 0.5, 0.5)


@pytest.mark.parametrize("epsilon", [1e-200, 1e-323])
def test_velocity_policy_symmetric_tiny_buffer_has_half_gain(epsilon):
    policy = VelocityCommandPolicy(safety_distance=0.0, epsilon=epsilon)
    # Halving a binary float gives an exactly symmetric representable midpoint.
    assert policy.human_gain(epsilon / 2.0) == 0.5


def test_velocity_policy_tiny_buffer_does_not_replace_curve_with_constant_gain():
    epsilon = 1e-200
    policy = VelocityCommandPolicy(safety_distance=0.0, epsilon=epsilon)
    assert policy.human_gain(epsilon / 4.0) == 0.0
    assert policy.human_gain(3.0 * epsilon / 4.0) == 1.0
    assert policy.human_gain(-epsilon) == 0.0
    assert policy.human_gain(epsilon) == 1.0


def test_velocity_policy_smooth_gain_matches_independent_decimal_formula():
    policy = VelocityCommandPolicy(safety_distance=1.0, epsilon=1.0)
    with localcontext() as context:
        context.prec = 60
        for distance in (1.125, 1.25, 1.5, 1.75, 1.875):
            offset = Decimal.from_float(distance) - Decimal(1)
            remaining = Decimal(1) - offset
            human = (-Decimal(1) / offset).exp()
            navigation = (-Decimal(1) / remaining).exp()
            expected = float(human / (human + navigation))
            assert policy.human_gain(distance) == pytest.approx(expected, rel=1e-14, abs=1e-15)
