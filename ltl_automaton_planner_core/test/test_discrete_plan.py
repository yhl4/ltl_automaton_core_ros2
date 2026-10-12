"""Tests for discrete prefix-suffix planning."""

from collections import Counter

from networkx import DiGraph
from networkx import MultiDiGraph
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


class CustomDiGraph(DiGraph):
    """Use the fallback route through an exact subclass."""


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
    original_search = discrete_plan._component_distances

    def record_search(graph, source, component):
        searched_sources.append(source)
        return original_search(graph, source, component)

    monkeypatch.setattr(
        discrete_plan,
        "_component_distances",
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
        "_component_distances",
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
    prefix_calls = []
    suffix_sources = []
    original_prefix = discrete_plan._prefix_distances
    original_single = discrete_plan._component_distances

    def record_prefix(graph, sources):
        prefix_calls.append((graph, sources))
        return original_prefix(graph, sources)

    def record_single(graph, source, component):
        suffix_sources.append(source)
        return original_single(graph, source, component)

    monkeypatch.setattr(
        discrete_plan,
        "_prefix_distances",
        record_prefix,
    )
    monkeypatch.setattr(
        discrete_plan,
        "_component_distances",
        record_single,
    )
    run, _ = dijkstra_plan_networkX(product, gamma=10)

    assert run is not None
    assert run.prefix[0] == ("i2", "q0")
    assert run.precost == 1
    assert run.totalcost == 31
    assert len(prefix_calls) == 1
    assert prefix_calls[0][0] is product
    assert prefix_calls[0][1] is product.graph["initial"]
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
    original_single = discrete_plan._component_distances

    def record_single(graph, source, component):
        suffix_sources.append(source)
        distances = original_single(graph, source, component)
        suffix_distances[source] = distances
        return distances

    monkeypatch.setattr(
        discrete_plan,
        "_component_distances",
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


def test_scc_topology_keeps_none_edges_without_copying_product_state(monkeypatch):
    """Keep structural SCC links while ignoring hidden edges for distances."""
    edges = [
        ("s", "a", 1), ("s", "b", 1),
        ("a", "b", 0), ("b", "a", 2), ("a", "a", 3),
    ]

    product_b = make_weighted_product(edges, initial="s", accepting="b")
    product_b.edges[("a", "q0"), ("b", "q0")]["weight"] = None
    product_b.graph["ts"].edges["a", "b"]["weight"] = None
    before_b_edges = [
        (source, target, dict(data))
        for source, target, data in product_b.edges(data=True)
    ]
    before_b_initial = product_b.graph["initial"]
    before_b_accept = product_b.graph["accept"]
    before_b_cycles = product_b.graph["accept_with_cycle"]
    before_b_possible = product_b.possible_states
    before_b_ts = product_b.graph["ts"]
    assert dijkstra_plan_networkX(product_b, gamma=10) == (None, None)
    assert list(product_b.edges(data=True)) == before_b_edges
    assert product_b.graph["initial"] is before_b_initial
    assert product_b.graph["accept"] is before_b_accept
    assert product_b.graph["accept_with_cycle"] is before_b_cycles
    assert product_b.possible_states is before_b_possible
    assert product_b.graph["ts"] is before_b_ts

    product = make_weighted_product(edges, initial="s", accepting="a")
    product.edges[("a", "q0"), ("b", "q0")]["weight"] = None
    product.graph["ts"].edges["a", "b"]["weight"] = None
    product.graph["accept"].add(("b", "q0"))
    product.build_accept_with_cycle()
    a = ("a", "q0")
    b = ("b", "q0")
    assert a in product.graph["accept_with_cycle"]
    assert b in product.graph["accept_with_cycle"]
    before_edges = [
        (source, target, dict(data))
        for source, target, data in product.edges(data=True)
    ]
    before_nodes = [
        (node, dict(data))
        for node, data in product.nodes(data=True)
    ]
    before_initial = product.graph["initial"]
    before_accept = product.graph["accept"]
    before_cycles = product.graph["accept_with_cycle"]
    before_possible = product.possible_states
    before_ts = product.graph["ts"]
    before_buchi = product.graph["buchi"]
    suffix_distances = {}
    original_search = discrete_plan._component_distances

    def record_search(graph, source, component):
        distances = original_search(graph, source, component)
        suffix_distances[source] = distances
        return distances

    monkeypatch.setattr(
        discrete_plan,
        "_component_distances",
        record_search,
    )

    run, _ = dijkstra_plan_networkX(product, gamma=10)

    assert run is not None
    assert suffix_distances[b][a] == 2
    assert b not in suffix_distances[a]
    assert run.prefix == [("s", "q0"), a]
    assert run.suffix == [a]
    assert (run.precost, run.sufcost, run.totalcost) == (1, 3, 31)
    assert b not in run.suffix
    assert list(product.nodes(data=True)) == before_nodes
    assert list(product.edges(data=True)) == before_edges
    assert product.graph["initial"] is before_initial
    assert product.graph["accept"] is before_accept
    assert product.graph["accept_with_cycle"] is before_cycles
    assert product.possible_states is before_possible
    assert product.graph["ts"] is before_ts
    assert product.graph["buchi"] is before_buchi


def test_dijkstra_closing_edges_keep_default_hidden_and_input_semantics():
    """Use one closing adjacency read while preserving complete run output."""
    product = make_weighted_product([
        ("s0", "goal", 2), ("goal", "goal", 10),
        ("goal", "tail", 1), ("tail", "goal", 1),
        ("goal", "hidden", 0), ("hidden", "goal", 0),
        ("outside", "goal", 0),
    ], accepting="goal")
    goal = ("goal", "q0")
    tail = ("tail", "q0")
    product.edges[("hidden", "q0"), goal]["weight"] = None
    initial = set(product.graph["initial"])
    acceptance = set(product.graph["accept"])
    cycles = set(product.graph["accept_with_cycle"])
    before_edges = [
        (source, target, dict(data))
        for source, target, data in product.edges(data=True)
    ]
    run, _ = dijkstra_plan_networkX(product, gamma=10)

    assert run.prefix == [("s0", "q0"), goal]
    assert run.suffix == [goal, tail]
    assert run.pre_plan == ["s0_to_goal"]
    assert run.suf_plan == ["goal_to_tail", "tail_to_goal"]
    assert run.pre_plan_cost == [0, 2]
    assert run.suf_plan_cost == [0, 1, 1]
    assert (run.precost, run.sufcost, run.totalcost) == (2, 2, 22)
    assert list(product.edges(data=True)) == before_edges
    assert product.graph["initial"] == initial
    assert product.graph["accept"] == acceptance
    assert product.graph["accept_with_cycle"] == cycles

    product.edges[tail, goal]["weight"] = 3
    product.graph["ts"].edges["tail", "goal"]["weight"] = 3
    run, _ = dijkstra_plan_networkX(product, gamma=10)

    assert run.prefix == [("s0", "q0"), goal]
    assert run.suffix == [goal, tail]
    assert run.suf_plan_cost == [0, 1, 3]
    assert (run.precost, run.sufcost, run.totalcost) == (2, 4, 42)


def test_component_distances_preserve_seen_equality_events():
    """Keep numeric equality hooks when another path reaches a seen node."""
    events = []

    class LoggedCost(float):
        """Keep arithmetic results observable without changing their values."""

        def __add__(self, other):
            """Return another logged arithmetic result."""
            return LoggedCost(float(self) + float(other))

        def __radd__(self, other):
            """Preserve the type when adding the initial integer distance."""
            return LoggedCost(float(other) + float(self))

        def __eq__(self, other):
            """Record both heap and already-seen distance equality."""
            events.append((float(self), float(other)))
            return float(self) == float(other)

    graph = DiGraph()
    graph.add_weighted_edges_from([
        ("s", "a", LoggedCost(0)), ("s", "b", LoggedCost(0)),
        ("a", "j", LoggedCost(1)), ("b", "j", LoggedCost(1)),
        ("j", "s", LoggedCost(0)),
    ])
    component = {"s", "a", "b", "j"}

    def original_weight(source, target, data):
        return data.get("weight", 1) if target in component else None

    expected = single_source_dijkstra_path_length(graph, "s", weight=original_weight)
    original_events = list(events)
    events.clear()
    actual = discrete_plan._component_distances(graph, "s", component)
    assert events == original_events and original_events
    assert list(actual) == list(expected) == ["s", "a", "b", "j"]
    assert [float(value) for value in actual.values()] == [0, 0, 0, 1]
    assert [type(value) for value in actual.values()] == [
        type(value) for value in expected.values()
    ]


def test_prefix_helper_native_default_none_and_zero_tie():
    """Preserve native tie order, default weights, and hidden None edges."""
    graph = DiGraph()
    graph.add_edge("s", "a", weight=0)
    graph.add_edge("s", "b", weight=0)
    graph.add_edge("a", "j")
    graph.add_edge("b", "j", weight=1)
    graph.add_edge("j", "s", weight=None)
    actual = discrete_plan._prefix_distances(graph, {"s"})
    assert list(actual.items()) == [("s", 0), ("a", 0), ("b", 0), ("j", 1)]


@pytest.mark.parametrize("graph_type", [CustomDiGraph, MultiDiGraph])
def test_prefix_helper_falls_back_for_non_native_graphs(monkeypatch, graph_type):
    """Use NetworkX's wrapper for custom and multigraph inputs."""
    graph = graph_type()
    graph.add_edge("s", "a", weight=3)
    graph.add_edge("s", "a", weight=1)
    graph.add_edge("a", "goal", weight=2)
    starts = {"s"}
    calls = []
    original = discrete_plan.multi_source_dijkstra_path_length

    def record(graph_arg, sources, **kwargs):
        calls.append((graph_arg, sources, kwargs))
        return original(graph_arg, sources, **kwargs)

    monkeypatch.setattr(
        discrete_plan,
        "multi_source_dijkstra_path_length",
        record,
    )
    actual = discrete_plan._prefix_distances(graph, starts)
    assert actual == {"s": 0, "a": 1, "goal": 3}
    assert len(calls) == 1
    assert calls[0][0] is graph
    assert calls[0][1] is starts
    assert calls[0][2] == {"weight": "weight"}


def test_reachable_components_keep_partition_order_and_input():
    """Keep the hand-computed SCC order, including exits and isolated nodes."""
    graph = DiGraph()
    graph.add_nodes_from(list("abcdefgh") + ["isolated"])
    graph.add_edges_from([
        ("a", "b"), ("b", "a"), ("b", "c"), ("c", "d"),
        ("d", "c"), ("d", "e"), ("e", "f"), ("f", "f"),
        ("g", "h"), ("h", "g"),
    ])
    before_nodes = list(graph.nodes(data=True))
    before_edges = list(graph.edges(data=True))
    assert list(discrete_plan._reachable_components(graph)) == [
        {"f"}, {"e"}, {"c", "d"}, {"a", "b"}, {"g", "h"}, {"isolated"},
    ]
    assert list(discrete_plan._reachable_components(DiGraph())) == []
    assert list(graph.nodes(data=True)) == before_nodes
    assert list(graph.edges(data=True)) == before_edges


@pytest.mark.parametrize("graph_type", [CustomDiGraph, MultiDiGraph])
def test_reachable_components_fall_back_for_non_native_graphs(monkeypatch, graph_type):
    """Retain NetworkX traversal for graph subclasses and multigraphs."""
    graph = graph_type()
    graph.add_edges_from([("a", "b"), ("b", "a"), ("b", "tail")])
    calls = []
    original = discrete_plan.strongly_connected_components

    def record(graph_arg):
        calls.append(graph_arg)
        return original(graph_arg)

    monkeypatch.setattr(discrete_plan, "strongly_connected_components", record)
    assert list(discrete_plan._reachable_components(graph)) == [{"tail"}, {"a", "b"}]
    assert calls == [graph]


@pytest.mark.parametrize("graph_factory", ["digraph", "prodaut", "custom_adj"])
def test_restore_tight_path_native_views_preserve_order_and_alias(graph_factory):
    """Read fresh native successor views while preserving edge hooks."""
    events = []

    class EdgeData(dict):
        """Record weight lookups outside the graph object."""

        def __init__(self, owner, weight):
            """Store an external owner label and edge weight."""
            super().__init__(weight=weight)
            self.owner = owner

        def get(self, key, default=1):
            """Record each edge data lookup and its default."""
            events.append(("edge_get", self.owner, key, default))
            return super().get(key, default)

    class InnerDict(dict):
        """Record inner neighbor iteration and item access."""

        def __iter__(self):
            """Record one neighbor iteration."""
            events.append(("inner_iter",))
            return super().__iter__()

        def __getitem__(self, key):
            """Record one neighbor data lookup."""
            events.append(("inner_get", key))
            return super().__getitem__(key)

    class OuterDict(dict):
        """Record outer successor lookups."""

        def __getitem__(self, key):
            """Record one source successor lookup."""
            events.append(("outer_get", key))
            return super().__getitem__(key)

    class AdjacencyGraph(DiGraph):
        """Record fallback adjacency property access."""

        @property
        def adj(self):
            """Return the standard adjacency view."""
            events.append(("adj_get",))
            return DiGraph.adj.fget(self)

    if graph_factory == "digraph":
        graph = DiGraph()
    elif graph_factory == "prodaut":
        graph = ProdAut(None, None)
    else:
        graph = AdjacencyGraph()
    nodes = ["s", "a", "b", "j"]
    graph.add_nodes_from(nodes)
    outer = OuterDict()
    graph._succ = outer
    graph._adj = outer
    for node in ["s", "a", "b", "j"]:
        outer[node] = InnerDict()
        if hasattr(graph, "_pred"):
            graph._pred[node] = {}
    for source, target, weight in [
        ("s", "s", 0), ("s", "a", 1), ("s", "b", 1),
        ("a", "s", 0), ("a", "j", 1), ("b", "j", 1),
    ]:
        data = EdgeData((source, target), weight)
        outer[source][target] = data
        graph._pred[target][source] = data
    distances = {"s": 0, "a": 1, "b": 1, "j": 2}
    sources = {"s"}
    before_distances = dict(distances)
    before_sources = set(sources)
    events.clear()

    actual = discrete_plan._restore_tight_path(graph, distances, sources, "j")

    assert actual[0] is nodes[0]
    assert actual[1] is nodes[1]
    assert actual[2] is nodes[3]
    assert distances == before_distances
    assert sources == before_sources
    edge_events = [event for event in events if event[0] == "edge_get"]
    assert edge_events == [
        ("edge_get", ("s", "a"), "weight", 1),
        ("edge_get", ("s", "b"), "weight", 1),
        ("edge_get", ("a", "j"), "weight", 1),
    ]
    assert [event for event in events if event[0] == "outer_get"] == [
        ("outer_get", "s"), ("outer_get", "a"),
    ]
    assert [event for event in events if event[0] == "inner_iter"] == [
        ("inner_iter",), ("inner_iter",),
    ]
    assert [event for event in events if event[0] == "inner_get"] == [
        ("inner_get", "a"), ("inner_get", "b"), ("inner_get", "j"),
    ]
    if graph_factory == "custom_adj":
        assert [event for event in events if event[0] == "adj_get"] == [
            ("adj_get",), ("adj_get",),
        ]
    else:
        assert not [event for event in events if event[0] == "adj_get"]


def test_restore_tight_path_reloads_rebound_successors():
    """Reload successors after an outer mapping changes during edge access."""
    events = []

    class EdgeData(dict):
        """Record edge reads for the rebound mapping."""

        def __init__(self, owner, weight):
            """Store the external edge owner and weight."""
            super().__init__(weight=weight)
            self.owner = owner

        def get(self, key, default=1):
            """Record one rebound edge lookup."""
            events.append(("edge_get", self.owner, key, default))
            return super().get(key, default)

    def edge(owner, weight):
        """Create edge data without storing logs in the graph."""
        return EdgeData(owner, weight)

    class ReboundOuter(dict):
        """Replace the outer map after the source adjacency is returned."""

        def __init__(self, owner, initial):
            """Bind the graph owner and initial successor map."""
            self.owner = owner
            self.rebound = False
            super().__init__(initial)

        def __getitem__(self, key):
            """Return a source view and perform the one replacement."""
            value = super().__getitem__(key)
            if key == "s" and not self.rebound:
                replacement = dict(self)
                replacement["a"] = dict(replacement["a"])
                replacement["a"]["j"] = edge(("a", "j"), 1)
                self.owner._succ = replacement
                self.owner._adj = replacement
                self.owner._pred["j"]["a"] = replacement["a"]["j"]
                self.rebound = True
                events.append(("rebound", "a-j", 9, 1))
            return value

    graph = DiGraph()
    nodes = ["s", "a", "b", "j"]
    graph.add_nodes_from(nodes)
    outer = {}
    for node in ["s", "a", "b", "j"]:
        outer[node] = {}
    for source, target, weight in [
        ("s", "s", 0), ("s", "a", 1), ("s", "b", 1),
        ("a", "s", 0), ("a", "j", 9), ("b", "j", 1),
    ]:
        data = edge((source, target), weight)
        outer[source][target] = data
        graph._pred[target][source] = data
    graph._succ = ReboundOuter(graph, outer)
    graph._adj = graph._succ
    distances = {"s": 0, "a": 1, "b": 1, "j": 2}
    sources = {"s"}
    before_distances = dict(distances)
    before_sources = set(sources)

    actual = discrete_plan._restore_tight_path(graph, distances, sources, "j")

    assert actual[0] is nodes[0]
    assert actual[1] is nodes[1]
    assert actual[2] is nodes[3]
    assert distances == before_distances
    assert sources == before_sources
    assert ("rebound", "a-j", 9, 1) in events
    assert ("edge_get", ("a", "j"), "weight", 1) in events


def _topology_input(graph_type):
    """Build the hand-ordered source graph used by all six controls."""
    graph = DiGraph() if graph_type == "digraph" else ProdAut(None, None)
    nodes = ["s", "b", "a", "tail"]
    graph.add_nodes_from(nodes)
    edges = [
        ("s", "b"), ("s", "a"), ("b", "s"), ("a", "s"),
        ("a", "tail"),
    ]
    for source, target in edges:
        data = {"sentinel": (source, target)}
        graph._succ[source][target] = data
        graph._pred[target][source] = data
    reachable = {"s": 0, "b": 0, "a": 0}
    expected_nodes = ["s", "b", "a"]
    expected_adj = [
        ["s", ["b", "a"]],
        ["b", ["s"]],
        ["a", ["s"]],
    ]
    expected_pred = [
        ["s", ["b", "a"]],
        ["b", ["s"]],
        ["a", ["s"]],
    ]
    expected_edges = [
        ["s", "b", True],
        ["s", "a", True],
        ["b", "s", True],
        ["a", "s", True],
    ]
    return graph, reachable, expected_nodes, expected_adj, expected_pred, expected_edges


def _assert_topology(result, expected_nodes, expected_adj, expected_pred,
                     expected_edges):
    """Check hand-computed order, empty attributes, and edge aliases."""
    assert list(result.nodes()) == expected_nodes
    assert [[source, list(result._succ[source])] for source in expected_nodes] == expected_adj
    assert [[target, list(result._pred[target])] for target in expected_nodes] == expected_pred
    actual_edges = []
    data_ids = []
    for source in expected_nodes:
        for target, data in result._succ[source].items():
            assert data == {}
            assert data is result._pred[target][source]
            actual_edges.append([source, target, data is result._pred[target][source]])
            data_ids.append(id(data))
    assert actual_edges == expected_edges
    assert len(data_ids) == len(set(data_ids))


def _source_snapshot(graph):
    """Capture source values, mapping identities, and edge-data identities."""
    nodes = [(node, dict(data), id(data)) for node, data in graph.nodes(data=True)]
    edges = [
        (source, target, dict(data), id(data))
        for source, target, data in graph.edges(data=True)
    ]
    inner_ids = {node: id(graph._succ[node]) for node in graph._succ}
    pred_inner_ids = {node: id(graph._pred[node]) for node in graph._pred}
    return nodes, edges, id(graph._succ), id(graph._pred), inner_ids, pred_inner_ids


def _assert_source_unchanged(graph, snapshot):
    """Require source values and all adjacency/data identities to persist."""
    nodes, edges, succ_id, pred_id, inner_ids, pred_inner_ids = snapshot
    assert [(node, dict(data), id(data))
            for node, data in graph.nodes(data=True)] == nodes
    assert [(source, target, dict(data), id(data))
            for source, target, data in graph.edges(data=True)] == edges
    assert id(graph._succ) == succ_id
    assert id(graph._pred) == pred_id
    assert {node: id(graph._succ[node]) for node in graph._succ} == inner_ids
    assert {node: id(graph._pred[node]) for node in graph._pred} == pred_inner_ids


@pytest.mark.parametrize("graph_type", ["digraph", "prodaut"])
def test_reachable_topology_native_order_alias_and_input(graph_type):
    """Use the native private source mapping for exact graph types only."""
    graph, reachable, expected_nodes, expected_adj, expected_pred, expected_edges = (
        _topology_input(graph_type)
    )
    source_before = _source_snapshot(graph)
    topology = discrete_plan._reachable_topology(graph, reachable)
    _assert_topology(
        topology, expected_nodes, expected_adj, expected_pred, expected_edges
    )
    _assert_source_unchanged(graph, source_before)
    assert topology._succ["s"]["b"] is topology._pred["b"]["s"]
    assert topology._succ["s"]["b"] is not topology._succ["s"]["a"]


class _AdjGetterGraph(DiGraph):
    """Record one public adjacency access for each reachable source."""

    def __init__(self):
        """Initialize the graph and its external event log."""
        super().__init__()
        self.adj_events = []

    @property
    def adj(self):
        """Record fallback property access and return the public view."""
        self.adj_events.append("adj")
        return DiGraph.adj.fget(self)


def test_reachable_topology_custom_adj_fallback_reads_each_source_once():
    """Subclass fallback preserves public adjacency access and source order."""
    graph = _AdjGetterGraph()
    graph.add_nodes_from(["s", "b", "a"])
    for source, target in [("s", "b"), ("s", "a"), ("b", "s"), ("a", "s")]:
        graph.add_edge(source, target)
    reachable = {"s": 0, "b": 0, "a": 0}
    source_before = _source_snapshot(graph)
    topology = discrete_plan._reachable_topology(graph, reachable)
    assert graph.adj_events == ["adj", "adj", "adj"]
    assert list(topology.nodes()) == ["s", "b", "a"]
    assert list(topology.edges()) == [
        ("s", "b"), ("s", "a"), ("b", "s"), ("a", "s")
    ]
    assert all(
        topology._succ[source][target] is topology._pred[target][source]
        for source, target in topology.edges()
    )
    _assert_source_unchanged(graph, source_before)


class _FactoryDict(dict):
    """Record topology factory construction and mutation externally."""

    events = []

    def __init__(self, *args, **kwargs):
        """Record construction without storing events in the graph."""
        type(self).events.append(("init", type(self).__name__))
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        """Record direct dictionary assignment."""
        type(self).events.append(("set", type(self).__name__, key))
        return super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        """Record add_edges_from dictionary updates."""
        type(self).events.append(("update", type(self).__name__))
        return super().update(*args, **kwargs)


class _EdgeFactoryDict(_FactoryDict):
    """Use the custom edge-data factory."""


class _InnerFactoryDict(_FactoryDict):
    """Use the custom inner adjacency factory."""


class _OuterFactoryDict(_FactoryDict):
    """Use the custom outer adjacency factory."""


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("edge", _EdgeFactoryDict),
        ("inner", _InnerFactoryDict),
        ("outer", _OuterFactoryDict),
    ],
)
def test_reachable_topology_custom_factory_fallback(factory_name, factory):
    """Custom factories force the public add_edges_from fallback."""
    graph = DiGraph()
    graph.add_nodes_from(["s", "b", "a"])
    for source, target in [("s", "b"), ("s", "a"), ("b", "s"), ("a", "s")]:
        graph.add_edge(source, target)
    reachable = {"s": 0, "b": 0, "a": 0}
    source_before = _source_snapshot(graph)
    old_factories = (
        DiGraph.adjlist_inner_dict_factory,
        DiGraph.adjlist_outer_dict_factory,
        DiGraph.edge_attr_dict_factory,
    )
    _FactoryDict.events = []
    add_edges_calls = []
    old_add_edges_from = DiGraph.add_edges_from

    def observe_add_edges(graph_arg, *args, **kwargs):
        """Record the one fallback construction call."""
        add_edges_calls.append(graph_arg)
        return old_add_edges_from(graph_arg, *args, **kwargs)

    try:
        if factory_name == "edge":
            DiGraph.edge_attr_dict_factory = factory
        elif factory_name == "inner":
            DiGraph.adjlist_inner_dict_factory = factory
        else:
            DiGraph.adjlist_outer_dict_factory = factory
        DiGraph.add_edges_from = observe_add_edges
        topology = discrete_plan._reachable_topology(graph, reachable)
    finally:
        DiGraph.add_edges_from = old_add_edges_from
        (
            DiGraph.adjlist_inner_dict_factory,
            DiGraph.adjlist_outer_dict_factory,
            DiGraph.edge_attr_dict_factory,
        ) = old_factories
    _assert_topology(
        topology,
        ["s", "b", "a"],
        [["s", ["b", "a"]], ["b", ["s"]], ["a", ["s"]]],
        [["s", ["b", "a"]], ["b", ["s"]], ["a", ["s"]]],
        [["s", "b", True], ["s", "a", True],
         ["b", "s", True], ["a", "s", True]],
    )
    assert len(add_edges_calls) == 1
    counts = Counter(event[0] for event in _FactoryDict.events)
    expected_counts = {
        "edge": {"init": 4, "update": 8, "set": 0},
        "inner": {"init": 6, "update": 0, "set": 8},
        "outer": {"init": 2, "update": 0, "set": 6},
    }[factory_name]
    assert set(counts) <= set(expected_counts)
    assert {event: counts[event] for event in expected_counts} == expected_counts
    _assert_source_unchanged(graph, source_before)
    assert (
        DiGraph.adjlist_inner_dict_factory,
        DiGraph.adjlist_outer_dict_factory,
        DiGraph.edge_attr_dict_factory,
    ) == old_factories
