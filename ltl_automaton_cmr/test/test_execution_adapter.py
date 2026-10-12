"""Check occurrence identity and reuse of the existing symbolic executor."""

from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from ltl_automaton_cmr.engine import plan, validate_concrete_lasso
from ltl_automaton_cmr.execution_adapter import (
    CapabilityError, ExecutionCursor, build_execution_snapshot,
    build_occurrence_projection, public_exact_float, to_ros_snapshot,
)
from ltl_automaton_cmr.vendor.ecc_p1 import (
    BuchiAutomaton, FormalAction, FormalFactorizedModel,
)
from ltl_automaton_cmr.vendor.ecc_p1.concretization import ConcreteLasso
from ltl_automaton_cmr.vendor.ecc_p1.model import ConcreteTransition
from ltl_automaton_execution.accepted_run_resolver import AcceptedRunResolver
from ltl_automaton_execution.execution import ExecutionManager
from ltl_automaton_execution.fake_runtime import FakeBackend, FakePlant
from ltl_automaton_execution.models import SymbolicState


def toggle_model(cost=1):
    action = FormalAction(
        "tick", frozenset({0, 1}), frozenset({0, 1}), frozenset(),
        lambda s: True, lambda s: (1 - s[0], 1 - s[1]), lambda s, t: cost,
    )
    return FormalFactorizedModel(
        (0, 1), ((0, 1), (0, 1)), frozenset({(0, 0)}), (action,),
        lambda s: frozenset(),
        BuchiAutomaton("q", frozenset({"q"}), lambda q, label: (q,)),
        task_ap=frozenset(), task_support={},
    )


def repeated_walk():
    """A valid accepting walk can repeat the same Product state internally."""
    nodes = tuple(((i,), "q") for i in range(3))
    suffix = (nodes[0], nodes[1], nodes[2], nodes[1], nodes[0])
    actions = ("go", "visit", "return", "back")
    edges = tuple(ConcreteTransition(s, a, t, Fraction(1))
                  for s, a, t in zip(suffix, actions, suffix[1:]))
    return ConcreteLasso((nodes[0],), suffix, (), edges, 0, 1, Fraction(0), Fraction(4))


def test_snapshot_retains_internal_repeated_nodes_and_every_action_occurrence():
    lasso = repeated_walk()
    projection = build_occurrence_projection(lasso, ("position",))
    snapshot = projection.snapshot
    assert projection.product_states == lasso.suffix[:-1]
    assert projection.product_states[1] == projection.product_states[3]
    assert len(snapshot.product_nodes) == 4
    assert len({node.node_id for node in snapshot.product_nodes}) == 4
    assert snapshot.accepted_run.prefix_node_ids == (0,)
    assert snapshot.accepted_run.suffix_node_ids == (0, 1, 2, 3)
    assert tuple((e.source_id, e.action, e.target_id) for e in snapshot.product_edges) == (
        (0, "go", 1), (1, "visit", 2), (2, "return", 3), (3, "back", 0),
    )
    assert projection.exact_edges == lasso.suffix_edges
    cursor = ExecutionCursor(snapshot)
    resolver = AcceptedRunResolver()
    observed = []
    for stamp in range(8):
        observation = cursor.observation()
        step = resolver.resolve(observation, snapshot)
        observed.append(step.action)
        assert cursor.accept_feedback(step.target_state, stamp)
    assert observed == ["go", "visit", "return", "back"] * 2


def test_prefix_repetitions_remain_separate_from_cyclic_suffix_entry():
    lasso = repeated_walk()
    prefix = lasso.suffix[:3] + (lasso.suffix[0],)
    prefix_edges = (
        ConcreteTransition(prefix[0], "p0", prefix[1], Fraction(1)),
        ConcreteTransition(prefix[1], "p1", prefix[2], Fraction(1)),
        ConcreteTransition(prefix[2], "p2", prefix[3], Fraction(1)),
    )
    lasso = replace(lasso, prefix=prefix, prefix_edges=prefix_edges, prefix_cost=Fraction(3))
    projection = build_occurrence_projection(lasso, ("position",))
    snapshot = projection.snapshot
    assert projection.product_states[0] == projection.product_states[3]
    assert snapshot.accepted_run.prefix_node_ids == (0, 1, 2, 3)
    assert snapshot.accepted_run.suffix_node_ids == (3, 4, 5, 6)
    assert len(snapshot.product_edges) == 7
    assert snapshot.product_edges[-1].target_id == 3


