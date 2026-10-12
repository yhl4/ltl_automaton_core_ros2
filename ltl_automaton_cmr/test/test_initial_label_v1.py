# Adapted only at import from frozen upstream CMR-LTL dad230c2.
"""Directed INITIAL_LABEL_V1 Product semantics checks."""

from ltl_automaton_cmr.vendor.ecc_p1 import (BuchiAutomaton, FormalAction, FormalFactorizedModel,
                    build_optimistic_abstraction)


def _model(label, transition, accepting=frozenset(), initial=(0,), domains=((0, 1),),
           actions=None, task_ap=frozenset({"p", "g", "safe"})):
    if actions is None:
        actions = (
            FormalAction("stay", frozenset({0}), frozenset({0}), frozenset(),
                          lambda state: True, lambda state: state, lambda source, target: 1),
        )
    return FormalFactorizedModel(
        (0,), tuple(tuple(domain) for domain in domains), frozenset({tuple(initial)}),
        tuple(actions), label,
        BuchiAutomaton("q0", frozenset(accepting), transition),
        task_ap=task_ap,
    )


def test_full_and_abstract_initial_products_consume_initial_label_once_and_branch():
    def transition(q, label):
        if q == "q0" and "p" in label:
            return ("q1", "q2")
        return (q,)

    model = _model(lambda state: frozenset({"p"}), transition,
                   accepting=frozenset({"q1", "q2"}))
    abstract = build_optimistic_abstraction(model, frozenset({0}))

    assert model.initial_product_states() == (((0,), "q1"), ((0,), "q2"))
    assert abstract.initial_states == (((0,), "q1"), ((0,), "q2"))


def test_q15_p_initial_observation_enters_accepting_monitor_state():
    def transition(q, label):
        if q == "q0":
            return ("accept",) if "p" in label else ("dead",)
        return (q,)

    actions = (
        FormalAction("loop", frozenset({0}), frozenset({0}), frozenset(),
                      lambda state: state[0] == 2, lambda state: state,
                      lambda source, target: 1),
        FormalAction("step", frozenset({0}), frozenset({0}), frozenset(),
                      lambda state: state[0] < 2, lambda state: (state[0] + 1,),
                      lambda source, target: 1),
    )
    model = _model(lambda state: frozenset({"p"}) if state[0] in (0, 2) else frozenset(),
                   transition, accepting=frozenset({"accept"}), initial=(0,),
                   domains=((0, 1, 2),), actions=actions)
    assert model.initial_product_states() == (((0,), "accept"),)


def test_q15_xp_consumes_q1_label_after_waiting_at_q0():
    def transition(q, label):
        if q == "q0":
            return ("wait",)
        if q == "wait":
            return ("accept",) if "p" in label else ("dead",)
        return (q,)

    actions = (
        FormalAction("loop", frozenset({0}), frozenset({0}), frozenset(),
                      lambda state: state[0] == 2, lambda state: state,
                      lambda source, target: 1),
        FormalAction("step", frozenset({0}), frozenset({0}), frozenset(),
                      lambda state: state[0] < 2, lambda state: (state[0] + 1,),
                      lambda source, target: 1),
    )
    model = _model(lambda state: frozenset({"p"}) if state[0] in (0, 2) else frozenset(),
                   transition, accepting=frozenset({"accept"}), initial=(0,),
                   domains=((0, 1, 2),), actions=actions)
    initial = model.initial_product_states()
    assert initial == (((0,), "wait"),)
    first_edge = model.transitions_from(initial[0])
    assert {(edge.target, edge.action) for edge in first_edge} == {(((1,), "dead"), "step")}


def test_initial_f_g_and_g_safe_cases_are_decided_at_q0():
    f_g = _model(lambda state: frozenset({"g"}),
                 lambda q, label: ("accept",) if "g" in label else (q,),
                 accepting=frozenset({"accept"}))
    assert f_g.initial_product_states() == (((0,), "accept"),)

    g_safe = _model(lambda state: frozenset() if state[0] == 0 else frozenset({"safe"}),
                    lambda q, label: ("dead",) if "safe" not in label else (q,),
                    accepting=frozenset({"q0"}), domains=((0, 1),),
                    actions=(FormalAction("to_safe", frozenset({0}), frozenset({0}), frozenset(),
                                          lambda state: state[0] == 0, lambda state: (1,),
                                          lambda source, target: 1),))
    assert g_safe.initial_product_states() == (((0,), "dead"),)


def test_nondeterministic_initial_label_preserves_all_full_and_abstract_states():
    model = _model(lambda state: frozenset({"p"}),
                   lambda q, label: ("left", "right") if q == "q0" else (q,),
                   accepting=frozenset({"left", "right"}))
    abstract = build_optimistic_abstraction(model, frozenset({0}))
    assert {state[1] for state in model.initial_product_states()} == {"left", "right"}
    assert {state[1] for state in abstract.initial_states} == {"left", "right"}
