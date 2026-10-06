import pytest

from ltl_automaton_planner_core.boolean_formulas.parser import (
    parse as parse_guard,
)
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


MULTI_BRANCH_PROMELA = """
never { /* duplicate branches */
T0_init:
    if
    :: (cargo) -> goto accept_S1
    :: (carry && ready) -> goto accept_S1
    :: (danger && alert) -> goto accept_S1
    fi;
accept_S1:
    skip
}
"""


@pytest.mark.parametrize(
    "label, expected_truth, expected_distance",
    [
        ({"cargo"}, True, 0),
        ({"carry", "ready"}, True, 0),
        ({"danger", "alert"}, True, 0),
        ({"carry"}, False, 1),
        ({"danger"}, False, 1),
        (set(), False, 1),
    ],
)
def test_duplicate_branch_guards_are_or_merged(
    label,
    expected_truth,
    expected_distance,
) -> None:
    """Merge same-target Promela options with OR guard semantics."""
    edges = parse(MULTI_BRANCH_PROMELA)
    guard = parse_guard(edges[("T0_init", "accept_S1")])

    assert len(edges) == 2
    assert guard.check(label) is expected_truth
    assert guard.distance(label) == expected_distance


def test_duplicate_branch_guard_merge_is_order_independent() -> None:
    """Produce equivalent OR semantics when same-target options are reversed."""
    reversed_promela = MULTI_BRANCH_PROMELA.replace(
        "    :: (cargo) -> goto accept_S1\n"
        "    :: (carry && ready) -> goto accept_S1\n"
        "    :: (danger && alert) -> goto accept_S1\n",
        "    :: (danger && alert) -> goto accept_S1\n"
        "    :: (carry && ready) -> goto accept_S1\n"
        "    :: (cargo) -> goto accept_S1\n",
    )
    forward = parse_guard(
        parse(MULTI_BRANCH_PROMELA)[("T0_init", "accept_S1")]
    )
    reverse = parse_guard(
        parse(reversed_promela)[("T0_init", "accept_S1")]
    )

    labels = [
        {"cargo"},
        {"carry", "ready"},
        {"danger", "alert"},
        {"carry"},
        {"danger"},
        set(),
    ]
    assert [forward.check(label) for label in labels] == [
        reverse.check(label) for label in labels
    ]
    assert [forward.distance(label) for label in labels] == [
        reverse.distance(label) for label in labels
    ]


@pytest.mark.parametrize(
    "malformed_promela",
    [
        (
            "never { /* missing fi */\n"
            "T0_init:\n"
            "    if\n"
            "    :: (1) -> goto T0_init\n"
            "}\n"
        ),
        (
            "never { /* missing brace */\n"
            "T0_init:\n"
            "    false;\n"
        ),
        (
            "never { /* undeclared target */\n"
            "T0_init:\n"
            "    if\n"
            "    :: (1) -> goto T1_state\n"
            "    fi;\n"
            "}\n"
        ),
        (
            "never { /* duplicate state */\n"
            "T0_init:\n"
            "    false;\n"
            "T0_init:\n"
            "    false;\n"
            "}\n"
        ),
        (
            "never { /* empty if */\n"
            "T0_init:\n"
            "    if\n"
            "    fi;\n"
            "}\n"
        ),
        "never { /* empty claim */\n}\n",
    ],
    ids=[
        "missing-fi",
        "missing-brace",
        "undeclared-target",
        "duplicate-state",
        "empty-if",
        "empty-claim",
    ],
)
def test_malformed_claim_boundaries_raise_parse_error(malformed_promela):
    """Reject malformed claims instead of returning incomplete graphs."""
    with pytest.raises(ParseException):
        parse(malformed_promela)
