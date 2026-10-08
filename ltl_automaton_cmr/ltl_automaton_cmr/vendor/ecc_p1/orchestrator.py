"""Minimal certified abstraction-refinement orchestration."""

from dataclasses import dataclass
from fractions import Fraction
from typing import FrozenSet, Optional, Tuple

from .abstraction import build_optimistic_abstraction
from .certificate import evaluate_certificate
from .concretization import ConcreteLasso, periodically_concretize, validate_identity_lift
from .model import FormalFactorizedModel
from .refinement import RefinementReason, deterministic_refinement
from .solver import AbstractLassoResult, solve_exact_abstract_lasso


@dataclass(frozen=True)
class RoundResult:
    precision: FrozenSet[int]
    lower_bound: Optional[Fraction]
    candidate_identity: Optional[Tuple[Tuple[str, ...], Tuple[str, ...]]]
    concretization_status: str
    ell: Optional[int]
    m: Optional[int]
    upper_bound: Optional[Fraction]
    added_dimension: Optional[int]
    refinement_reason: Optional[RefinementReason]


@dataclass(frozen=True)
class ECCResult:
    status: str
    initial_precision: FrozenSet[int]
    final_precision: FrozenSet[int]
    rounds: Tuple[RoundResult, ...]
    full_precision_fallback: bool
    final_lasso: Optional[ConcreteLasso]
    final_cost: Optional[Fraction]


def run_ecc(model: FormalFactorizedModel, initial_precision: FrozenSet[int]) -> ECCResult:
    precision = frozenset(initial_precision)
    if not precision.issubset(model.dimensions):
        raise ValueError("initial precision must be a subset of dimensions")
    rounds = []
    fallback = False
    while True:
        abstract = build_optimistic_abstraction(model, precision)
        candidate = solve_exact_abstract_lasso(abstract)
        if candidate is None:
            status = "INFEASIBLE" if precision == frozenset(model.dimensions) else "ABSTRACT_INFEASIBLE"
            rounds.append(RoundResult(precision, None, None, "NOT_RUN", None, None, None, None, None))
            return ECCResult(status, initial_precision, precision, tuple(rounds), fallback, None, None)
        if precision == frozenset(model.dimensions):
            concretization = validate_identity_lift(model, candidate)
        else:
            concretization = periodically_concretize(model, abstract, candidate)
        certificate = evaluate_certificate(candidate.lower_bound, concretization)
        concrete = concretization.concrete_lasso
        reason = None
        added = None
        if certificate.status == "OPTIMALITY_CERTIFIED":
            rounds.append(RoundResult(precision, candidate.lower_bound, candidate.identity,
                                      concretization.status, concrete.ell, concrete.m,
                                      certificate.upper_bound, None, None))
            return ECCResult(certificate.status, initial_precision, precision, tuple(rounds), fallback,
                             concrete, certificate.upper_bound)
        if precision == frozenset(model.dimensions):
            # Full precision has identity projection; no further refinement is legal.
            fallback = True
            rounds.append(RoundResult(precision, candidate.lower_bound, candidate.identity,
                                      concretization.status, concrete.ell if concrete else None,
                                      concrete.m if concrete else None, certificate.upper_bound, None, None))
            status = "FULL_PRECISION_NOT_CERTIFIED" if certificate.status != "OPTIMALITY_CERTIFIED" else certificate.status
            return ECCResult(status, initial_precision, precision, tuple(rounds), fallback,
                             concrete, certificate.upper_bound if concrete else None)
        reason = deterministic_refinement(model, abstract, candidate, certificate.status)
        added = reason.added_dimension
        rounds.append(RoundResult(precision, candidate.lower_bound, candidate.identity,
                                  concretization.status, concrete.ell if concrete else None,
                                  concrete.m if concrete else None, certificate.upper_bound, added, reason))
        precision = reason.new_precision
