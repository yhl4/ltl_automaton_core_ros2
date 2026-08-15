"""In-memory plant, execution, observation, and abstraction runtime."""

from dataclasses import dataclass

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
        if execution_delay_sec < 0.0:
            raise ValueError("Execution delay must be non-negative.")
        self._plant = plant
        self._scheduler = scheduler
        self._delay = float(execution_delay_sec)

    def execute(self, step, completion):
        """Schedule success without blocking the caller."""
        def finish():
            self._plant.set_state(step.target_state)
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
