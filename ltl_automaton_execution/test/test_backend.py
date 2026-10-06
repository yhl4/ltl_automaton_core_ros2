"""Pure execution, plant, observation, and abstraction regressions."""

from dataclasses import fields

import pytest

from ltl_automaton_execution.accepted_run_resolver import AcceptedRunResolver
from ltl_automaton_execution.execution import ExecutionManager
from ltl_automaton_execution.fake_runtime import FakeBackend
from ltl_automaton_execution.fake_runtime import FakePlant
from ltl_automaton_execution.fake_runtime import FakePlantObservation
from ltl_automaton_execution.fake_runtime import FakeStateAbstraction
from ltl_automaton_execution.fake_runtime import FakeStateObserver
from ltl_automaton_execution.models import AcceptedRun
from ltl_automaton_execution.models import ExecutionCompletion
from ltl_automaton_execution.models import ExecutionObservation
from ltl_automaton_execution.models import ExecutionStep
from ltl_automaton_execution.models import PlanningSnapshot
from ltl_automaton_execution.models import ProductEdge
from ltl_automaton_execution.models import ProductNode
from ltl_automaton_execution.models import SymbolicState


def _state(value):
    return SymbolicState(("region",), (value,))


def _step():
    return ExecutionStep(
        "planner-a", 1, 0, "move", _state("r1"), _state("r2"), (1,), (2,)
    )


def _observation(generation=1, sequence=0, instance="planner-a"):
    return ExecutionObservation(
        instance, generation, sequence, (1,), True, "move"
    )


def _snapshot(generation=1, instance="planner-a"):
    return PlanningSnapshot(
        instance,
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


def test_a1_backend_completion_has_no_symbolic_state_authority():
    assert [field.name for field in fields(ExecutionCompletion)] == [
        "success", "message"
    ]


@pytest.mark.parametrize("delay", [0.0, 0.25, 1e10])
def test_a2_fake_execution_updates_plant_only_after_delay(delay):
    plant = FakePlant(_state("r1"))
    scheduler = ManualScheduler()
    completions = []
    backend = FakeBackend(plant, scheduler, execution_delay_sec=delay)

    assert backend.execute(_step(), completions.append)
    assert plant.current_state == _state("r1")
    assert completions == []
    assert scheduler.calls[0][0] == delay
    scheduler.calls[0][1]()
    assert plant.current_state == _state("r2")
    assert completions == [ExecutionCompletion(
        True, "Fake execution completed action move."
    )]


@pytest.mark.parametrize(
    "delay", [-1.0, float("nan"), float("inf"), -float("inf"), True, "0.5", None],
)
def test_fake_backend_rejects_invalid_delay_before_scheduling(delay):
    """Reject malformed delays without executing or observing a state change."""
    plant = FakePlant(_state("r1"))
    scheduler = ManualScheduler()
    with pytest.raises(ValueError, match="execution_delay_sec"):
        FakeBackend(plant, scheduler, execution_delay_sec=delay)
    assert plant.current_state == _state("r1")
    assert scheduler.calls == []


def test_fake_observer_failure_reports_completion_without_rolling_back_truth():
    """Preserve an observer error and the actual plant update, but report failure."""
    plant = FakePlant(_state("r1"))
    scheduler = ManualScheduler()
    completions = []
    observed = []

    def fail(observation):
        observed.append(observation)
        raise RuntimeError("Injected observation delivery failure.")

    plant.add_listener(fail)
    assert FakeBackend(plant, scheduler).execute(_step(), completions.append)
    with pytest.raises(RuntimeError, match="Injected observation delivery failure"):
        scheduler.calls[0][1]()
    assert plant.current_state == _state("r2")
    assert observed == [FakePlantObservation(_state("r2"))]
    assert len(completions) == 1
    assert not completions[0].success
    assert "Injected observation delivery failure" in completions[0].message


def test_fake_observer_failure_releases_manager_for_new_authority_step():
    """An asynchronous observation error must not leave dispatch permanently busy."""
    plant = FakePlant(_state("r1"))
    scheduler = ManualScheduler()
    diagnostics = []

    def fail(_observation):
        raise RuntimeError("Injected observation delivery failure.")

    plant.add_listener(fail)
    manager = ExecutionManager(
        AcceptedRunResolver(), FakeBackend(plant, scheduler), diagnostics.append,
    )
    first = _observation()
    assert manager.observe_authority(first)
    assert manager.dispatch(first, _snapshot())
    with pytest.raises(RuntimeError, match="Injected observation delivery failure"):
        scheduler.calls[0][1]()
    assert not manager.in_flight
    assert "Injected observation delivery failure" in diagnostics[-1]
    assert plant.current_state == _state("r2")
    assert not manager.dispatch(first, _snapshot())
    assert len(scheduler.calls) == 1
    plant.remove_listener(fail)
    latest = ExecutionObservation("planner-a", 1, 1, (2,), True, "wait")
    assert manager.observe_authority(latest)
    assert manager.dispatch(latest, _snapshot())
    scheduler.calls[1][1]()
    assert not manager.in_flight
    assert plant.current_state == _state("r2")


def test_a3_fake_state_observer_emits_exactly_once_per_plant_update():
    plant = FakePlant()
    observations = []
    observer = FakeStateObserver(plant)
    observer.start(observations.append)
    plant.set_state(_state("r2"))
    observer.stop()
    plant.set_state(_state("r1"))
    assert observations == [FakePlantObservation(_state("r2"))]


def test_a4_fake_abstraction_preserves_exact_ordered_state():
    state = SymbolicState(("region", "load"), ("r2", "holding"))
    assert FakeStateAbstraction().abstract(
        FakePlantObservation(state)
    ) == state


def test_a5_failed_backend_does_not_change_or_observe_plant():
    plant = FakePlant(_state("r1"))
    observed = []
    observer = FakeStateObserver(plant)
    observer.start(observed.append)
    backend = RecordingBackend()
    diagnostics = []
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, diagnostics.append
    )
    observation = _observation()
    assert manager.observe_authority(observation)
    assert manager.dispatch(observation, _snapshot())
    backend.calls[0][1](ExecutionCompletion(False, "controller failed"))
    assert plant.current_state == _state("r1")
    assert observed == []
    assert diagnostics == ["controller failed"]
    assert not manager.dispatch(observation, _snapshot())


