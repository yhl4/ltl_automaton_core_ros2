"""Backend seam for fake, simulated, or physical execution."""

from typing import Callable
from typing import Protocol

from ltl_automaton_execution.models import ExecutionCompletion
from ltl_automaton_execution.models import ExecutionStep


CompletionCallback = Callable[[ExecutionCompletion], None]


class ExecutionBackend(Protocol):
    """Asynchronously execute one symbolic step without ROS message objects."""

    def execute(
        self,
        step: ExecutionStep,
        completion: CompletionCallback,
    ) -> bool:
        """Accept one non-blocking dispatch and later invoke completion."""
