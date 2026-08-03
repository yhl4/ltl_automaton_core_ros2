"""Construct and evaluate Büchi automata for LTL missions."""

import logging
from itertools import product as cartesian_product

from networkx import DiGraph

from ..boolean_formulas.parser import parse as parse_guard
from .ltl2ba import parse_ltl
from .promela import find_states, find_symbols


_LOGGER = logging.getLogger(__name__)


def buchi_from_ltl(formula, buchi_type):
    """Construct a Büchi automaton from an LTL formula."""
    edges = parse_ltl(formula)
    symbols = find_symbols(formula)
    states, initial_states, accepting_states = find_states(edges)

    buchi = DiGraph(
        type=buchi_type,
        initial=initial_states,
        accept=accepting_states,
        symbols=symbols,
    )

    for state in states:
        buchi.add_node(state)

    for source, target in edges:
        guard_formula = edges[(source, target)]
        guard_expression = parse_guard(guard_formula)

        buchi.add_edge(
            source,
            target,
            guard=guard_expression,
            guard_formula=guard_formula,
        )

    return buchi


def mission_to_buchi(hard_spec, soft_spec):
    """Construct a Büchi automaton for hard and soft specifications."""
    if hard_spec and not soft_spec:
        buchi = buchi_from_ltl(
            hard_spec,
            "hard_buchi",
        )
    elif soft_spec and not hard_spec:
        buchi = buchi_from_ltl(
            soft_spec,
            "soft_buchi",
        )
    elif hard_spec and soft_spec:
        buchi = duo_buchi_from_ltls(
            hard_spec,
            soft_spec,
        )
    else:
        raise ValueError(
            "At least one hard or soft LTL specification is required."
        )

    _LOGGER.info(
        "Full Büchi automaton constructed with %d states and %d transitions.",
        buchi.number_of_nodes(),
        buchi.number_of_edges(),
    )

    return buchi


def duo_buchi_from_ltls(hard_spec, soft_spec):
    """Combine hard and soft Büchi automata into a safe Büchi automaton."""
    hard_buchi = buchi_from_ltl(
        hard_spec,
        "hard_buchi",
    )
    soft_buchi = buchi_from_ltl(
        soft_spec,
        "soft_buchi",
    )

    symbols = set(hard_buchi.graph["symbols"]).union(
        soft_buchi.graph["symbols"]
    )

    duo_buchi = DiGraph(
        type="safe_buchi",
        hard=hard_buchi,
        soft=soft_buchi,
        symbols=symbols,
    )

    initial_states = set()
    accepting_states = set()

    product_nodes = cartesian_product(
        hard_buchi.nodes,
        soft_buchi.nodes,
        [1, 2],
    )

    for hard_node, soft_node, level in product_nodes:
        duo_node = (
            hard_node,
            soft_node,
            level,
        )

        duo_buchi.add_node(
            duo_node,
            hard=hard_node,
            soft=soft_node,
            level=level,
        )

        if (
            hard_node in hard_buchi.graph["initial"]
            and soft_node in soft_buchi.graph["initial"]
            and level == 1
        ):
            initial_states.add(duo_node)

        if (
            hard_node in hard_buchi.graph["accept"]
            and level == 1
        ):
            accepting_states.add(duo_node)

    duo_buchi.graph["accept"] = accepting_states
    duo_buchi.graph["initial"] = initial_states

    for source_node in duo_buchi.nodes:
        for target_node in duo_buchi.nodes:
            source_hard, source_soft, source_level = check_duo_attributes(
                duo_buchi,
                source_node,
            )
            target_hard, target_soft, target_level = check_duo_attributes(
                duo_buchi,
                target_node,
            )

            if (
                target_hard not in hard_buchi.neighbors(source_hard)
                or target_soft not in soft_buchi.neighbors(source_soft)
            ):
                continue

            hard_guard = hard_buchi.edges[
                source_hard,
                target_hard,
            ]["guard"]

            soft_guard = soft_buchi.edges[
                source_soft,
                target_soft,
            ]["guard"]

            valid_level_transition = (
                (
                    source_hard not in hard_buchi.graph["accept"]
                    and source_level == 1
                    and target_level == 1
                )
                or (
                    source_hard in hard_buchi.graph["accept"]
                    and source_level == 1
                    and target_level == 2
                )
                or (
                    source_soft not in soft_buchi.graph["accept"]
                    and source_level == 2
                    and target_level == 2
                )
                or (
                    source_soft in soft_buchi.graph["accept"]
                    and source_level == 2
                    and target_level == 1
                )
            )

            if valid_level_transition:
                duo_buchi.add_edge(
                    source_node,
                    target_node,
                    hardguard=hard_guard,
                    softguard=soft_guard,
                )

    return duo_buchi


def check_duo_attributes(duo_buchi, node):
    """Return the hard, soft, and level attributes of a combined node."""
    node_data = duo_buchi.nodes[node]

    return (
        node_data["hard"],
        node_data["soft"],
        node_data["level"],
    )


def check_label_for_buchi_edge(
    buchi,
    label,
    source_node,
    target_node,
):
    """Check a TS label against a Büchi transition."""
    buchi_type = buchi.graph["type"]
    edge = buchi.edges[source_node, target_node]

    if buchi_type == "hard_buchi":
        truth = edge["guard"].check(label)
        distance = 0

    elif buchi_type == "soft_buchi":
        truth = True
        distance = edge["guard"].distance(label)

    elif buchi_type == "safe_buchi":
        truth = edge["hardguard"].check(label)

        if truth:
            distance = edge["softguard"].distance(label)
        else:
            distance = 1000

    else:
        raise ValueError(
            f"Unsupported Büchi automaton type: {buchi_type}"
        )

    return truth, distance
