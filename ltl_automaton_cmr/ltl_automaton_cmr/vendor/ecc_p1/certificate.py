"""Explicit lower/upper-bound status layer."""

from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

from .concretization import ConcretizationResult


@dataclass(frozen=True)
class CertificateResult:
    status: str
    lower_bound: Fraction
    upper_bound: Optional[Fraction]


def evaluate_certificate(lower_bound: Fraction, concretization: ConcretizationResult) -> CertificateResult:
    if concretization.status != "CONCRETIZABLE":
        return CertificateResult("NOT_CONCRETIZABLE_AT_CURRENT_PRECISION", lower_bound, None)
    upper_bound = concretization.concrete_lasso.upper_bound
    if lower_bound == upper_bound:
        return CertificateResult("OPTIMALITY_CERTIFIED", lower_bound, upper_bound)
    return CertificateResult("CONCRETIZABLE_NOT_OPTIMALITY_CERTIFIED", lower_bound, upper_bound)
