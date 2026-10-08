"""Tests for discrete prefix-suffix planning."""

from collections import Counter

from networkx import DiGraph
from networkx import single_source_dijkstra_path_length
import pytest

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
        ts.add_edge(
            source,
            target,
            weight=cost,
            action=f"{source}_to_{target}",
        )
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


@pytest.mark.parametrize("target_first", [True, False])
def test_tight_recovery_keeps_path_with_target_first_or_last(target_first):
    """Recover the same direct path independently of sibling adjacency order."""
    graph = DiGraph()
    edges = [("source", "branch", 1), ("branch", "tail", 1)]
    edges.insert(0 if target_first else 1, ("source", "target", 1))
    graph.add_weighted_edges_from(edges)
    distances = single_source_dijkstra_path_length(graph, "source")
    before = [(source, target, dict(data)) for source, target, data in graph.edges(data=True)]
    assert discrete_plan._restore_tight_path(
        graph, distances, {"source"}, "target",
    ) == ["source", "target"]
    assert list(graph.edges(data=True)) == before
    assert distances == {"source": 0, "branch": 1, "target": 1, "tail": 2}


def test_tight_recovery_preserves_first_parent_through_zero_cost_ties():
    """Keep the original BFS parent choice even with later equal paths and cycles."""
    graph = DiGraph()
    graph.add_weighted_edges_from([
        ("source", "a", 0), ("source", "b", 0),
        ("a", "b", 0), ("b", "a", 0),
        ("a", "target", 1), ("b", "target", 1),
    ])
    distances = single_source_dijkstra_path_length(graph, "source")
    assert discrete_plan._restore_tight_path(
        graph, distances, {"source"}, "target",
    ) == ["source", "a", "target"]
    assert discrete_plan._restore_tight_path(
        graph, distances, {"source", "target"}, "target",
    ) == ["target"]


def test_float_shortest_path_recovery_uses_exact_distances():
    """Recover the strict Dijkstra path for 0.1 + 0.2 versus 0.3."""
    product = make_weighted_product([
        ("s0", "via", 0.1), ("via", "goal", 0.2),
        ("s0", "goal", 0.3), ("goal", "goal", 1.0),
    ], accepting="goal")
    run, _ = dijkstra_plan_networkX(product)

    assert run is not None
    assert run.precost == 0.3
    assert run.prefix == [("s0", "q0"), ("goal", "q0")]


def test_accepting_dead_end_is_excluded_from_cycle_search(monkeypatch):
    """Ignore an accepting dead end with no accepting cycle."""
    product = make_weighted_product([
        ("s0", "s1", 3), ("s1", "s1", 1),
        ("s0", "dead", 0), ("dead", "sink", 0), ("sink", "sink", 0),
    ])
    product.graph["accept"].add(("dead", "q0"))
    product.build_accept_with_cycle()
    searched_sources = []
    original_search = discrete_plan.single_source_dijkstra_path_length

    def record_search(graph, source, **kwargs):
        searched_sources.append(source)
        return original_search(graph, source, **kwargs)

    monkeypatch.setattr(
        discrete_plan,
        "single_source_dijkstra_path_length",
        record_search,
    )
    run, _ = dijkstra_plan_networkX(product, gamma=10)
    assert (run.precost, run.sufcost, run.totalcost) == (3, 1, 13)
    assert ("dead", "q0") not in searched_sources


def test_no_accepting_cycle_returns_without_shortest_path_search(monkeypatch):
    """Reject an acyclic accepting graph before attempting prefix search."""
    product = make_weighted_product([("s0", "s1", 1)])

    def unexpected_search(*args, **kwargs):
        raise AssertionError(
            "A graph without an accepting cycle needs no path search."
        )

    monkeypatch.setattr(
        discrete_plan,
        "single_source_dijkstra_path_length",
        unexpected_search,
    )
    monkeypatch.setattr(
        discrete_plan,
        "multi_source_dijkstra_path_length",
        unexpected_search,
    )
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
    original_multi = discrete_plan.multi_source_dijkstra_path_length
    original_single = discrete_plan.single_source_dijkstra_path_length

    def record_multi(graph, sources, **kwargs):
        multi_calls.append(set(sources))
        return original_multi(graph, sources, **kwargs)

    def record_single(graph, source, **kwargs):
        suffix_sources.append(source)
        return original_single(graph, source, **kwargs)

    monkeypatch.setattr(
        discrete_plan,
        "multi_source_dijkstra_path_length",
        record_multi,
    )
    monkeypatch.setattr(
        discrete_plan,
        "single_source_dijkstra_path_length",
        record_single,
    )
    run, _ = dijkstra_plan_networkX(product, gamma=10)

    assert run is not None
    assert run.prefix[0] == ("i2", "q0")
    assert run.precost == 1
    assert run.totalcost == 31
    assert len(multi_calls) == 1
    assert suffix_sources == [("goal", "q0")]


