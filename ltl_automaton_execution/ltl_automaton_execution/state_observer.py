"""ROS-independent observation source contract."""

from typing import Callable
from typing import Generic
from typing import Protocol
from typing import TypeVar


ObservationT = TypeVar("ObservationT")
ObservationCallback = Callable[[ObservationT], None]


class StateObserver(Protocol, Generic[ObservationT]):
    """Emit simulator or robot observations independently of execution."""

    def start(self, on_observation: ObservationCallback[ObservationT]) -> None:
        """Start event-driven observation delivery."""

    def stop(self) -> None:
        """Stop observation delivery."""
