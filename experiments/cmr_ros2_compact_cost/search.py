"""V12 compact-graph integer scalarization before duplicate-arc comparison."""

from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace
from typing import Any, Callable

import networkx as nx

from experiments.cmr_ros2_bfull_reuse import backend as v4
from experiments.cmr_ros2_bfull_target import backend as v5
from experiments.cmr_ros2_bfull_compact import backend as v3
from experiments.cmr_ros2_exact_cost_reuse import search as _v11
from experiments.cmr_ros2_real.bound_runner import _clone_function


def _compact_graph(ordered_nodes, rows, work, scalarize):
    """Build the original compact graph, optionally scalarizing exact integers early."""
    graph = nx.DiGraph()
    graph.add_nodes_from(range(len(ordered_nodes)))
    arc_objects = {}
    for _, source, target, cost, edge in rows:
        work["compact_cost_requests"] += 1
        if scalarize and isinstance(cost, Fraction) and cost.denominator == 1:
            cost = cost.numerator
            work["compact_cost_scalarized_before_insert"] += 1
        key = (source, target)
        if key not in arc_objects:
            graph.add_edge(source, target, weight=cost)
            arc_objects[key] = edge
        else:
            work["compact_cost_comparisons"] += 1
            if cost < graph[source][target]["weight"]:
                graph.add_edge(source, target, weight=cost)
                arc_objects[key] = edge

    for _, _, data in graph.edges(data=True):
        cost = data["weight"]
        if isinstance(cost, Fraction) and cost.denominator == 1:
            data["weight"] = cost.numerator
            work["integer_weight_edges"] += 1
        elif type(cost) is int:
            work["integer_weight_edges"] += 1
        else:
            work["fractional_weight_edges"] += 1
    return graph, arc_objects


def _scalar_solve(
    abstract,
    work: dict[str, Any] | None = None,
    phase_call: Callable[..., Any] | None = None,
    *,
    scalarize: bool = True,
):
    """V7's small clone skeleton with a solve-local compact graph closure."""
    if work is None:
        work = {}
    work.update(integer_weight_edges=0, fractional_weight_edges=0,
                compact_cost_requests=0, compact_cost_scalarized_before_insert=0,
                compact_cost_comparisons=0)

    def compact_graph(ordered_nodes, rows):
        return _compact_graph(ordered_nodes, rows, work, bool(scalarize))

    compact = SimpleNamespace(**dict(vars(v3), _compact_graph=compact_graph))
    reused = _clone_function(v4.solve_cmr_lasso, {"_v3": compact})
    target_globals = SimpleNamespace(
        solve_cmr_lasso=reused, _suffix_graph=v4._suffix_graph)
    target = _clone_function(v5.solve_cmr_lasso, {"_v4": target_globals})
    return target(abstract, work=work, phase_call=phase_call)


def _solver_factory(scalarize):
    scalar_solve = _clone_function(_scalar_solve, {})
    kwdefaults = dict(scalar_solve.__kwdefaults__ or {})
    kwdefaults["scalarize"] = bool(scalarize)
    scalar_solve.__kwdefaults__ = kwdefaults
    local_v7 = SimpleNamespace(solve_cmr_lasso=scalar_solve)
    return _clone_function(
        _v11._solver_with_local_base, {"_v7": local_v7})


def solve_cmr_lasso(
    abstract,
    work: dict[str, Any] | None = None,
    phase_call: Callable[..., Any] | None = None,
    *,
    scalarize: bool = True,
    reuse_exact: bool = True,
    reuse_suffix: bool = True,
    reuse_witness: bool = True,
):
    """Run V11 search with optional early integer scalarization."""
    if work is None:
        work = {}
    work.update(compact_cost_requests=0,
                compact_cost_scalarized_before_insert=0,
                compact_cost_comparisons=0)

    local_solve = _clone_function(
        _v11.solve_cmr_lasso,
        {"_solver_with_local_base": _solver_factory(scalarize)},
    )
    return local_solve(
        abstract, work=work, phase_call=phase_call,
        reuse_exact=reuse_exact, reuse_suffix=reuse_suffix,
        reuse_witness=reuse_witness,
    )


__all__ = ["_compact_graph", "solve_cmr_lasso"]
