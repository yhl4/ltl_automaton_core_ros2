from networkx import DiGraph

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
