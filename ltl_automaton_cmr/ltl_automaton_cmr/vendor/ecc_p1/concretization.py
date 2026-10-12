"""Global periodic concretization over the full finite Product state space."""

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Optional, Tuple

from .abstraction import AbstractTransition, OptimisticAbstractModel, project_product
from .model import ConcreteTransition, FormalFactorizedModel, ProductState
from .solver import AbstractLassoResult, GAMMA


@dataclass(frozen=True)
class ConcreteLasso:
    prefix: Tuple[ProductState, ...]
    suffix: Tuple[ProductState, ...]
    prefix_edges: Tuple[ConcreteTransition, ...]
    suffix_edges: Tuple[ConcreteTransition, ...]
    ell: int
    m: int
    prefix_cost: Fraction
    suffix_cost: Fraction

    @property
    def upper_bound(self) -> Fraction:
        return self.prefix_cost + GAMMA * self.suffix_cost


@dataclass(frozen=True)
class ConcretizationResult:
    status: str
    concrete_lasso: Optional[ConcreteLasso] = None
    reason: str = ""


def validate_identity_lift(model: FormalFactorizedModel,
                           candidate: AbstractLassoResult) -> ConcretizationResult:
    """Validate a full-precision abstract lasso as its exact full lasso.

    At full precision the projected Product state is the full Product state.
    This validator deliberately checks the finite candidate directly instead
    of invoking the general periodic replay search.
    """
    if candidate.precision != frozenset(model.dimensions):
        return ConcretizationResult("NOT_CONCRETIZABLE",
                                    reason="identity lift requires full precision")

    prefix = tuple((tuple(state), q) for state, q in candidate.prefix)
    suffix = tuple((tuple(state), q) for state, q in candidate.suffix)

    def reject(reason: str) -> ConcretizationResult:
        return ConcretizationResult("NOT_CONCRETIZABLE",
                                    reason=f"identity-lift rejected: {reason}")

    if not prefix or not suffix:
        return reject("empty prefix or suffix")
    if len(prefix) != len(candidate.prefix_edges) + 1:
        return reject("prefix/edge length mismatch")
    if len(suffix) != len(candidate.suffix_edges) + 1:
        return reject("suffix/edge length mismatch")
    if not candidate.suffix_edges:
        return reject("suffix must contain at least one edge")
    if prefix[0] not in model.initial_product_states():
        return reject("prefix does not start at an initial Product state")
    if prefix[-1] != suffix[0] or suffix[0] != suffix[-1]:
        return reject("invalid prefix/suffix split or loop closure")
    if not any(q in model.buchi.accepting for _, q in suffix[:-1]):
        return reject("suffix does not visit an accepting Product state")

    def validate_path(states, abstract_edges):
        concrete_edges = []
        cost = Fraction(0)
        for index, abstract_edge in enumerate(abstract_edges):
            source = states[index]
            target = states[index + 1]
            if abstract_edge.source != source or abstract_edge.target != target:
                return None, None, "candidate edge states do not match"
            matches = tuple(edge for edge in model.transitions_from(source)
                            if edge.action == abstract_edge.action
                            and edge.target == target
                            and edge.cost == abstract_edge.cost)
            if len(matches) != 1:
                return None, None, "action identity, Büchi transition, or exact edge cost mismatch"
            concrete_edges.append(matches[0])
            cost += matches[0].cost
        return tuple(concrete_edges), cost, ""

    prefix_edges, prefix_cost, reason = validate_path(prefix, candidate.prefix_edges)
    if prefix_edges is None:
        return reject(reason)
    suffix_edges, suffix_cost, reason = validate_path(suffix, candidate.suffix_edges)
    if suffix_edges is None:
        return reject(reason)
    total = prefix_cost + GAMMA * suffix_cost
    if candidate.prefix_cost != prefix_cost or candidate.suffix_cost != suffix_cost:
        return reject("candidate component cost differs from exact edge costs")
    if candidate.lower_bound != total:
        return reject("candidate objective differs from exact identity-lift cost")

    concrete = ConcreteLasso(prefix, suffix, prefix_edges, suffix_edges,
                             ell=0, m=1,
                             prefix_cost=prefix_cost, suffix_cost=suffix_cost)
    return ConcretizationResult("CONCRETIZABLE", concrete,
                                reason="identity-lift validator accepted")


