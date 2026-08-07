"""Search accepting prefix-suffix runs in a product automaton."""

import logging
import time
from collections import defaultdict

from networkx import dijkstra_predecessor_and_distance

from .product import ProdAut_Run


_LOGGER = logging.getLogger(__name__)


def dijkstra_plan_networkX(product, gamma=10):
    """Find an accepting run with NetworkX Dijkstra search."""
    start = time.time()
    runs = {}
    loops = {}

    for prod_target in product.graph["accept"]:
        if product.has_edge(prod_target, prod_target):
            loops[prod_target] = (
                product.edges[prod_target, prod_target]["weight"],
                [prod_target],
            )
            continue

        cycle_costs: dict[object, float] = {}
        loop_pre, loop_dist = dijkstra_predecessor_and_distance(
            product,
            prod_target,
            weight="weight",
        )

        for target_pred in product.predecessors(prod_target):
            if target_pred in loop_dist:
                cycle_costs[target_pred] = (
                    loop_dist[target_pred]
                    + product.edges[target_pred, prod_target]["weight"]
                )

        if cycle_costs:
            optimal_predecessor = min(
                cycle_costs,
                key=lambda node: cycle_costs[node],
            )
            suffix = compute_path_from_pre(
                loop_pre,
                optimal_predecessor,
            )
            loops[prod_target] = (
                cycle_costs[optimal_predecessor],
                suffix,
            )

    for prod_init in product.graph["initial"]:
        line_costs: dict[object, float] = {}
        line_pre, line_dist = dijkstra_predecessor_and_distance(
            product,
            prod_init,
            weight="weight",
        )

        for target, (suffix_cost, _) in loops.items():
            if target in line_dist:
                line_costs[target] = (
                    line_dist[target] + gamma * suffix_cost
                )

        if not line_costs:
            continue

        optimal_target = min(
            line_costs,
            key=lambda node: line_costs[node],
        )
        prefix = compute_path_from_pre(
            line_pre,
            optimal_target,
        )
        prefix_cost = line_dist[optimal_target]
        suffix_cost, suffix = loops[optimal_target]

        runs[(prod_init, optimal_target)] = (
            prefix,
            prefix_cost,
            suffix,
            suffix_cost,
        )

    if not runs:
        _LOGGER.error(
            "No accepting run found in NetworkX Dijkstra planning."
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
        "NetworkX Dijkstra planning completed in %.2fs: "
        "prefix cost %.2f, suffix cost %.2f.",
        elapsed,
        prefix_cost,
        suffix_cost,
    )
    return run, elapsed


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
    """Compute possible product states from a TS execution trace."""
    if not trace:
        return set()

    possible_states = {
        (trace[0], buchi_state)
        for buchi_state in product.graph["buchi"].graph["initial"]
    }

    for ts_state in trace[1:]:
        next_states = set()

        for product_node in possible_states:
            for successor, _ in product.fly_successors(product_node):
                if successor[0] == ts_state:
                    next_states.add(successor)

        possible_states = next_states

    return possible_states


def improve_plan_given_history(product, trace):
    """Replan from product states consistent with execution history."""
    new_initial_set = prod_states_given_history(
        product,
        trace,
    )

    if not new_initial_set:
        return None

    new_run, _ = dijkstra_plan_optimal(
        product,
        gamma=10,
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
