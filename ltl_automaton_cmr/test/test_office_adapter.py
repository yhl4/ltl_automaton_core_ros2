"""Source-fidelity and snapshot contract checks; no Office benchmark loop."""

from fractions import Fraction
import hashlib
from importlib.resources import files

import pytest

from ltl_automaton_cmr.office import (
    ASSET_SHA256, FAMILY_PRIOR, OFFICE8_QUERY_IDS, load_office_query,
)


def test_byte_preserved_office_inputs_and_monitor():
    for name, expected in ASSET_SHA256.items():
        data = files("ltl_automaton_cmr").joinpath("assets", name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected
    monitor = files("ltl_automaton_cmr").joinpath("vendor", "office_monitor_dsl.py").read_bytes()
    assert hashlib.sha256(monitor).hexdigest() == (
        "2025d63042d96b381350665bbf8cd8a6a284f6f2af16292f2a2dbf5edab6942b")


def test_office8_means_eight_queries_with_ten_dimensions():
    for query_id in OFFICE8_QUERY_IDS:
        query = load_office_query(query_id)
        assert query.query_id == query_id
        assert query.dimension_names == ("r", "p", "d", "b", "f", "l", "c", "w", "j", "s")
        assert query.family_prior == FAMILY_PRIOR == frozenset({0, 1, 2, 3})
        assert len(query.model.dimensions) == 10
        assert len(query.model.actions) == 48
    query = load_office_query()
    assert query.hard_task == "F(p=E)"
    assert query.model.task_support == {"p=E": frozenset({1})}
    assert "badge" in query.dimension_meanings[3]
    with pytest.raises(ValueError, match="Office8"):
        load_office_query("X1")


def test_badge_guard_and_atomic_multidimensional_effect():
    query = load_office_query()
    named = query.initial_named_state
    named["r"] = "H"
    unbadged = load_office_query(initial_state=named).model
    initial = next(iter(unbadged.initial_states))
    assert "open_door_from_hub" not in {edge.action for edge in unbadged.state_transitions_from(initial)}
    named["b"] = "robot"
    badged = load_office_query(initial_state=named).model
    initial = next(iter(badged.initial_states))
    door = next(edge for edge in badged.state_transitions_from(initial)
                if edge.action == "open_door_from_hub")
    assert query.decode_state(door.target)[2:4] == ("open", "robot")
    named.update(r="P", f="dirty", l="on", w="full")
    wash_model = load_office_query(initial_state=named).model
    initial = next(iter(wash_model.initial_states))
    wash = next(edge for edge in wash_model.state_transitions_from(initial) if edge.action == "wash_floor")
    before, after = query.decode_state(initial), query.decode_state(wash.target)
    assert after[4] == "wet" and after[7] == "empty"
    assert [i for i, (left, right) in enumerate(zip(before, after)) if left != right] == [4, 7]
    assert wash.cost == Fraction(3) and isinstance(wash.cost, Fraction)


def test_initial_goal_is_consumed_before_any_action():
    query = load_office_query()
    assert not any(q in query.model.buchi.accepting for _, q in query.model.initial_product_states())
    snapshot = query.initial_named_state
    snapshot["p"] = "E"
    achieved = load_office_query(initial_state=snapshot).model
    assert any(q in achieved.buchi.accepting for _, q in achieved.initial_product_states())


@pytest.mark.parametrize("snapshot", [
    {"p": "E"}, [0] * 9, [False] * 10, [0.0] * 10, [99] * 10,
])
def test_snapshot_rejects_partial_inexact_or_out_of_domain_values(snapshot):
    with pytest.raises((ValueError, TypeError)):
        load_office_query(initial_state=snapshot)
