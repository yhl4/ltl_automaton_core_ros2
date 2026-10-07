from networkx import DiGraph
from networkx import NetworkXError
import pytest

from ltl_automaton_planner_core.ltl_tools.ts import TSModel


def make_region_model() -> DiGraph:
    model = DiGraph()

    model.graph["initial"] = {("r1",)}
    model.graph["ts_state_format"] = "region"

    model.add_node(("r1",))
    model.add_node(("r2",))

    model.add_edge(
        ("r1",),
        ("r2",),
        action="goto_r2",
        guard="1",
        weight=2.0,
    )

    return model


def make_load_model() -> DiGraph:
    model = DiGraph()

    model.graph["initial"] = {("empty",)}
    model.graph["ts_state_format"] = "load"

    model.add_node(("empty",))
    model.add_node(("loaded",))

    model.add_edge(
        ("empty",),
        ("loaded",),
        action="load",
        guard="r2",
        weight=1.0,
    )

    return model


def test_build_full_composes_nodes_and_initial_state() -> None:
    model = TSModel([
        make_region_model(),
        make_load_model(),
    ])

    model.build_full()

    assert set(model.nodes) == {
        ("r1", "empty"),
        ("r1", "loaded"),
        ("r2", "empty"),
        ("r2", "loaded"),
    }

    assert model.graph["initial"] == {
        ("r1", "empty"),
    }


def test_action_guard_controls_edges() -> None:
    model = TSModel([
        make_region_model(),
        make_load_model(),
    ])

    model.build_full()

    assert model.has_edge(
        ("r1", "empty"),
        ("r2", "empty"),
    )

    assert model.has_edge(
        ("r2", "empty"),
        ("r2", "loaded"),
    )

    assert not model.has_edge(
        ("r1", "empty"),
        ("r1", "loaded"),
    )


def test_set_initial_state() -> None:
    model = TSModel([
        make_region_model(),
        make_load_model(),
    ])

    model.build_full()

    assert model.set_initial(("r2", "loaded")) is True
    assert model.graph["initial"] == {("r2", "loaded")}
    assert model.set_initial(("unknown", "state")) is False


@pytest.mark.parametrize(
    "initial_factory", [lambda: {("r1",)}, lambda: [("r1",)]],
    ids=["set", "list"],
)
def test_single_dimension_initial_ownership_and_rebuild(initial_factory):
    """Keep single-dimension initial containers independent across builds."""
    factor = make_region_model()
    factor.graph["initial"] = initial_factory()
    model = TSModel([factor])
    sibling = TSModel([factor])
    model.build_full()
    sibling.build_full()

    expected_initial = initial_factory()
    model.graph["initial"].clear()
    assert factor.graph["initial"] == expected_initial
    assert sibling.graph["initial"] == expected_initial

    _append_initial(factor.graph["initial"], ("r2",))
    expected_empty = [] if isinstance(model.graph["initial"], list) else set()
    assert model.graph["initial"] == expected_empty
    assert sibling.graph["initial"] == expected_initial
    assert model.edges[("r1",), ("r2",)] == factor.edges[("r1",), ("r2",)]
    assert model.set_initial(("r2",)) is True
    assert model.graph["initial"] == {("r2",)}
    assert model.set_initial(("unknown",)) is False
    assert model.graph["initial"] == {("r2",)}

    model.build_full()
    rebuilt_initial = initial_factory()
    _append_initial(rebuilt_initial, ("r2",))
    assert model.graph["initial"] == rebuilt_initial
    model.graph["initial"].clear()
    assert factor.graph["initial"] == rebuilt_initial


def _append_initial(initial, state):
    if isinstance(initial, list):
        initial.append(state)
    else:
        initial.add(state)


def test_single_dimension_guard_is_enforced():
    """Apply the same source-label guard rule to one-dimensional systems."""
    region = make_region_model()
    for state in region:
        region.nodes[state]["label"] = {state[0]}
    region[("r1",)][("r2",)]["guard"] = "r2"
    model = TSModel([region])
    model.build_full()
    assert not model.has_edge(("r1",), ("r2",))


def make_factor_model(states, initial):
    """Create an edgeless factor for Cartesian composition checks."""
    graph = DiGraph(initial=set(initial))
    graph.graph["ts_state_format"] = "factor"
    for state in states:
        graph.add_node(state)
    return graph


