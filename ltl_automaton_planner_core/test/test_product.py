"""Tests for TS-Büchi product automata."""

from copy import deepcopy

from networkx import DiGraph
import pytest

from ltl_automaton_planner_core.boolean_formulas.parser import (
    parse as parse_guard,
)
from ltl_automaton_planner_core.ltl_tools.product import ProdAut
from ltl_automaton_planner_core.ltl_tools.product import ProdAut_Run
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


@pytest.mark.parametrize("with_nodes, accept_type", [(False, set), (True, frozenset)])
def test_empty_acceptance_resets_cycles_without_scc_and_recomputes_when_restored(
    with_nodes, accept_type, monkeypatch,
):
    """Skip an empty acceptance set and reread restored accepting self-loops."""
    product = ProdAut(create_test_ts(), create_test_buchi())
    if with_nodes:
        product.build_full()
    product.graph["accept"] = accept_type()
    empty_acceptance = product.graph["accept"]
    previous_cycles = {"stale"}
    product.graph["accept_with_cycle"] = previous_cycles
    before_nodes = [(node, dict(data)) for node, data in product.nodes(data=True)]
    before_edges = [(source, target, dict(data)) for source, target, data
                    in product.edges(data=True)]
    initial = set(product.graph["initial"])
    possible = set(product.possible_states) if with_nodes else None
    scc_calls = []
    original_scc = product_module.strongly_connected_components

    def record_scc(graph):
        scc_calls.append(graph)
        return original_scc(graph)

    monkeypatch.setattr(product_module, "strongly_connected_components", record_scc)
    product.build_accept_with_cycle()
    assert scc_calls == []
    assert product.graph["accept_with_cycle"] == set()
    assert product.graph["accept_with_cycle"] is not previous_cycles
    assert previous_cycles == {"stale"}
    assert product.graph["accept"] is empty_acceptance
    assert list(product.nodes(data=True)) == before_nodes
    assert list(product.edges(data=True)) == before_edges
    assert product.graph["initial"] == initial
    if with_nodes:
        assert product.possible_states == possible
        goal = ("s1", "q1")
        product.graph["accept"] = {goal}
        product.build_accept_with_cycle()
        assert scc_calls == [product]
        assert product.graph["accept_with_cycle"] == {goal}
        product.remove_edge(goal, goal)
        product.build_accept_with_cycle()
        assert scc_calls == [product, product]
        assert product.graph["accept_with_cycle"] == set()
        assert product.graph["initial"] == initial
        assert product.possible_states == possible


@pytest.mark.parametrize("self_loop", [False, True])
def test_missing_acceptance_keeps_original_scc_diagnostics(self_loop, monkeypatch):
    """Preserve acyclic fallback and exact cyclic error when accept is absent."""
    product = ProdAut(create_test_ts(), create_test_buchi())
    product.add_node("plain")
    if self_loop:
        product.add_edge("plain", "plain")
    del product.graph["accept"]
    previous_cycles = {"stale"}
    product.graph["accept_with_cycle"] = previous_cycles
    scc_calls = []
    original_scc = product_module.strongly_connected_components

    def record_scc(graph):
        scc_calls.append(graph)
        return original_scc(graph)

    monkeypatch.setattr(product_module, "strongly_connected_components", record_scc)
    if self_loop:
        with pytest.raises(KeyError) as caught:
            product.build_accept_with_cycle()
        assert caught.value.args == ("accept",)
        assert product.graph["accept_with_cycle"] is previous_cycles
    else:
        product.build_accept_with_cycle()
        assert product.graph["accept_with_cycle"] == set()
        assert product.graph["accept_with_cycle"] is not previous_cycles
    assert scc_calls == [product]
    assert "accept" not in product.graph
    assert previous_cycles == {"stale"}
    assert list(product) == ["plain"]
    assert list(product.edges) == ([("plain", "plain")] if self_loop else [])


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


