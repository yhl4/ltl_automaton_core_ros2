"""Deterministic non-LLM ECC refinement policy."""

from dataclasses import dataclass
from typing import FrozenSet, Iterable, Tuple

from .abstraction import OptimisticAbstractModel
from .model import FormalFactorizedModel
from .solver import AbstractLassoResult


@dataclass(frozen=True)
class RefinementReason:
    old_precision: FrozenSet[int]
    new_precision: FrozenSet[int]
    added_dimension: int
    candidate_actions: Tuple[str, ...]
    relevant_k_entries: Tuple[Tuple[str, Tuple[int, ...]], ...]
    occurrence_counts: Tuple[Tuple[int, int], ...]
    tie_break: str
    fallback_used: bool
    certificate_status: str


def deterministic_refinement(model: FormalFactorizedModel, abstract: OptimisticAbstractModel,
                             candidate: AbstractLassoResult, certificate_status: str) -> RefinementReason:
    precision = abstract.precision
    occurrences = tuple(edge.action for edge in candidate.prefix_edges + candidate.suffix_edges)
    supports = model.supports()
    relevant = tuple((action, tuple(sorted(supports[action].k - precision))) for action in sorted(set(occurrences)))
    counts: dict[int, int] = {}
    for action in occurrences:
        for dimension in supports[action].k - precision:
            counts[dimension] = counts.get(dimension, 0) + 1
    if counts:
        added = min(counts, key=lambda dimension: (-counts[dimension], dimension))
        fallback = False
        tie_break = "descending occurrence frequency, then ascending dimension ID"
    else:
        remaining = sorted(set(model.dimensions) - precision)
        if not remaining:
            raise ValueError("refinement requested at full precision")
        added = remaining[0]
        fallback = True
        tie_break = "global ascending dimension ID fallback"
    new_precision = frozenset(set(precision) | {added})
    if not precision < new_precision:
        raise AssertionError("ECC refinement must strictly increase precision")
    return RefinementReason(frozenset(precision), new_precision, added, occurrences, relevant,
                            tuple(sorted(counts.items())), tie_break, fallback, certificate_status)