def test_three_factor_composition_preserves_order_and_node_metadata():
    """Compose factors lazily while preserving tuple order and metadata."""
    factors = [
        make_factor_model([("a",), ("b",)], {("a",)}),
        make_factor_model([("x",), ("y",)], {("x",)}),
        make_factor_model([("0",), ("1",)], {("0",)}),
    ]
    model = TSModel(factors)
    model.compose_nodes(factors)

    assert list(model.nodes) == [
        ("a", "x", "0"),
        ("a", "x", "1"),
        ("a", "y", "0"),
        ("a", "y", "1"),
        ("b", "x", "0"),
        ("b", "x", "1"),
        ("b", "y", "0"),
        ("b", "y", "1"),
    ]
    assert model.nodes[("a", "x", "0")]["label"] == (
        "a", "x", "0"
    )
    assert model.nodes[("a", "x", "0")]["marker"] == "unvisited"


def test_composed_initial_states_use_all_factor_initials():
    """Update initial states from the Cartesian product of factor initials."""
    factors = [
        make_factor_model([("a",), ("b",)], {("a",), ("b",)}),
        make_factor_model([("x",), ("y",)], {("x",), ("y",)}),
    ]
    model = TSModel(factors)
    model.compose_initial(factors)

    assert model.graph["initial"] == {
        ("a", "x"),
        ("a", "y"),
        ("b", "x"),
        ("b", "y"),
    }


def test_node_product_public_list_contract_including_empty_factors():
    """Keep the public list helper behavior for zero and empty inputs."""
    assert TSModel.node_product() == [()]
    assert TSModel.node_product([("a",)], []) == []
    assert TSModel.node_product(
        [("a",), ("b",)],
        [("x",), ("y",)],
    ) == [
        ("a", "x"),
        ("a", "y"),
        ("b", "x"),
        ("b", "y"),
    ]


def _branching_factors():
    region, load = make_region_model(), make_load_model()
    region.add_edge(("r1",), ("r1",), action="stay_region", guard="1", weight=3.0)
    region.add_edge(("r2",), ("r2",), action="stay_r2", guard="empty", weight=4.0)
    load.add_edge(("empty",), ("empty",), action="wait", guard="1", weight=5.0)
    load.add_edge(("loaded",), ("loaded",), action="hold", guard="r2", weight=6.0)
    return [region, load]


def test_factor_successors_preserve_order_cross_dimension_guards_and_overwrites():
    """Match hand-specified edges with source-label guards and self-loop collisions."""
    factors = _branching_factors()
    model = TSModel(factors)
    model.build_full()
    assert list(model) == [
        ("r1", "empty"), ("r1", "loaded"), ("r2", "empty"), ("r2", "loaded"),
    ]
    expected = [
        (("r1", "empty"), ("r2", "empty"), "goto_r2", "1", 2.0),
        (("r1", "empty"), ("r1", "empty"), "wait", "1", 5.0),
        (("r1", "loaded"), ("r2", "loaded"), "goto_r2", "1", 2.0),
        (("r1", "loaded"), ("r1", "loaded"), "stay_region", "1", 3.0),
        (("r2", "empty"), ("r2", "empty"), "wait", "1", 5.0),
        (("r2", "empty"), ("r2", "loaded"), "load", "r2", 1.0),
        (("r2", "loaded"), ("r2", "loaded"), "hold", "r2", 6.0),
    ]
    assert list(model.edges) == [(source, target) for source, target, *_ in expected]
    for source, target, action, guard, weight in expected:
        assert model.edges[source, target] == dict(
            action=action, guard=guard, weight=weight, marker="visited",
        )
    assert model.graph["initial"] == {("r1", "empty")}
    assert model.graph["ts_state_format"] == ["region", "load"]
    assert model.state_models is factors
    for node, attributes in model.nodes(data=True):
        assert attributes == dict(label=node, marker="unvisited")


def test_factor_successors_rebuild_reads_new_guards_edges_actions_costs_and_initials():
    """Read changed factors again and discard earlier composed transitions."""
    factors = _branching_factors()
    model = TSModel(factors)
    model.build_full()
    region, load = factors
    region.edges[("r1",), ("r2",)].update(weight=2.5, action="updated_go")
    region.remove_edge(("r1",), ("r1",))
    region.add_edge(("r2",), ("r1",), action="return", guard="loaded", weight=7.0)
    load.edges[("empty",), ("loaded",)].update(guard="r1", action="new_load", weight=9.5)
    region.graph["initial"] = {("r2",)}
    load.graph["initial"] = {("loaded",)}
    model.build_full()
    assert model.graph["initial"] == {("r2", "loaded")}
    assert not model.has_edge(("r1", "loaded"), ("r1", "loaded"))
    assert not model.has_edge(("r2", "empty"), ("r2", "loaded"))
    assert not model.has_edge(("r2", "empty"), ("r1", "empty"))
    for source, target, action, guard, weight in (
        (("r1", "empty"), ("r1", "loaded"), "new_load", "r1", 9.5),
        (("r1", "loaded"), ("r2", "loaded"), "updated_go", "1", 2.5),
        (("r2", "loaded"), ("r1", "loaded"), "return", "loaded", 7.0),
    ):
        assert model.edges[source, target] == dict(
            action=action, guard=guard, weight=weight, marker="visited",
        )


