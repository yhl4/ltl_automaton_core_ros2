"""ROS-independent policies used by the mixed-initiative nodes."""

import math

from geometry_msgs.msg import Twist
from ltl_automaton_msgs.msg import TransitionSystemState


def clone_ts_state(state):
    """Copy a TransitionSystemState without sharing mutable arrays."""
    return TransitionSystemState(
        states=list(state.states),
        state_dimension_names=list(state.state_dimension_names),
    )


def validate_ts_state(state, required_dimension):
    """Validate state shape and the presence of a required dimension."""
    if len(state.states) != len(state.state_dimension_names):
        raise ValueError(
            "TS state count does not match its state-dimension count."
        )
    if required_dimension not in state.state_dimension_names:
        raise ValueError(
            f"TS state does not contain dimension {required_dimension!r}."
        )
    try:
        unique_dimensions = len(set(state.state_dimension_names)) == len(
            state.state_dimension_names
        )
    except TypeError:
        seen_dimensions = []
        unique_dimensions = True
        for dimension in state.state_dimension_names:
            if any(dimension == seen for seen in seen_dimensions):
                unique_dimensions = False
                break
            seen_dimensions.append(dimension)
    if not unique_dimensions:
        raise ValueError("TS state dimension names must be unique.")


class BoolCommandPolicy:
    """Resolve the state reached by a configured Boolean action."""

    def __init__(self, transition_system, state_dimension_name, monitored_action):
        try:
            nodes = transition_system["state_models"][state_dimension_name][
                "nodes"
            ]
        except KeyError as error:
            raise ValueError(
                f"Transition system has no dimension {state_dimension_name!r}."
            ) from error
        self.state_dimension_name = state_dimension_name
        self.monitored_action = monitored_action
        self.action_to_state = {
            source: {
                action: target
                for target, action in node["connected_to"].items()
            }
            for source, node in nodes.items()
        }

    def potential_state(self, current_state):
        """Return a copied TS state after the monitored action."""
        validate_ts_state(current_state, self.state_dimension_name)
        dimension_index = current_state.state_dimension_names.index(
            self.state_dimension_name
        )
        source = current_state.states[dimension_index]
        try:
            target = self.action_to_state[source][self.monitored_action]
        except KeyError as error:
            raise ValueError(
                f"Action {self.monitored_action!r} is unavailable from "
                f"state {source!r}."
            ) from error
        result = clone_ts_state(current_state)
        result.states[dimension_index] = target
        return result


