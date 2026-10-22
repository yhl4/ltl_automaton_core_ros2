"""V9 search adapter with a solve-local witness-key cache."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from experiments.cmr_ros2_bfull_reuse import backend as _v4
from experiments.cmr_ros2_real.bound_runner import _clone_function
from experiments.cmr_ros2_search_entry import backend as _v7
from experiments.cmr_ros2_smoke import backend as _base


def _normalize_witnesses(witnesses):
    """Keep the frozen witness normalization and sort key unchanged."""
    return tuple(sorted(
        (tuple(w.source), w.action, tuple(w.target), _base._exact(w.cost))
        for w in witnesses
    ))


def _cached_edge_rows(
    abstract: Any,
    node_id: dict[Any, int],
    *,
    work: dict[str, Any],
    reuse_witness: bool,
    witness_cache: dict[int, tuple[tuple[Any, ...], tuple[Any, ...]]],
):
    """Reproduce the base row builder with identity-safe witness memoization."""
    rows = []
    for edge in getattr(abstract, "transitions", ()):
        cost = _base._exact(edge.cost)
        if cost < 0:
            raise ValueError("negative costs are outside the CMR smoke contract")

        raw_witnesses = edge.witnesses
        work["witness_key_requests"] += 1
        normalized = None
        if reuse_witness and type(raw_witnesses) is tuple:
            token = id(raw_witnesses)
            cached = witness_cache.get(token)
            if cached is not None and cached[0] is raw_witnesses:
                normalized = cached[1]
                work["witness_key_cache_hits"] += 1
        if normalized is None:
            normalized = _normalize_witnesses(raw_witnesses)
            work["witness_key_computations"] += 1
            work["witness_items_normalized"] += len(normalized)
            if reuse_witness and type(raw_witnesses) is tuple:
                # Keep the tuple itself strongly referenced to prevent id reuse.
                witness_cache[id(raw_witnesses)] = (raw_witnesses, normalized)

        key = (
            node_id[edge.source],
            edge.action,
            node_id[edge.target],
            cost,
            normalized,
        )
        rows.append((key, node_id[edge.source], node_id[edge.target], cost, edge))
    rows.sort(key=lambda row: row[0])
    return rows


def _solver_with_local_base(
    *,
    work: dict[str, Any],
    reuse_witness: bool,
):
    witness_cache: dict[int, tuple[tuple[Any, ...], tuple[Any, ...]]] = {}

    def edge_rows(abstract, node_id):
        return _cached_edge_rows(
            abstract,
            node_id,
            work=work,
            reuse_witness=reuse_witness,
            witness_cache=witness_cache,
        )

    base_globals = dict(vars(_base))
    base_globals["_edge_rows"] = edge_rows
    local_base = SimpleNamespace(**base_globals)
    local_v4_solve = _clone_function(
        _v4.solve_cmr_lasso,
        {"_base": local_base},
    )
    local_v4 = SimpleNamespace(
        solve_cmr_lasso=local_v4_solve,
        _suffix_graph=_v4._suffix_graph,
    )
    return _clone_function(_v7.solve_cmr_lasso, {"v4": local_v4})


def solve_cmr_lasso(
    abstract,
    work: dict[str, Any] | None = None,
    phase_call: Callable[..., Any] | None = None,
    *,
    reuse_witness: bool = True,
):
    """Run the V7 solver with a cache scoped to this solve only."""
    if work is None:
        work = {}
    work.update({
        "witness_key_requests": 0,
        "witness_key_computations": 0,
        "witness_key_cache_hits": 0,
        "witness_items_normalized": 0,
    })
    solver = _solver_with_local_base(
        work=work,
        reuse_witness=bool(reuse_witness),
    )
    return solver(abstract, work=work, phase_call=phase_call)


__all__ = ["solve_cmr_lasso"]
