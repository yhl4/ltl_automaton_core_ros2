"""Exact accepting-lasso search over a finite abstract product graph."""

from dataclasses import dataclass
from fractions import Fraction
import heapq
from typing import Optional, Tuple

from .abstraction import AbstractProductState, AbstractTransition, OptimisticAbstractModel
from .model import exact_cost

GAMMA = Fraction(10, 1)


@dataclass
class SearchStats:
    """Optional counters; cumulative work is distinct from unique graph size."""
    expanded_states: int = 0
    shortest_path_calls: int = 0
    queue_pushes: int = 0
    queue_pops: int = 0
    prefix_expansions: int = 0
    suffix_expansions: int = 0
    prefix_settled: int = 0
    lower_bound_settled: int = 0
    suffix_settled: int = 0
    reachable_nodes: int = 0
    product_states_unique: int = 0
    qualifying_sccs: int = 0
    candidate_entries: int = 0
    exact_entry_searches: int = 0
    bound_pruned_entries: int = 0


@dataclass(frozen=True)
class AbstractLassoResult:
    status: str
    precision: frozenset[int]
    prefix: Tuple[AbstractProductState, ...]
    suffix: Tuple[AbstractProductState, ...]
    prefix_edges: Tuple[AbstractTransition, ...]
    suffix_edges: Tuple[AbstractTransition, ...]
    prefix_cost: Fraction
    suffix_cost: Fraction
    lower_bound: Fraction
    accepting_product_states: Tuple[AbstractProductState, ...]
    provenance: str = "exact finite abstract product search"

    @property
    def identity(self) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        return (tuple(edge.action for edge in self.prefix_edges), tuple(edge.action for edge in self.suffix_edges))


