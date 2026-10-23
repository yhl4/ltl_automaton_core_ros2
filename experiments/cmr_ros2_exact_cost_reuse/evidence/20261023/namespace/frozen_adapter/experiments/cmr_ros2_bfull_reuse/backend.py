"""Compact ROS2 lasso adapter with bounded graph/view reuse."""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Callable

import networkx as nx

from experiments.cmr_ros2_bfull_compact import backend as _v3
from experiments.cmr_ros2_smoke import backend as _base
from experiments.cmr_ros2_bfull_perf import backend as _v2


GAMMA = Fraction(10, 1)


def _call(phase_call, phase: str, function: Callable[..., Any], *args):
    return phase_call(phase, function, *args)


def _suffix_graph(graph, component, entry, accepting_ids, work):
    entry_accepting = entry in accepting_ids
    seen_layers = (True,) if entry_accepting else (False, True)
    lift = nx.DiGraph()
    for node in component:
        for seen in seen_layers:
            lift.add_node((node, seen))
    dummy = (-1, False)
    lift.add_node(dummy)
    for source, target, data in graph.edges(data=True):
        if source not in component or target not in component:
            continue
        for seen in seen_layers:
            next_seen = seen or target in accepting_ids
            if next_seen in seen_layers:
                lift.add_edge((source, seen), (target, next_seen),
                              weight=data["weight"])
    for target in graph.successors(entry):
        if target in component:
            next_seen = entry_accepting or target in accepting_ids
            lift.add_edge(dummy, (target, next_seen),
                          weight=graph[entry][target]["weight"])
    work.setdefault("suffix_lifts", []).append({
        "entry": entry, "entry_accepting": entry_accepting,
        "layers": len(seen_layers), "nodes": lift.number_of_nodes(),
        "edges": lift.number_of_edges(),
    })
    return lift, dummy, (entry, True)


