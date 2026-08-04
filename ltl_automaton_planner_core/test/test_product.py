"""Tests for TS-Büchi product automata."""

from networkx import DiGraph

from ltl_automaton_planner_core.boolean_formulas.parser import (
    parse as parse_guard,
)
from ltl_automaton_planner_core.ltl_tools.product import ProdAut


def create_test_ts() -> DiGraph:
    """Create a minimal transition system."""
    ts = DiGraph(
        initial={"s0"},
    )

    ts.add_node(
        "s0",
        label={"start"},
    )
    ts.add_node(
        "s1",
        label={"goal"},
    )

    ts.add_edge(
        "s0",
        "s1",
        weight=2.0,
        action="goto_s1",
    )
    ts.add_edge(
        "s1",
        "s1",
        weight=1.0,
        action="stay_s1",
    )

    return ts


def create_test_buchi() -> DiGraph:
    """Create a minimal hard Büchi automaton."""
    buchi = DiGraph(
        type="hard_buchi",
        initial={"q0"},
        accept={"q1"},
        symbols={"start", "goal"},
    )

    buchi.add_node("q0")
    buchi.add_node("q1")

    buchi.add_edge(
        "q0",
        "q1",
        guard=parse_guard("start"),
        guard_formula="start",
    )
    buchi.add_edge(
        "q1",
        "q1",
        guard=parse_guard("goal"),
        guard_formula="goal",
    )

    return buchi


def test_product_composition_and_projection() -> None:
    """Compose and project a product state."""
    product = ProdAut(
        create_test_ts(),
        create_test_buchi(),
    )

    product_node = product.composition(
        "s0",
        "q0",
    )

    assert product_node == ("s0", "q0")
    assert product.projection(product_node) == ("s0", "q0")
    assert product_node in product.graph["initial"]


def test_build_full_product() -> None:
    """Build a full TS-Büchi product automaton."""
    product = ProdAut(
        create_test_ts(),
        create_test_buchi(),
    )

    product.build_full()

    initial_node = ("s0", "q0")
    accepting_node = ("s1", "q1")

    assert initial_node in product.graph["initial"]
    assert accepting_node in product.graph["accept"]

    assert product.has_edge(
        initial_node,
        accepting_node,
    )
    assert product.has_edge(
        accepting_node,
        accepting_node,
    )

    edge_data = product.edges[
        initial_node,
        accepting_node,
    ]

    assert edge_data["transition_cost"] == 2.0
    assert edge_data["soft_task_dist"] == 0
    assert edge_data["weight"] == 2.0
    assert edge_data["action"] == "goto_s1"

    assert accepting_node in product.graph["accept_with_cycle"]


def test_update_beta() -> None:
    """Recalculate product edge weights after updating beta."""
    product = ProdAut(
        create_test_ts(),
        create_test_buchi(),
    )

    product.build_full()
    product.update_beta(500)

    edge_data = product.edges[
        ("s0", "q0"),
        ("s1", "q1"),
    ]

    assert product.graph["beta"] == 500
    assert edge_data["weight"] == 2.0
