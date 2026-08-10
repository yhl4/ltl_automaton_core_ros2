"""Regression tests for the frozen Demo-D1 household fixture."""

from pathlib import Path

import pytest
import yaml

from ltl_automaton_planner_core.configuration.transition_system import (
    state_models_from_ts,
)
from ltl_automaton_planner_core.ltl_tools.ltl_planner import LTLPlanner
from ltl_automaton_planner_core.ltl_tools.ts import TSModel


FIXTURE = (
    Path(__file__).parents[1]
    / "config"
    / "demo_d1_household_ts.yaml"
)
REGIONS = ("l0", "d0", "n1", "k0", "h1", "h2", "h4", "b0", "s0")
STATIONS = ("lp0", "c0", "sd0", "f0", "kc0", "bp0")


def _fixture_data():
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def _transition_system():
    model = TSModel(state_models_from_ts(_fixture_data()))
    model.build_full()
    return model


def _plan(hard_task):
    planner = LTLPlanner(
        _transition_system(),
        hard_spec=hard_task,
        soft_spec="(b0 || ! b0)",
        beta=1000,
        gamma=10,
    )
    assert planner.optimal(style="static") is True
    return planner


def _spatial_route_and_cost(planner, target):
    transition_system = planner.product.graph["ts"]
    route = [planner.run.line[0][0]]
    movement_cost = 0.0
    for source, destination in zip(
        planner.run.line,
        planner.run.line[1:],
    ):
        if source[0] != destination[0]:
            route.append(destination[0])
            movement_cost += transition_system.edges[
                source,
                destination,
            ]["weight"]
        if destination[0] == target:
            break
    return route, movement_cost


def test_household_fixture_freezes_dimensions_nodes_and_station_branches():
    data = _fixture_data()
    spatial = data["state_models"]["2d_pose_region"]

    assert data["state_dim"] == ["2d_pose_region", "gripper_state"]
    assert spatial["initial"] == "l0"
    assert data["state_models"]["gripper_state"]["initial"] == "empty"
    assert set(spatial["nodes"]) == set(REGIONS + STATIONS)
    assert len(spatial["nodes"]) == 15
    assert all(
        spatial["nodes"][node]["attr"]["type"] == "square"
        for node in REGIONS
    )
    assert all(
        spatial["nodes"][node]["attr"]["type"] == "station"
        for node in STATIONS
    )
    assert all(
        spatial["nodes"][node]["attr"]["pose"]
        for node in REGIONS + STATIONS
    )
    assert {
        node: set(spatial["nodes"][node]["connected_to"]) - {node}
        for node in STATIONS
    } == {
        "lp0": {"l0"},
        "c0": {"l0"},
        "sd0": {"s0"},
        "f0": {"k0"},
        "kc0": {"k0"},
        "bp0": {"b0"},
    }


def test_household_compound_labels_and_interaction_guards():
    transition_system = _transition_system()

    assert transition_system.graph["initial"] == {("l0", "empty")}
    assert set(transition_system.nodes[("k0", "holding")]["label"]) == {
        "k0",
        "holding",
    }
    assert transition_system.edges[
        ("lp0", "empty"),
        ("lp0", "holding"),
    ]["action"] == "pick"
    assert not transition_system.has_edge(
        ("l0", "empty"),
        ("l0", "holding"),
    )
    assert transition_system.edges[
        ("bp0", "holding"),
        ("bp0", "empty"),
    ]["action"] == "place"
    assert not transition_system.has_edge(
        ("k0", "holding"),
        ("k0", "empty"),
    )


def test_household_reachability_uses_frozen_shortcut_cost():
    planner = _plan("<> k0")
    route, movement_cost = _spatial_route_and_cost(planner, "k0")

    assert route == ["l0", "d0", "n1", "k0"]
    assert movement_cost == pytest.approx(4.0)


def test_household_avoidance_uses_frozen_hallway_cost():
    planner = _plan("<> k0 && [] ! d0")
    route, movement_cost = _spatial_route_and_cost(planner, "k0")

    assert "d0" not in {state[0] for state in planner.run.line}
    assert route == ["l0", "h1", "h2", "h4", "k0"]
    assert movement_cost == pytest.approx(5.4)


def test_household_holding_goal_requires_pick_at_living_room_station():
    planner = _plan("<> holding")
    pick_index = planner.run.pre_plan.index("pick")

    assert any(action.startswith("goto_") for action in planner.run.pre_plan)
    assert planner.run.line[pick_index] == ("lp0", "empty")
    assert planner.run.line[pick_index + 1] == ("lp0", "holding")


def test_household_pick_then_place_uses_frozen_interaction_stations():
    planner = _plan("<> (holding && <> empty)")
    pick_index = planner.run.pre_plan.index("pick")
    place_index = planner.run.pre_plan.index("place")

    assert pick_index < place_index
    assert planner.run.line[pick_index] == ("lp0", "empty")
    assert planner.run.line[pick_index + 1] == ("lp0", "holding")
    assert planner.run.line[place_index] == ("bp0", "holding")
    assert planner.run.line[place_index + 1] == ("bp0", "empty")
