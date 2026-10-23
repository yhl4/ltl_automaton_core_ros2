"""Bounded SCC/pruning variant of the isolated ROS2 lasso adapter."""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Callable

import networkx as nx

from experiments.cmr_ros2_smoke import backend as _base


GAMMA = Fraction(10, 1)


def _call(phase_call: Callable[..., Any], phase: str, function: Callable[..., Any], *args):
    return phase_call(phase, function, *args)


def _original_graph(ordered_nodes, rows, reachable):
    """Build the min-parallel-edge graph used only for SCC and lower bounds."""
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(reachable))
    for _, source, target, cost, _ in rows:
        if source not in reachable or target not in reachable:
            continue
        if graph.has_edge(source, target):
            graph[source][target]["weight"] = min(graph[source][target]["weight"], cost)
        else:
            graph.add_edge(source, target, weight=cost)
    return graph


def _qualifying_sccs(graph, accepting_ids):
    qualifying = []
    for component in nx.strongly_connected_components(graph):
        component = frozenset(component)
        if not component.intersection(accepting_ids):
            continue
        has_cycle = len(component) > 1 or any(
            node in component and graph.has_edge(node, node) for node in component
        )
        if has_cycle:
            qualifying.append(component)
    return tuple(sorted(qualifying, key=lambda item: tuple(sorted(item))))


def _component_rows(rows, component):
    return [row for row in rows if row[1] in component and row[2] in component]


def _suffix_candidate(abstract, ordered_nodes, component, rows, entry, accepting_ids,
                      phase_call, discrete_plan):
    local_rows = _component_rows(rows, component)
    if not local_rows:
        return None
    lifted_base, local_edges = _base._edge_node_graph(ordered_nodes, local_rows)
    lifted = _base._accepting_lift(lifted_base, local_edges, accepting_ids)
    all_lifted = set(lifted)
    start = (entry, entry in accepting_ids)
    finish = (entry, True)
    distances = _call(phase_call, "suffix", discrete_plan._component_distances,
                      lifted, start, all_lifted)
    best = None
    for predecessor, edge_data in lifted.pred[finish].items():
        if predecessor not in distances or predecessor == finish:
            continue
        closing = edge_data.get("weight", 1)
        if closing is None:
            continue
        suffix_cost = Fraction(distances[predecessor]) + _base._exact(closing)
        candidate = (suffix_cost, predecessor, distances)
        if best is None or suffix_cost < best[0]:
            best = candidate
    if best is None:
        return None
    suffix_cost, predecessor, distances = best
    suffix_path = _call(phase_call, "restore", discrete_plan._restore_tight_path,
                        lifted, distances, {start}, predecessor)
    suffix_path.append(finish)
    suffix, suffix_edges = _base._decode_lifted_path(suffix_path, ordered_nodes, local_edges)
    _base._validate_decoded(suffix, suffix_edges, require_nonempty=True)
    if suffix[0] != suffix[-1] or not any(state[1] in abstract.accepting_buchi_states
                                          for state in suffix):
        raise RuntimeError("suffix is not a non-empty accepting closed walk")
    if sum((_base._exact(edge.cost) for edge in suffix_edges), Fraction(0, 1)) != suffix_cost:
        raise RuntimeError("suffix cost differs from distance cost")
    return suffix_cost, suffix, suffix_edges


def solve_cmr_lasso(abstract: Any, work: dict[str, Any] | None = None,
                    phase_call: Callable[..., Any] | None = None):
    """Solve accepting lassos with SCC lower bounds and entry pruning."""
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
                 "exact_entry_searches": 0, "bound_pruned_entries": 0})
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
    base, edge_objects = _base._edge_node_graph(ordered_nodes, rows)
    accepting_ids = {node_id[state] for state in ordered_nodes
                     if state[1] in abstract.accepting_buchi_states}
    initial_ids = {node_id[state] for state in abstract.initial_states}
    prefix_distances = _call(phase_call, "prefix", discrete_plan._prefix_distances,
                             base, initial_ids)
    reachable = {node for node in prefix_distances if isinstance(node, int)
                 and node < len(ordered_nodes)}
    work["reachable_nodes"] = len(reachable)
    original = _original_graph(ordered_nodes, rows, reachable)
    work.update({"unique_original_nodes": original.number_of_nodes(),
                 "unique_original_edges": original.number_of_edges(),
                 "reachable_original_nodes": len(reachable),
                 "reachable_original_edges": original.number_of_edges()})
    qualifying = _qualifying_sccs(original, accepting_ids)
    work["qualifying_sccs"] = len(qualifying)
    entries = []
    for component_index, component in enumerate(qualifying):
        local = original.subgraph(component).copy()
        accepting_local = set(component).intersection(accepting_ids)
        reverse = local.reverse(copy=True)
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
        candidate = _suffix_candidate(
            abstract, ordered_nodes, qualifying[component_index], rows, entry,
            accepting_ids, phase_call, discrete_plan)
        if candidate is None:
            continue
        suffix_cost, suffix, suffix_edges = candidate
        objective = prefix_cost + GAMMA * suffix_cost
        if best is None or objective < best[0]:
            best = (objective, prefix_cost, suffix_cost)
            best_payload = (entry, suffix, suffix_edges)
    if best is None or best_payload is None:
        return None
    objective, prefix_cost, suffix_cost = best
    entry, suffix, suffix_edges = best_payload
    prefix_path = _call(phase_call, "restore", discrete_plan._restore_tight_path,
                        base, prefix_distances, initial_ids, entry)
    prefix, prefix_edges = _base._decode_path(prefix_path, ordered_nodes, edge_objects)
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
        provenance="ROS2 discrete_plan SCC lower-bound/pruning adapter",
    )


__all__ = ["GAMMA", "solve_cmr_lasso"]