def test_factor_successors_empty_composition_keeps_empty_graph():
    """An empty factor yields no composed states, edges, or initial states."""
    empty = DiGraph(initial=set(), ts_state_format="empty")
    model = TSModel([make_region_model(), empty])
    model.build_full()
    assert list(model) == []
    assert list(model.edges) == []
    assert model.graph["initial"] == set()
    assert model._guard_cache == {}


def test_factor_successors_missing_factor_state_keeps_networkx_error():
    """Retain the original graph error for a malformed composed source."""
    factors = _branching_factors()
    model = TSModel(factors)
    model.add_node(("missing", "empty"), label=("missing", "empty"))
    with pytest.raises(NetworkXError, match="missing"):
        model.compose_edges(factors)


def _shared_guard_factors():
    region, load = make_region_model(), make_load_model()
    for graph, prefix, weight in ((region, "region", 10), (load, "load", 20)):
        for source in graph:
            for target in graph:
                graph.add_edge(
                    source, target, action=f"{prefix}_{target[0]}",
                    guard="r2 || empty", weight=weight,
                )
    return [region, load]


def _record_guard_checks(monkeypatch, model):
    checks = []
    original = model.is_action_allowed

    def checked(guard, label):
        checks.append((guard, tuple(label)))
        return original(guard, label)

    monkeypatch.setattr(model, "is_action_allowed", checked)
    return checks


def test_shared_guard_keeps_source_truth_edge_order_and_dimension_overwrite(monkeypatch):
    """Reuse a shared true or false guard while retaining hand-specified edges."""
    model = TSModel(_shared_guard_factors())
    checks = _record_guard_checks(monkeypatch, model)
    model.build_full()
    assert checks == [
        ("r2 || empty", ("r1", "empty")),
        ("r2 || empty", ("r1", "loaded")),
        ("r2 || empty", ("r2", "empty")),
        ("r2 || empty", ("r2", "loaded")),
    ]
    expected = [
        (("r1", "empty"), ("r2", "empty"), "region_r2", 10),
        (("r1", "empty"), ("r1", "empty"), "load_empty", 20),
        (("r1", "empty"), ("r1", "loaded"), "load_loaded", 20),
        (("r2", "empty"), ("r1", "empty"), "region_r1", 10),
        (("r2", "empty"), ("r2", "empty"), "load_empty", 20),
        (("r2", "empty"), ("r2", "loaded"), "load_loaded", 20),
        (("r2", "loaded"), ("r1", "loaded"), "region_r1", 10),
        (("r2", "loaded"), ("r2", "loaded"), "load_loaded", 20),
        (("r2", "loaded"), ("r2", "empty"), "load_empty", 20),
    ]
    assert list(model.edges) == [(source, target) for source, target, *_ in expected]
    for source, target, action, weight in expected:
        assert model.edges[source, target] == dict(
            action=action, guard="r2 || empty", weight=weight, marker="visited",
        )


def test_source_guard_reuse_is_fresh_for_each_composition_and_public_check(monkeypatch):
    """Read source labels again on each call and keep the public checker uncached."""
    factors = _shared_guard_factors()
    model = TSModel(factors)
    checks = _record_guard_checks(monkeypatch, model)
    model.build_full()
    initial_checks = list(checks)
    model.build_full()
    assert checks == initial_checks * 2
    assert len(initial_checks) == 4

    for graph in factors:
        for _source, _target, data in graph.edges(data=True):
            data["guard"] = "!r2 && loaded"
    checks.clear()
    model.build_full()
    assert checks == [
        ("!r2 && loaded", label) for _guard, label in initial_checks
    ]
    assert list(model.edges) == [
        (("r1", "loaded"), ("r2", "loaded")),
        (("r1", "loaded"), ("r1", "loaded")),
        (("r1", "loaded"), ("r1", "empty")),
    ]
    assert model.is_action_allowed("!r2 && loaded", ("r1", "loaded"))
    assert not model.is_action_allowed("!r2 && loaded", ("r2", "loaded"))
    assert checks[-2:] == [
        ("!r2 && loaded", ("r1", "loaded")),
        ("!r2 && loaded", ("r2", "loaded")),
    ]