def _legacy_margin_product(buchi_type, matching_branch_first):
    ts = DiGraph(initial={"s0"})
    ts.add_nodes_from([("s0", {"label": {"allow"}}), ("s1", {"label": {"allow"}})])
    ts.add_edge("s0", "s1", weight=2, action="go")
    ts.add_edge("s1", "s1", weight=3, action="stay")
    buchi = DiGraph(type=buchi_type, initial={"q0"}, accept={"q1"})
    buchi.add_nodes_from(["q0", "q1", "q2"])
    if buchi_type == "safe_buchi":
        guards = {"hardguard": parse_guard("allow"), "softguard": parse_guard("preferred")}
    else:
        guards = {"guard": parse_guard("allow" if buchi_type == "hard_buchi" else "preferred")}
    targets = ["q1", "q2"] if matching_branch_first else ["q2", "q1"]
    for target in targets:
        buchi.add_edge("q0", target, **guards)
    buchi.add_edge("q1", "q0", **guards)
    buchi.add_edge("q1", "q1", **guards)
    return ProdAut(ts, buchi, beta=4)


def _legacy_margin_input_snapshot(ts, buchi):
    return deepcopy((
        list(ts.nodes(data=True)), list(ts.edges(data=True)), list(buchi.nodes(data=True)),
        [(source, target, [(name, id(guard), vars(guard)) for name, guard in data.items()])
         for source, target, data in buchi.edges(data=True)],
    ))


@pytest.mark.parametrize("buchi_type", ["hard_buchi", "soft_buchi", "safe_buchi"])
@pytest.mark.parametrize("matching_branch_first", [False, True])
def test_legacy_margin_membership_survives_other_edges_and_refreshes(
    buchi_type, matching_branch_first,
):
    """Apply each alternating demo pair regardless of earlier membership queries."""
    product = _legacy_margin_product(buchi_type, matching_branch_first)
    first_pair = (("s0", "q0"), ("s1", "q1"))
    second_pair = (("s1", "q0"), ("s1", "q2"))
    # Duplicate pairs are one membership hit; an unpaired final entry is ignored.
    opt_path = list(first_pair + second_pair + first_pair + (("unpaired", "q9"),))
    before_path = tuple(opt_path)
    ts = product.graph["ts"]
    buchi = product.graph["buchi"]
    before_inputs = _legacy_margin_input_snapshot(ts, buchi)
    penalty = 0 if buchi_type == "hard_buchi" else 4
    expected = {
        (("s0", "q0"), ("s1", "q2")): 3 + penalty,
        first_pair: 2 + penalty,
        (("s0", "q1"), ("s1", "q0")): 3 + penalty,
        (("s0", "q1"), ("s1", "q1")): 3 + penalty,
        second_pair: 3 + penalty,
        (("s1", "q0"), ("s1", "q1")): 4 + penalty,
        # This consecutive pair bridges two demo pairs and must keep its margin.
        (("s1", "q1"), ("s1", "q0")): 4 + penalty,
        (("s1", "q1"), ("s1", "q1")): 4 + penalty,
    }

    product.build_full_margin(opt_path)

    assert set(product.edges) == set(expected)
    for edge, weight in expected.items():
        assert product.edges[edge] == {
            "weight": weight,
            "transition_cost": 2 if edge[0][0] == "s0" else 3,
            "soft_task_dist": 0 if buchi_type == "hard_buchi" else 1,
        }
    assert product.graph["initial"] == {("s0", "q0")}
    assert product.graph["accept"] == {("s0", "q1"), ("s1", "q1")}
    assert product.graph["accept_with_cycle"] == {("s1", "q1")}
    assert tuple(opt_path) == before_path
    assert _legacy_margin_input_snapshot(ts, buchi) == before_inputs
    previous_nodes = list(product.nodes(data=True))
    previous_edges = list(product.edges)

    loop_pair = (("s1", "q1"), ("s1", "q1"))
    product.build_full_margin(loop_pair)

    expected[first_pair] += 1
    expected[second_pair] += 1
    expected[loop_pair] -= 1
    assert {edge: product.edges[edge]["weight"] for edge in product.edges} == expected
    assert list(product.nodes(data=True)) == previous_nodes
    assert list(product.edges) == previous_edges
    assert _legacy_margin_input_snapshot(ts, buchi) == before_inputs


