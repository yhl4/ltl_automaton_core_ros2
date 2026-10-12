# Adapted only at import from frozen upstream CMR-LTL dad230c2.
from fractions import Fraction

from ltl_automaton_cmr.vendor.ecc_p1 import (BuchiAutomaton, FormalAction, FormalFactorizedModel,
                    build_optimistic_abstraction, deterministic_refinement,
                    periodically_concretize, run_ecc, solve_exact_abstract_lasso)


def buchi():
    return BuchiAutomaton("q0", frozenset({"q0"}), lambda q, label: (q,))


def make_model(dimensions, domains, initial, action):
    return FormalFactorizedModel(tuple(dimensions), tuple(tuple(d) for d in domains),
                                 frozenset({tuple(initial)}), (action,),
                                 lambda state: frozenset(), buchi())


def stay_action(name="stay", cost_value=1, support=frozenset({0})):
    return FormalAction(name, frozenset(support), frozenset(support), frozenset(support),
                        lambda state: True, lambda state: state,
                        lambda source, target: cost_value)


def hidden_toggle_model():
    action = FormalAction("tick", frozenset({1}), frozenset({1}), frozenset(),
                          lambda state: True,
                          lambda state: (state[0], 1 - state[1]),
                          lambda source, target: 1)
    return make_model((0, 1), ((0,), (0, 1)), (0, 0), action)


def gap_model():
    action = FormalAction("loop", frozenset({1}), frozenset({1}), frozenset({1}),
                          lambda state: True,
                          lambda state: (state[0], 1 if state[1] == 0 else 1),
                          lambda source, target: 1 if source[1] == 0 else 5)
    return make_model((0, 1), ((0,), (0, 1)), (0, 0), action)


def spurious_model():
    action = FormalAction("drift", frozenset({1}), frozenset({1}), frozenset(),
                          lambda state: state[1] == 0,
                          lambda state: (state[0], 1),
                          lambda source, target: 1)
    return make_model((0, 1), ((0,), (0, 1)), (0, 0), action)


def test_action_support_and_union_are_formal_and_deterministic():
    action = FormalAction("a", frozenset({0}), frozenset({1}), frozenset({2}),
                          lambda state: True, lambda state: state,
                          lambda source, target: Fraction(2))
    model = make_model((0, 1, 2), ((0,), (0,), (0,)), (0, 0, 0), action)
    support = model.supports()["a"]
    assert support.read == frozenset({0})
    assert support.write == frozenset({1})
    assert support.cost_support == frozenset({2})
    assert support.k == frozenset({0, 1, 2})


def test_same_witness_minimum_and_parallel_actions_are_preserved():
    a = stay_action("a", 3)
    b = stay_action("b", 1)
    model = FormalFactorizedModel((0,), ((0,),), frozenset({(0,)}), (a, b),
                                   lambda state: frozenset(), buchi())
    abstract = build_optimistic_abstraction(model, frozenset({0}))
    edges = [edge for edge in abstract.transitions if edge.source == ((0,), "q0")]
    assert [(edge.action, edge.cost) for edge in edges] == [("a", Fraction(3)), ("b", Fraction(1))]
    assert all(edge.witnesses and min(w.cost for w in edge.witnesses) == edge.cost for edge in edges)


def test_hidden_only_step_is_projected_as_time_preserving_self_loop():
    abstract = build_optimistic_abstraction(hidden_toggle_model(), frozenset({0}))
    assert any(edge.source == edge.target and edge.action == "tick" for edge in abstract.transitions)


def test_fixture_1_strict_simple_certificate():
    model = make_model((0,), ((0,),), (0,), stay_action())
    result = run_ecc(model, frozenset({0}))
    assert result.status == "OPTIMALITY_CERTIFIED"
    assert result.rounds[-1].ell == 0 and result.rounds[-1].m == 1
    assert result.final_cost == Fraction(10)


def test_fixture_2_periodic_hidden_cycle_m_gt_one():
    model = hidden_toggle_model()
    abstract = build_optimistic_abstraction(model, frozenset({0}))
    candidate = solve_exact_abstract_lasso(abstract)
    concrete = periodically_concretize(model, abstract, candidate)
    assert concrete.status == "CONCRETIZABLE"
    assert concrete.concrete_lasso.m == 2
    assert concrete.concrete_lasso.suffix[0] == concrete.concrete_lasso.suffix[-1]
    assert concrete.concrete_lasso.upper_bound == Fraction(20)


def test_fixture_3_concretizable_gap_then_refinement_and_certificate():
    result = run_ecc(gap_model(), frozenset({0}))
    assert result.rounds[0].concretization_status == "CONCRETIZABLE"
    assert result.rounds[0].ell == 1 and result.rounds[0].m == 1
    assert result.rounds[0].lower_bound < result.rounds[0].upper_bound
    assert result.status == "OPTIMALITY_CERTIFIED"
    assert result.final_precision == frozenset({0, 1})


def test_fixture_4_spurious_candidate_is_not_current_precision_infeasible():
    model = spurious_model()
    abstract = build_optimistic_abstraction(model, frozenset({0}))
    candidate = solve_exact_abstract_lasso(abstract)
    concrete = periodically_concretize(model, abstract, candidate)
    assert concrete.status == "NOT_CONCRETIZABLE"
    result = run_ecc(model, frozenset({0}))
    assert result.rounds[0].concretization_status == "NOT_CONCRETIZABLE"
    assert result.rounds[0].added_dimension == 1


def test_fixture_5_refinement_fallback_adds_global_first_hidden_dimension():
    model = make_model((0, 1), ((0,), (0, 1)), (0, 0), stay_action(support=frozenset({0})))
    abstract = build_optimistic_abstraction(model, frozenset({0}))
    candidate = solve_exact_abstract_lasso(abstract)
    reason = deterministic_refinement(model, abstract, candidate, "CONCRETIZABLE_NOT_OPTIMALITY_CERTIFIED")
    assert reason.fallback_used is True
    assert reason.added_dimension == 1
    assert reason.old_precision < reason.new_precision


def test_fixture_6_full_precision_has_identity_and_no_extra_refinement():
    model = gap_model()
    result = run_ecc(model, frozenset(model.dimensions))
    assert result.status == "OPTIMALITY_CERTIFIED"
    assert result.final_precision == frozenset(model.dimensions)
    assert result.rounds[-1].added_dimension is None


def test_refinement_frequency_then_dimension_id_tie_break():
    actions = (
        FormalAction("a", frozenset({1, 2}), frozenset(), frozenset(), lambda s: True,
                     lambda s: s, lambda s, t: 1),
    )
    model = FormalFactorizedModel((0, 1, 2), ((0,), (0,), (0,)), frozenset({(0, 0, 0)}), actions,
                                  lambda s: frozenset(), buchi())
    abstract = build_optimistic_abstraction(model, frozenset({0}))
    candidate = solve_exact_abstract_lasso(abstract)
    reason = deterministic_refinement(model, abstract, candidate, "NOT_CONCRETIZABLE_AT_CURRENT_PRECISION")
    assert reason.added_dimension == 1