def test_networkx_dijkstra_skips_unreachable_suffix(monkeypatch):
    """Restrict suffix search to the accepting target's SCC."""
    product = make_weighted_product([
        ("s0", "goal", 1), ("goal", "goal", 1),
        ("goal", "cycle", 2), ("cycle", "goal", 2),
        ("goal", "tail", 0), ("tail", "tail2", 0),
        ("dead", "dead", 0),
    ], accepting="goal")
    product.graph["accept"].add(("dead", "q0"))
    product.build_accept_with_cycle()
    suffix_sources = []
    suffix_distances = {}
    original_single = discrete_plan.single_source_dijkstra_path_length

    def record_single(graph, source, **kwargs):
        suffix_sources.append(source)
        distances = original_single(graph, source, **kwargs)
        suffix_distances[source] = distances
        return distances

    monkeypatch.setattr(
        discrete_plan,
        "single_source_dijkstra_path_length",
        record_single,
    )
    run, _ = dijkstra_plan_networkX(product)

    assert run is not None
    assert run.precost == 1
    assert suffix_sources == [("goal", "q0")]
    assert ("cycle", "q0") in suffix_distances[("goal", "q0")]
    assert ("tail", "q0") not in suffix_distances[("goal", "q0")]
    assert ("tail2", "q0") not in suffix_distances[("goal", "q0")]

    previous_initial = set(product.graph["initial"])
    previous_possible_states = set(
        getattr(product, "possible_states", set())
    )

    def unexpected_scc(*args, **kwargs):
        raise AssertionError(
            "An unreachable accepting target must skip SCC construction."
        )

    monkeypatch.setattr(
        discrete_plan,
        "strongly_connected_components",
        unexpected_scc,
    )
    assert dijkstra_plan_networkX(
        product,
        start_set={("tail", "q0")},
    ) == (None, None)
    assert product.graph["initial"] == previous_initial
    assert set(getattr(product, "possible_states", set())) == (
        previous_possible_states
    )


def test_networkx_dijkstra_zero_cost_multi_source_prefix_is_finite():
    """Keep a finite zero-cost prefix from an explicit start."""
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


def test_cycle_search_preserves_unreachable_acceptance_and_reads_changed_edges():
    """Recompute reachable cycles without changing input state or acceptance sets."""
    product = make_weighted_product([
        ("s0", "a", 2), ("a", "a", 3),
        ("s0", "b", 6), ("b", "b", 1), ("dead", "dead", 0),
    ], accepting="a")
    product.graph["accept"] = {("a", "q0"), ("b", "q0"), ("dead", "q0")}
    product.build_accept_with_cycle()
    product.possible_states = {("s0", "q0")}
    initial = set(product.graph["initial"])
    acceptance = set(product.graph["accept"])
    cycles = set(product.graph["accept_with_cycle"])

    def plan_and_check(expected_prefix, expected_suffix, expected_cost):
        before = [(source, target, dict(data)) for source, target, data
                  in product.edges(data=True)]
        before_ts = [(source, target, dict(data)) for source, target, data
                     in product.graph["ts"].edges(data=True)]
        run, _ = dijkstra_plan_networkX(product, gamma=1)
        assert run.prefix == expected_prefix
        assert run.suffix == expected_suffix
        assert (run.precost, run.sufcost, run.totalcost) == expected_cost
        assert list(product.edges(data=True)) == before
        assert list(product.graph["ts"].edges(data=True)) == before_ts
        assert product.graph["initial"] == initial
        assert product.graph["accept"] == acceptance
        assert product.graph["accept_with_cycle"] == cycles
        assert product.possible_states == initial

    plan_and_check([("s0", "q0"), ("a", "q0")], [("a", "q0")], (2, 3, 5))
    product.graph["ts"].add_edge("s0", "dead", weight=0, action="reach_dead")
    product.add_edge(("s0", "q0"), ("dead", "q0"), weight=0, action="reach_dead")
    plan_and_check([("s0", "q0"), ("dead", "q0")], [("dead", "q0")], (0, 0, 0))
    product.remove_edge(("s0", "q0"), ("dead", "q0"))
    product.graph["ts"].remove_edge("s0", "dead")
    plan_and_check([("s0", "q0"), ("a", "q0")], [("a", "q0")], (2, 3, 5))


