"""Pure preservation checks for hard/soft Buchi composition."""

from networkx import DiGraph
import pytest

from ltl_automaton_planner_core.boolean_formulas.parser import parse as parse_guard
from ltl_automaton_planner_core.ltl_tools import buchi


def _components():
    hard = DiGraph(
        type="hard_buchi", initial=["h0"], accept=["h1"], symbols=["go", "goal"],
    )
    soft = DiGraph(
        type="soft_buchi", initial=["s0"], accept=["s2"], symbols=["pref"],
    )
    for source, target, formula in (
        ("h0", "h0", "!go"), ("h0", "h1", "go"),
        ("h1", "h0", "1"), ("h1", "h1", "goal"),
    ):
        hard.add_edge(source, target, guard=parse_guard(formula))
    for source, target, formula in (
        ("s0", "s1", "pref"), ("s1", "s2", "!pref"), ("s2", "s0", "1"),
    ):
        soft.add_edge(source, target, guard=parse_guard(formula))
    return hard, soft


def _build(monkeypatch, hard, soft):
    components = {"hard_buchi": hard, "soft_buchi": soft}
    monkeypatch.setattr(
        buchi, "buchi_from_ltl", lambda _formula, kind: components[kind],
    )
    return buchi.duo_buchi_from_ltls("hard", "soft")


def test_duo_preserves_nodes_levels_edge_order_and_component_guard_identity(monkeypatch):
    """Match the hand-specified level transitions on a 2-by-3 component graph."""
    hard, soft = _components()
    duo = _build(monkeypatch, hard, soft)
    level_targets = (
        (("h0", "s0"), (1, 2)),
        (("h0", "s1"), (1, 2)),
        (("h0", "s2"), (1, 1)),
        (("h1", "s0"), (2, 2)),
        (("h1", "s1"), (2, 2)),
        (("h1", "s2"), (2, 1)),
    )
    soft_target = {"s0": "s1", "s1": "s2", "s2": "s0"}
    expected_nodes = [
        (hard_node, soft_node, level)
        for (hard_node, soft_node), _ in level_targets
        for level in (1, 2)
    ]
    expected_edges = [
        ((hard_node, soft_node, level), (target_hard, soft_target[soft_node], target_level))
        for (hard_node, soft_node), targets in level_targets
        for level, target_level in enumerate(targets, 1)
        for target_hard in ("h0", "h1")
    ]
    assert list(duo) == expected_nodes
    assert list(duo.edges) == expected_edges
    assert duo.graph["initial"] == {("h0", "s0", 1)}
    assert duo.graph["accept"] == {("h1", name, 1) for name in ("s0", "s1", "s2")}
    assert duo.graph["symbols"] == {"go", "goal", "pref"}
    assert duo.graph["hard"] is hard
    assert duo.graph["soft"] is soft
    for node, attributes in duo.nodes(data=True):
        assert attributes == dict(hard=node[0], soft=node[1], level=node[2])
    for source, target, attributes in duo.edges(data=True):
        assert attributes["hardguard"] is hard.edges[source[0], target[0]]["guard"]
        assert attributes["softguard"] is soft.edges[source[1], target[1]]["guard"]


@pytest.mark.parametrize("blocked_component", ["hard", "soft"])
def test_duo_keeps_blocking_component_nodes_without_inventing_edges(
    monkeypatch, blocked_component,
):
    """Retain all composed nodes when one component has no transitions."""
    hard, soft = _components()
    blocked = hard if blocked_component == "hard" else soft
    blocked.remove_edges_from(list(blocked.edges))
    duo = _build(monkeypatch, hard, soft)
    assert len(duo) == 12
    assert duo.number_of_edges() == 0
    assert duo.graph["initial"] == {("h0", "s0", 1)}
    assert duo.graph["accept"] == {("h1", name, 1) for name in ("s0", "s1", "s2")}


def test_duo_reads_replaced_guard_again_on_a_later_build(monkeypatch):
    """A later build uses a new component guard without changing earlier edges."""
    hard, soft = _components()
    old_guard = soft.edges["s0", "s1"]["guard"]
    first = _build(monkeypatch, hard, soft)
    new_guard = parse_guard("!pref")
    soft.edges["s0", "s1"]["guard"] = new_guard
    second = _build(monkeypatch, hard, soft)
    pair = (("h0", "s0", 1), ("h1", "s1", 1))
    assert first.edges[pair]["softguard"] is old_guard
    assert second.edges[pair]["softguard"] is new_guard
    assert list(first) == list(second)
    assert list(first.edges) == list(second.edges)
