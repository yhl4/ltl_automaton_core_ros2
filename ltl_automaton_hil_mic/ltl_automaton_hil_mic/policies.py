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
        if safety_distance < 0.0:
            raise ValueError("safety distance must be non-negative.")
        if epsilon <= 0.0:
            raise ValueError("epsilon must be positive.")
        if deadband < 0.0:
            raise ValueError("deadband must be non-negative.")
        self.safety_distance = safety_distance
        self.epsilon = epsilon
        self.deadband = deadband
        self.max_linear = max_linear
        self.max_angular = max_angular

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
    def _bound(value, maximum):
        return max(-maximum, min(maximum, value))

    def bound(self, command):
        """Return a saturated copy of a velocity command."""
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
        return result

    @staticmethod
    def magnitude(command):
        """Return the larger linear or angular Euclidean magnitude."""
        linear = math.sqrt(
            command.linear.x**2
            + command.linear.y**2
            + command.linear.z**2
        )
        angular = math.sqrt(
            command.angular.x**2
            + command.angular.y**2
            + command.angular.z**2
        )
        return max(linear, angular)

    @staticmethod
    def _rho(value):
        return math.exp(-1.0 / value) if value > 0.0 else 0.0

    def human_gain(self, distance_to_trap):
        """Return the smooth human-command gain in the safety buffer."""
        if distance_to_trap <= self.safety_distance:
            return 0.0
        if distance_to_trap >= self.safety_distance + self.epsilon:
            return 1.0
        from_safety = self._rho(distance_to_trap - self.safety_distance)
        from_human = self._rho(
            self.epsilon + self.safety_distance - distance_to_trap
        )
        return from_safety / (from_safety + from_human)

    def mix(self, human, navigation, distance_to_trap=None):
        """Choose or blend commands for the current trap distance."""
        if self.magnitude(human) < self.deadband:
            return self._clone(navigation)
        bounded_human = self.bound(human)
        if distance_to_trap is None:
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
        return result
