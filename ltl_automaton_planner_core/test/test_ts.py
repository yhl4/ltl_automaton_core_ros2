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
