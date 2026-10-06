import pytest

from ltl_automaton_planner_core.boolean_formulas.parser import parse


def test_and_not_expression() -> None:
    expression = parse("a && !b")

    assert expression.check({"a"})
    assert not expression.check({"a", "b"})


def test_or_expression() -> None:
    expression = parse("a || b")

    assert expression.check({"a"})
    assert expression.check({"b"})
    assert not expression.check(set())


def test_distance() -> None:
    expression = parse("a && b")

    assert expression.distance({"a", "b"}) == 0
    assert expression.distance({"a"}) == 1
    assert expression.distance(set()) == 2


@pytest.mark.parametrize("formula", ["", "a)", "(a", "a &&", "a @ b"])
def test_malformed_guard_is_rejected(formula):
    """Reject incomplete guards and unconsumed or illegal tokens."""
    with pytest.raises(ValueError):
        parse(formula)


def test_negated_constant_and_repeated_negation():
    """Evaluate negated truth and nested negation without dropping tokens."""
    assert not parse("!1").check(set())
    assert parse("!1").distance(set()) == float("inf")
    assert parse("!!a").check({"a"})
    assert parse("!(!a || b)").check({"a"})


def test_mixed_case_identifiers_keep_case_sensitive_truth_and_distance():
    """Keep native lowercase-start identifiers intact through guard evaluation."""
    expression = parse("cargoReady1 && !dangerZone2")
    assert expression.check({"cargoReady1"})
    assert expression.distance({"cargoReady1"}) == 0
    assert not expression.check({"cargoready1"})
    assert expression.distance({"cargoready1"}) == 1
    assert not expression.check({"cargoReady1", "dangerZone2"})
    assert expression.distance({"cargoReady1", "dangerZone2"}) == 1