def solve_exact_abstract_lasso(abstract: OptimisticAbstractModel,
                               stats: Optional[SearchStats] = None,
                               *, prune: bool = True) -> Optional[AbstractLassoResult]:
    """Return a minimum-cost non-empty accepting lasso, or ``None``.

    The objective is ``prefix_cost + GAMMA * suffix_cost``. Product states
    and parallel transition objects are kept distinct. Equal-cost paths keep
    the first path induced by the canonical node, edge, and heap order.
    """
    if stats is None:
        stats = SearchStats()

    states = set(abstract.states)
    states.update(abstract.initial_states)
    for edge in abstract.transitions:
        states.add(edge.source)
        states.add(edge.target)
    ordered_nodes = tuple(sorted((tuple(state), q) for state, q in states))
    node_id = {state: index for index, state in enumerate(ordered_nodes)}
    stats.product_states_unique = len(ordered_nodes)

    # Materialize once. The original transition object is retained for exact
    # witness reconstruction, including distinct actions on parallel arcs.
    edge_rows = []
    for edge in abstract.transitions:
        cost = exact_cost(edge.cost)
        if cost < 0:
            raise ValueError("negative costs are outside the ECC-P1 contract")
        witnesses = tuple(sorted((tuple(w.source), w.action, tuple(w.target), exact_cost(w.cost))
                                 for w in edge.witnesses))
        key = (node_id[edge.source], edge.action, node_id[edge.target], cost, witnesses)
        edge_rows.append((key, node_id[edge.source], node_id[edge.target], cost, edge))
    edge_rows.sort(key=lambda row: row[0])

    forward = [[] for _ in ordered_nodes]
    reverse = [[] for _ in ordered_nodes]
    neighbors = [set() for _ in ordered_nodes]
    reverse_neighbors = [set() for _ in ordered_nodes]
    for _, source, target, cost, edge in edge_rows:
        forward[source].append((target, cost, edge))
        reverse[target].append((source, cost, edge))
        neighbors[source].add(target)
        reverse_neighbors[target].add(source)
    forward_neighbors = tuple(tuple(sorted(row)) for row in neighbors)
    reverse_neighbors = tuple(tuple(sorted(row)) for row in reverse_neighbors)

    initial_ids = tuple(sorted({node_id[state] for state in abstract.initial_states}))
    if not initial_ids:
        return None
    reachable = set(initial_ids)
    stack = list(reversed(initial_ids))
    while stack:
        source = stack.pop()
        for target in forward_neighbors[source]:
            if target not in reachable:
                reachable.add(target)
                stack.append(target)
    stats.reachable_nodes = len(reachable)

    components = _iterative_kosaraju(reachable, forward_neighbors, reverse_neighbors)
    accepting = abstract.accepting_buchi_states
    qualifying = []
    for component in components:
        has_accepting = any(ordered_nodes[item][1] in accepting for item in component)
        has_cycle = (len(component) > 1 or any(target == component[0]
                                                for target, _, _ in forward[component[0]]))
        if has_accepting and has_cycle:
            qualifying.append(component)
    stats.qualifying_sccs = len(qualifying)
    if not qualifying:
        return None

    distances, roots, parents = _multi_source_dijkstra(initial_ids, forward, stats, "prefix")
    entries = []
    for component_index, component in enumerate(qualifying):
        component_set = set(component)
        accepting_sources = tuple(sorted(item for item in component
                                          if ordered_nodes[item][1] in accepting))
        if prune:
            local_forward = {item: tuple(row for row in forward[item] if row[0] in component_set)
                             for item in component}
            local_reverse = {item: tuple(row for row in reverse[item] if row[0] in component_set)
                             for item in component}
            to_accepting = _multi_source_dijkstra(accepting_sources, local_reverse, stats, "lower_bound")[0]
            from_accepting = _multi_source_dijkstra(accepting_sources, local_forward, stats, "lower_bound")[0]
        else:
            to_accepting = from_accepting = {}

        for item in component:
            if item not in distances:
                continue
            if prune:
                out_cost = min(cost for target, cost, _ in forward[item] if target in component_set)
                cycle_lb = max(to_accepting[item] + from_accepting[item], out_cost)
                entry_lb = distances[item] + GAMMA * cycle_lb
            else:
                entry_lb = distances[item]
            entries.append((entry_lb, distances[item], item, component_index))
    entries.sort(key=lambda row: (row[0], row[1], row[2]))
    stats.candidate_entries = len(entries)
    if not entries:
        return None

    best = None
    index = 0
    while index < len(entries):
        entry_lb, prefix_cost, entry, component_index = entries[index]
        if prune and best is not None and entry_lb >= best[0]:
            stats.bound_pruned_entries += len(entries) - index
            break

        stats.exact_entry_searches += 1
        suffix = _shortest_accepting_closed_walk(entry, qualifying[component_index],
                                                 ordered_nodes, node_id, forward, accepting, stats)
        if suffix is not None:
            suffix_ids, suffix_edges, suffix_cost = suffix
            objective = prefix_cost + GAMMA * suffix_cost
            if best is None or objective < best[0]:
                prefix_ids, prefix_edges = _reconstruct_prefix(entry, roots, parents)
                accepting_nodes = tuple(sorted({ordered_nodes[item] for item in suffix_ids
                                                if ordered_nodes[item][1] in accepting}))
                best = (objective, prefix_cost, suffix_cost, prefix_ids, suffix_ids,
                        prefix_edges, suffix_edges, accepting_nodes, entry)
        index += 1

    if best is None:
        return None
    return AbstractLassoResult(
        status="ABSTRACT_OPTIMAL",
        precision=abstract.precision,
        prefix=tuple(ordered_nodes[item] for item in best[3]),
        suffix=tuple(ordered_nodes[item] for item in best[4]),
        prefix_edges=tuple(best[5]),
        suffix_edges=tuple(best[6]),
        prefix_cost=best[1],
        suffix_cost=best[2],
        lower_bound=best[0],
        accepting_product_states=best[7],
    )


def _iterative_kosaraju(reachable, forward_neighbors, reverse_neighbors):
    """Return deterministic SCCs using iterative Kosaraju DFS passes."""
    seen = set()
    finish = []
    for start in sorted(reachable):
        if start in seen:
            continue
        seen.add(start)
        frames = [(start, 0)]
        while frames:
            source, offset = frames[-1]
            row = forward_neighbors[source]
            if offset < len(row):
                target = row[offset]
                frames[-1] = (source, offset + 1)
                if target in reachable and target not in seen:
                    seen.add(target)
                    frames.append((target, 0))
            else:
                finish.append(source)
                frames.pop()

    assigned = set()
    components = []
    for start in reversed(finish):
        if start in assigned:
            continue
        assigned.add(start)
        component = []
        stack = [start]
        while stack:
            source = stack.pop()
            component.append(source)
            for target in reversed(reverse_neighbors[source]):
                if target in reachable and target not in assigned:
                    assigned.add(target)
                    stack.append(target)
        components.append(tuple(sorted(component)))
    return tuple(components)


