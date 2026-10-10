"""Behavioral checks at the unified CMR engine boundary."""

from dataclasses import replace
from fractions import Fraction
import json
from types import SimpleNamespace

import pytest

from ltl_automaton_cmr import engine
from ltl_automaton_cmr.vendor.ecc_p1 import (
    BuchiAutomaton, FormalAction, FormalFactorizedModel, run_ecc,
)


def formal_model(cost=1, task_ap=frozenset({"p"}), task_support=None):
    action = FormalAction(
        "loop", frozenset({0}), frozenset(), frozenset(),
        lambda s: True, lambda s: s, lambda s, t: cost,
    )
    return FormalFactorizedModel(
        (0, 1, 2), ((0,), (0,), (0,)), frozenset({(0, 0, 0)}), (action,),
        lambda s: frozenset({"p"}),
        BuchiAutomaton("q", frozenset({"q"}), lambda q, label: (q,)),
        task_ap=task_ap,
        task_support={"p": frozenset({0})} if task_support is None else task_support,
    )


def cost_gap_model():
    action = FormalAction(
        "loop", frozenset({1}), frozenset({1}), frozenset({1}),
        lambda s: True, lambda s: (s[0], 1, s[2]),
        lambda s, t: 1 if s[1] == 0 else 5,
    )
    return replace(formal_model(), local_states=((0,), (0, 1), (0,)), actions=(action,))


@pytest.mark.parametrize("arm,precision", [
    ("FULL", frozenset({0, 1, 2})),
    ("AP", frozenset({0})),
    ("FAMILY", frozenset({0, 2})),
])
def test_all_arms_use_same_exact_kernel_and_only_change_initial_precision(arm, precision):
    model = cost_gap_model()
    result = engine.plan(model, arm=arm, family_prior=(2,))
    frozen = run_ecc(model, precision)
    assert result.initial_precision == frozen.initial_precision == precision
    assert result.final_precision == frozen.final_precision
    assert result.status == frozen.status == "OPTIMALITY_CERTIFIED"
    assert result.lasso == frozen.final_lasso
    assert result.cost == frozen.final_cost == Fraction(51)
    assert len(result.rounds) == len(frozen.rounds)
    for row, reference in zip(result.rounds, frozen.rounds):
        assert row["precision"] == sorted(reference.precision)
        assert row["lower_bound"] == str(reference.lower_bound)
        assert row["upper_bound"] == str(reference.upper_bound)
        assert row["candidate_prefix_actions"] == list(reference.candidate_identity[0])
        assert row["candidate_suffix_actions"] == list(reference.candidate_identity[1])
        restoration = row["restoration"]
        assert (restoration["added_dimension"] if restoration else None) == reference.added_dimension
    assert result.rounds[-1]["lower_bound_exact"] == result.rounds[-1]["upper_bound_exact"]


def test_fixed_family_prior_is_copied_once_from_a_single_use_iterable():
    result = engine.plan(cost_gap_model(), arm="FAMILY", family_prior=iter((2,)))
    assert result.family_prior == frozenset({2})
    assert result.initial_precision == frozenset({0, 2})
    assert result.final_precision == frozenset({0, 1, 2})
    assert result.rounds[0]["restoration"]["added_dimension"] == 1


def test_exact_certification_and_machine_readable_records_never_round_costs():
    result = engine.plan(formal_model(Fraction(1, 3)), arm="AP")
    assert result.cost == Fraction(10, 3)
    final = result.rounds[-1]
    expected = {"text": "10/3", "numerator": 10, "denominator": 3}
    assert final["lower_bound_exact"] == expected
    assert final["upper_bound_exact"] == expected
    encoded = json.loads(json.dumps(result.to_dict()))
    assert encoded["objective"] == expected
    assert encoded["lasso"]["suffix_edges"][0]["cost"] == {
        "text": "1/3", "numerator": 1, "denominator": 3,
    }
    assert encoded["rounds"][0]["candidate_suffix_actions"] == ["loop"]
    assert encoded["rounds"][0]["precision"] == [0]
    assert encoded["rounds"][0]["restoration_scores"] == [
        {"dimension": 1, "count": 0}, {"dimension": 2, "count": 0},
    ]
    assert encoded["total_seconds"] >= 0
    assert all(t >= 0 for t in final["phase_seconds"].values())


