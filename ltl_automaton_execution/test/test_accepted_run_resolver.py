"""Pure accepted-run resolution regressions."""

import pytest

from ltl_automaton_execution.accepted_run_resolver import AcceptedRunResolver
from ltl_automaton_execution.accepted_run_resolver import ResolutionError
from ltl_automaton_execution.models import AcceptedRun
from ltl_automaton_execution.models import ExecutionObservation
from ltl_automaton_execution.models import PlanningSnapshot
from ltl_automaton_execution.models import ProductEdge
from ltl_automaton_execution.models import ProductNode
from ltl_automaton_execution.models import SymbolicState


def _state(value):
    return SymbolicState(("region",), (value,))


def _snapshot():
    return PlanningSnapshot(
        "planner-a",
        4,
        (
            ProductNode(1, _state("r1")),
            ProductNode(2, _state("r1")),
            ProductNode(3, _state("r2")),
            ProductNode(4, _state("r3")),
            ProductNode(5, _state("r4")),
        ),
        (
            ProductEdge(1, 3, "prefix"),
            ProductEdge(2, 3, "prefix"),
            ProductEdge(3, 4, "suffix"),
            ProductEdge(4, 5, "suffix-next"),
            ProductEdge(5, 3, "suffix-close"),
        ),
        AcceptedRun((1, 3), (3, 4, 5)),
    )


def _observation(node_ids=(1,), action="prefix", instance="planner-a", generation=4):
    return ExecutionObservation(
        instance,
        generation,
        tuple(node_ids),
        True,
        action,
    )


@pytest.mark.parametrize(
    "observation",
    [
        _observation(instance="planner-b"),
        _observation(generation=5),
    ],
)
def test_e1_snapshot_identity_must_match(observation):
    with pytest.raises(ResolutionError, match="identity"):
        AcceptedRunResolver().resolve(observation, _snapshot())


def test_e1_matching_identity_is_accepted():
    step = AcceptedRunResolver().resolve(_observation(), _snapshot())
    assert step.planner_instance_id == "planner-a"
    assert step.planning_generation == 4


def test_e2_multiple_product_nodes_must_reduce_to_one_ts_state():
    snapshot = _snapshot()
    step = AcceptedRunResolver().resolve(
        _observation((1, 2)),
        snapshot,
    )
    assert step.source_state == _state("r1")

    with pytest.raises(ResolutionError, match="distinct symbolic"):
        AcceptedRunResolver().resolve(
            _observation((1, 3)),
            snapshot,
        )


def test_e3_prefix_step_is_exact():
    step = AcceptedRunResolver().resolve(_observation(), _snapshot())
    assert step.action == "prefix"
    assert step.source_state == _state("r1")
    assert step.target_state == _state("r2")


def test_e4_prefix_and_suffix_share_the_actual_boundary_node():
    snapshot = _snapshot()
    assert snapshot.accepted_run.prefix_node_ids[-1] == (
        snapshot.accepted_run.suffix_node_ids[0]
    )
    step = AcceptedRunResolver().resolve(
        _observation((3,), "suffix"),
        snapshot,
    )
    assert step.source_state == _state("r2")
    assert step.target_state == _state("r3")


def test_e5_ordinary_suffix_step_is_exact():
    step = AcceptedRunResolver().resolve(
        _observation((4,), "suffix-next"),
        _snapshot(),
    )
    assert step.target_state == _state("r4")


def test_e6_suffix_closing_edge_is_resolved():
    step = AcceptedRunResolver().resolve(
        _observation((5,), "suffix-close"),
        _snapshot(),
    )
    assert step.target_state == _state("r2")


def test_e7_missing_action_fails_closed():
    with pytest.raises(ResolutionError, match="not represented"):
        AcceptedRunResolver().resolve(
            _observation(action="unknown"),
            _snapshot(),
        )


def test_e8_distinct_retained_targets_are_ambiguous():
    snapshot = _snapshot()
    ambiguous = PlanningSnapshot(
        snapshot.planner_instance_id,
        snapshot.planning_generation,
        snapshot.product_nodes,
        snapshot.product_edges + (
            ProductEdge(3, 2, "bridge"),
            ProductEdge(2, 4, "prefix"),
        ),
        AcceptedRun((1, 3, 2, 4, 5, 3), (3, 4, 5)),
    )
    with pytest.raises(ResolutionError, match="ambiguous"):
        AcceptedRunResolver().resolve(
            _observation((1, 2)),
            ambiguous,
        )
