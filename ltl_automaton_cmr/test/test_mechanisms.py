"""Small directed frozen CMR mechanism regressions, with no benchmark data."""

from fractions import Fraction

from ltl_automaton_cmr.vendor.ecc_p1 import (
    BuchiAutomaton, FormalAction, FormalFactorizedModel,
    build_optimistic_abstraction, deterministic_refinement,
    periodically_concretize, run_ecc, solve_exact_abstract_lasso,
)
from ltl_automaton_cmr.vendor.ecc_p1.abstraction import (
    AbstractTransition, OptimisticAbstractModel,
)
from ltl_automaton_cmr.vendor.ecc_p1.solver import AbstractLassoResult


def accepting_buchi():
    return BuchiAutomaton("q", frozenset({"q"}), lambda q, label: (q,))


def hidden_model(domain, transitions):
    """One hidden action can have a transient and an arbitrarily long period."""
    successor = dict(transitions)
    action = FormalAction(
        "tick", frozenset({0}), frozenset({0}), frozenset(),
        lambda state: state[0] in successor,
        lambda state: (successor[state[0]],), lambda source, target: 1,
    )
    return FormalFactorizedModel(
        (0,), (tuple(domain),), frozenset({(0,)}), (action,),
        lambda state: frozenset(), accepting_buchi(),
        task_ap=frozenset(), task_support={},
    )


def abstract_graph(n, edges, accepting, initial=(0,)):
    """Explicit graph fixture adapted from upstream test_scc_solver.graph."""
    nodes = tuple(((i,), f"q{i}") for i in range(n))
    return OptimisticAbstractModel(
        frozenset({0}), nodes, tuple(nodes[i] for i in initial),
        tuple(AbstractTransition(nodes[s], a, nodes[t], Fraction(c), ())
              for s, t, c, a in edges), {}, {},
        frozenset(f"q{i}" for i in accepting), tuple((i,) for i in range(n)),
    )


def test_accepting_scc_can_enter_at_nonaccepting_node():
    # Frozen SCC regression: accepting-entry partitioning incorrectly costs 21.
    abstract = abstract_graph(2, ((0, 1, 1, "go"), (1, 0, 1, "back")), (1,))
    candidate = solve_exact_abstract_lasso(abstract)
    assert candidate.prefix == (abstract.states[0],)
    assert candidate.suffix == (abstract.states[0], abstract.states[1], abstract.states[0])
    assert candidate.lower_bound == Fraction(20)
    assert candidate.prefix[-1][1] not in abstract.accepting_buchi_states
    assert candidate.suffix_edges


def test_accepting_dead_end_does_not_count_as_a_closed_walk():
    abstract = abstract_graph(2, ((0, 1, 0, "go"),), (1,))
    assert solve_exact_abstract_lasso(abstract) is None


def test_exact_fraction_objective_retains_denominator():
    # Frozen directed fixture: prefix 1/3 plus ten suffixes of 1/7.
    abstract = abstract_graph(
        2, ((0, 1, Fraction(1, 3), "go"), (1, 1, Fraction(1, 7), "loop")), (1,),
    )
    candidate = solve_exact_abstract_lasso(abstract)
    assert candidate.prefix_cost == Fraction(1, 3)
    assert candidate.suffix_cost == Fraction(1, 7)
    assert candidate.lower_bound == Fraction(37, 21)


def test_atomic_multidimension_effect_and_action_parallelism_survive_projection():
    actions = (
        FormalAction("fast", frozenset({0, 1}), frozenset({0, 1}), frozenset(),
                     lambda s: True, lambda s: (1 - s[0], 1 - s[1]), lambda s, t: 1),
        FormalAction("slow", frozenset({0, 1}), frozenset({0, 1}), frozenset(),
                     lambda s: True, lambda s: (1 - s[0], 1 - s[1]), lambda s, t: 3),
    )
    model = FormalFactorizedModel(
        (0, 1), ((0, 1), (0, 1)), frozenset({(0, 0)}), actions,
        lambda s: frozenset(), accepting_buchi(), task_ap=frozenset(),
    )
    edges = model.state_transitions_from((0, 0))
    assert {(e.action, e.target, e.cost) for e in edges} == {
        ("fast", (1, 1), Fraction(1)), ("slow", (1, 1), Fraction(3)),
    }
    projected = build_optimistic_abstraction(model, frozenset())
    assert {(e.action, e.cost) for e in projected.transitions} == {
        ("fast", Fraction(1)), ("slow", Fraction(3)),
    }
    assert all(e.source == e.target for e in projected.transitions)
    assert run_ecc(model, frozenset()).final_cost == Fraction(20)


def test_projection_bucket_is_source_action_target_with_same_witness_minimum():
    action = FormalAction(
        "tick", frozenset({1}), frozenset({1}), frozenset({1}),
        lambda s: True, lambda s: (s[0], 1 - s[1]),
        lambda s, t: Fraction(1, 7) if s[1] == 0 else Fraction(2, 3),
    )
    model = FormalFactorizedModel(
        (0, 1), ((0,), (0, 1)), frozenset({(0, 0)}), (action,),
        lambda s: frozenset(), accepting_buchi(), task_ap=frozenset(),
    )
    projected = build_optimistic_abstraction(model, frozenset({0}))
    assert len(projected.transitions) == 1
    edge = projected.transitions[0]
    assert edge.source == edge.target
    assert edge.cost == Fraction(1, 7)
    assert {w.cost for w in edge.witnesses} == {Fraction(1, 7), Fraction(2, 3)}
    assert edge.cost == min(w.cost for w in edge.witnesses)