def test_a6_observer_and_abstraction_work_without_execution():
    plant = FakePlant()
    abstracted = []
    abstraction = FakeStateAbstraction()
    observer = FakeStateObserver(plant)
    observer.start(
        lambda observation: abstracted.append(
            abstraction.abstract(observation)
        )
    )
    plant.set_state(_state("external"))
    assert abstracted == [_state("external")]


@pytest.mark.parametrize(
    "dimensions, values",
    [
        ((), ()),
        (("region",), ()),
        (("",), ("r1",)),
        (("region",), ("",)),
        (("region", "region"), ("r1", "r2")),
    ],
)
def test_symbolic_state_rejects_malformed_dimensions(dimensions, values):
    with pytest.raises(ValueError):
        SymbolicState(dimensions, values)


def test_a7_abstraction_rejects_unsupported_or_malformed_observation():
    class MalformedState:
        dimension_names = ("region", "region")
        states = ("r1", "r2")

    abstraction = FakeStateAbstraction()
    assert abstraction.abstract(object()) is None
    assert abstraction.abstract(FakePlantObservation(MalformedState())) is None


def test_a8_in_flight_old_generation_still_updates_observed_plant():
    plant = FakePlant(_state("r1"))
    scheduler = ManualScheduler()
    backend = FakeBackend(plant, scheduler)
    observed = []
    observer = FakeStateObserver(plant)
    observer.start(observed.append)
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, lambda _message: None
    )
    first = _observation(1)
    second = _observation(2)
    assert manager.observe_authority(first)
    assert manager.dispatch(first, _snapshot(1))
    assert manager.observe_authority(second)
    assert not manager.dispatch(second, _snapshot(2))
    scheduler.calls[0][1]()
    assert plant.current_state == _state("r2")
    assert observed == [FakePlantObservation(_state("r2"))]
    assert not manager.is_current(first)
    assert manager.is_current(second)
    assert not manager.in_flight