class VelocityCommandPolicy:
    """Bound and blend human and navigation velocity commands."""

    def __init__(
        self,
        *,
        safety_distance=1.2,
        epsilon=1.5,
        deadband=0.2,
        max_linear=(0.5, 0.5, 0.5),
        max_angular=(2.0, 2.0, 2.0),
    ):
        for name, value in (
            ("safety distance", safety_distance),
            ("epsilon", epsilon),
            ("deadband", deadband),
        ):
            try:
                finite = math.isfinite(value)
            except (TypeError, OverflowError) as error:
                raise ValueError(f"{name} must be finite.") from error
            if not finite:
                raise ValueError(f"{name} must be finite.")
        if safety_distance < 0.0:
            raise ValueError("safety distance must be non-negative.")
        if epsilon <= 0.0:
            raise ValueError("epsilon must be positive.")
        if deadband < 0.0:
            raise ValueError("deadband must be non-negative.")
        limits = []
        for name, values in (
            ("max_linear", max_linear),
            ("max_angular", max_angular),
        ):
            try:
                values = tuple(values)
            except TypeError as error:
                raise ValueError(f"{name} must contain exactly three values.") from error
            if len(values) != 3:
                raise ValueError(f"{name} must contain exactly three values.")
            for value in values:
                try:
                    finite = math.isfinite(value)
                except (TypeError, OverflowError) as error:
                    raise ValueError(f"{name} values must be finite.") from error
                if not finite or value < 0.0:
                    raise ValueError(
                        f"{name} values must be finite and non-negative."
                    )
            limits.append(values)
        self.safety_distance = safety_distance
        self.epsilon = epsilon
        self.deadband = deadband
        self.max_linear, self.max_angular = limits

    @staticmethod
    def _clone(command):
        result = Twist()
        result.linear.x = command.linear.x
        result.linear.y = command.linear.y
        result.linear.z = command.linear.z
        result.angular.x = command.angular.x
        result.angular.y = command.angular.y
        result.angular.z = command.angular.z
        return result

    @staticmethod
    def validate_command(command):
        """Validate all six finite components of a Twist command."""
        try:
            values = (
                command.linear.x,
                command.linear.y,
                command.linear.z,
                command.angular.x,
                command.angular.y,
                command.angular.z,
            )
        except AttributeError as error:
            raise ValueError("Command must provide six Twist components.") from error
        try:
            finite = all(math.isfinite(value) for value in values)
        except (TypeError, OverflowError) as error:
            raise ValueError("Twist components must be finite numbers.") from error
        if not finite:
            raise ValueError("Twist components must be finite numbers.")

    @staticmethod
    def _bound(value, maximum):
        return max(-maximum, min(maximum, value))

    def bound(self, command):
        """Return a saturated copy of a velocity command."""
        self.validate_command(command)
        result = self._clone(command)
        for name, maximum in zip(("x", "y", "z"), self.max_linear):
            setattr(
                result.linear,
                name,
                self._bound(getattr(result.linear, name), maximum),
            )
        for name, maximum in zip(("x", "y", "z"), self.max_angular):
            setattr(
                result.angular,
                name,
                self._bound(getattr(result.angular, name), maximum),
            )
        self.validate_command(result)
        return result

    @staticmethod
    def magnitude(command):
        """Return the larger linear or angular Euclidean magnitude."""
        VelocityCommandPolicy.validate_command(command)
        linear = math.hypot(
            command.linear.x, command.linear.y, command.linear.z
        )
        angular = math.hypot(
            command.angular.x, command.angular.y, command.angular.z
        )
        return max(linear, angular)

    def human_gain(self, distance_to_trap):
        """Return the smooth human-command gain in the safety buffer."""
        try:
            finite = math.isfinite(distance_to_trap)
        except (TypeError, OverflowError) as error:
            raise ValueError("Distance to trap must be finite.") from error
        if not finite:
            raise ValueError("Distance to trap must be finite.")
        if distance_to_trap <= self.safety_distance:
            return 0.0
        offset = distance_to_trap - self.safety_distance
        if offset >= self.epsilon:
            return 1.0
        remaining = self.epsilon - offset
        exp_mag = (
            abs(remaining - offset)
            / max(offset, remaining)
            / min(offset, remaining)
        )
        tail = math.exp(-exp_mag)
        if offset < remaining:
            return tail / (1.0 + tail)
        return 1.0 / (1.0 + tail)

    def mix(self, human, navigation, distance_to_trap=None):
        """Choose or blend commands for the current trap distance."""
        human_magnitude = self.magnitude(human)
        self.validate_command(navigation)
        if distance_to_trap is not None:
            try:
                finite = math.isfinite(distance_to_trap)
            except (TypeError, OverflowError) as error:
                raise ValueError("Distance to trap must be finite.") from error
            if not finite:
                raise ValueError("Distance to trap must be finite.")
        if human_magnitude < self.deadband:
            result = self._clone(navigation)
            self.validate_command(result)
            return result
        bounded_human = self.bound(human)
        if distance_to_trap is None:
            self.validate_command(bounded_human)
            return bounded_human
        gain = self.human_gain(distance_to_trap)
        result = Twist()
        for vector_name in ("linear", "angular"):
            human_vector = getattr(bounded_human, vector_name)
            navigation_vector = getattr(navigation, vector_name)
            result_vector = getattr(result, vector_name)
            for axis in ("x", "y", "z"):
                setattr(
                    result_vector,
                    axis,
                    (1.0 - gain) * getattr(navigation_vector, axis)
                    + gain * getattr(human_vector, axis),
                )
        self.validate_command(result)
        return result
