"""ROS-independent state-abstraction contract."""

from typing import Generic
from typing import Protocol
from typing import TypeVar

from ltl_automaton_execution.models import SymbolicState


ObservationT = TypeVar("ObservationT")


class StateAbstraction(Protocol, Generic[ObservationT]):
    """Convert one raw observation to symbolic state, or reject it."""

    def abstract(self, observation: ObservationT) -> SymbolicState | None:
        """Return a safe symbolic state or None when abstraction fails."""
