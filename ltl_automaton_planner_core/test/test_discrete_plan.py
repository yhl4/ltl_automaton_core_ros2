"""Tests for discrete prefix-suffix planning."""

from networkx import DiGraph

from ltl_automaton_planner_core.boolean_formulas.parser import (
    parse as parse_guard,
)
from ltl_automaton_planner_core.ltl_tools.discrete_plan import (
    dijkstra_plan_networkX,
    improve_plan_given_history,
    prod_states_given_history,
)
from ltl_automaton_planner_core.ltl_tools import discrete_plan
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


def make_weighted_product(edges, initial="s0", accepting="s1"):
    """Build a one-state Büchi product for hand-computed cycle costs."""
    ts = DiGraph(initial={initial})
    for source, target, cost in edges:
        ts.add_edge(source, target, weight=cost, action=f"{source}_to_{target}")
    for state in ts:
        ts.nodes[state]["label"] = set()
    buchi = DiGraph(type="hard_buchi", initial={"q0"}, accept={"q0"})
    buchi.add_edge("q0", "q0", guard=parse_guard("1"))
    product = ProdAut(ts, buchi)
    product.build_full()
    product.graph["accept"] = {(accepting, "q0")}
    product.build_accept_with_cycle()
    return product


def test_cheaper_cycle_is_considered_alongside_accepting_self_loop():
    """Choose cost 4 rather than an accepting self-loop costing 100."""
    product = make_weighted_product([
        ("s0", "s1", 1), ("s1", "s1", 100),
        ("s1", "s2", 2), ("s2", "s1", 2),
    ])
    run, _ = dijkstra_plan_networkX(product, gamma=10)
    assert run.precost == 1
    assert run.sufcost == 4
    assert run.totalcost == 41
    assert run.suf_plan == ["s1_to_s2", "s2_to_s1"]


def test_zero_cost_cycle_has_finite_prefix_and_suffix_paths():
    """Do not follow cyclic predecessor links on zero-cost shortest paths."""
    product = make_weighted_product([("s0", "s1", 0), ("s1", "s0", 0)])
    run, _ = dijkstra_plan_networkX(product)
    assert run.totalcost == 0
    assert run.prefix == [("s0", "q0"), ("s1", "q0")]
    assert run.suffix == [("s1", "q0"), ("s0", "q0")]


def test_zero_cost_accepting_self_loop():
    """Keep a zero-cost self-loop without a cyclic prefix reconstruction."""
    product = make_weighted_product([("s1", "s1", 0)], initial="s1")
    run, _ = dijkstra_plan_networkX(product)
    assert run.totalcost == 0
    assert run.prefix == [("s1", "q0")]
    assert run.suffix == [("s1", "q0")]


def test_accepting_dead_end_is_excluded_from_cycle_search(monkeypatch):
    """Ignore a cheaper accepting dead end that only reaches a nonaccepting cycle."""
    product = make_weighted_product([
        ("s0", "s1", 3), ("s1", "s1", 1),
        ("s0", "dead", 0), ("dead", "sink", 0), ("sink", "sink", 0),
    ])
    product.graph["accept"].add(("dead", "q0"))
    product.build_accept_with_cycle()
    searched_sources = []
    original_search = discrete_plan.single_source_dijkstra

    def record_search(graph, source, **kwargs):
        searched_sources.append(source)
        return original_search(graph, source, **kwargs)

    monkeypatch.setattr(discrete_plan, "single_source_dijkstra", record_search)
    run, _ = dijkstra_plan_networkX(product, gamma=10)
    assert (run.precost, run.sufcost, run.totalcost) == (3, 1, 13)
    assert ("dead", "q0") not in searched_sources


def test_no_accepting_cycle_returns_without_shortest_path_search(monkeypatch):
    """Reject an acyclic accepting graph before attempting prefix search."""
    product = make_weighted_product([("s0", "s1", 1)])

    def unexpected_search(*args, **kwargs):
        raise AssertionError("A graph without an accepting cycle needs no path search.")

    monkeypatch.setattr(discrete_plan, "single_source_dijkstra", unexpected_search)
    monkeypatch.setattr(discrete_plan, "multi_source_dijkstra", unexpected_search)
    assert dijkstra_plan_networkX(product) == (None, None)


def test_networkx_dijkstra_uses_explicit_start_without_mutating_initial():
    """Use an explicit Product start and preserve the graph's initial set."""
    product = create_test_product()
    previous_initial = set(product.graph["initial"])

    run, _ = dijkstra_plan_networkX(
        product,
        start_set={("s1", "q1")},
    )
    assert run is not None
    assert run.prefix == [("s1", "q1")]
    assert product.graph["initial"] == previous_initial

    assert dijkstra_plan_networkX(product, start_set=set()) == (None, None)
    assert product.graph["initial"] == previous_initial


