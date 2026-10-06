"""Tests for TS-Büchi product automata."""

from networkx import DiGraph
import pytest

from ltl_automaton_planner_core.boolean_formulas.parser import (
    parse as parse_guard,
)
from ltl_automaton_planner_core.ltl_tools.product import ProdAut
from ltl_automaton_planner_core.ltl_tools import buchi as buchi_module
from ltl_automaton_planner_core.ltl_tools.discrete_plan import dijkstra_plan_networkX
from ltl_automaton_planner_core.ltl_tools import product as product_module


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


def test_accepting_state_must_belong_to_a_cycle():
    """Exclude an accepting state that only reaches a nonaccepting cycle."""
    product = ProdAut(create_test_ts(), create_test_buchi())
    product.add_edges_from([("accept", "other"), ("other", "other")])
    product.graph["accept"] = {"accept"}
    product.build_accept_with_cycle()
    assert product.graph["accept_with_cycle"] == set()


def test_accepting_cycle_cache_is_rebuilt_after_edge_removal():
    """Discard accepting states whose cycle has been removed."""
    product = ProdAut(create_test_ts(), create_test_buchi())
    product.add_edge("accept", "accept")
    product.graph["accept"] = {"accept"}
    product.build_accept_with_cycle()
    assert product.graph["accept_with_cycle"] == {"accept"}
    product.remove_edge("accept", "accept")
    product.build_accept_with_cycle()
    assert product.graph["accept_with_cycle"] == set()


def test_full_product_rebuild_discards_removed_ts_edges():
    """Remove stale Product edges when rebuilding a changed source graph."""
    ts = create_test_ts()
    product = ProdAut(ts, create_test_buchi())
    product.build_full()
    ts.remove_edge("s1", "s1")
    product.build_full()
    assert not product.has_edge(("s1", "q1"), ("s1", "q1"))
    assert product.graph["accept_with_cycle"] == set()


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


class _CountingGuard:
    """Small deterministic guard double for product cache checks."""

    def __init__(self, required_label, distance):
        self.required_label = required_label
        self.distance_value = distance

    def check(self, label):
        return self.required_label in label

    def distance(self, label):
        del label
        return self.distance_value


def create_cached_safe_product():
    """Create a safe Büchi product with shared and distinct guard groups."""
    ts = DiGraph(initial={"allow", "deny"})
    ts.add_node("allow", label={"allow"})
    ts.add_node("deny", label={"deny"})
    ts.add_edge("allow", "allow", weight=2.0, action="stay_allow")
    ts.add_edge("deny", "deny", weight=2.0, action="stay_deny")

    buchi = DiGraph(
        type="safe_buchi",
        initial={"source"},
        accept={"shared_a"},
    )
    buchi.add_nodes_from(["source", "shared_a", "shared_b", "distinct"])
    shared_hard = _CountingGuard("allow", 0.0)
    shared_soft = _CountingGuard("preferred", 0.5)
    buchi.add_edge(
        "source",
        "shared_a",
        hardguard=shared_hard,
        softguard=shared_soft,
    )
    buchi.add_edge(
        "source",
        "shared_b",
        hardguard=shared_hard,
        softguard=shared_soft,
    )
    buchi.add_edge(
        "source",
        "distinct",
        hardguard=shared_hard,
        softguard=_CountingGuard("other", 2.0),
    )
    return ProdAut(ts, buchi, beta=3.0)


def test_build_full_caches_shared_safe_guards_per_ts_label(monkeypatch):
    """Cache shared guards per source label and rebuild after label changes."""
    product = create_cached_safe_product()
    original_check = product_module.check_label_for_buchi_edge
    calls = []

    def counting_check(buchi, label, source, target):
        data = buchi.edges[source, target]
        calls.append(
            (
                id(data["hardguard"]),
                id(data["softguard"]),
                frozenset(label),
            )
        )
        return original_check(buchi, label, source, target)

    monkeypatch.setattr(
        product_module,
        "check_label_for_buchi_edge",
        counting_check,
    )
    product.build_full()

    assert len(calls) == 4
    assert len(set(calls)) == 4
    allow_source = ("allow", "source")
    deny_source = ("deny", "source")
    assert product.has_edge(allow_source, ("allow", "shared_a"))
    assert product.has_edge(allow_source, ("allow", "shared_b"))
    assert product.has_edge(allow_source, ("allow", "distinct"))
    assert not list(product.out_edges(deny_source))
    edge_data = product.edges[allow_source, ("allow", "shared_a")]
    assert edge_data["soft_task_dist"] == 0.5
    assert edge_data["weight"] == 2.0 + 3.0 * 0.5
    distinct_edge = product.edges[allow_source, ("allow", "distinct")]
    assert distinct_edge["soft_task_dist"] == 2.0
    assert distinct_edge["weight"] == 2.0 + 3.0 * 2.0

    product.graph["ts"].nodes["allow"]["label"] = {"deny"}
    product.build_full()
    assert not list(product.out_edges(allow_source))

    product.graph["ts"].nodes["allow"]["label"] = {"allow"}
    product.build_full()
    assert product.has_edge(allow_source, ("allow", "shared_a"))

    # Even an unchanged guard object must be reevaluated after a rebuild.
    product.graph["buchi"].edges["source", "shared_a"]["hardguard"].required_label = "deny"
    product.build_full()
    assert not list(product.out_edges(allow_source))
    assert product.has_edge(deny_source, ("deny", "shared_a"))