@pytest.mark.parametrize("opt_path", [[], [("s0", "q0")]])
def test_legacy_margin_short_input_keeps_all_edge_penalties(opt_path):
    """Keep the original full margin when the input has no complete pair."""
    product = _legacy_margin_product("hard_buchi", False)

    product.build_full_margin(opt_path)

    assert product.number_of_edges() == 8
    assert all(
        data["weight"] == data["transition_cost"] + 1
        for _, _, data in product.edges(data=True)
    )


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


def test_run_output_reuses_each_edge_lookup_and_refreshes_repeated_actions(monkeypatch):
    """Read each edge once while retaining repeated actions and fresh output lists."""
    product = ProdAut(create_test_ts(), create_test_buchi())
    product.build_full()
    ts = product.graph["ts"]
    lookups = []
    original_getitem = DiGraph.__getitem__

    def record_lookup(graph, source):
        if graph is ts:
            lookups.append(source)
        return original_getitem(graph, source)

    monkeypatch.setattr(DiGraph, "__getitem__", record_lookup)
    start, goal = ("s0", "q0"), ("s1", "q1")
    prefix, suffix = [start, goal, goal, goal], [goal]
    before = [(source, target, dict(data)) for source, target, data
              in product.edges(data=True)]
    before_ts = [(source, target, dict(data)) for source, target, data in ts.edges(data=True)]
    run = ProdAut_Run(product, prefix, 4, suffix, 1, 14)
    assert run.prefix is prefix and run.suffix is suffix
    assert prefix == [start, goal, goal, goal] and suffix == [goal]
    assert run.line == ["s0", "s1", "s1", "s1"]
    assert run.loop == ["s1", "s1"]
    assert run.pre_prod_edges == [(start, goal), (goal, goal), (goal, goal)]
    assert run.suf_prod_edges == [(goal, goal)]
    assert run.pre_plan == ["goto_s1", "stay_s1", "stay_s1"]
    assert run.suf_plan == ["stay_s1"]
    assert run.pre_plan_cost == [0, 2.0, 1.0, 1.0]
    assert run.suf_plan_cost == [0, 1.0]
    assert (run.precost, run.sufcost, run.totalcost) == (4, 1, 14)
    assert list(run.pre_ts_edges) == list(run.suf_ts_edges) == []
    assert lookups == ["s0", "s1", "s1", "s1"]
    assert list(product.edges(data=True)) == before
    assert list(ts.edges(data=True)) == before_ts
    old_outputs = (run.pre_plan, run.suf_plan, run.pre_plan_cost, run.suf_plan_cost)
    ts.edges["s1", "s1"].update(action="changed_stay", weight=7)
    updated_ts = [(source, target, dict(data)) for source, target, data in ts.edges(data=True)]
    lookups.clear()
    run.plan_output(product)
    assert lookups == ["s0", "s1", "s1", "s1"]
    assert run.pre_plan == ["goto_s1", "changed_stay", "changed_stay"]
    assert run.suf_plan == ["changed_stay"]
    assert run.pre_plan_cost == [0, 2.0, 7, 7]
    assert run.suf_plan_cost == [0, 7]
    assert (run.precost, run.sufcost, run.totalcost) == (4, 1, 14)
    assert old_outputs == (["goto_s1", "stay_s1", "stay_s1"], ["stay_s1"],
                           [0, 2.0, 1.0, 1.0], [0, 1.0])
    assert all(new is not old for new, old in zip(
        (run.pre_plan, run.suf_plan, run.pre_plan_cost, run.suf_plan_cost), old_outputs,
    ))
    assert list(product.edges(data=True)) == before
    assert list(ts.edges(data=True)) == updated_ts