def test_networkx_dijkstra_uses_one_multi_source_prefix(monkeypatch):
    """Choose the best real source without per-source prefix searches."""
    product = make_weighted_product([
        ("i1", "goal", 2), ("i2", "goal", 1),
        ("goal", "goal", 3),
    ], initial="i1", accepting="goal")
    product.graph["initial"] = {
        ("i1", "q0"),
        ("i2", "q0"),
    }
    multi_calls = []
    suffix_sources = []
    original_multi = discrete_plan.multi_source_dijkstra
    original_single = discrete_plan.single_source_dijkstra

    def record_multi(graph, sources, **kwargs):
        multi_calls.append(set(sources))
        return original_multi(graph, sources, **kwargs)

    def record_single(graph, source, **kwargs):
        suffix_sources.append(source)
        return original_single(graph, source, **kwargs)

    monkeypatch.setattr(discrete_plan, "multi_source_dijkstra", record_multi)
    monkeypatch.setattr(discrete_plan, "single_source_dijkstra", record_single)
    run, _ = dijkstra_plan_networkX(product, gamma=10)

    assert run is not None
    assert run.prefix[0] == ("i2", "q0")
    assert run.precost == 1
    assert run.totalcost == 31
    assert len(multi_calls) == 1
    assert suffix_sources == [("goal", "q0")]


def test_networkx_dijkstra_skips_unreachable_accepting_cycle_suffix(monkeypatch):
    """Do not run suffix search for an accepting cycle unreachable from starts."""
    product = make_weighted_product([
        ("s0", "goal", 1), ("goal", "goal", 1),
        ("dead", "dead", 0),
    ], accepting="goal")
    product.graph["accept"].add(("dead", "q0"))
    product.build_accept_with_cycle()
    suffix_sources = []
    original_single = discrete_plan.single_source_dijkstra

    def record_single(graph, source, **kwargs):
        suffix_sources.append(source)
        return original_single(graph, source, **kwargs)

    monkeypatch.setattr(discrete_plan, "single_source_dijkstra", record_single)
    run, _ = dijkstra_plan_networkX(product)

    assert run is not None
    assert suffix_sources == [("goal", "q0")]


def test_networkx_dijkstra_zero_cost_multi_source_prefix_is_finite():
    """Keep a finite zero-cost cycle and begin the prefix at its explicit start."""
    product = make_weighted_product([
        ("i1", "goal", 0), ("goal", "i1", 0),
        ("i2", "goal", 0),
    ], initial="i1", accepting="goal")
    starts = {("i1", "q0"), ("i2", "q0")}
    run, _ = dijkstra_plan_networkX(
        product,
        start_set=starts,
    )

    assert run is not None
    assert run.prefix[0] in starts
    assert run.prefix[-1] == ("goal", "q0")
    assert len(run.prefix) <= len(product)
    assert run.totalcost == 0


def test_product_history_follows_complete_product_successors():
    """Resolve a source-label history through the built Product graph."""
    product = create_test_product()

    assert prod_states_given_history(product, ["s0", "s1"]) == {
        ("s1", "q1"),
    }
    assert prod_states_given_history(product, []) == set()
    assert prod_states_given_history(product, ["unknown"]) == set()
    assert prod_states_given_history(product, ["s0", "s0"]) == set()
    assert improve_plan_given_history(product, ["unknown"]) is None
    assert improve_plan_given_history(product, ["s0", "s0"]) is None


def test_history_replanning_passes_gamma_to_networkx_search():
    """Select different accepted cycles for gamma one and ten."""
    product = make_weighted_product([
        ("s0", "a", 0), ("a", "a", 4),
        ("s0", "b", 8), ("b", "b", 1),
    ])
    product.graph["accept"] = {
        ("a", "q0"),
        ("b", "q0"),
    }
    product.build_accept_with_cycle()

    low_gamma = improve_plan_given_history(
        product,
        ["s0"],
        gamma=1,
    )
    high_gamma = improve_plan_given_history(
        product,
        ["s0"],
        gamma=10,
    )

    assert low_gamma is not None
    assert high_gamma is not None
    assert low_gamma.suffix == [("a", "q0")]
    assert low_gamma.totalcost == 4
    assert high_gamma.suffix == [("b", "q0")]
    assert high_gamma.totalcost == 18
