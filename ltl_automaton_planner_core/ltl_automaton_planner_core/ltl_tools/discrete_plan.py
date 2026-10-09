"""Search accepting prefix-suffix runs in a product automaton."""

import logging
import time
from collections import defaultdict
from collections import deque
from heapq import heappop
from heapq import heappush
from itertools import count
from itertools import islice

from networkx import DiGraph
from networkx import NodeNotFound
from networkx import multi_source_dijkstra_path_length
from networkx import strongly_connected_components

from .product import ProdAut, ProdAut_Run


_LOGGER = logging.getLogger(__name__)


def dijkstra_plan_networkX(product, gamma=10, start_set=None):
    """Search a full Product from explicit or unchanged initial starts."""
    start = time.perf_counter()
    init_set = (
        product.graph["initial"]
        if start_set is None
        else start_set
    )
    if not init_set:
        _LOGGER.error("No accepting run found from the requested start set.")
        return None, None
    accepting_cycles = (
        product.graph["accept"] & product.graph["accept_with_cycle"]
    )
    if not accepting_cycles:
        _LOGGER.error("No accepting run found in NetworkX Dijkstra planning.")
        return None, None

    prefix_dist = _prefix_distances(product, init_set)
    reachable_accepting = {
        target
        for target in accepting_cycles
        if target in prefix_dist
    }
    if not reachable_accepting:
        _LOGGER.error(
            "No accepting run found in NetworkX Dijkstra planning."
        )
        return None, None

    target_components = {}
    # Any accepting cycle used by a valid run must be prefix reachable.
    reachable_product = DiGraph()
    reachable_product.add_nodes_from(prefix_dist)
    if type(product) is DiGraph or type(product) is ProdAut:
        source_adjacency = product._succ
        reachable_product.add_edges_from(
            (source, target)
            for source in prefix_dist
            for target in source_adjacency[source]
            if target in prefix_dist
        )
    else:
        reachable_product.add_edges_from(
            (source, target)
            for source in prefix_dist
            for target in product.adj[source]
            if target in prefix_dist
        )
    for component in strongly_connected_components(reachable_product):
        reachable_targets = component & reachable_accepting
        for target in reachable_targets:
            target_components[target] = component

    best_plan = None

    for prod_target in accepting_cycles:
        if prod_target not in prefix_dist:
            continue

        component = target_components[prod_target]

        loop_dist = _component_distances(product, prod_target, component)

        optimal_predecessor = None
        suffix_cost = None
        found_cycle = False
        for target_pred, edge_data in product.pred[prod_target].items():
            edge_weight = edge_data.get("weight", 1)
            if target_pred in loop_dist and edge_weight is not None:
                candidate_cost = (
                    loop_dist[target_pred]
                    + edge_weight
                )
                if not found_cycle or candidate_cost < suffix_cost:
                    optimal_predecessor = target_pred
                    suffix_cost = candidate_cost
                    found_cycle = True

        if not found_cycle:
            continue

        prefix_cost = prefix_dist[prod_target]
        candidate = (
            prod_target,
            optimal_predecessor,
            prefix_cost,
            suffix_cost,
            loop_dist,
        )
        if (
            best_plan is None
            or prefix_cost + gamma * suffix_cost < (
                best_plan[2] + gamma * best_plan[3]
            )
        ):
            best_plan = candidate

    if best_plan is None:
        _LOGGER.error(
            "No accepting run found in NetworkX Dijkstra planning."
        )
        return None, None

    (
        prod_target,
        optimal_predecessor,
        prefix_cost,
        suffix_cost,
        loop_dist,
    ) = best_plan
    prefix = _restore_tight_path(
        product,
        prefix_dist,
        init_set,
        prod_target,
    )
    suffix = _restore_tight_path(
        product,
        loop_dist,
        {prod_target},
        optimal_predecessor,
    )
    total_cost = prefix_cost + gamma * suffix_cost

    run = ProdAut_Run(
        product,
        prefix,
        prefix_cost,
        suffix,
        suffix_cost,
        total_cost,
    )
    elapsed = time.perf_counter() - start

    _LOGGER.debug(
        "NetworkX Dijkstra planning completed in %.2fs: "
        "prefix cost %.2f, suffix cost %.2f.",
        elapsed,
        prefix_cost,
        suffix_cost,
    )
    return run, elapsed


