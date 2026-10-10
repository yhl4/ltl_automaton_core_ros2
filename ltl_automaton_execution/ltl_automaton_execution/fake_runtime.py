"""In-memory plant, execution, observation, and abstraction runtime."""

from dataclasses import dataclass
import math

from ltl_automaton_execution.models import ExecutionCompletion
from ltl_automaton_execution.models import SymbolicState


@dataclass(frozen=True)
class FakePlantObservation:
    """One raw observation emitted by the fake plant."""

    state: SymbolicState


class FakePlant:
    """Own current fake state and notify observers of each reported update."""

    def __init__(self, initial_state=None):
        self._current_state = initial_state
        self._listeners = []

    @property
    def current_state(self):
        """Return the latest fake symbolic state, if one has been set."""
        return self._current_state

    def add_listener(self, listener):
        """Register one state-observation callback."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener):
        """Remove a previously registered callback."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def set_state(self, state):
        """Set current fake truth and emit exactly one event per listener."""
        if not isinstance(state, SymbolicState):
            raise TypeError("FakePlant state must be a SymbolicState.")
        self._current_state = state
        observation = FakePlantObservation(state)
        for listener in tuple(self._listeners):
            listener(observation)


class FakeBackend:
    """Complete one accepted symbolic step after a configured delay."""

    def __init__(self, plant, scheduler, execution_delay_sec=0.5):
        error_message = "execution_delay_sec must be finite and non-negative."
        try:
            if isinstance(execution_delay_sec, (bool, str, bytes)):
                raise TypeError("Execution delay must be numeric.")
            delay = float(execution_delay_sec)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(error_message) from error
        if not math.isfinite(delay) or delay < 0.0:
            raise ValueError(error_message)
        self._plant = plant
        self._scheduler = scheduler
        self._delay = delay

    def execute(self, step, completion):
        """Schedule a plant update and report its completion without blocking."""
        def finish():
            try:
                self._plant.set_state(step.target_state)
            except Exception as error:
                completion(ExecutionCompletion(
                    False,
                    f"Fake execution state update failed: {error}",
                ))
                raise
            completion(ExecutionCompletion(
                True,
                f"Fake execution completed action {step.action}.",
            ))

        return bool(self._scheduler(self._delay, finish))


class FakeStateObserver:
    """Forward FakePlant events through the generic observer contract."""

    def __init__(self, plant):
        self._plant = plant
        self._callback = None

    def start(self, on_observation):
        """Subscribe to future fake-plant updates."""
        if self._callback is not None:
            raise RuntimeError("FakeStateObserver is already running.")
        self._callback = on_observation
        self._plant.add_listener(on_observation)

    def stop(self):
        """Stop forwarding fake-plant updates."""
        if self._callback is None:
            return
        self._plant.remove_listener(self._callback)
        self._callback = None


class FakeStateAbstraction:
    """Return structurally valid symbolic state from a fake observation."""

    def abstract(self, observation):
        """Return exact fake state or None for unsupported/malformed input."""
        if not isinstance(observation, FakePlantObservation):
            return None
        if not isinstance(observation.state, SymbolicState):
            return None
        return observation.state
