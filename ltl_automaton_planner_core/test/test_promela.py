import pytest

from ltl_automaton_planner_core.ltl_tools.promela import (
    ParseException,
    Parser,
    find_states,
    find_symbols,
    parse,
)


PROMELA_OUTPUT = """
never { /*<> cargo*/
T0_init:
    if
    :: (cargo) -> goto accept_S1
    :: (!cargo) -> goto T0_init
    fi;
accept_S1:
    skip
}
"""


def test_parse_promela_edges() -> None:
    """Parse transitions from LTL2BA Promela output."""
    edges = parse(PROMELA_OUTPUT)

    assert edges[("T0_init", "accept_S1")] == "(cargo)"
    assert edges[("T0_init", "T0_init")] == "(!cargo)"
    assert edges[("accept_S1", "accept_S1")] == "1"


def test_find_initial_and_accepting_states() -> None:
    """Identify initial and accepting Büchi states."""
    edges = parse(PROMELA_OUTPUT)
    states, initial_states, accepting_states = find_states(edges)

    assert set(states) == {"T0_init", "accept_S1"}
    assert set(initial_states) == {"T0_init"}
    assert set(accepting_states) == {"accept_S1"}


def test_find_symbols_preserves_complete_identifier_names() -> None:
    """Keep underscores and digits while sorting and deduplicating names."""
    formula = "[] (!danger_zone2 || cargo_ready1) && <> cargo_ready1 && r0_1 && home"
    assert find_symbols(formula) == [
        "cargo_ready1", "danger_zone2", "home", "r0_1",
    ]


def test_boolean_constants_are_not_atomic_proposition_names() -> None:
    """Exclude native constants while retaining similarly named propositions."""
    assert find_symbols("true || false || true_value0 || false_alarm1") == [
        "false_alarm1", "true_value0",
    ]


def test_parse_blocked_state_preserves_declared_initial() -> None:
    """Retain a declared initial state even when it has no transitions."""
    parser = Parser("never {    /* <> (false) */\nT0_init:\n    false;\n}\n")
    edges = parser.parse()
    assert edges == {}
    assert find_states(edges, parser.states) == (["T0_init"], ["T0_init"], [])


def test_missing_never_header_raises_a_parse_error() -> None:
    """Reject malformed translator output with an explicit parser error."""
    with pytest.raises(ParseException):
        parse("T0_init:\n    false;\n}")