@pytest.mark.parametrize("buchi_type", ["hard_buchi", "soft_buchi"])
def test_parallel_promela_guards_preserve_feasibility_and_cost(monkeypatch, buchi_type):
    """Retain an earlier enabled branch in hard and soft Product planning."""
    claim = """never { /* <> (cargo || danger) */
T0_init:
    if
    :: (cargo) -> goto accept_S1
    :: (danger) -> goto accept_S1
    fi;
accept_S1:
    skip
}
"""
    monkeypatch.setattr(buchi_module, "run_ltl2ba", lambda formula: claim)
    buchi = buchi_module.buchi_from_ltl("<> (cargo || danger)", buchi_type)
    ts = DiGraph(initial={"s0"})
    ts.add_node("s0", label={"cargo"})
    ts.add_edge("s0", "s0", weight=2.0, action="stay")
    product = ProdAut(ts, buchi, beta=5)
    product.build_full()

    initial = ("s0", "T0_init")
    accepting = ("s0", "accept_S1")
    assert product.has_edge(initial, accepting)
    edge = product.edges[initial, accepting]
    assert edge["transition_cost"] == 2.0
    assert edge["soft_task_dist"] == 0
    assert edge["weight"] == 2.0

    run, _ = dijkstra_plan_networkX(product, gamma=10)
    assert run is not None
    assert run.prefix == [initial, accepting]
    assert run.suffix == [accepting]
    assert run.precost == 2.0
    assert run.sufcost == 2.0
    assert run.totalcost == 2.0 + 10 * 2.0


def _branched_product(buchi_type):
    ts = DiGraph(initial={"s0"})
    ts.add_node("s0", label={"allow"})
    ts.add_node("s1", label={"preferred"})
    ts.add_node("isolated", label=set())
    ts.add_edge("s0", "s1", weight=0.1, action="go")
    ts.add_edge("s0", "s0", weight=0.2, action="stay")
    ts.add_edge("s1", "s0", weight=0.3, action="return")
    buchi = DiGraph(type=buchi_type, initial={"q0"}, accept={"q1"})
    buchi.add_nodes_from(["q0", "q1", "q2"])
    hard_guard = parse_guard("allow")
    soft_guard = parse_guard("preferred")
    if buchi_type == "safe_buchi":
        guards = dict(hardguard=hard_guard, softguard=soft_guard)
    else:
        guards = dict(guard=hard_guard if buchi_type == "hard_buchi" else soft_guard)
    buchi.add_edge("q0", "q1", **guards)
    buchi.add_edge("q1", "q1", **guards)
    return ProdAut(ts, buchi, beta=2.5)


@pytest.mark.parametrize("buchi_type", ["hard_buchi", "soft_buchi", "safe_buchi"])
def test_full_product_preserves_branched_order_attributes_and_source_costs(buchi_type):
    """Match hand-specified graph results with branching and isolated states."""
    product = _branched_product(buchi_type)
    product.build_full()
    expected_nodes = [
        ("s0", "q0"), ("s1", "q1"), ("s0", "q1"), ("s0", "q2"),
        ("s1", "q0"), ("s1", "q2"),
        ("isolated", "q0"), ("isolated", "q1"), ("isolated", "q2"),
    ]
    expected_edges = [
        (("s0", "q0"), ("s1", "q1")),
        (("s0", "q0"), ("s0", "q1")),
        (("s0", "q1"), ("s1", "q1")),
        (("s0", "q1"), ("s0", "q1")),
    ]
    if buchi_type == "soft_buchi":
        expected_edges.insert(2, (("s1", "q1"), ("s0", "q1")))
        expected_edges.append((("s1", "q0"), ("s0", "q1")))
    assert list(product) == expected_nodes
    assert list(product.edges) == expected_edges
    assert product.graph["initial"] == {("s0", "q0")}
    assert product.possible_states == {("s0", "q0")}
    assert product.graph["accept"] == {
        ("s0", "q1"), ("s1", "q1"), ("isolated", "q1"),
    }
    cyclic_accepts = {("s0", "q1")}
    if buchi_type == "soft_buchi":
        cyclic_accepts.add(("s1", "q1"))
    assert product.graph["accept_with_cycle"] == cyclic_accepts
    for node, attributes in product.nodes(data=True):
        assert attributes == dict(ts=node[0], buchi=node[1], marker="unvisited")
    for source, target, attributes in product.edges(data=True):
        ts_edge = product.graph["ts"].edges[source[0], target[0]]
        distance = int(buchi_type != "hard_buchi" and source[0] == "s0")
        assert attributes == dict(
            transition_cost=ts_edge["weight"], soft_task_dist=distance,
            weight=ts_edge["weight"] + 2.5 * distance, action=ts_edge["action"],
        )


def test_full_product_rebuild_reads_changed_ts_successors_cost_and_action():
    """Rebuild from changed source data without retaining old transitions."""
    product = _branched_product("soft_buchi")
    ts, buchi = product.graph["ts"], product.graph["buchi"]
    product.build_full()
    ts.edges["s0", "s1"].update(weight=7.0, action="updated_go")
    ts.remove_edge("s0", "s0")
    ts.add_edge("s0", "isolated", weight=4.0, action="new_exit")
    ts.graph["initial"] = {"s1"}
    product.build_full()
    assert product.graph["ts"] is ts
    assert product.graph["buchi"] is buchi
    assert product.graph["initial"] == {("s1", "q0")}
    assert product.possible_states == {("s1", "q0")}
    assert product.graph["accept_with_cycle"] == {("s0", "q1"), ("s1", "q1")}
    for source in (("s0", "q0"), ("s0", "q1")):
        assert not product.has_edge(source, ("s0", "q1"))
        assert product.edges[source, ("s1", "q1")] == dict(
            transition_cost=7.0, soft_task_dist=1, weight=9.5, action="updated_go",
        )
        assert product.edges[source, ("isolated", "q1")] == dict(
            transition_cost=4.0, soft_task_dist=1, weight=6.5, action="new_exit",
        )
