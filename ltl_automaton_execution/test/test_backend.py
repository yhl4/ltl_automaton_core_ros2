"""Pure backend and injected-manager seam regressions."""

from ltl_automaton_execution.accepted_run_resolver import AcceptedRunResolver
from ltl_automaton_execution.execution_manager import ExecutionManager
from ltl_automaton_execution.fake_backend import FakeBackend
from ltl_automaton_execution.models import AcceptedRun
from ltl_automaton_execution.models import ExecutionObservation
from ltl_automaton_execution.models import ExecutionResult
from ltl_automaton_execution.models import ExecutionStep
from ltl_automaton_execution.models import PlanningSnapshot
from ltl_automaton_execution.models import ProductEdge
from ltl_automaton_execution.models import ProductNode
from ltl_automaton_execution.models import SymbolicState


def _state(value):
    return SymbolicState(("region",), (value,))


def _step():
    return ExecutionStep(
        "planner-a",
        1,
        "move",
        _state("r1"),
        _state("r2"),
        (1,),
        (2,),
    )


def _observation(generation=1):
    return ExecutionObservation(
        "planner-a", generation, (1,), True, "move"
    )


def _snapshot(generation=1):
    return PlanningSnapshot(
        "planner-a",
        generation,
        (ProductNode(1, _state("r1")), ProductNode(2, _state("r2"))),
        (ProductEdge(1, 2, "move"), ProductEdge(2, 2, "wait")),
        AcceptedRun((1, 2), (2,)),
    )


class ManualScheduler:
    def __init__(self):
        self.calls = []

    def __call__(self, delay, callback):
        self.calls.append((delay, callback))
        return True


class RecordingBackend:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    def execute(self, step, completion):
        self.calls.append((step, completion))
        return self.accepted


def test_e9_fake_backend_completes_target_after_injected_delay():
    scheduler = ManualScheduler()
    results = []
    backend = FakeBackend(scheduler, execution_delay_sec=0.25)

    assert backend.execute(_step(), results.append)
    assert results == []
    assert scheduler.calls[0][0] == 0.25
    scheduler.calls[0][1]()
    assert results == [ExecutionResult(
        True, _state("r2"), "Fake execution completed action move."
    )]


def test_e10_backend_failure_produces_no_successful_observation():
    backend = RecordingBackend()
    observed = []
    diagnostics = []
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, observed.append, diagnostics.append
    )
    observation = _observation()
    assert manager.observe_authority(observation)
    assert manager.dispatch(observation, _snapshot())
    backend.calls[0][1](ExecutionResult(False, None, "controller failed"))
    assert observed == []
    assert diagnostics == ["controller failed"]


def test_e11_recording_backend_proves_interface_seam_and_deduplication():
    backend = RecordingBackend()
    observed = []
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, observed.append, lambda _message: None
    )
    observation = _observation()
    assert manager.observe_authority(observation)
    assert manager.dispatch(observation, _snapshot())
    assert not manager.dispatch(observation, _snapshot())
    assert len(backend.calls) == 1
    assert backend.calls[0][0].action == "move"
    backend.calls[0][1](ExecutionResult(True, _state("r2"), "done"))
    assert observed == [_state("r2")]


def test_in_flight_completion_survives_new_generation_authority():
    backend = RecordingBackend()
    observed = []
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, observed.append, lambda _message: None
    )
    first = _observation(1)
    second = _observation(2)
    assert manager.observe_authority(first)
    assert manager.dispatch(first, _snapshot(1))
    assert manager.observe_authority(second)
    assert not manager.dispatch(second, _snapshot(2))
    backend.calls[0][1](ExecutionResult(True, _state("r2"), "done"))
    assert observed == [_state("r2")]
    assert not manager.is_current(first)
    assert manager.is_current(second)