def test_explicit_start_uses_its_reachable_component_without_changing_initial():
    """Choose a disconnected zero-cost accepting loop from an explicit start."""
    product = make_weighted_product([
        ("s0", "goal", 2), ("goal", "goal", 3), ("dead", "dead", 0),
    ], accepting="goal")
    product.graph["accept"].add(("dead", "q0"))
    product.build_accept_with_cycle()
    initial = set(product.graph["initial"])
    starts = {("dead", "q0")}
    run, _ = dijkstra_plan_networkX(product, gamma=10, start_set=starts)
    assert run.prefix == run.suffix == [("dead", "q0")]
    assert (run.precost, run.sufcost, run.totalcost) == (0, 0, 0)
    assert starts == {("dead", "q0")}
    assert product.graph["initial"] == initial


def test_hidden_weight_edge_keeps_only_executable_accepting_cycles():
    """A None-weight link joins a structural SCC without providing a path."""
    product = make_weighted_product([
        ("s0", "goal", 2), ("goal", "goal", 3),
        ("goal", "hidden", 0), ("hidden", "goal", 0),
    ], accepting="goal")
    product.edges[("goal", "q0"), ("hidden", "q0")]["weight"] = None
    product.graph["accept"].add(("hidden", "q0"))
    product.build_accept_with_cycle()

    run, _ = dijkstra_plan_networkX(product, gamma=10)
    assert run.prefix == [("s0", "q0"), ("goal", "q0")]
    assert run.suffix == [("goal", "q0")]
    assert (run.precost, run.sufcost, run.totalcost) == (2, 3, 32)
    run, _ = dijkstra_plan_networkX(product, gamma=10, start_set={("hidden", "q0")})
    assert run.prefix == [("hidden", "q0"), ("goal", "q0")]
    assert run.suffix == [("goal", "q0")]
    assert (run.precost, run.sufcost, run.totalcost) == (0, 3, 30)
    assert product.edges[("goal", "q0"), ("hidden", "q0")]["weight"] is None
    assert product.graph["initial"] == {("s0", "q0")}


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


def _make_repeated_history_product():
    """Create a small converging Product graph for history filtering."""
    product = DiGraph()
    product.graph["buchi"] = DiGraph(initial={"q0"})
    for node in (
        ("s0", "q0"), ("s0", "q1"),
        ("s1", "q0"), ("s1", "q1"),
    ):
        product.add_node(node)

    for source in (("s0", "q0"), ("s0", "q1")):
        product.add_edge(source, ("s1", "q0"))
        product.add_edge(source, ("s1", "q1"))
    for source in (("s1", "q0"), ("s1", "q1")):
        product.add_edge(source, ("s0", "q0"))
        product.add_edge(source, ("s0", "q1"))
    return product


def test_history_reuses_successors_per_call_and_preserves_belief(monkeypatch):
    """Enumerate each repeated Product source once within one history call."""
    product = _make_repeated_history_product()
    trace = ["s0", "s1", "s0", "s1", "s0"]
    before_trace = list(trace)
    calls = []
    original_successors = product.successors

    def record_successors(node):
        calls.append(node)
        return original_successors(node)

    monkeypatch.setattr(product, "successors", record_successors)
    result = prod_states_given_history(product, trace)

    expected_sources = {
        ("s0", "q0"), ("s0", "q1"),
        ("s1", "q0"), ("s1", "q1"),
    }
    assert result == {("s0", "q0"), ("s0", "q1")}
    assert Counter(calls) == Counter({source: 1 for source in expected_sources})
    assert trace == before_trace


def test_history_successors_refresh_between_calls_and_empty_cases_remain():
    """Read changed edges on the next call and preserve empty-history results."""
    product = _make_repeated_history_product()
    trace = ["s0", "s1", "s0"]
    assert prod_states_given_history(product, trace) == {
        ("s0", "q0"), ("s0", "q1"),
    }

    for source in (("s1", "q0"), ("s1", "q1")):
        product.remove_edge(source, ("s0", "q0"))
    product.add_node(("s0", "q2"))
    product.add_edge(("s1", "q1"), ("s0", "q2"))
    assert prod_states_given_history(product, trace) == {
        ("s0", "q1"), ("s0", "q2"),
    }

    assert prod_states_given_history(product, []) == set()
    assert prod_states_given_history(product, ["unknown"]) == set()
    assert prod_states_given_history(product, ["s0", "dead"]) == set()


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


