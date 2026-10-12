"""Isolated CMR accepting-lasso adapter for the ROS2 distance helpers.

This is a research smoke prototype.  It does not change the ROS2 planner and
is not a replacement for the qualified CMR campaign solver.  Parallel abstract
transitions are represented by explicit edge nodes so that their action and
witness objects remain recoverable after a NetworkX distance search.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import networkx as nx


GAMMA = Fraction(10, 1)


def _canonical_nodes(abstract: Any) -> tuple[tuple[Any, Any], ...]:
    """Assign deterministic integer ids to every abstract Product state."""
    states = set(getattr(abstract, "states", ()))
    states.update(getattr(abstract, "initial_states", ()))
    for edge in getattr(abstract, "transitions", ()):
        states.add(edge.source)
        states.add(edge.target)
    return tuple(sorted((tuple(state), q) for state, q in states))


def _exact(value: Any) -> Fraction:
    """Use the qualified CMR conversion, rejecting bool/float costs."""
    from ecc_p1.model import exact_cost

    return exact_cost(value)


def _edge_rows(
    abstract: Any, node_id: dict[Any, int]
) -> list[tuple[Any, int, int, Fraction, Any]]:
    """Sort transitions with the same canonical key as the CMR solver."""
    rows = []
    for edge in getattr(abstract, "transitions", ()):
        cost = _exact(edge.cost)
        if cost < 0:
            raise ValueError("negative costs are outside the CMR smoke contract")
        witnesses = tuple(sorted(
            (tuple(w.source), w.action, tuple(w.target), _exact(w.cost))
            for w in edge.witnesses
        ))
        key = (node_id[edge.source], edge.action, node_id[edge.target], cost, witnesses)
        rows.append((key, node_id[edge.source], node_id[edge.target], cost, edge))
    rows.sort(key=lambda row: row[0])
    return rows


def _edge_node_graph(
    ordered_nodes: tuple[tuple[Any, Any], ...],
    rows: list[tuple[Any, int, int, Fraction, Any]],
) -> tuple[nx.DiGraph, dict[int, Any]]:
    """Build a simple graph whose edge nodes preserve parallel transitions."""
    graph = nx.DiGraph()
    graph.add_nodes_from(range(len(ordered_nodes) + len(rows)))
    edge_objects: dict[int, Any] = {}
    offset = len(ordered_nodes)
    for index, (_, source, target, cost, edge) in enumerate(rows):
        edge_node = offset + index
        edge_objects[edge_node] = edge
        graph.add_edge(source, edge_node, weight=cost)
        graph.add_edge(edge_node, target, weight=Fraction(0, 1))
    return graph, edge_objects


def _accepting_lift(
    base: nx.DiGraph,
    edge_objects: dict[int, Any],
    accepting_ids: set[int],
) -> nx.DiGraph:
    """Add a boolean acceptance-memory layer to the edge-node graph."""
    lifted = nx.DiGraph()
    for node in base:
        lifted.add_node((node, False))
        lifted.add_node((node, True))
    for edge_node in edge_objects:
        source = next(base.predecessors(edge_node))
        target = next(base.successors(edge_node))
        cost = base[source][edge_node]["weight"]
        for seen in (False, True):
            lifted.add_edge((source, seen), (edge_node, seen), weight=cost)
            next_seen = seen or target in accepting_ids
            lifted.add_edge((edge_node, seen), (target, next_seen), weight=Fraction(0, 1))
    return lifted


def _decode_path(
    path: list[Any], ordered_nodes: tuple[tuple[Any, Any], ...], edge_objects: dict[int, Any]
):
    """Decode original state ids and edge-node ids into object paths."""
    states = [
        ordered_nodes[item]
        for item in path
        if isinstance(item, int) and item < len(ordered_nodes)
    ]
    edges = [edge_objects[item] for item in path if isinstance(item, int) and item in edge_objects]
    return states, edges


def _decode_lifted_path(path: list[tuple[int, bool]], ordered_nodes, edge_objects):
    """Drop the acceptance flag before decoding a lifted path."""
    plain_path = [node for node, _ in path]
    return _decode_path(plain_path, ordered_nodes, edge_objects)


def _validate_decoded(states, edges, *, require_nonempty: bool) -> None:
    """Check decoded state/edge adjacency and optional non-empty requirement."""
    if (require_nonempty and len(edges) == 0) or len(states) != len(edges) + 1:
        raise RuntimeError("decoded lasso path is empty or structurally inconsistent")
    for source, edge, target in zip(states, edges, states[1:]):
        if edge.source != source or edge.target != target:
            raise RuntimeError("decoded abstract transition does not match its path")


def solve_cmr_lasso(abstract: Any):
    """Return a CMR-shaped lasso result using the ROS2 distance primitives.

    The search enumerates every prefix-reachable product entry, including
    non-accepting entries.  A two-layer ``seen_accept`` graph makes the suffix
    acceptance condition explicit while preserving the original transition
    objects and parallel action/witness arcs.
    """
    required = ("precision", "states", "initial_states", "transitions", "accepting_buchi_states")
    missing = [name for name in required if not hasattr(abstract, name)]
    if missing:
        raise TypeError(f"abstract is missing required fields: {missing}")

    from ltl_automaton_planner_core.ltl_tools import discrete_plan
    from ecc_p1.solver import AbstractLassoResult

    ordered_nodes = _canonical_nodes(abstract)
    if not ordered_nodes or not abstract.initial_states:
        return None
    node_id = {state: index for index, state in enumerate(ordered_nodes)}
    rows = _edge_rows(abstract, node_id)
    if not rows:
        return None

    base, edge_objects = _edge_node_graph(ordered_nodes, rows)
    accepting_ids = {
        node_id[state]
        for state in ordered_nodes
        if state[1] in abstract.accepting_buchi_states
    }
    initial_ids = {node_id[state] for state in abstract.initial_states}
    prefix_dist = discrete_plan._prefix_distances(base, initial_ids)
    lifted = _accepting_lift(base, edge_objects, accepting_ids)
    all_lifted = set(lifted)

    best = None
    for entry in sorted(prefix_dist):
        if entry >= len(ordered_nodes):
            continue
        start = (entry, entry in accepting_ids)
        finish = (entry, True)
        distances = discrete_plan._component_distances(lifted, start, all_lifted)
        for predecessor, edge_data in lifted.pred[finish].items():
            if predecessor not in distances or predecessor == finish:
                continue
            closing_weight = edge_data.get("weight", 1)
            if closing_weight is None:
                continue
            suffix_cost = Fraction(distances[predecessor]) + _exact(closing_weight)
            if suffix_cost < 0:
                raise ValueError("negative suffix cost")
            objective = Fraction(prefix_dist[entry]) + GAMMA * suffix_cost
            candidate = (
                objective, Fraction(prefix_dist[entry]), suffix_cost,
                entry, predecessor, distances,
            )
            if best is None or objective < best[0]:
                best = candidate

    if best is None:
        return None

    objective, prefix_cost, suffix_cost, entry, predecessor, distances = best
    prefix_lift = discrete_plan._restore_tight_path(base, prefix_dist, initial_ids, entry)
    suffix_lift = discrete_plan._restore_tight_path(lifted, distances, {(
        entry, entry in accepting_ids
    )}, predecessor)
    suffix_lift.append((entry, True))

    prefix, prefix_edges = _decode_path(prefix_lift, ordered_nodes, edge_objects)
    suffix, suffix_edges = _decode_lifted_path(suffix_lift, ordered_nodes, edge_objects)
    _validate_decoded(prefix, prefix_edges, require_nonempty=False)
    _validate_decoded(suffix, suffix_edges, require_nonempty=True)
    if suffix[0] != suffix[-1] or len(suffix_edges) < 1:
        raise RuntimeError("suffix must be a non-empty closed walk")

    accepting_states = tuple(sorted({
        state for state in suffix if state[1] in abstract.accepting_buchi_states
    }))
    if not accepting_states:
        raise RuntimeError("suffix did not visit an accepting product state")
    if sum((_exact(edge.cost) for edge in prefix_edges), Fraction(0, 1)) != prefix_cost:
        raise RuntimeError("decoded prefix cost differs from distance cost")
    if sum((_exact(edge.cost) for edge in suffix_edges), Fraction(0, 1)) != suffix_cost:
        raise RuntimeError("decoded suffix cost differs from distance cost")
    return AbstractLassoResult(
        status="ABSTRACT_OPTIMAL",
        precision=abstract.precision,
        prefix=tuple(prefix),
        suffix=tuple(suffix),
        prefix_edges=tuple(prefix_edges),
        suffix_edges=tuple(suffix_edges),
        prefix_cost=Fraction(prefix_cost),
        suffix_cost=Fraction(suffix_cost),
        lower_bound=Fraction(objective),
        accepting_product_states=accepting_states,
        provenance="ROS2 discrete_plan distance-helper CMR smoke adapter",
    )


__all__ = ["GAMMA", "solve_cmr_lasso"]
