"""Deterministic fake-plant backend with an injectable scheduler."""

from ltl_automaton_execution.models import ExecutionCompletion


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