@pytest.mark.parametrize("container", [list, tuple])
def test_prod_run_to_prod_edges_repeated_prefix_and_empty_suffix(container):
    """Keep repeated edge order and empty suffix without changing run fields."""
    product = ProdAut(create_test_ts(), create_test_buchi())
    product.build_full()
    start, goal = ("s0", "q0"), ("s1", "q1")
    run = ProdAut_Run(product, [start, goal], 2, [goal], 1, 12)
    prefix = container([start, goal, goal, goal])
    suffix = []
    old_pre_edges = run.pre_prod_edges
    old_suf_edges = run.suf_prod_edges
    old_fields = deepcopy(
        (
            run.line,
            run.loop,
            run.pre_plan,
            run.suf_plan,
            run.pre_plan_cost,
            run.suf_plan_cost,
            run.precost,
            run.sufcost,
            run.totalcost,
        )
    )
    run.prefix = prefix
    run.suffix = suffix

    run.prod_run_to_prod_edges()

    assert run.pre_prod_edges == [
        (start, goal),
        (goal, goal),
        (goal, goal),
    ]
    assert run.suf_prod_edges == []
    assert isinstance(run.pre_prod_edges, list)
    assert isinstance(run.suf_prod_edges, list)
    assert run.pre_prod_edges is not prefix
    assert run.pre_prod_edges is not old_pre_edges
    assert run.suf_prod_edges is not suffix
    assert prefix == container([start, goal, goal, goal])
    assert suffix == []
    assert (
        run.line,
        run.loop,
        run.pre_plan,
        run.suf_plan,
        run.pre_plan_cost,
        run.suf_plan_cost,
        run.precost,
        run.sufcost,
        run.totalcost,
    ) == old_fields
    assert old_suf_edges == [(goal, goal)]


def test_prod_run_to_prod_edges_tuple_suffix_keeps_partial_update_error():
    """Keep tuple suffix concatenation TypeError after prefix update."""
    product = ProdAut(create_test_ts(), create_test_buchi())
    product.build_full()
    start, goal = ("s0", "q0"), ("s1", "q1")
    run = ProdAut_Run(product, [start, goal], 2, [goal], 1, 12)
    old_suf_edges = run.suf_prod_edges
    run.prefix = [start, goal, goal]
    run.suffix = (goal,)

    with pytest.raises(TypeError):
        run.prod_run_to_prod_edges()

    assert run.pre_prod_edges == [(start, goal), (goal, goal)]
    assert run.suf_prod_edges is old_suf_edges
    assert run.suf_prod_edges == [(goal, goal)]


@pytest.mark.parametrize("empty_prefix", [False, True])
def test_run_output_keeps_empty_prefix_and_single_node_suffix(empty_prefix, monkeypatch):
    """Keep no prefix actions and exactly one accepting self-loop action."""
    product = ProdAut(create_test_ts(), create_test_buchi())
    product.build_full()
    ts = product.graph["ts"]
    lookups = []
    original_getitem = DiGraph.__getitem__

    def record_lookup(graph, source):
        if graph is ts:
            lookups.append(source)
        return original_getitem(graph, source)

    monkeypatch.setattr(DiGraph, "__getitem__", record_lookup)
    goal = ("s1", "q1")
    prefix = [] if empty_prefix else [goal]
    run = ProdAut_Run(product, prefix, 0, [goal], 1, 10)
    assert run.line == ([] if empty_prefix else ["s1"])
    assert run.loop == ["s1", "s1"]
    assert run.pre_prod_edges == []
    assert run.suf_prod_edges == [(goal, goal)]
    assert run.pre_plan == [] and run.pre_plan_cost == [0]
    assert run.suf_plan == ["stay_s1"] and run.suf_plan_cost == [0, 1.0]
    assert lookups == ["s1"]


@pytest.mark.parametrize("missing_field", ["action", "weight"])
def test_run_output_edge_error_preserves_action_before_weight(missing_field):
    """Keep exact KeyError and prefix output produced before a missing edge field."""
    product = ProdAut(create_test_ts(), create_test_buchi())
    product.build_full()
    start, goal = ("s0", "q0"), ("s1", "q1")
    run = ProdAut_Run(product, [start, goal], 2, [goal], 1, 12)
    ts = product.graph["ts"]
    del ts.edges["s0", "s1"][missing_field]
    before = [(source, target, dict(data)) for source, target, data in ts.edges(data=True)]
    with pytest.raises(KeyError) as caught:
        run.plan_output(product)
    assert caught.value.args == (missing_field,)
    assert run.pre_plan == ([] if missing_field == "action" else ["goto_s1"])
    assert run.pre_plan_cost == [0]
    assert run.suf_plan == ["stay_s1"] and run.suf_plan_cost == [0, 1.0]
    assert list(ts.edges(data=True)) == before
