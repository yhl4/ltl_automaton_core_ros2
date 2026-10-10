"""Pure accepted-run resolution regressions."""

from dataclasses import replace

import pytest

from ltl_automaton_execution.accepted_run_resolver import AcceptedRunResolver
from ltl_automaton_execution.accepted_run_resolver import ResolutionError
from ltl_automaton_execution.models import AcceptedRun
from ltl_automaton_execution.models import ExecutionObservation
from ltl_automaton_execution.models import ExecutionStep
from ltl_automaton_execution.models import PlanningSnapshot
from ltl_automaton_execution.models import ProductEdge
from ltl_automaton_execution.models import ProductNode
from ltl_automaton_execution.models import SymbolicState


class UnhashableString(str):
    __hash__ = None


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


def _observation(
    node_ids=(1,), action="prefix", instance="planner-a", generation=4,
    sequence=0,
):
    return ExecutionObservation(
        instance,
        generation,
        sequence,
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
    assert step.execution_step_seq == 0


def test_step_sequence_is_carried_into_resolved_step():
    step = AcceptedRunResolver().resolve(
        _observation(sequence=9), _snapshot()
    )
    assert step.execution_step_seq == 9


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


@pytest.mark.parametrize("node_ids", [(1, 2, 5), (5, 2, 1, 2, 5, 1)])
@pytest.mark.parametrize("unhashable_node_id", [None, 1, 3])
def test_multiple_candidate_pairs_keep_complete_sorted_product_ids(
    node_ids, unhashable_node_id,
):
    """Keep all matched IDs while omitting current nodes with no matching edge."""
    snapshot = PlanningSnapshot(
        "planner-a", 4,
        tuple(
            ProductNode(
                node_id,
                _state(
                    UnhashableString("r1" if node_id in (1, 2, 5) else "r2")
                    if node_id == unhashable_node_id
                    else "r1" if node_id in (1, 2, 5) else "r2"
                ),
            )
            for node_id in range(1, 6)
        ),
        (
            ProductEdge(1, 3, "move"),
            ProductEdge(3, 2, "bridge"),
            ProductEdge(2, 4, "move"),
            ProductEdge(4, 1, "bridge"),
            ProductEdge(1, 4, "move"),
            ProductEdge(4, 4, "wait"),
        ),
        AcceptedRun((1, 3, 2, 4, 1, 4), (4,)),
    )
    if unhashable_node_id is not None:
        state = next(
            node.ts_state for node in snapshot.product_nodes
            if node.node_id == unhashable_node_id
        )
        assert type(state.states[0]) is UnhashableString
    resolver = AcceptedRunResolver()
    expected = ExecutionStep(
        "planner-a", 4, 9, "move", _state("r1"), _state("r2"), (1, 2), (3, 4),
    )
    assert resolver.resolve(_observation(node_ids, "move", sequence=9), snapshot) == expected
    assert resolver.resolve(_observation(tuple(reversed(node_ids)), "move", sequence=9),
                            snapshot) == expected
    assert resolver._indexed_snapshot is snapshot


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


@pytest.mark.parametrize("suffix", [(3, 3), (3, 4, 5, 3)])
def test_repeated_suffix_start_is_rejected_without_replacing_index(suffix):
    """Reject explicitly closed suffixes even when the extra self-loop exists."""
    snapshot = _snapshot()
    resolver = AcceptedRunResolver()
    resolver.resolve(_observation(), snapshot)
    malformed = replace(
        snapshot,
        planning_generation=5,
        product_edges=snapshot.product_edges + (ProductEdge(3, 3, "wait"),),
        accepted_run=AcceptedRun((1, 3), suffix),
    )

    with pytest.raises(ResolutionError) as error:
        resolver.resolve(_observation(generation=5), malformed)

    assert str(error.value) == "Accepted suffix repeats its start node at the end."
    assert resolver._indexed_snapshot is snapshot
    assert resolver.resolve(_observation(), snapshot).target_state == _state("r2")


def test_single_node_suffix_keeps_its_closing_self_loop():
    """A one-node suffix represents one implicit self-loop action."""
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        product_edges=snapshot.product_edges + (ProductEdge(3, 3, "wait"),),
        accepted_run=AcceptedRun((1, 3), (3,)),
    )
    step = AcceptedRunResolver().resolve(_observation((3,), "wait"), snapshot)
    assert step.action == "wait"
    assert step.source_state == step.target_state == _state("r2")
    assert step.source_product_node_ids == step.target_product_node_ids == (3,)


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


def test_retained_run_with_missing_target_node_fails_closed():
    snapshot = _snapshot()
    resolver = AcceptedRunResolver()
    assert resolver.resolve(_observation(), snapshot).target_state == _state("r2")
    incomplete = replace(
        snapshot,
        product_nodes=tuple(node for node in snapshot.product_nodes if node.node_id != 3),
    )
    with pytest.raises(ResolutionError, match="missing Product nodes"):
        resolver.resolve(_observation(), incomplete)
    assert resolver._indexed_snapshot is snapshot


