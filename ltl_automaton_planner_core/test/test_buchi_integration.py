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


def test_true_and_false_claims_keep_native_states_and_symbols() -> None:
    """Preserve native true/false automata without fake transitions."""
    true_buchi = buchi_from_ltl(
        "<> (true)",
        "hard_buchi",
    )
    false_buchi = buchi_from_ltl(
        "<> (false)",
        "hard_buchi",
    )

    assert set(true_buchi.graph["symbols"]) == set()
    assert set(true_buchi.graph["initial"]) == {"accept_init"}
    assert set(true_buchi.graph["accept"]) == {"accept_init"}
    assert true_buchi.has_edge("accept_init", "accept_init")

    assert set(false_buchi.nodes) == {"T0_init"}
    assert set(false_buchi.graph["initial"]) == {"T0_init"}
    assert set(false_buchi.graph["accept"]) == set()
    assert false_buchi.number_of_edges() == 0
    assert set(false_buchi.graph["symbols"]) == set()


@pytest.mark.parametrize("hard_symbol, soft_symbol", [
    ("cargo_ready1", "danger_zone2"),
    ("cargoReady1", "dangerZone2"),
])
def test_symbol_names_with_underscores_and_digits_remain_atomic(hard_symbol, soft_symbol):
    """Keep proposition names intact in original and combined Büchi graphs."""
    hard = buchi_from_ltl(
        "<> " + hard_symbol,
        "hard_buchi",
    )
    soft = buchi_from_ltl(
        "[] !" + soft_symbol,
        "soft_buchi",
    )
    combined = mission_to_buchi(
        hard_spec="<> " + hard_symbol,
        soft_spec="[] !" + soft_symbol,
    )

    assert set(hard.graph["symbols"]) == {hard_symbol}
    assert set(soft.graph["symbols"]) == {soft_symbol}
    assert set(combined.graph["symbols"]) == {
        hard_symbol,
        soft_symbol,
    }

    hard_guard_symbols = {
        edge_data["guard"].symbol
        for _, _, edge_data in hard.edges(data=True)
        if hasattr(edge_data["guard"], "symbol")
    }
    soft_guard_symbols = {
        edge_data["guard"].symbol
        for _, _, edge_data in soft.edges(data=True)
        if hasattr(edge_data["guard"], "symbol")
    }
    combined_hard_symbols = {
        edge_data["hardguard"].symbol
        for _, _, edge_data in combined.edges(data=True)
        if hasattr(edge_data["hardguard"], "symbol")
    }
    combined_soft_symbols = {
        edge_data["softguard"].symbol
        for _, _, edge_data in combined.edges(data=True)
        if hasattr(edge_data["softguard"], "symbol")
    }

    assert hard_symbol in hard_guard_symbols
    assert soft_symbol in soft_guard_symbols
    assert hard_symbol in combined_hard_symbols
    assert soft_symbol in combined_soft_symbols