def test_hidden_transient_and_multiple_periods_concretize_before_certification():
    # Adapted upstream SCC CMR fixture: two transient steps and a 2-cycle.
    model = hidden_model((0, 1, 2, 3), ((0, 1), (1, 2), (2, 3), (3, 2)))
    projected = build_optimistic_abstraction(model, frozenset())
    candidate = solve_exact_abstract_lasso(projected)
    lifted = periodically_concretize(model, projected, candidate)
    assert candidate.lower_bound == Fraction(10)
    assert lifted.status == "CONCRETIZABLE"
    lasso = lifted.concrete_lasso
    assert (lasso.ell, lasso.m, lasso.upper_bound) == (2, 2, Fraction(22))
    assert tuple(s[0] for s in lasso.prefix) == ((0,), (1,), (2,))
    assert tuple(s[0] for s in lasso.suffix) == ((2,), (3,), (2,))
    result = run_ecc(model, frozenset())
    assert result.rounds[0].lower_bound < result.rounds[0].upper_bound
    assert result.rounds[0].added_dimension == 0
    assert result.final_cost == Fraction(22)


def refinement_fixture(action_supports, occurrences, precision=frozenset(), prefix_length=0):
    actions = tuple(FormalAction(
        name, read, write, cost, lambda s: True, lambda s: s, lambda s, t: 1,
    ) for name, (read, write, cost) in sorted(action_supports.items()))
    model = FormalFactorizedModel(
        (0, 1, 2), ((0,), (0,), (0,)), frozenset({(0, 0, 0)}), actions,
        lambda s: frozenset(), accepting_buchi(), task_ap=frozenset(),
    )
    abstract = build_optimistic_abstraction(model, precision)
    node = abstract.initial_states[0]
    by_action = {e.action: e for e in abstract.transitions}
    edges = tuple(by_action[name] for name in occurrences)
    candidate = AbstractLassoResult(
        status="EXACT_OPTIMAL", precision=precision, prefix=(node,) * (prefix_length + 1),
        suffix=(node,) * (len(edges) - prefix_length + 1),
        prefix_edges=edges[:prefix_length], suffix_edges=edges[prefix_length:],
        prefix_cost=Fraction(prefix_length), suffix_cost=Fraction(len(edges) - prefix_length),
        lower_bound=Fraction(prefix_length + 10 * (len(edges) - prefix_length)), accepting_product_states=(node,),
    )
    return deterministic_refinement(model, abstract, candidate, "NOT_CONCRETIZABLE")


def test_restoration_counts_each_occurrence_and_union_support_once():
    reason = refinement_fixture({
        "a": (frozenset({1}), frozenset({1}), frozenset({1})),
        "b": (frozenset(), frozenset(), frozenset({2})),
    }, ("a", "b", "b"))
    assert reason.occurrence_counts == ((1, 1), (2, 2))
    assert reason.candidate_actions == ("a", "b", "b")
    assert reason.added_dimension == 2
    assert reason.new_precision == frozenset({2})
    assert not reason.fallback_used


def test_restoration_tie_selects_lowest_hidden_dimension_id():
    reason = refinement_fixture({
        "a": (frozenset({2}), frozenset({1}), frozenset()),
    }, ("a", "a"))
    assert reason.occurrence_counts == ((1, 2), (2, 2))
    assert reason.added_dimension == 1


def test_restoration_allzero_selects_global_lowest_hidden_dimension_id():
    reason = refinement_fixture({
        "a": (frozenset({2}), frozenset(), frozenset()),
    }, ("a", "a"), precision=frozenset({2}))
    assert reason.occurrence_counts == ()
    assert reason.fallback_used
    assert reason.added_dimension == 0

def test_restoration_counts_finite_prefix_and_suffix_occurrences_together():
    reason = refinement_fixture({
        "a": (frozenset({1}), frozenset(), frozenset()),
        "b": (frozenset(), frozenset(), frozenset({2})),
    }, ("a", "a", "b"), prefix_length=2)
    assert reason.candidate_actions == ("a", "a", "b")
    assert reason.occurrence_counts == ((1, 2), (2, 1))
    assert reason.added_dimension == 1


def test_exact_solver_ties_keep_canonical_action_under_input_permutations():
    edges = ((0, 0, 0, "b"), (0, 0, 0, "a"))
    forward = solve_exact_abstract_lasso(abstract_graph(1, edges, (0,)))
    reverse = solve_exact_abstract_lasso(abstract_graph(1, tuple(reversed(edges)), (0,)))
    assert forward.lower_bound == reverse.lower_bound == 0
    assert forward.suffix == reverse.suffix
    assert tuple(e.action for e in forward.suffix_edges) == ("a",)
    assert tuple(e.action for e in reverse.suffix_edges) == ("a",)
    assert len(forward.suffix_edges) == 1