def periodically_concretize(model: FormalFactorizedModel, abstract: OptimisticAbstractModel,
                             candidate: AbstractLassoResult) -> ConcretizationResult:
    """Find a globally consistent concrete lasso, with finite recurrence search."""
    prefix_candidates = []
    for initial in model.initial_product_states():
        if project_product(initial, abstract.precision, model.dimensions) != candidate.prefix[0]:
            continue
        prefix_candidates.extend(_replay(model, [(initial, (initial,), (), Fraction(0))],
                                         candidate.prefix_edges, abstract.precision))
    for boundary_state, prefix_states, prefix_edges, prefix_cost in prefix_candidates:
        found = _find_periodic_cycle(model, abstract, candidate, boundary_state)
        for ell, m, transient_periods, recurrent_periods in found:
            full_prefix_states = list(prefix_states)
            full_prefix_edges = list(prefix_edges)
            for period_states, period_edges, period_cost in transient_periods:
                _append_path(full_prefix_states, full_prefix_edges, period_states, period_edges)
                prefix_cost += period_cost
            suffix_start = recurrent_periods[0][0][0]
            suffix_states = [suffix_start]
            suffix_edges = []
            suffix_cost = Fraction(0)
            for period_states, period_edges, period_cost in recurrent_periods:
                _append_path(suffix_states, suffix_edges, period_states, period_edges)
                suffix_cost += period_cost
            concrete = ConcreteLasso(tuple(full_prefix_states), tuple(suffix_states), tuple(full_prefix_edges),
                                     tuple(suffix_edges), ell, m, prefix_cost, suffix_cost)
            if suffix_states[0] != suffix_states[-1] or not suffix_edges:
                continue
            return ConcretizationResult("CONCRETIZABLE", concrete)
    return ConcretizationResult("NOT_CONCRETIZABLE", reason="no finite full-Product recurrent lift")


def _replay(model, candidates, edges: Tuple[AbstractTransition, ...], precision):
    current = candidates
    for abstract_edge in edges:
        next_candidates = []
        for source, states, concrete_edges, cost in current:
            for edge in _matching_edges(model, source, abstract_edge, precision):
                next_candidates.append((edge.target, states + (edge.target,), concrete_edges + (edge,),
                                        cost + edge.cost))
        current = sorted(next_candidates, key=lambda item: (item[0], item[1], item[2]))
        if not current:
            return []
    return current


def _matching_edges(model: FormalFactorizedModel, source: ProductState,
                    abstract_edge: AbstractTransition, precision):
    # Replay uses the authoritative formal transition relation, not the stored
    # abstract witness. This makes the check global and independent.
    return tuple(edge for edge in model.transitions_from(source)
                 if edge.action == abstract_edge.action
                 and project_product(edge.source, precision, model.dimensions) == abstract_edge.source
                 and project_product(edge.target, precision, model.dimensions) == abstract_edge.target)


def _find_periodic_cycle(model, abstract, candidate, start):
    """Find periodic closures with recursive-DFS semantics and a safe stack."""
    suffix = candidate.suffix_edges
    normalized = []

    # This explicit frame stack emulates the old nested visit_split exactly:
    # each frame owns one path-local boundary/period list and advances through
    # its sorted _replay results one child at a time. Descending by appending a
    # frame preserves recursive DFS order without depending on Python's stack.
    stack = [{
        "state": start,
        "boundary_states": [start],
        "periods": [],
        "children": _replay(model, [(start, (start,), (), Fraction(0))], suffix,
                             abstract.precision),
        "next_child": 0,
    }]
    while stack:
        frame = stack[-1]
        if frame["next_child"] >= len(frame["children"]):
            stack.pop()
            continue

        next_state, states, edges, cost = frame["children"][frame["next_child"]]
        frame["next_child"] += 1
        period = (states, edges, cost)
        boundary_states = frame["boundary_states"]
        periods = frame["periods"]
        if next_state in boundary_states:
            index = boundary_states.index(next_state)
            normalized.append((index, len(periods) + 1 - index,
                               periods[:index], periods[index:] + [period]))
            continue

        child_boundary_states = boundary_states + [next_state]
        child_periods = periods + [period]
        stack.append({
            "state": next_state,
            "boundary_states": child_boundary_states,
            "periods": child_periods,
            "children": _replay(model, [(next_state, (next_state,), (), Fraction(0))],
                                 suffix, abstract.precision),
            "next_child": 0,
        })
    return sorted(normalized, key=lambda item: (item[0], item[1], item[2]))


def _append_path(states, edges, path_states, path_edges):
    if not path_states:
        return
    states.extend(path_states[1:])
    edges.extend(path_edges)