@pytest.mark.parametrize("first_tail, second_tail", [("a", "b"), ("b", "a")])
def test_closing_cycle_ties_keep_predecessor_order_and_read_new_weights(
    first_tail, second_tail,
):
    """Keep the first cost-five cycle, then reread a changed closing edge."""
    product = make_weighted_product([
        ("s0", "goal", 2), (first_tail, "goal", 4),
        (second_tail, "goal", 4), ("goal", first_tail, 1),
        ("goal", second_tail, 1), ("goal", "goal", 10),
        ("outside", "goal", 0), ("goal", "hidden", 0),
        ("hidden", "goal", 0),
    ], accepting="goal")
    goal = ("goal", "q0")
    hidden = ("hidden", "q0")
    product.edges[hidden, goal]["weight"] = None
    predecessors = list(product.predecessors(goal))
    assert predecessors.index((first_tail, "q0")) < predecessors.index((second_tail, "q0"))
    initial = set(product.graph["initial"])
    acceptance = set(product.graph["accept"])
    cycles = set(product.graph["accept_with_cycle"])

    for expected_tail, expected_cost in [(first_tail, 5), (second_tail, 1)]:
        before_edges = [(source, target, dict(data)) for source, target, data
                        in product.edges(data=True)]
        before_ts = [(source, target, dict(data)) for source, target, data
                     in product.graph["ts"].edges(data=True)]
        run, _ = dijkstra_plan_networkX(product, gamma=10)
        assert run.prefix == [("s0", "q0"), goal]
        assert run.suffix == [goal, (expected_tail, "q0")]
        assert (run.precost, run.sufcost, run.totalcost) == (
            2, expected_cost, 2 + 10 * expected_cost,
        )
        assert run.suf_prod_edges == [
            (goal, (expected_tail, "q0")), ((expected_tail, "q0"), goal),
        ]
        assert run.pre_plan == ["s0_to_goal"]
        assert run.suf_plan == [f"goal_to_{expected_tail}", f"{expected_tail}_to_goal"]
        assert run.pre_plan_cost == [0, 2]
        assert run.suf_plan_cost == [0, 1, expected_cost - 1]
        assert list(product.edges(data=True)) == before_edges
        assert list(product.graph["ts"].edges(data=True)) == before_ts
        assert product.graph["initial"] == initial
        assert product.graph["accept"] == acceptance
        assert product.graph["accept_with_cycle"] == cycles
        assert product.possible_states == initial
        product.edges[(second_tail, "q0"), goal]["weight"] = 0
        product.graph["ts"].edges[second_tail, "goal"]["weight"] = 0


@pytest.mark.parametrize("gamma", [0, 10])
def test_closing_cycle_uses_default_weight_and_ignores_hidden_edges(gamma):
    """Use weight one for the closing edge and reject a cheaper hidden cycle."""
    product = make_weighted_product([
        ("s0", "goal", 2), ("goal", "goal", 10),
        ("goal", "tail", 1), ("tail", "goal", 1),
        ("goal", "hidden", 0), ("hidden", "goal", 0),
        ("outside", "goal", 0),
    ], accepting="goal")
    goal = ("goal", "q0")
    tail = ("tail", "q0")
    del product.edges[tail, goal]["weight"]
    product.edges[("hidden", "q0"), goal]["weight"] = None
    before = [(source, target, dict(data)) for source, target, data in product.edges(data=True)]
    run, _ = dijkstra_plan_networkX(product, gamma=gamma)
    assert run.prefix == [("s0", "q0"), goal]
    assert run.suffix == [goal, tail]
    assert (run.precost, run.sufcost, run.totalcost) == (2, 2, 2 + gamma * 2)
    assert run.suf_plan_cost == [0, 1, 1]
    assert list(product.edges(data=True)) == before
    assert "weight" not in product.edges[tail, goal]


def test_closing_cycle_without_usable_predecessor_returns_no_run():
    """Reject a structural accepting loop whose only closing edge is hidden."""
    product = make_weighted_product([
        ("s0", "goal", 2), ("goal", "goal", 0),
    ], accepting="goal")
    goal = ("goal", "q0")
    product.edges[goal, goal]["weight"] = None
    before = [(source, target, dict(data)) for source, target, data in product.edges(data=True)]
    initial = set(product.graph["initial"])
    cycles = set(product.graph["accept_with_cycle"])
    assert goal in cycles
    assert dijkstra_plan_networkX(product) == (None, None)
    assert list(product.edges(data=True)) == before
    assert product.graph["initial"] == initial
    assert product.graph["accept_with_cycle"] == cycles
