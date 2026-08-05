"""Integration tests for Büchi construction using real ltl2ba."""

import shutil

import pytest

from ltl_automaton_planner_core.ltl_tools.buchi import (
    buchi_from_ltl,
    mission_to_buchi,
)


pytestmark = pytest.mark.skipif(
    shutil.which("ltl2ba") is None,
    reason="The real ltl2ba executable is not available in PATH.",
)


def test_construct_hard_buchi_from_real_ltl2ba() -> None:
    """Construct a hard Büchi automaton from a real translation."""
    buchi = buchi_from_ltl(
        "<> cargo",
        "hard_buchi",
    )

    assert buchi.graph["type"] == "hard_buchi"
    assert "cargo" in buchi.graph["symbols"]

    assert buchi.number_of_nodes() > 0
    assert buchi.number_of_edges() > 0

    assert buchi.graph["initial"]
    assert buchi.graph["accept"]

    for _, _, edge_data in buchi.edges(data=True):
        assert "guard" in edge_data
        assert "guard_formula" in edge_data


def test_construct_mission_buchi() -> None:
    """Construct a mission Büchi automaton from a hard specification."""
    buchi = mission_to_buchi(
        hard_spec="[] !danger && <> cargo",
        soft_spec=None,
    )

    assert buchi.graph["type"] == "hard_buchi"
    assert {"danger", "cargo"}.issubset(
        set(buchi.graph["symbols"])
    )
