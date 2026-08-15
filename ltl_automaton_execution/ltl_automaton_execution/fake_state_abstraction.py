"""Identity-like abstraction for fake-plant observations."""

from ltl_automaton_execution.fake_plant import FakePlantObservation
from ltl_automaton_execution.models import SymbolicState


class FakeStateAbstraction:
    """Revalidate and preserve an ordered fake symbolic state."""

    def abstract(self, observation):
        """Return exact fake state or None for unsupported/malformed input."""
        if not isinstance(observation, FakePlantObservation):
            return None
        try:
            return SymbolicState(
                tuple(observation.state.dimension_names),
                tuple(observation.state.states),
            )
        except (AttributeError, TypeError, ValueError):
            return None
