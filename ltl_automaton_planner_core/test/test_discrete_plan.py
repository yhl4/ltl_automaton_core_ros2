"""Tests for discrete prefix-suffix planning."""

from networkx import DiGraph

from ltl_automaton_planner_core.boolean_formulas.parser import (
    parse as parse_guard,
)
from ltl_automaton_planner_core.ltl_tools.discrete_plan import (
    dijkstra_plan_networkX,
)
from ltl_automaton_planner_core.ltl_tools.product import ProdAut


def create_test_product() -> ProdAut:
    """Create a minimal product automaton with an accepting self-loop."""
    ts = DiGraph(initial={"s0"})

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

    product = ProdAut(
        ts,
        buchi,
    )
    product.build_full()

    return product


def test_networkx_dijkstra_finds_accepting_run() -> None:
    """Find a prefix and accepting suffix with Dijkstra search."""
    product = create_test_product()

    run, elapsed = dijkstra_plan_networkX(
        product,
        gamma=10,
    )

    initial_node = ("s0", "q0")
    accepting_node = ("s1", "q1")

    assert run is not None
    assert elapsed is not None
    assert elapsed >= 0

    assert run.prefix == [
        initial_node,
        accepting_node,
    ]
    assert run.suffix == [
        accepting_node,
    ]

    assert run.pre_prod_edges == [
        (
            initial_node,
            accepting_node,
        )
    ]
    assert run.suf_prod_edges == [
        (
            accepting_node,
            accepting_node,
        )
    ]

    assert run.line == [
        "s0",
        "s1",
    ]
    assert run.loop == [
        "s1",
        "s1",
    ]

    assert run.pre_plan == [
        "goto_s1",
    ]
    assert run.suf_plan == [
        "stay_s1",
    ]

    assert run.precost == 2.0
    assert run.sufcost == 1.0
    assert run.totalcost == 12.0