# The _prefix_distances and _component_distances helpers are adapted from NetworkX 2.4.
# Copyright (c) 2004-2019, NetworkX Developers.
# Copyright (c) Aric Hagberg, Dan Schult, and Pieter Swart.
# The following BSD-3-Clause notice applies to these helpers:
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
#  * Neither the name of the NetworkX Developers nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

def _prefix_distances(product, sources):
    """Find prefix distances with native weight lookup when supported."""
    if type(product) is not DiGraph and type(product) is not ProdAut:
        return multi_source_dijkstra_path_length(
            product,
            sources=sources,
            weight="weight",
        )
    if "is_multigraph" in product.__dict__:
        return multi_source_dijkstra_path_length(
            product,
            sources=sources,
            weight="weight",
        )
    if not sources:
        raise ValueError("sources must not be empty")
    if product.is_multigraph():
        return multi_source_dijkstra_path_length(
            product,
            sources=sources,
            weight="weight",
        )
    successors = product._succ if product.is_directed() else product._adj
    push = heappush
    pop = heappop
    distances = {}
    seen = {}
    sequence = count()
    fringe = []
    target = None
    for source in sources:
        if source not in product:
            raise NodeNotFound("Source {} not in G".format(source))
        seen[source] = 0
        push(fringe, (0, next(sequence), source))
    while fringe:
        distance, _, current = pop(fringe)
        if current in distances:
            continue
        distances[current] = distance
        if current == target:
            break
        for successor, data in successors[current].items():
            cost = data.get("weight", 1)
            if cost is None:
                continue
            candidate = distances[current] + cost
            if successor in distances:
                if candidate < distances[successor]:
                    raise ValueError("Contradictory paths found:", "negative weights?")
            elif successor not in seen or candidate < seen[successor]:
                seen[successor] = candidate
                push(fringe, (candidate, next(sequence), successor))
            elif candidate == seen[successor]:
                pass
    return distances


def _component_distances(product, source, component):
    """Find suffix distances with NetworkX's ordering and component filter."""
    # Adapted from NetworkX 2.4's distance-only Dijkstra loop; license below.
    # Keep source-set hashing and the target=None comparison observable.
    sources = {source}
    successors = product._succ if product.is_directed() else product._adj
    push = heappush
    pop = heappop
    distances = {}
    seen = {}
    sequence = count()
    fringe = []
    target = None
    for start in sources:
        if start not in product:
            raise NodeNotFound("Source {} not in G".format(start))
        seen[start] = 0
        push(fringe, (0, next(sequence), start))
    while fringe:
        distance, _, current = pop(fringe)
        if current in distances:
            continue
        distances[current] = distance
        if current == target:
            break
        for successor, data in successors[current].items():
            if successor not in component:
                continue
            cost = data.get("weight", 1)
            if cost is None:
                continue
            candidate = distance + cost
            if successor in distances:
                if candidate < distances[successor]:
                    raise ValueError("Contradictory paths found:", "negative weights?")
            elif successor not in seen or candidate < seen[successor]:
                seen[successor] = candidate
                push(fringe, (candidate, next(sequence), successor))
            elif candidate == seen[successor]:
                # NetworkX evaluates equality even when pred=None.
                pass
    return distances