def test_parallel_action_identity_at_equal_product_states_is_preserved():
    product = ((0,), "q")
    prefix_edge = ConcreteTransition(product, "a", product, Fraction(1))
    suffix_edge = ConcreteTransition(product, "b", product, Fraction(2))
    lasso = ConcreteLasso(
        (product, product), (product, product), (prefix_edge,), (suffix_edge,),
        0, 1, Fraction(1), Fraction(2),
    )
    snapshot = build_execution_snapshot(lasso, ("position",))
    assert tuple((e.source_id, e.action, e.target_id) for e in snapshot.product_edges) == (
        (0, "a", 1), (1, "b", 1),
    )
    cursor = ExecutionCursor(snapshot)
    resolver = AcceptedRunResolver()
    first = resolver.resolve(cursor.observation(), snapshot)
    assert first.action == "a"
    assert cursor.accept_feedback(first.target_state, 1)
    second = resolver.resolve(cursor.observation(), snapshot)
    assert second.action == "b"


def test_certified_rational_multidimension_lasso_runs_existing_fake_backend():
    model = toggle_model(Fraction(1, 3))
    result = plan(model)
    validate_concrete_lasso(model, result.lasso)
    snapshot = build_execution_snapshot(result.lasso, ("x", "y"))
    cursor = ExecutionCursor(snapshot)
    resolver = AcceptedRunResolver()
    diagnostics = []
    scheduled = []

    def scheduler(delay, callback):
        scheduled.append(callback)
        return True

    plant = FakePlant(snapshot.product_nodes[0].ts_state)
    manager = ExecutionManager(
        resolver, FakeBackend(plant, scheduler, execution_delay_sec=0), diagnostics.append,
    )
    for stamp in range(4):
        observation = cursor.observation()
        assert observation.execution_step_seq == stamp
        assert manager.observe_authority(observation)
        assert manager.dispatch(observation, snapshot)
        assert not manager.dispatch(observation, snapshot)
        assert manager.in_flight
        scheduled.pop(0)()
        assert not manager.in_flight
        assert cursor.step_seq == stamp
        assert plant.current_state.states == (("1", "1") if stamp % 2 == 0 else ("0", "0"))
        assert cursor.accept_feedback(plant.current_state, stamp)
        assert not cursor.accept_feedback(plant.current_state, stamp)
    assert result.cost == Fraction(20, 3)
    assert diagnostics == []


def test_feedback_wrong_state_and_stale_stamp_do_not_advance_occurrence():
    snapshot = build_execution_snapshot(plan(toggle_model()).lasso, ("x", "y"))
    cursor = ExecutionCursor(snapshot)
    expected = AcceptedRunResolver().resolve(cursor.observation(), snapshot).target_state
    assert not cursor.accept_feedback(SymbolicState(("x", "y"), ("wrong", "wrong")), 10)
    assert not cursor.accept_feedback(expected, 9)
    assert cursor.step_seq == 0
    assert cursor.accept_feedback(expected, 11)
    assert cursor.step_seq == 1


@pytest.mark.parametrize("value", [Fraction(1, 3), 2**53 + 1, 10**400, True, 0.5])
def test_public_float64_rejects_costs_it_cannot_carry_losslessly(value):
    with pytest.raises(CapabilityError):
        public_exact_float(value)


@pytest.mark.parametrize("value", [0, 1, 2**53, Fraction(1, 2), Fraction(3, 8)])
def test_public_float64_accepts_exact_binary_rationals_only(value):
    assert Fraction.from_float(public_exact_float(value)) == value