@pytest.mark.parametrize("remove_node", [False, True])
def test_missing_closing_edge_is_reported_before_missing_nodes(remove_node):
    """Keep missing-edge diagnostics and the prior valid index on conversion failure."""
    snapshot = _snapshot()
    resolver = AcceptedRunResolver()
    resolver.resolve(_observation(), snapshot)
    incomplete = replace(
        snapshot, planning_generation=5,
        product_edges=tuple(
            edge for edge in snapshot.product_edges
            if (edge.source_id, edge.target_id) != (5, 3)
        ),
        product_nodes=tuple(
            node for node in snapshot.product_nodes
            if not remove_node or node.node_id != 3
        ),
    )
    with pytest.raises(ResolutionError) as error:
        resolver.resolve(_observation(generation=5), incomplete)
    assert str(error.value) == "Accepted run references missing Product edges: [(5, 3)]."
    assert resolver._indexed_snapshot is snapshot
    assert resolver.resolve(_observation(), snapshot).target_state == _state("r2")


def test_resolver_reuses_one_snapshot_then_switches_generation():
    resolver = AcceptedRunResolver()
    snapshot = _snapshot()
    assert resolver.resolve(_observation(), snapshot).target_state == _state("r2")
    assert resolver.resolve(
        _observation((5,), "suffix-close"), snapshot,
    ).target_state == _state("r2")
    replacement = replace(
        snapshot,
        planning_generation=5,
        product_nodes=tuple(
            replace(node, ts_state=_state("new-r2")) if node.node_id == 3 else node
            for node in snapshot.product_nodes
        ),
    )
    assert resolver.resolve(
        _observation(generation=5), replacement,
    ).target_state == _state("new-r2")
    with pytest.raises(ResolutionError, match="identity"):
        resolver.resolve(_observation(), replacement)


@pytest.mark.parametrize("accepted_run, expected", [
    (AcceptedRun((3,), (3,)), ((3, 3),)),
    (AcceptedRun((1, 3), (3, 4, 5)), ((1, 3), (3, 4), (4, 5), (5, 3))),
    (AcceptedRun((1, 3, 1, 3), (3, 4, 5, 4)),
     ((1, 3), (3, 1), (1, 3), (3, 4), (4, 5), (5, 4), (4, 3))),
])
def test_retained_pair_tuple_preserves_order_duplicates_and_closure(accepted_run, expected):
    """Keep one tuple with repeated prefix edges and exactly one implicit closure."""
    base = _snapshot()
    snapshot = replace(base, accepted_run=accepted_run, product_edges=base.product_edges + (
        ProductEdge(3, 3, "wait"), ProductEdge(3, 1, "prefix-return"),
        ProductEdge(5, 4, "suffix-return"), ProductEdge(4, 3, "close-from-four"),
    ))
    graph_pairs = {(edge.source_id, edge.target_id) for edge in snapshot.product_edges}
    assert all(pair in graph_pairs for pair in expected)
    pairs = AcceptedRunResolver._retained_pairs(snapshot)
    assert type(pairs) is tuple
    assert pairs == expected
    assert snapshot.accepted_run is accepted_run
    assert snapshot.accepted_run.prefix_node_ids == accepted_run.prefix_node_ids
    assert snapshot.accepted_run.suffix_node_ids == accepted_run.suffix_node_ids


@pytest.mark.parametrize("accepted_run, message", [
    (AcceptedRun((), ()), "Accepted run has no prefix nodes."),
    (AcceptedRun((1,), ()), "Accepted run has no suffix nodes."),
    (AcceptedRun((1,), (3,)),
     "Accepted prefix and suffix do not share their boundary node."),
])
def test_retained_pair_structure_failure_keeps_index_and_recovers(accepted_run, message):
    """Retain the valid index when pair conversion rejects the next generation."""
    resolver = AcceptedRunResolver()
    snapshot = _snapshot()
    previous_step = resolver.resolve(_observation(), snapshot)
    nodes, targets = resolver._nodes, resolver._retained_targets
    malformed = replace(snapshot, planning_generation=5, accepted_run=accepted_run)
    with pytest.raises(ResolutionError) as caught:
        resolver.resolve(_observation(generation=5), malformed)
    assert str(caught.value) == message
    assert resolver._indexed_snapshot is snapshot
    assert resolver._nodes is nodes and resolver._retained_targets is targets
    assert resolver.resolve(_observation(), snapshot) == previous_step
    replacement = replace(snapshot, planning_generation=6)
    assert resolver.resolve(_observation(generation=6), replacement) == replace(
        previous_step, planning_generation=6,
    )
    assert resolver._indexed_snapshot is replacement


def test_missing_repeated_pair_diagnostic_keeps_order_duplicates_and_index():
    """Preserve repeated missing pairs before a missing-node error and cache commit."""
    resolver = AcceptedRunResolver()
    snapshot = _snapshot()
    previous_step = resolver.resolve(_observation(), snapshot)
    malformed = replace(
        snapshot, planning_generation=5,
        accepted_run=AcceptedRun((1, 3, 1, 3), (3, 4, 5)),
        product_edges=tuple(edge for edge in snapshot.product_edges
                            if (edge.source_id, edge.target_id) != (1, 3)),
        product_nodes=tuple(node for node in snapshot.product_nodes if node.node_id != 1),
    )
    with pytest.raises(ResolutionError) as caught:
        resolver.resolve(_observation(generation=5), malformed)
    assert str(caught.value) == (
        "Accepted run references missing Product edges: [(1, 3), (3, 1), (1, 3)]."
    )
    assert resolver._indexed_snapshot is snapshot
    assert resolver.resolve(_observation(), snapshot) == previous_step