def _restore_tight_path(product, distances, sources, target):
    """Recover one finite shortest path from a distance-only result."""
    if target not in distances:
        raise RuntimeError(
            "Cannot recover a shortest path to a finite-distance target."
        )

    source_set = set(sources)
    parent = {
        source: None
        for source in source_set
        if source in distances
    }
    queue = deque(parent)

    while queue:
        current = queue.popleft()
        if current == target:
            break
        current_distance = distances[current]
        successors = product.adj[current]
        for successor in successors:
            if successor in parent:
                continue
            edge_weight = successors[successor].get("weight", 1)
            if edge_weight is None:
                continue
            if (
                current_distance + edge_weight
                != distances.get(successor)
            ):
                continue
            parent[successor] = current
            if successor == target:
                # The BFS parent chain is fixed when the target is found.
                queue.clear()
                break
            queue.append(successor)

    if target not in parent:
        raise RuntimeError(
            "Cannot recover a tight shortest path to the selected target."
        )

    path = []
    node = target
    while node is not None:
        path.append(node)
        node = parent[node]
    path.reverse()
    return path


def dijkstra_plan_optimal(product, gamma=10, start_set=None):
    """Find an optimal accepting run from the given product states."""
    start = time.time()
    runs = {}
    accept_set = product.graph["accept"]
    init_set = (
        product.graph["initial"]
        if start_set is None
        else start_set
    )
    loop_cache = {}

    for init_prod_node in init_set:
        for prefix, prefix_cost in dijkstra_targets(
            product,
            init_prod_node,
            accept_set,
        ):
            accepting_node = prefix[-1]

            if accepting_node in loop_cache:
                suffix, suffix_cost = loop_cache[accepting_node]
            else:
                suffix, suffix_cost = dijkstra_loop(
                    product,
                    accepting_node,
                )
                loop_cache[accepting_node] = (
                    suffix,
                    suffix_cost,
                )

            if suffix:
                runs[(prefix[0], accepting_node)] = (
                    prefix,
                    prefix_cost,
                    suffix,
                    suffix_cost,
                )

    if not runs:
        _LOGGER.error(
            "No accepting run found in optimal planning."
        )
        return None, None

    prefix, prefix_cost, suffix, suffix_cost = min(
        runs.values(),
        key=lambda plan: plan[1] + gamma * plan[3],
    )
    total_cost = prefix_cost + gamma * suffix_cost

    run = ProdAut_Run(
        product,
        prefix,
        prefix_cost,
        suffix,
        suffix_cost,
        total_cost,
    )
    elapsed = time.time() - start

    _LOGGER.debug(
        "Optimal Dijkstra planning completed in %.2fs: "
        "prefix cost %.2f, suffix cost %.2f.",
        elapsed,
        prefix_cost,
        suffix_cost,
    )
    return run, elapsed


def dijkstra_plan_bounded(product, time_limit=3.0, gamma=10):
    """Find the best accepting run discovered before a time limit."""
    start = time.time()
    deadline = start + time_limit

    runs = {}
    accept_set = product.graph["accept"]
    init_set = product.graph["initial"]
    loop_cache = {}

    _LOGGER.debug("Bounded Dijkstra planning started.")
    _LOGGER.debug(
        "Number of accepting states: %d.",
        len(accept_set),
    )
    _LOGGER.debug(
        "Number of initial states: %d.",
        len(init_set),
    )

    for init_prod_node in init_set:
        if time.time() >= deadline:
            break

        for prefix, prefix_cost in dijkstra_targets(
            product,
            init_prod_node,
            accept_set,
            deadline=deadline,
        ):
            accepting_node = prefix[-1]

            if accepting_node in loop_cache:
                suffix, suffix_cost = loop_cache[accepting_node]
            else:
                suffix, suffix_cost = dijkstra_loop(
                    product,
                    accepting_node,
                    deadline=deadline,
                )
                loop_cache[accepting_node] = (
                    suffix,
                    suffix_cost,
                )

            if suffix:
                runs[(prefix[0], accepting_node)] = (
                    prefix,
                    prefix_cost,
                    suffix,
                    suffix_cost,
                )

            if time.time() >= deadline:
                return _build_best_run(
                    product,
                    runs,
                    gamma,
                    start,
                    "Bounded Dijkstra planning",
                )

    return _build_best_run(
        product,
        runs,
        gamma,
        start,
        "Bounded Dijkstra planning",
    )


