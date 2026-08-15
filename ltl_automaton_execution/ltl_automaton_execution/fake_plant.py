"""In-memory plant used by simulator-independent fake execution."""

from dataclasses import dataclass

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
