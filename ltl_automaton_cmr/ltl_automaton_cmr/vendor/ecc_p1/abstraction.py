"""Deterministic optimistic TS projection with same-witness edge costs."""

from dataclasses import dataclass
from fractions import Fraction
import time
from typing import Any, FrozenSet, Iterable, Mapping, Optional, Tuple

from .model import (FormalActionSupport, FormalFactorizedModel, ProductState, State,
                    StateTransition)

AbstractState = Tuple[int, ...]
AbstractProductState = Tuple[AbstractState, str]

def project_state(state: State, precision: FrozenSet[int],
                  dimensions: Optional[Tuple[int, ...]] = None) -> AbstractState:
    """Project by authoritative dimension IDs while preserving their order."""
    positions = ({dimension: index for index, dimension in enumerate(dimensions)}
                 if dimensions is not None else {dimension: dimension for dimension in precision})
    unknown = set(precision) - set(positions)
    if unknown:
        raise ValueError(f"precision contains unknown dimensions: {sorted(unknown)}")
    return tuple(state[positions[index]] for index in sorted(precision))


def project_product(product: ProductState, precision: FrozenSet[int],
                    dimensions: Optional[Tuple[int, ...]] = None) -> AbstractProductState:
    state, q = product
    return (project_state(state, precision, dimensions), q)


@dataclass(frozen=True)
class AbstractTransition:
    source: AbstractProductState
    action: str
    target: AbstractProductState
    cost: Fraction
    witnesses: Tuple[StateTransition, ...]


@dataclass(frozen=True)
class OptimisticAbstractModel:
    precision: FrozenSet[int]
    states: Tuple[AbstractProductState, ...]
    initial_states: Tuple[AbstractProductState, ...]
    transitions: Tuple[AbstractTransition, ...]
    labels: Mapping[AbstractState, FrozenSet[str]]
    supports: Mapping[str, FormalActionSupport]
    accepting_buchi_states: FrozenSet[str]
    reachable_ts_states: Tuple[AbstractState, ...]
    provenance: str = "reachable TS existential projection; same-witness minimum cost; initial-label Product"
    reduced_ts_edge_count: int = 0

    def outgoing(self, source: AbstractProductState) -> Tuple[AbstractTransition, ...]:
        return tuple(edge for edge in self.transitions if edge.source == source)


def build_optimistic_abstraction(model: FormalFactorizedModel,
                                 precision: Iterable[int], *,
                                 timing: Optional[dict[str, Any]] = None) -> OptimisticAbstractModel:
    """Build T_S first, then its reachable initially consumed Buchi Product."""
    visible = frozenset(precision)
    if not visible.issubset(model.dimensions):
        raise ValueError("precision must be a subset of model dimensions")

    full_ts_started = time.perf_counter_ns()
    full_states, full_edges = _reachable_full_ts(model)
    full_ts_ended = time.perf_counter_ns()
    full_ts_time = full_ts_ended - full_ts_started
    reduction_started = time.perf_counter_ns()
    task_ap = model.task_propositions(full_states)
    if model.task_support:
        missing = task_ap - set(model.task_support)
        if missing:
            raise ValueError(f"task support is missing propositions: {sorted(missing)}")
        task_support = set().union(*(set(model.task_support[p]) for p in task_ap))
        if not task_support.issubset(visible):
            raise ValueError("task support is not contained in the requested precision")

    abstract_states = tuple(sorted({project_state(state, visible, model.dimensions)
                                    for state in full_states}))
    abstract_initial = tuple(sorted({project_state(state, visible, model.dimensions)
                                     for state in model.initial_states}))
    ts_buckets: dict[tuple[AbstractState, str, AbstractState], list[StateTransition]] = {}
    for transition in full_edges:
        key = (project_state(transition.source, visible, model.dimensions),
               transition.action,
               project_state(transition.target, visible, model.dimensions))
        ts_buckets.setdefault(key, []).append(transition)
    abstract_ts = []
    for key, witnesses in sorted(ts_buckets.items(), key=lambda item: item[0]):
        ordered = tuple(sorted(witnesses, key=lambda e: (e.cost, e.source, e.target, e.action)))
        abstract_ts.append((key[0], key[1], key[2], ordered[0].cost, ordered))

    labels: dict[AbstractState, FrozenSet[str]] = {}
    for abstract_state in abstract_states:
        bucket = [state for state in full_states
                  if project_state(state, visible, model.dimensions) == abstract_state]
        task_labels = {frozenset(model.label(state)) & task_ap for state in bucket}
        if len(task_labels) != 1:
            raise ValueError(f"task label disagreement in projected bucket {abstract_state}")
        labels[abstract_state] = next(iter(task_labels))

    ts_outgoing: dict[AbstractState, list[tuple[AbstractState, str, AbstractState, Fraction, tuple[StateTransition, ...]]]] = {}
    for abstract_edge in abstract_ts:
        ts_outgoing.setdefault(abstract_edge[0], []).append(abstract_edge)

    reduction_ended = time.perf_counter_ns()
    reduction_time = reduction_ended - reduction_started
    product_started = time.perf_counter_ns()

    initial_products = tuple(sorted(
        (state, buchi_state)
        for state in abstract_initial
        for buchi_state in set(model.buchi.transition(
            model.buchi.initial, labels[state]))
    ))
    product_states = set(initial_products)
    queue = list(initial_products)
    product_edges: list[AbstractTransition] = []
    while queue:
        source = queue.pop(0)
        for _, action, target_state, cost, witnesses in ts_outgoing.get(source[0], ()):
            next_buchi = tuple(sorted(set(model.buchi.transition(source[1], labels[target_state]))))
            for buchi_state in next_buchi:
                target = (target_state, buchi_state)
                product_edges.append(AbstractTransition(source, action, target, cost, witnesses))
                if target not in product_states:
                    product_states.add(target)
                    queue.append(target)

    result = OptimisticAbstractModel(
        precision=visible,
        states=tuple(sorted(product_states)),
        initial_states=tuple(sorted(initial_products)),
        transitions=tuple(sorted(product_edges, key=lambda e: (e.source, e.action, e.target, e.cost))),
        labels=labels,
        supports=model.supports(),
        accepting_buchi_states=model.buchi.accepting,
        reachable_ts_states=abstract_states,
        reduced_ts_edge_count=len(abstract_ts),
    )
    if timing is not None:
        product_ended = time.perf_counter_ns()
        timing["T_full_ts_ns"] = full_ts_time
        timing["T_reduction_ns"] = reduction_time
        timing["T_product_ns"] = product_ended - product_started
        timing["intervals_ns"] = {
            "T_full_ts": [full_ts_started, full_ts_ended],
            "T_reduction": [reduction_started, reduction_ended],
            "T_product": [product_started, product_ended],
        }
    return result


def _reachable_full_ts(model: FormalFactorizedModel) -> tuple[Tuple[State, ...], Tuple[StateTransition, ...]]:
    queue = list(sorted(model.initial_states))
    seen = set(queue)
    edges: list[StateTransition] = []
    while queue:
        source = queue.pop(0)
        for transition in model.state_transitions_from(source):
            edges.append(transition)
            if transition.target not in seen:
                seen.add(transition.target)
                queue.append(transition.target)
    return tuple(sorted(seen)), tuple(sorted(edges, key=lambda e: (e.source, e.action, e.target, e.cost)))