def _build_best_run(product, runs, gamma, start, planner_name):
    """Build the minimum-cost run from collected candidates."""
    if not runs:
        _LOGGER.error(
            "No accepting run found in %s.",
            planner_name,
        )
        return None, None

    prefix, prefix_cost, suffix, suffix_cost = min(
        runs.values(),
        key=lambda plan: plan[1] + gamma * plan[3],
    )
    total_cost = prefix_cost + gamma * suffix_cost

    run = ProdAut_Run(
        product,
        prefix,
        prefix_cost,
        suffix,
        suffix_cost,
        total_cost,
    )
    elapsed = time.time() - start

    _LOGGER.debug(
        "%s completed in %.2fs: prefix cost %.2f, "
        "suffix cost %.2f.",
        planner_name,
        elapsed,
        prefix_cost,
        suffix_cost,
    )
    return run, elapsed


def dijkstra_targets(
    product,
    prod_source,
    prod_targets,
    deadline=None,
):
    """Yield shortest paths from one source to feasible target states."""
    to_visit = {prod_source}
    visited = set()
    distance = defaultdict(lambda: float("inf"))
    predecessor = {}
    distance[prod_source] = 0

    feasible_targets = set()

    for prod_accept in prod_targets:
        if deadline is not None and time.time() >= deadline:
            return

        if product.accept_predecessors(prod_accept):
            feasible_targets.add(prod_accept)

    while to_visit and feasible_targets:
        if deadline is not None and time.time() >= deadline:
            return

        current_node = min(
            to_visit,
            key=lambda node: distance[node],
        )
        to_visit.remove(current_node)
        visited.add(current_node)

        current_distance = distance[current_node]

        for successor, cost in product.fly_successors(current_node):
            if deadline is not None and time.time() >= deadline:
                return

            new_distance = current_distance + cost

            if new_distance < distance[successor]:
                distance[successor] = new_distance
                predecessor[successor] = [current_node]

            if successor not in visited:
                to_visit.add(successor)

        if current_node in feasible_targets:
            feasible_targets.remove(current_node)
            yield (
                compute_path_from_pre(
                    predecessor,
                    current_node,
                ),
                distance[current_node],
            )


def dijkstra_loop(
    product,
    prod_accept,
    deadline=None,
):
    """Find a minimum cycle returning to an accepting product state."""
    if deadline is not None and time.time() >= deadline:
        return None, None

    paths = {}
    costs: dict[object, float] = {}
    accept_predecessors = product.accept_predecessors(prod_accept)

    for tail, cost in dijkstra_targets(
        product,
        prod_accept,
        accept_predecessors,
        deadline=deadline,
    ):
        if not tail:
            continue

        accept_predecessor = tail[-1]
        paths[accept_predecessor] = tail
        costs[accept_predecessor] = (
            cost
            + product.edges[
                accept_predecessor,
                prod_accept,
            ]["weight"]
        )

    if not costs:
        return None, None

    minimum_predecessor = min(
        costs,
        key=lambda node: costs[node],
    )
    return (
        paths[minimum_predecessor],
        costs[minimum_predecessor],
    )


def compute_path_from_pre(predecessor, target):
    """Reconstruct a path from a predecessor mapping."""
    node = target
    path = [node]

    while node in predecessor:
        predecessor_list = predecessor[node]

        if not predecessor_list:
            break

        node = predecessor_list[0]
        path.append(node)

    path.reverse()
    return path


def prod_states_given_history(product, trace):
    """Trace observed TS states through the already built Product edges."""
    if not trace:
        return set()

    possible_states = {
        (trace[0], buchi_state)
        for buchi_state in product.graph["buchi"].graph["initial"]
        if (trace[0], buchi_state) in product
    }
    successor_tables = {}

    for ts_state in islice(trace, 1, None):
        next_states = set()

        for product_node in possible_states:
            successors = successor_tables.get(product_node)
            if successors is None:
                successors = tuple(product.successors(product_node))
                successor_tables[product_node] = successors
            for successor in successors:
                if successor[0] == ts_state:
                    next_states.add(successor)

        possible_states = next_states

    return possible_states


