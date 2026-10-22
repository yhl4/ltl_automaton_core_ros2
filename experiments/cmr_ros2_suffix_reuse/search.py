"""V10 solve-local reuse of the accepting suffix lift."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

import networkx as nx

from experiments.cmr_ros2_bfull_reuse import backend as _v4
from experiments.cmr_ros2_real.bound_runner import _clone_function
from experiments.cmr_ros2_reduction_reuse import search as _v9
from experiments.cmr_ros2_search_entry import backend as _v7
from experiments.cmr_ros2_smoke import backend as _base


class _EdgeScanProxy:
    """Forward the V4 graph surface while counting the real edge iteration."""

    def __init__(self, graph, work):
        self._graph = graph
        self._work = work

    def edges(self, *args, **kwargs):
        self._work["suffix_graph_source_edge_scans"] += 1
        for edge in self._graph.edges(*args, **kwargs):
            self._work["suffix_graph_source_edges_examined"] += 1
            yield edge

    def successors(self, node):
        return self._graph.successors(node)

    def __getitem__(self, node):
        return self._graph[node]


class SuffixGraphContext:
    """Cache only accepting lift materialization for one solver invocation."""

    def __init__(self, work: dict[str, Any]):
        self.work = work
        self.graph = None
        self.accepting_ids: frozenset[Any] | None = None
        self._component_indexes: dict[frozenset[Any], tuple[Any, ...]] = {}
        self._component_nodes: dict[frozenset[Any], tuple[Any, ...]] = {}
        self._cache: dict[tuple[frozenset[Any], bool], tuple[nx.DiGraph, Any, Any]] = {}

    def _bind(self, graph, accepting_ids):
        accepting = frozenset(accepting_ids)
        if self.graph is None:
            self.graph = graph
            self.accepting_ids = accepting
            return accepting
        if graph is not self.graph or accepting != self.accepting_ids:
            raise ValueError("suffix graph context cannot cross graph or accepting-set identity")
        return accepting

    def _index(self, graph, component_key):
        if component_key in self._component_indexes:
            return self._component_indexes[component_key]
        component_nodes = tuple(component_key)
        rows = []
        self.work["suffix_graph_source_edge_scans"] += 1
        for source, target, data in graph.edges(data=True):
            self.work["suffix_graph_source_edges_examined"] += 1
            if source in component_key and target in component_key:
                rows.append((source, target, data["weight"]))
        # Publish the component index only after the complete scan succeeds.
        rows = tuple(rows)
        self._component_nodes[component_key] = component_nodes
        self._component_indexes[component_key] = rows
        self.work["suffix_graph_component_indexes"] += 1
        return rows

    def _append_lift_record(self, entry, entry_accepting, lift):
        self.work.setdefault("suffix_lifts", []).append({
            "entry": entry,
            "entry_accepting": entry_accepting,
            "layers": 1 if entry_accepting else 2,
            "nodes": lift.number_of_nodes(),
            "edges": lift.number_of_edges(),
        })

    def _materialize(self, graph, component_key, entry, accepting, rows):
        self.work["suffix_graph_materializations"] += 1
        entry_accepting = entry in accepting
        seen_layers = (True,) if entry_accepting else (False, True)
        lift = nx.DiGraph()
        for node in self._component_nodes[component_key]:
            for seen in seen_layers:
                lift.add_node((node, seen))
        dummy = (-1, False)
        lift.add_node(dummy)
        for source, target, weight in rows:
            for seen in seen_layers:
                next_seen = seen or target in accepting
                if next_seen in seen_layers:
                    lift.add_edge((source, seen), (target, next_seen), weight=weight)
        for target in graph.successors(entry):
            if target in component_key:
                next_seen = entry_accepting or target in accepting
                lift.add_edge(dummy, (target, next_seen),
                              weight=graph[entry][target]["weight"])
        self._append_lift_record(entry, entry_accepting, lift)
        return lift, dummy, (entry, True)

    def _rebind_dummy(self, lift, graph, component_key, entry, accepting):
        dummy = (-1, False)
        predecessors = tuple(lift.predecessors(dummy))
        if predecessors:
            raise ValueError("cached suffix dummy unexpectedly has incoming edges")
        for successor in tuple(lift.successors(dummy)):
            lift.remove_edge(dummy, successor)
        for target in graph.successors(entry):
            if target in component_key:
                next_seen = entry in accepting or target in accepting
                lift.add_edge(dummy, (target, next_seen),
                              weight=graph[entry][target]["weight"])
        self.work["suffix_graph_dummy_rebinds"] += 1
        self._append_lift_record(entry, entry in accepting, lift)
        return lift, dummy, (entry, True)

    def get(self, graph, component, entry, accepting_ids, work=None):
        del work
        self.work["suffix_graph_requests"] += 1
        accepting = self._bind(graph, accepting_ids)
        component_key = frozenset(component)
        key = (component_key, entry in accepting)
        cached = self._cache.get(key)
        if cached is not None:
            self.work["suffix_graph_reuses"] += 1
            return self._rebind_dummy(cached[0], graph, component_key, entry, accepting)
        rows = self._index(graph, component_key)
        try:
            value = self._materialize(graph, component_key, entry, accepting, rows)
        except Exception:
            # Do not publish a partially built graph or cache entry; a completed index remains valid.
            self._cache.pop(key, None)
            raise
        self._cache[key] = value
        return value


def _solver_with_local_base(*, work, reuse_witness, suffix_context):
    witness_cache: dict[int, tuple[tuple[Any, ...], tuple[Any, ...]]] = {}

    def edge_rows(abstract, node_id):
        return _v9._cached_edge_rows(
            abstract, node_id, work=work, reuse_witness=reuse_witness,
            witness_cache=witness_cache,
        )

    base_globals = dict(vars(_base))
    base_globals["_edge_rows"] = edge_rows
    local_base = SimpleNamespace(**base_globals)
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
):
    """Run V9 search with accepting-lift reuse scoped to this solve."""
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
    })
    if reuse_suffix:
        context = SuffixGraphContext(work)
        solver = _solver_with_local_base(
            work=work, reuse_witness=bool(reuse_witness), suffix_context=context,
        )
    else:
        def direct_suffix(graph, component, entry, accepting_ids, local_work):
            work["suffix_graph_requests"] += 1
            work["suffix_graph_materializations"] += 1
            proxy = _EdgeScanProxy(graph, work)
            return _v4._suffix_graph(proxy, component, entry, accepting_ids, local_work)

        context = None
        solver = _solver_with_local_base(
            work=work, reuse_witness=bool(reuse_witness),
            suffix_context=SimpleNamespace(get=direct_suffix),
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


__all__ = ["SuffixGraphContext", "solve_cmr_lasso"]