def test_step_sequence_allows_repeated_action_after_completion():
    backend = RecordingBackend()
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, lambda _message: None
    )
    first = _observation(sequence=0)
    second = _observation(sequence=1)
    assert manager.observe_authority(first)
    assert manager.dispatch(first, _snapshot())
    backend.calls[0][1](ExecutionCompletion(True, "done"))
    assert manager.observe_authority(second)
    assert manager.dispatch(second, _snapshot())
    assert [call[0].execution_step_seq for call in backend.calls] == [0, 1]


def test_duplicate_and_reverse_step_sequences_are_rejected():
    diagnostics = []
    backend = RecordingBackend()
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, diagnostics.append
    )
    current = _observation(sequence=2)
    assert manager.observe_authority(current)
    assert manager.dispatch(current, _snapshot())
    backend.calls[0][1](ExecutionCompletion(True, "done"))
    assert manager.observe_authority(_observation(sequence=2))
    assert not manager.dispatch(_observation(sequence=2), _snapshot())
    assert not manager.observe_authority(_observation(sequence=1))
    assert len(backend.calls) == 1
    assert "stale execution step" in diagnostics[-1]


def test_epoch_change_resets_step_sequence_deduplication():
    backend = RecordingBackend()
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, lambda _message: None
    )
    first = _observation(generation=1, sequence=4)
    second = _observation(
        generation=1, sequence=0, instance="planner-b"
    )
    assert manager.observe_authority(first)
    assert manager.dispatch(first, _snapshot())
    backend.calls[0][1](ExecutionCompletion(True, "done"))
    assert manager.observe_authority(second)
    assert manager.dispatch(second, _snapshot(instance="planner-b"))
    assert len(backend.calls) == 2


def test_busy_manager_keeps_latest_sequence_and_ignores_duplicate_completion():
    backend = RecordingBackend()
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, lambda _message: None
    )
    first = _observation(sequence=0)
    latest = _observation(sequence=1)
    assert manager.observe_authority(first)
    assert manager.dispatch(first, _snapshot())
    old_completion = backend.calls[0][1]
    assert manager.observe_authority(latest)
    assert not manager.dispatch(latest, _snapshot())
    old_completion(ExecutionCompletion(True, "done"))
    assert manager.dispatch(latest, _snapshot())
    assert manager.in_flight
    old_completion(ExecutionCompletion(True, "duplicate"))
    assert manager.in_flight
    backend.calls[1][1](ExecutionCompletion(True, "done"))
    assert not manager.in_flight


def test_a9_recording_backend_seam_has_no_observation_capability():
    backend = RecordingBackend()
    manager = ExecutionManager(
        AcceptedRunResolver(), backend, lambda _message: None
    )
    observation = _observation()
    assert manager.observe_authority(observation)
    assert manager.dispatch(observation, _snapshot())
    assert not manager.dispatch(observation, _snapshot())
    assert len(backend.calls) == 1
    assert backend.calls[0][0].action == "move"
    backend.calls[0][1](ExecutionCompletion(True, "done"))
    assert not manager.in_flight


def test_backend_exception_releases_busy_state_and_reports_failure():
    """Do not leave execution permanently busy after a dispatch exception."""
    class BrokenBackend:
        def execute(self, step, completion):
            raise RuntimeError("controller disconnected")

    diagnostics = []
    manager = ExecutionManager(AcceptedRunResolver(), BrokenBackend(), diagnostics.append)
    observation = _observation()
    assert manager.observe_authority(observation)
    assert not manager.dispatch(observation, _snapshot())
    assert not manager.in_flight
    assert "controller disconnected" in diagnostics[-1]
