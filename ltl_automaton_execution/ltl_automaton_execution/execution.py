"""ROS-independent execution interfaces and dispatch policy."""

from typing import Callable
from typing import Protocol

from ltl_automaton_execution.accepted_run_resolver import ResolutionError
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


class ExecutionManager:
    """Dispatch at most one current-authority command while preserving truth."""

    def __init__(self, resolver, backend, diagnostic):
        self._resolver = resolver
        self._backend = backend
        self._diagnostic = diagnostic
        self._active_instance = None
        self._active_generation = None
        self._retired_instances = set()
        self._latest_step_seq = None
        self._attempted_step_seq = None
        self._in_flight = False
        self._flight_token = None

    @property
    def in_flight(self):
        return self._in_flight

    def observe_authority(self, observation):
        """Accept monotonic authority and reject observations known stale."""
        instance = observation.planner_instance_id
        generation = observation.planning_generation
        if not instance:
            self._diagnostic("Observation has no planner instance identity.")
            return False
        if instance in self._retired_instances:
            self._diagnostic("Ignoring observation from a retired planner instance.")
            return False
        if self._active_instance is None:
            self._active_instance = instance
            self._active_generation = generation
            self._latest_step_seq = observation.execution_step_seq
            self._attempted_step_seq = None
            return True
        if instance != self._active_instance:
            self._retired_instances.add(self._active_instance)
            self._active_instance = instance
            self._active_generation = generation
            self._latest_step_seq = observation.execution_step_seq
            self._attempted_step_seq = None
            return True
        if generation < self._active_generation:
            self._diagnostic("Ignoring stale planning generation.")
            return False
        if generation > self._active_generation:
            self._active_generation = generation
            self._latest_step_seq = observation.execution_step_seq
            self._attempted_step_seq = None
            return True
        if observation.execution_step_seq < self._latest_step_seq:
            self._diagnostic("Ignoring stale execution step sequence.")
            return False
        if observation.execution_step_seq > self._latest_step_seq:
            self._latest_step_seq = observation.execution_step_seq
            self._attempted_step_seq = None
        return True

    def is_current(self, observation):
        """Return whether this observation still owns command-start authority."""
        return (
            observation.planner_instance_id == self._active_instance
            and observation.planning_generation == self._active_generation
        )

    def dispatch(self, observation, snapshot):
        """Resolve and dispatch once without invalidating in-flight completion."""
        if not self.is_current(observation):
            self._diagnostic("Execution authority changed before dispatch.")
            return False
        step_seq = observation.execution_step_seq
        if step_seq != self._latest_step_seq:
            self._diagnostic("Execution step sequence is stale.")
            return False
        if step_seq == self._attempted_step_seq:
            return False
        if self._in_flight:
            self._diagnostic("Execution backend is busy.")
            return False
        self._attempted_step_seq = step_seq
        try:
            step = self._resolver.resolve(observation, snapshot)
        except ResolutionError as error:
            self._diagnostic(str(error))
            return False

        self._in_flight = True
        flight_token = object()
        self._flight_token = flight_token

        def completed(result):
            if self._flight_token is not flight_token:
                return
            self._flight_token = None
            self._in_flight = False
            if not result.success:
                self._diagnostic(
                    result.message or "Execution backend reported failure."
                )

        try:
            accepted = self._backend.execute(step, completed)
        except Exception as error:
            if self._flight_token is flight_token:
                self._flight_token = None
                self._in_flight = False
            self._diagnostic(f"Execution backend dispatch failed: {error}")
            return False
        if accepted:
            return True
        if self._flight_token is flight_token:
            self._flight_token = None
            self._in_flight = False
        self._diagnostic("Execution backend rejected dispatch.")
        return False
