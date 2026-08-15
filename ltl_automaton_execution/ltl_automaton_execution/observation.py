"""ROS-independent observation and state-abstraction interfaces."""

from typing import Callable
from typing import Generic
from typing import Protocol
from typing import TypeVar

from ltl_automaton_execution.models import SymbolicState


ObservationT = TypeVar("ObservationT")
ObservationCallback = Callable[[ObservationT], None]


class StateObserver(Protocol, Generic[ObservationT]):
    """Emit simulator or robot observations independently of execution."""

    def start(self, on_observation: ObservationCallback[ObservationT]) -> None:
        """Start event-driven observation delivery."""

    def stop(self) -> None:
        """Stop observation delivery."""


class StateAbstraction(Protocol, Generic[ObservationT]):
    """Convert one raw observation to symbolic state, or reject it."""

    def abstract(self, observation: ObservationT) -> SymbolicState | None:
        """Return a safe symbolic state or None when abstraction fails."""
