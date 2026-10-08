"""Unified CMR orchestration using the unchanged frozen exact kernel.

FULL, AP, and FAMILY differ only in their initial precision. A caller must
provide explicit task propositions and their support mapping. Guards, effects,
labels, and costs are pure deterministic oracles for one fixed finite model.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from fractions import Fraction
import time
from typing import Iterable

from .vendor.ecc_p1.abstraction import build_optimistic_abstraction
from .vendor.ecc_p1.certificate import evaluate_certificate
from .vendor.ecc_p1.concretization import (
    ConcreteLasso, periodically_concretize, validate_identity_lift,
)
from .vendor.ecc_p1.model import FormalFactorizedModel, exact_cost
from .vendor.ecc_p1.refinement import deterministic_refinement
from .vendor.ecc_p1.solver import GAMMA, SearchStats, solve_exact_abstract_lasso

KERNEL_REPOSITORY = "https://github.com/yhl4/CMR-LTL"
KERNEL_COMMIT = "dad230c2f54d9d5eb85d5e8dfd01e2d6c229afbc"
KERNEL_PATH = (
    "reproducibility/paper_20261005_r2/core/qualified_p1/"
    "ecc_p1_formal_kernel/ecc_p1"
)


def fraction_record(value: int | Fraction | None) -> dict | None:
    """Represent exact costs without a floating-point conversion."""
    if value is None:
        return None
    value = exact_cost(value)
    return {
        "text": str(value),
        "numerator": value.numerator,
        "denominator": value.denominator,
    }


def _product_record(state) -> dict:
    return {"state": list(state[0]), "buchi": state[1]}


def lasso_record(lasso: ConcreteLasso | None) -> dict | None:
    """Keep every occurrence, parallel action identity, and final closure."""
    if lasso is None:
        return None

    def edge_record(edge):
        return {
            "source": _product_record(edge.source),
            "action": edge.action,
            "target": _product_record(edge.target),
            "cost": fraction_record(edge.cost),
        }

    return {
        "prefix": [_product_record(state) for state in lasso.prefix],
        "suffix": [_product_record(state) for state in lasso.suffix],
        "prefix_edges": [edge_record(edge) for edge in lasso.prefix_edges],
        "suffix_edges": [edge_record(edge) for edge in lasso.suffix_edges],
        "ell": lasso.ell,
        "m": lasso.m,
        "prefix_cost": fraction_record(lasso.prefix_cost),
        "suffix_cost": fraction_record(lasso.suffix_cost),
        "objective": fraction_record(lasso.upper_bound),
        "suffix_representation": "closed: final state repeats suffix entry",
    }


@dataclass(frozen=True)
class PlanResult:
    status: str
    arm: str
    initial_precision: frozenset[int]
    final_precision: frozenset[int]
    family_prior: frozenset[int]
    rounds: tuple[dict, ...]
    lasso: ConcreteLasso | None
    cost: Fraction | None
    total_seconds: float
    infeasibility_reason: str | None = None

    @property
    def final_lasso(self):
        return self.lasso

    @property
    def final_cost(self):
        return self.cost

    def to_dict(self) -> dict:
        return {
            "schema": "ltl-automaton-cmr-plan-v1",
            "status": self.status,
            "arm": self.arm,
            "initial_precision": sorted(self.initial_precision),
            "final_precision": sorted(self.final_precision),
            "family_prior": sorted(self.family_prior),
            "gamma": fraction_record(GAMMA),
            "objective": fraction_record(self.cost),
            "rounds": list(self.rounds),
            "lasso": lasso_record(self.lasso),
            "total_seconds": self.total_seconds,
            "infeasibility_reason": self.infeasibility_reason,
            "kernel": {
                "repository": KERNEL_REPOSITORY,
                "commit": KERNEL_COMMIT,
                "path": KERNEL_PATH,
                "license": "MIT",
            },
        }


class CertificationError(RuntimeError):
    """Full precision cannot return a plan unless exact LB equals exact UB."""

    def __init__(self, message: str, rounds: Iterable[dict] = ()):
        super().__init__(message)
        self.rounds = tuple(rounds)

    def to_dict(self) -> dict:
        return {
            "schema": "ltl-automaton-cmr-plan-v1",
            "status": "FULL_PRECISION_NOT_CERTIFIED",
            "error": str(self),
            "rounds": list(self.rounds),
        }


def _dimension_set(values: Iterable[int], dimensions: frozenset[int], name: str):
    result = frozenset(values)
    if any(type(value) is not int for value in result):
        raise TypeError(name + " must contain integer dimension IDs")
    if not result <= dimensions:
        raise ValueError(name + " contains unknown dimension IDs")
    return result


def task_precision(model: FormalFactorizedModel) -> frozenset[int]:
    """Validate the adapter boundary and return the explicit AP support."""
    dimensions = frozenset(model.dimensions)
    if len(dimensions) != len(model.dimensions):
        raise ValueError("dimension IDs must be unique")
    if any(type(dimension) is not int for dimension in dimensions):
        raise TypeError("dimension IDs must be integers")
    if model.task_ap is None:
        raise ValueError("CMR requires explicit task_ap and task_support")
    if any(not isinstance(ap, str) or not ap for ap in model.task_ap):
        raise ValueError("task AP must contain nonempty proposition strings")
    missing = set(model.task_ap) - set(model.task_support)
    if missing:
        raise ValueError("task support is missing propositions: " + repr(sorted(missing)))
    precision = set()
    for proposition in model.task_ap:
        precision.update(_dimension_set(
            model.task_support[proposition], dimensions, "task support"))
    for action in model.actions:
        for name in ("read", "write", "cost_support"):
            _dimension_set(getattr(action, name), dimensions, "action " + name)
    if not model.initial_states:
        raise ValueError("CMR requires at least one initial state")
    for state in model.initial_states:
        if len(state) != len(model.dimensions):
            raise ValueError("initial state has wrong dimension count")
        if any(value not in domain for value, domain in zip(state, model.local_states)):
            raise ValueError("initial state is outside the declared domains")
    return frozenset(precision)


def validate_concrete_lasso(model: FormalFactorizedModel, lasso: ConcreteLasso) -> None:
    """Recheck the concrete witness before it can cross the execution boundary."""
    def require(condition, message):
        if not condition:
            raise CertificationError("invalid concrete lasso: " + message)

    require(bool(lasso.prefix) and bool(lasso.suffix), "empty state sequence")
    require(len(lasso.prefix) == len(lasso.prefix_edges) + 1, "prefix length mismatch")
    require(len(lasso.suffix) == len(lasso.suffix_edges) + 1, "suffix length mismatch")
    require(bool(lasso.suffix_edges), "empty accepting suffix")
    require(lasso.prefix[0] in model.initial_product_states(), "noninitial prefix")
    require(lasso.prefix[-1] == lasso.suffix[0], "prefix/suffix split mismatch")
    require(lasso.suffix[0] == lasso.suffix[-1], "suffix does not close")
    require(any(q in model.buchi.accepting for _, q in lasso.suffix[:-1]),
            "suffix does not visit acceptance")
    require(type(lasso.ell) is int and lasso.ell >= 0, "invalid transient count")
    require(type(lasso.m) is int and lasso.m >= 1, "invalid recurrent period count")
    for states, edges, cost in (
        (lasso.prefix, lasso.prefix_edges, lasso.prefix_cost),
        (lasso.suffix, lasso.suffix_edges, lasso.suffix_cost),
    ):
        require(sum((exact_cost(edge.cost) for edge in edges), Fraction(0)) == exact_cost(cost),
                "component cost mismatch")
        for index, edge in enumerate(edges):
            require(edge.source == states[index] and edge.target == states[index + 1],
                    "edge/path state mismatch")
            require(edge in model.transitions_from(edge.source),
                    "action, target, Buchi state, or exact cost differs from original model")


def _scores(model, precision, candidate):
    occurrences = tuple(edge.action for edge in candidate.prefix_edges + candidate.suffix_edges)
    supports = model.supports()
    counts = Counter()
    for action in occurrences:
        counts.update(supports[action].k - precision)
    return [
        {"dimension": dimension, "count": counts[dimension]}
        for dimension in sorted(set(model.dimensions) - precision)
    ]


def _restoration_record(reason):
    if reason is None:
        return None
    return {
        "old_precision": sorted(reason.old_precision),
        "new_precision": sorted(reason.new_precision),
        "added_dimension": reason.added_dimension,
        "candidate_action_occurrences": list(reason.candidate_actions),
        "hidden_support_by_action": [
            {"action": action, "dimensions": list(dimensions)}
            for action, dimensions in reason.relevant_k_entries
        ],
        "occurrence_counts": [
            {"dimension": dimension, "count": count}
            for dimension, count in reason.occurrence_counts
        ],
        "tie_break": reason.tie_break,
        "fallback_used": reason.fallback_used,
        "certificate_status": reason.certificate_status,
    }


def plan(model: FormalFactorizedModel, arm: str = "AP",
         family_prior: Iterable[int] = ()) -> PlanResult:
    """Run exact CMR; return only a certified lasso or an exact-empty result.

    RF is copied once and affects S0 only. The fixed GAMMA=10 objective and all
    subsequent operations are shared by FULL, AP, and FAMILY.
    """
    started = time.perf_counter()
    arm = arm.upper()
    if arm not in {"FULL", "AP", "FAMILY"}:
        raise ValueError("arm must be FULL, AP, or FAMILY")
    all_dimensions = frozenset(model.dimensions)
    ap_precision = task_precision(model)
    frozen_prior = _dimension_set(family_prior, all_dimensions, "family prior")
    initial = {
        "FULL": all_dimensions,
        "AP": ap_precision,
        "FAMILY": ap_precision | frozen_prior,
    }[arm]
    precision = initial
    rounds = []

    for round_index in range(len(all_dimensions) + 1):
        round_started = time.perf_counter()
        phases = {}
        kernel_timing = {}
        phase_started = time.perf_counter()
        abstract = build_optimistic_abstraction(model, precision, timing=kernel_timing)
        phases["abstraction"] = time.perf_counter() - phase_started
        stats = SearchStats()
        phase_started = time.perf_counter()
        candidate = solve_exact_abstract_lasso(abstract, stats)
        phases["exact_search"] = time.perf_counter() - phase_started
        row = {
            "round": round_index,
            "precision": sorted(precision),
            "task_ap_support": sorted(ap_precision),
            "ts_states": len(abstract.reachable_ts_states),
            "ts_edges": abstract.reduced_ts_edge_count,
            "product_states": len(abstract.states),
            "product_edges": len(abstract.transitions),
            "search": asdict(stats),
            "abstraction_provenance": abstract.provenance,
            "kernel_timing_ns": kernel_timing,
            "phase_seconds": phases,
            "lower_bound": None,
            "upper_bound": None,
            "candidate_prefix_actions": [],
            "candidate_suffix_actions": [],
            "restoration": None,
        }

        if candidate is None:
            reason = (
                "exact_empty_full_product" if precision == all_dimensions
                else "exact_empty_optimistic_product"
            )
            row.update(status="INFEASIBLE", infeasibility_reason=reason,
                       seconds=time.perf_counter() - round_started)
            rounds.append(row)
            # Every concrete accepting lasso projects to this optimistic
            # action-preserving product. Exact emptiness is a negative proof.
            return PlanResult(
                "INFEASIBLE", arm, initial, precision, frozen_prior,
                tuple(rounds), None, None, time.perf_counter() - started, reason,
            )

        row.update(
            lower_bound=str(candidate.lower_bound),
            lower_bound_exact=fraction_record(candidate.lower_bound),
            candidate_prefix_actions=list(candidate.identity[0]),
            candidate_suffix_actions=list(candidate.identity[1]),
            restoration_scores=_scores(model, precision, candidate),
        )
        phase_started = time.perf_counter()
        lift = (
            validate_identity_lift(model, candidate)
            if precision == all_dimensions
            else periodically_concretize(model, abstract, candidate)
        )
        phases["concretization"] = time.perf_counter() - phase_started
        concrete = lift.concrete_lasso
        phase_started = time.perf_counter()
        if concrete is not None:
            validate_concrete_lasso(model, concrete)
        certificate = evaluate_certificate(candidate.lower_bound, lift)
        phases["certificate"] = time.perf_counter() - phase_started
        row.update(
            status=certificate.status,
            lift_status=lift.status,
            lift_reason=lift.reason,
            upper_bound=str(certificate.upper_bound) if certificate.upper_bound is not None else None,
            upper_bound_exact=fraction_record(certificate.upper_bound),
            ell=concrete.ell if concrete is not None else None,
            m=concrete.m if concrete is not None else None,
        )
        if certificate.status == "OPTIMALITY_CERTIFIED":
            if concrete is None or candidate.lower_bound != concrete.upper_bound:
                raise CertificationError("certificate violated exact LB=UB invariant", rounds + [row])
            row["seconds"] = time.perf_counter() - round_started
            rounds.append(row)
            return PlanResult(
                certificate.status, arm, initial, precision, frozen_prior,
                tuple(rounds), concrete, exact_cost(concrete.upper_bound),
                time.perf_counter() - started,
            )

        if precision == all_dimensions:
            row.update(status="FULL_PRECISION_NOT_CERTIFIED",
                       seconds=time.perf_counter() - round_started)
            rounds.append(row)
            raise CertificationError(
                "full precision did not establish exact LB=UB: " + certificate.status,
                rounds,
            )

        phase_started = time.perf_counter()
        reason = deterministic_refinement(model, abstract, candidate, certificate.status)
        phases["refinement"] = time.perf_counter() - phase_started
        row["restoration"] = _restoration_record(reason)
        row["seconds"] = time.perf_counter() - round_started
        rounds.append(row)
        precision = reason.new_precision

    raise CertificationError("refinement exceeded the finite dimension bound", rounds)
