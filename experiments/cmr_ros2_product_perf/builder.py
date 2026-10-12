"""Product-builder V6: local Buchi successor memoization and FIFO traversal.

The reduction and full-transition-system construction intentionally follow the
authority builder.  The only Product changes are a per-build successor cache
and ``deque`` FIFO scheduling; no cache is shared between builds.
"""

import time
from collections import deque
from fractions import Fraction
from typing import Any, FrozenSet, Iterable, Optional

from ecc_p1.model import FormalFactorizedModel, StateTransition
from ecc_p1.abstraction import (
    AbstractState,
    AbstractTransition,
    OptimisticAbstractModel,
    project_state,
    _reachable_full_ts,
)


def build_optimistic_abstraction(
    model: FormalFactorizedModel,
    precision: Iterable[int],
    *,
    timing: Optional[dict[str, Any]] = None,
    work: Optional[dict[str, Any]] = None,
) -> OptimisticAbstractModel:
    """Build the grouped abstraction with a local Buchi successor cache."""
    visible = frozenset(precision)
    if not visible.issubset(model.dimensions):
        raise ValueError("precision must be a subset of model dimensions")

    if work is None:
        work = {}
    work.update({
        "precision": sorted(visible),
        "completed": False,
        "full_ts_rebuild_calls": 0,
        "buchi_queries": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "cache_entries": 0,
        "product_states": 0,
        "product_edges": 0,
        "reachable_ts_states": 0,
        "reduced_ts_edges": 0,
    })

    full_ts_started = time.perf_counter_ns()
    full_states, full_edges = _reachable_full_ts(model)
    full_ts_ended = time.perf_counter_ns()
    # Keep the bookkeeping outside the authority full-TS timing interval.
    work["full_ts_rebuild_calls"] += 1
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

    # Each reachable full state is checked once. Preserve the task-label
    # consistency guard even when declared support metadata is incorrect.
    labels: dict[AbstractState, FrozenSet[str]] = {}
    disagreements = set()
    for state in full_states:
        abstract_state = project_state(state, visible, model.dimensions)
        task_label = frozenset(model.label(state)) & task_ap
        if abstract_state in labels and labels[abstract_state] != task_label:
            disagreements.add(abstract_state)
        else:
            labels[abstract_state] = task_label
    if disagreements:
        raise ValueError(f"task label disagreement in projected bucket {min(disagreements)}")
    labels = {state: labels[state] for state in abstract_states}

    ts_outgoing: dict[AbstractState, list[tuple[AbstractState, str, AbstractState, Fraction, tuple[StateTransition, ...]]]] = {}
    for abstract_edge in abstract_ts:
        ts_outgoing.setdefault(abstract_edge[0], []).append(abstract_edge)

    reduction_ended = time.perf_counter_ns()
    reduction_time = reduction_ended - reduction_started
    work["reachable_ts_states"] = len(abstract_states)
    work["reduced_ts_edges"] = len(abstract_ts)
    product_started = time.perf_counter_ns()

    buchi_cache: dict[tuple[Any, FrozenSet[str]], tuple[Any, ...]] = {}

    def buchi_successors(state: Any, label: FrozenSet[str]) -> tuple[Any, ...]:
        normalized = frozenset(label)
        key = (state, normalized)
        work["buchi_queries"] += 1
        if key in buchi_cache:
            work["cache_hits"] += 1
            return buchi_cache[key]
        work["cache_misses"] += 1
        successors = tuple(sorted(set(model.buchi.transition(state, normalized))))
        buchi_cache[key] = successors
        work["cache_entries"] = len(buchi_cache)
        return successors

    initial_products = tuple(sorted(
        (state, buchi_state)
        for state in abstract_initial
        for buchi_state in buchi_successors(
            model.buchi.initial, labels[state])
    ))
    product_states = set(initial_products)
    queue = deque(initial_products)
    product_edges: list[AbstractTransition] = []
    while queue:
        source = queue.popleft()
        for _, action, target_state, cost, witnesses in ts_outgoing.get(source[0], ()):
            next_buchi = buchi_successors(source[1], labels[target_state])
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
    work["product_states"] = len(product_states)
    work["product_edges"] = len(product_edges)
    work["completed"] = True
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