def _multi_source_dijkstra(sources, adjacency, stats, phase):
    if stats is not None:
        stats.shortest_path_calls += 1
    distances = {}
    roots = {}
    parents = {}
    heap = []
    for source in sorted(set(sources)):
        distances[source] = Fraction(0)
        roots[source] = source
        heapq.heappush(heap, (Fraction(0), source))
        if stats is not None:
            stats.queue_pushes += 1
    while heap:
        if stats is not None:
            stats.queue_pops += 1
        distance, source = heapq.heappop(heap)
        if distances.get(source) != distance:
            continue
        if stats is not None:
            stats.expanded_states += 1
            if phase == "prefix":
                stats.prefix_expansions += 1
                stats.prefix_settled += 1
            else:
                stats.lower_bound_settled += 1
        for target, cost, edge in adjacency[source]:
            candidate = distance + cost
            old_distance = distances.get(target)
            if old_distance is None or candidate < old_distance:
                distances[target] = candidate
                roots[target] = roots[source]
                parents[target] = (source, edge)
                heapq.heappush(heap, (candidate, target))
                if stats is not None:
                    stats.queue_pushes += 1
    return distances, roots, parents


def _reconstruct_prefix(entry, roots, parents):
    node = entry
    reverse_ids = [node]
    reverse_edges = []
    while node in parents:
        node, edge = parents[node]
        reverse_ids.append(node)
        reverse_edges.append(edge)
    if node != roots[entry]:
        raise AssertionError("prefix parent chain does not reach its selected initial root")
    return tuple(reversed(reverse_ids)), tuple(reversed(reverse_edges))


def _shortest_accepting_closed_walk(entry, component, nodes, node_id, forward, accepting, stats):
    """Dijkstra on (Product node, accepted) after a mandatory real first edge."""
    component_set = set(component)
    entry_accepting = nodes[entry][1] in accepting
    distances = {}
    parents = {}
    heap = []
    if stats is not None:
        stats.shortest_path_calls += 1

    # Virtual source edges are represented by seed parents. They preserve the
    # first actual transition and make an empty suffix impossible.
    for target, cost, edge in forward[entry]:
        if target not in component_set:
            continue
        seen_accepting = entry_accepting or nodes[target][1] in accepting
        state = (target, seen_accepting)
        if state not in distances or cost < distances[state]:
            distances[state] = cost
            parents[state] = (None, edge)
            heapq.heappush(heap, (cost, target, seen_accepting))
            if stats is not None:
                stats.queue_pushes += 1

    goal = (entry, True)
    while heap:
        if stats is not None:
            stats.queue_pops += 1
        distance, source, seen_accepting = heapq.heappop(heap)
        state = (source, seen_accepting)
        if distances.get(state) != distance:
            continue
        if stats is not None:
            stats.expanded_states += 1
            stats.suffix_expansions += 1
            stats.suffix_settled += 1
        if state == goal:
            reverse_edges = []
            cursor = state
            while True:
                previous, edge = parents[cursor]
                reverse_edges.append(edge)
                if previous is None:
                    break
                cursor = previous
            edges = tuple(reversed(reverse_edges))
            state_ids = [entry]
            state_ids.extend(node_id[edge.target] for edge in edges)
            return tuple(state_ids), edges, distance
        for target, cost, edge in forward[source]:
            if target not in component_set:
                continue
            next_seen = seen_accepting or nodes[target][1] in accepting
            target_state = (target, next_seen)
            candidate = distance + cost
            old_distance = distances.get(target_state)
            if old_distance is None or candidate < old_distance:
                distances[target_state] = candidate
                parents[target_state] = (state, edge)
                heapq.heappush(heap, (candidate, target, next_seen))
                if stats is not None:
                    stats.queue_pushes += 1
    return None