def test_reduced_exact_empty_is_an_infeasibility_proof_without_restoration():
    model = formal_model(task_ap=frozenset(), task_support={})
    model = replace(model, buchi=BuchiAutomaton(
        "q", frozenset({"unreachable"}), lambda q, label: (q,),
    ))
    result = engine.plan(model)
    assert result.status == "INFEASIBLE"
    assert result.initial_precision == result.final_precision == frozenset()
    assert result.infeasibility_reason == "exact_empty_optimistic_product"
    assert result.lasso is None and result.cost is None
    assert len(result.rounds) == 1
    assert result.rounds[0]["restoration"] is None


def test_full_uncertified_raises_instead_of_returning_executable_lasso(monkeypatch):
    monkeypatch.setattr(engine, "evaluate_certificate", lambda lower, lift: SimpleNamespace(
        status="CONCRETIZABLE_NOT_OPTIMALITY_CERTIFIED", upper_bound=lift.concrete_lasso.upper_bound,
    ))
    with pytest.raises(engine.CertificationError, match="full precision") as failure:
        engine.plan(formal_model(), arm="FULL")
    assert failure.value.rounds[-1]["status"] == "FULL_PRECISION_NOT_CERTIFIED"
    assert failure.value.to_dict()["status"] == "FULL_PRECISION_NOT_CERTIFIED"


@pytest.mark.parametrize("field", ["read", "write", "cost_support"])
def test_unknown_action_support_ids_are_rejected(field):
    model = formal_model()
    action = replace(model.actions[0], **{field: frozenset({99})})
    with pytest.raises(ValueError, match="unknown dimension"):
        engine.plan(replace(model, actions=(action,)))


def test_task_support_mapping_is_required_and_must_name_declared_dimensions():
    with pytest.raises(ValueError, match="explicit task_ap"):
        engine.plan(replace(formal_model(), task_ap=None))
    with pytest.raises(ValueError, match="missing propositions"):
        engine.plan(formal_model(task_support={}))
    with pytest.raises(ValueError, match="unknown dimension"):
        engine.plan(formal_model(task_support={"p": frozenset({99})}))


def test_ap_support_contains_only_explicit_task_propositions():
    model = formal_model(task_support={"p": frozenset({0}), "irrelevant": frozenset({2})})
    assert engine.plan(model).initial_precision == frozenset({0})


def test_label_disagreement_detects_unsound_ap_support():
    model = replace(
        formal_model(), local_states=((0,), (0, 1), (0,)),
        initial_states=frozenset({(0, 0, 0), (0, 1, 0)}),
        label=lambda s: frozenset({"p"}) if s[1] else frozenset(),
    )
    with pytest.raises(ValueError, match="label disagreement"):
        engine.plan(model)


@pytest.mark.parametrize("cost", [0.5, True])
def test_float_and_bool_costs_are_rejected_before_certification(cost):
    with pytest.raises(TypeError, match="integer or Fraction"):
        engine.plan(formal_model(cost))


@pytest.mark.parametrize("prior,error", [((99,), ValueError), ((True,), TypeError)])
def test_invalid_family_prior_is_rejected(prior, error):
    with pytest.raises(error):
        engine.plan(formal_model(), arm="FAMILY", family_prior=prior)


def test_concrete_validation_rejects_modified_action_identity_and_component_cost():
    model = formal_model()
    lasso = engine.plan(model).lasso
    wrong_action = replace(lasso.suffix_edges[0], action="different")
    with pytest.raises(engine.CertificationError, match="original model"):
        engine.validate_concrete_lasso(model, replace(lasso, suffix_edges=(wrong_action,)))
    with pytest.raises(engine.CertificationError, match="component cost"):
        engine.validate_concrete_lasso(model, replace(lasso, suffix_cost=Fraction(2)))