def test_ros_export_rejects_uncertified_result_before_message_import():
    with pytest.raises(CapabilityError, match="certified"):
        to_ros_snapshot(
            SimpleNamespace(status="INFEASIBLE", lasso=None), toggle_model(), ("x", "y"),
        )


def test_ros_export_reports_rational_capability_limit_after_exact_certification():
    model = toggle_model(Fraction(1, 3))
    result = plan(model)
    assert result.status == "OPTIMALITY_CERTIFIED"
    with pytest.raises(CapabilityError, match="float64 cannot losslessly"):
        to_ros_snapshot(result, model, ("x", "y"))


def test_snapshot_rejects_invalid_closure_and_edge_identity():
    lasso = repeated_walk()
    with pytest.raises(CapabilityError, match="closed-walk"):
        build_execution_snapshot(replace(lasso, suffix=lasso.suffix[:-1]), ("position",))
    wrong = replace(lasso.suffix_edges[0], action="x", target=((2,), "q"))
    with pytest.raises(CapabilityError, match="identity"):
        build_execution_snapshot(replace(lasso, suffix_edges=(wrong,) + lasso.suffix_edges[1:]),
                                 ("position",))


def test_snapshot_rejects_dimension_or_value_encoding_loss():
    lasso = repeated_walk()
    with pytest.raises(CapabilityError, match="dimension counts"):
        build_execution_snapshot(lasso, ("x", "y"))
    with pytest.raises(CapabilityError, match="symbolic"):
        build_execution_snapshot(lasso, ("position",), (("zero",),))

@pytest.mark.parametrize("domain", [
    ("same", "same", "other"), ("zero", "", "two"), ("zero", None, "two"),
])
def test_snapshot_rejects_duplicate_or_invalid_symbolic_domain_labels(domain):
    with pytest.raises(CapabilityError, match="unique nonempty"):
        build_execution_snapshot(repeated_walk(), ("position",), (domain,))


@pytest.mark.parametrize("bad_value", [-1, True, 0.0, "0", 2])
def test_snapshot_rejects_negative_noninteger_or_outofrange_symbolic_indices(bad_value):
    node = ((bad_value,), "q")
    edge = ConcreteTransition(node, "stay", node, Fraction(1))
    lasso = ConcreteLasso(
        (node,), (node, node), (), (edge,), 0, 1, Fraction(0), Fraction(1),
    )
    with pytest.raises(CapabilityError, match="lossless symbolic index"):
        build_execution_snapshot(lasso, ("position",), (("zero", "one"),))


def test_cursor_rejects_feedback_at_or_before_the_installed_snapshot_stamp():
    snapshot = build_execution_snapshot(plan(toggle_model()).lasso, ("x", "y"))
    cursor = ExecutionCursor(snapshot, minimum_stamp=100)
    expected = AcceptedRunResolver().resolve(cursor.observation(), snapshot).target_state
    assert not cursor.accept_feedback(expected, 99)
    assert not cursor.accept_feedback(expected, 100)
    assert cursor.step_seq == 0
    assert cursor.accept_feedback(expected, 101)
    assert cursor.step_seq == 1

def test_certified_python_handoff_revalidates_exact_original_model():
    from ltl_automaton_cmr.execution_adapter import certified_execution_snapshot
    model = toggle_model(Fraction(1, 3))
    result = plan(model, arm="FULL")
    snapshot = certified_execution_snapshot(result, model, ("x", "y"))
    assert len(snapshot.product_edges) == 2
    altered = replace(model, actions=(replace(model.actions[0], cost=lambda s, t: 2),))
    with pytest.raises(Exception, match="original model"):
        certified_execution_snapshot(result, altered, ("x", "y"))


def test_certified_python_handoff_rejects_noncertified_result():
    from ltl_automaton_cmr.execution_adapter import certified_execution_snapshot
    model = toggle_model()
    result = replace(plan(model, arm="FULL"), status="FULL_PRECISION_NOT_CERTIFIED")
    with pytest.raises(CapabilityError, match="certified"):
        certified_execution_snapshot(result, model, ("x", "y"))