def solve_cmr_lasso(abstract: Any, work: dict[str, Any] | None = None,
                    phase_call: Callable[..., Any] | None = None):
    """Solve accepting lassos with V3 semantics and controlled graph reuse."""
    required = ("precision", "states", "initial_states", "transitions",
                "accepting_buchi_states")
    missing = [name for name in required if not hasattr(abstract, name)]
    if missing:
        raise TypeError(f"abstract is missing required fields: {missing}")
    if work is None:
        work = {}
    if phase_call is None:
        phase_call = lambda _phase, function, *args: function(*args)
    work.update({"product_states_unique": 0, "reachable_nodes": 0,
                 "qualifying_sccs": 0, "candidate_entries": 0,
                 "exact_entry_searches": 0, "bound_pruned_entries": 0,
                 "graph_reuses": 0, "subgraph_copies": 0, "reverse_views": 0,
                 "suffix_lifts": []})
    from ecc_p1.solver import AbstractLassoResult
    from ltl_automaton_planner_core.ltl_tools import discrete_plan

    ordered_nodes = _base._canonical_nodes(abstract)
    work["product_states_unique"] = len(ordered_nodes)
    if not ordered_nodes or not abstract.initial_states:
        return None
    node_id = {state: index for index, state in enumerate(ordered_nodes)}
    rows = _base._edge_rows(abstract, node_id)
    if not rows:
        return None
    graph, arc_objects = _v3._compact_graph(ordered_nodes, rows)
    accepting_ids = {node_id[state] for state in ordered_nodes
                     if state[1] in abstract.accepting_buchi_states}
    initial_ids = {node_id[state] for state in abstract.initial_states}
    prefix_distances = _call(phase_call, "prefix", discrete_plan._prefix_distances,
                             graph, initial_ids)
    reachable = {node for node in prefix_distances if isinstance(node, int)}
    work["reachable_nodes"] = len(reachable)
    if reachable == set(graph.nodes):
        local_graph = graph
        work["graph_reuses"] += 1
    else:
        local_graph = graph.subgraph(reachable).copy()
        work["subgraph_copies"] += 1
    work["unique_original_nodes"] = local_graph.number_of_nodes()
    work["unique_original_edges"] = local_graph.number_of_edges()
    work["reachable_original_nodes"] = local_graph.number_of_nodes()
    work["reachable_original_edges"] = local_graph.number_of_edges()
    qualifying = _v2._qualifying_sccs(local_graph, accepting_ids)
    work["qualifying_sccs"] = len(qualifying)
    entries = []
    for component_index, component in enumerate(qualifying):
        if set(component) == set(local_graph.nodes):
            local = local_graph
            work["graph_reuses"] += 1
        else:
            local = local_graph.subgraph(component).copy()
            work["subgraph_copies"] += 1
        accepting_local = set(component).intersection(accepting_ids)
        reverse = local.reverse(copy=False)
        work["reverse_views"] += 1
        to_accept = _call(phase_call, "lower_bound", discrete_plan._prefix_distances,
                          reverse, accepting_local)
        from_accept = _call(phase_call, "lower_bound", discrete_plan._prefix_distances,
                            local, accepting_local)
        for entry in sorted(component):
            if entry not in prefix_distances or entry not in to_accept or entry not in from_accept:
                continue
            outgoing = [data["weight"] for _, target, data in local.out_edges(entry, data=True)
                        if target in component]
            if not outgoing:
                continue
            cycle_lb = max(Fraction(to_accept[entry]) + Fraction(from_accept[entry]),
                           min(map(Fraction, outgoing)))
            entry_lb = Fraction(prefix_distances[entry]) + GAMMA * cycle_lb
            entries.append((entry_lb, Fraction(prefix_distances[entry]), entry, component_index))
    entries.sort(key=lambda row: (row[0], row[1], row[2]))
    work["candidate_entries"] = len(entries)
    best = None
    best_payload = None
    for index, (entry_lb, prefix_cost, entry, component_index) in enumerate(entries):
        if best is not None and entry_lb >= best[0]:
            work["bound_pruned_entries"] += len(entries) - index
            break
        work["exact_entry_searches"] += 1
        lift, dummy, finish = _suffix_graph(
            local_graph, qualifying[component_index], entry, accepting_ids, work)
        distances = _call(phase_call, "suffix", discrete_plan._component_distances,
                          lift, dummy, set(lift))
        if finish not in distances:
            continue
        suffix_path = _call(phase_call, "restore", discrete_plan._restore_tight_path,
                            lift, distances, {dummy}, finish)
        suffix_cost = Fraction(distances[finish])
        suffix, suffix_edges = _v3._decode_suffix(
            suffix_path, ordered_nodes, arc_objects, entry)
        _base._validate_decoded(suffix, suffix_edges, require_nonempty=True)
        if suffix[0] != suffix[-1] or not any(
                state[1] in abstract.accepting_buchi_states for state in suffix):
            raise RuntimeError("suffix is not a non-empty accepting closed walk")
        if sum((_base._exact(edge.cost) for edge in suffix_edges), Fraction(0, 1)) != suffix_cost:
            raise RuntimeError("suffix cost differs from distance cost")
        objective = prefix_cost + GAMMA * suffix_cost
        if best is None or objective < best[0]:
            best = (objective, prefix_cost, suffix_cost)
            best_payload = (entry, suffix, suffix_edges)
    if best is None or best_payload is None:
        return None
    objective, prefix_cost, suffix_cost = best
    entry, suffix, suffix_edges = best_payload
    prefix_path = _call(phase_call, "restore", discrete_plan._restore_tight_path,
                        graph, prefix_distances, initial_ids, entry)
    prefix, prefix_edges = _v3._prefix_edges(prefix_path, ordered_nodes, arc_objects)
    _base._validate_decoded(prefix, prefix_edges, require_nonempty=False)
    if sum((_base._exact(edge.cost) for edge in prefix_edges), Fraction(0, 1)) != prefix_cost:
        raise RuntimeError("prefix cost differs from distance cost")
    accepting_states = tuple(sorted({state for state in suffix
                                     if state[1] in abstract.accepting_buchi_states}))
    if not accepting_states:
        raise RuntimeError("suffix did not visit an accepting Product state")
    return AbstractLassoResult(
        status="ABSTRACT_OPTIMAL", precision=abstract.precision,
        prefix=tuple(prefix), suffix=tuple(suffix),
        prefix_edges=tuple(prefix_edges), suffix_edges=tuple(suffix_edges),
        prefix_cost=Fraction(prefix_cost), suffix_cost=Fraction(suffix_cost),
        lower_bound=Fraction(objective), accepting_product_states=accepting_states,
        provenance="ROS2 discrete_plan compact graph-reuse adapter",
    )


__all__ = ["GAMMA", "solve_cmr_lasso"]