def improve_plan_given_history(product, trace, gamma=10):
    """Replan a full Product from history with the configured suffix weight."""
    new_initial_set = prod_states_given_history(
        product,
        trace,
    )

    if not new_initial_set:
        return None

    new_run, _ = dijkstra_plan_networkX(
        product,
        gamma=gamma,
        start_set=new_initial_set,
    )
    return new_run


def validate_and_revise_after_ts_change(
    run,
    product,
    sense_info,
    com_info,
):
    """Validate a run after a TS change and revise invalid segments."""
    new_prefix = None
    new_suffix = None
    prefix_invalid = False
    suffix_invalid = False
    start = time.time()

    changed_regions = (
        product.graph["ts"]
        .graph["region"]
        .update_after_region_change(
            sense_info,
            com_info,
        )
    )

    if not changed_regions:
        return True

    for index, product_edge in enumerate(run.pre_prod_edges):
        from_ts_node, _ = product_edge[0]
        to_ts_node, _ = product_edge[1]

        successor_ts_nodes = {
            successor
            for successor, _ in product.graph["ts"].fly_successors(
                from_ts_node
            )
        }

        if to_ts_node not in successor_ts_nodes:
            prefix_invalid = True
            _LOGGER.error(
                "The current prefix contains invalid edges; "
                "revision is required."
            )
            new_prefix = dijkstra_revise_once(
                product,
                run.prefix,
                index,
            )
            break

    for index, product_edge in enumerate(run.suf_prod_edges):
        from_ts_node, _ = product_edge[0]
        to_ts_node, _ = product_edge[1]

        successor_ts_nodes = {
            successor
            for successor, _ in product.graph["ts"].fly_successors(
                from_ts_node
            )
        }

        if to_ts_node not in successor_ts_nodes:
            suffix_invalid = True
            _LOGGER.error(
                "The current suffix contains invalid edges; "
                "revision is required."
            )

            closed_suffix = list(run.suffix)
            closed_suffix.append(run.suffix[0])

            revised_closed_suffix = dijkstra_revise_once(
                product,
                closed_suffix,
                index,
            )

            if (
                revised_closed_suffix
                and revised_closed_suffix[0]
                == revised_closed_suffix[-1]
            ):
                new_suffix = revised_closed_suffix[:-1]
            else:
                new_suffix = revised_closed_suffix
            break

    if not prefix_invalid and not suffix_invalid:
        return True

    if prefix_invalid and new_prefix is None:
        _LOGGER.error("Prefix revision failed.")
        return False

    if suffix_invalid and new_suffix is None:
        _LOGGER.error("Suffix revision failed.")
        return False

    if new_prefix is not None:
        run.prefix = new_prefix

    if new_suffix is not None:
        run.suffix = new_suffix

    run.prod_run_to_prod_edges()
    run.plan_output(product)

    _LOGGER.info(
        "TS-change validation and revision completed in %.2fs.",
        time.time() - start,
    )
    return True


def dijkstra_revise(
    product,
    run_segment,
    broken_edge_index,
):
    """Reconnect a broken run segment to a later state."""
    source_node = run_segment[broken_edge_index]
    suffix_segment = run_segment[broken_edge_index + 1:]

    for bridge, _ in dijkstra_targets(
        product,
        source_node,
        suffix_segment,
    ):
        bridge_target = bridge[-1]
        reversed_segment = list(reversed(run_segment))
        reverse_index = reversed_segment.index(bridge_target)
        forward_index = len(run_segment) - reverse_index - 1

        return (
            run_segment[:broken_edge_index]
            + bridge
            + run_segment[forward_index + 1:]
        )

    return None


def dijkstra_revise_once(
    product,
    run_segment,
    broken_edge_index,
):
    """Reconnect a broken run segment directly to its final state."""
    source_node = run_segment[broken_edge_index]
    target_set = {run_segment[-1]}

    for bridge, _ in dijkstra_targets(
        product,
        source_node,
        target_set,
    ):
        return (
            run_segment[:broken_edge_index]
            + bridge
        )

    return None
