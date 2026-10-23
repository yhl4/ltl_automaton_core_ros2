"""V11 search adapter with solve-local exact Fraction reuse."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable
from fractions import Fraction

from experiments.cmr_ros2_bfull_reuse import backend as _v4
from experiments.cmr_ros2_real.bound_runner import _clone_function
from experiments.cmr_ros2_reduction_reuse import search as _v9
from experiments.cmr_ros2_search_entry import backend as _v7
from experiments.cmr_ros2_smoke import backend as _base
from experiments.cmr_ros2_suffix_reuse import search as _v10


def _exact_converter(work: dict[str, Any], reuse_exact: bool = True):
    """Return the original converter with only exact Fraction values short-circuited."""
    def convert(value: Any) -> Fraction:
        work["exact_cost_requests"] += 1
        if reuse_exact and type(value) is Fraction:
            work["exact_cost_reuses"] += 1
            return value
        work["exact_cost_fallbacks"] += 1
        return _base._exact(value)
    return convert


def _solver_with_local_base(*, work, reuse_witness, suffix_context, reuse_exact):
    exact = _exact_converter(work, reuse_exact)
    witness_cache: dict[int, tuple[tuple[Any, ...], tuple[Any, ...]]] = {}

    local_base = SimpleNamespace(**dict(vars(_base), _exact=exact))
    normalize = _clone_function(_v9._normalize_witnesses, {"_base": local_base})
    cached_rows = _clone_function(
        _v9._cached_edge_rows,
        {"_base": local_base, "_normalize_witnesses": normalize},
    )

    def edge_rows(abstract, node_id):
        return cached_rows(
            abstract, node_id, work=work, reuse_witness=reuse_witness,
            witness_cache=witness_cache,
        )

    local_base._edge_rows = edge_rows
    local_v4_solve = _clone_function(_v4.solve_cmr_lasso, {"_base": local_base})
    local_v4 = SimpleNamespace(
        solve_cmr_lasso=local_v4_solve,
        _suffix_graph=suffix_context.get,
    )
    return _clone_function(_v7.solve_cmr_lasso, {"v4": local_v4})


def solve_cmr_lasso(
    abstract,
    work: dict[str, Any] | None = None,
    phase_call: Callable[..., Any] | None = None,
    *,
    reuse_witness: bool = True,
    reuse_suffix: bool = True,
    reuse_exact: bool = True,
):
    """Run V10 search with a solve-local exact Fraction fast path."""
    if work is None:
        work = {}
    work.update({
        "witness_key_requests": 0,
        "witness_key_computations": 0,
        "witness_key_cache_hits": 0,
        "witness_items_normalized": 0,
        "suffix_graph_requests": 0,
        "suffix_graph_materializations": 0,
        "suffix_graph_reuses": 0,
        "suffix_graph_source_edge_scans": 0,
        "suffix_graph_source_edges_examined": 0,
        "suffix_graph_component_indexes": 0,
        "suffix_graph_dummy_rebinds": 0,
        "exact_cost_requests": 0,
        "exact_cost_reuses": 0,
        "exact_cost_fallbacks": 0,
    })
    if reuse_suffix:
        context = _v10.SuffixGraphContext(work)
        solver = _solver_with_local_base(
            work=work, reuse_witness=bool(reuse_witness),
            suffix_context=context, reuse_exact=bool(reuse_exact),
        )
    else:
        def direct_suffix(graph, component, entry, accepting_ids, local_work):
            del local_work
            work["suffix_graph_requests"] += 1
            work["suffix_graph_materializations"] += 1
            proxy = _v10._EdgeScanProxy(graph, work)
            return _v4._suffix_graph(proxy, component, entry, accepting_ids, work)

        context = None
        solver = _solver_with_local_base(
            work=work, reuse_witness=bool(reuse_witness),
            suffix_context=SimpleNamespace(get=direct_suffix),
            reuse_exact=bool(reuse_exact),
        )
    try:
        return solver(abstract, work=work, phase_call=phase_call)
    finally:
        if context is not None:
            context.graph = None
            context.accepting_ids = None
            context._cache.clear()
            context._component_indexes.clear()
            context._component_nodes.clear()


__all__ = ["_exact_converter", "solve_cmr_lasso"]
