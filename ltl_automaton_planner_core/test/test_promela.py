from ltl_automaton_planner_core.ltl_tools.promela import (
    find_states,
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
