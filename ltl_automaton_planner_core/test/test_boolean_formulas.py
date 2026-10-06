from itertools import product

import pytest

from ltl_automaton_planner_core.boolean_formulas.parser import (
    Parser,
    SymbolExpression,
    parse,
)


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


def test_guard_token_consumption_preserves_precedence_and_remaining_symbols():
    """Check a hand-derived NNF over all labels and consume each symbol once."""
    formula = "!a || b && !(cargoReady1 || !d)"
    parser = Parser(formula)
    names = ("a", "b", "cargoReady1", "d")
    assert set(parser.symbols()) == set(names)

    expression = parser.parse()
    assert expression.formula == formula
    assert repr(expression) == (
        "ORExpression(NotSymbolExpression(a), ANDExpression(SymbolExpression(b), "
        "ANDExpression(NotSymbolExpression(cargoReady1), SymbolExpression(d))))"
    )
    assert not parser.tokens
    assert parser.symbols() == []
    for flags in product((False, True), repeat=len(names)):
        label = {name for name, present in zip(names, flags) if present}
        assert expression.check(label) == (
            "a" not in label
            or ("b" in label and "cargoReady1" not in label and "d" in label)
        )
        assert expression.distance(label) == min(
            int("a" in label),
            int("b" not in label) + int("cargoReady1" in label) + int("d" not in label),
        )


@pytest.mark.parametrize("operator", ["&&", "||"])
def test_long_flat_guard_preserves_operand_order_and_distance(operator):
    """Check 256 operands against simple conjunction/disjunction reference values."""
    names = [f"p{index}" for index in range(256)]
    formula = f" {operator} ".join(names)
    parser = Parser(formula)
    assert set(parser.symbols()) == set(names)
    expression = parser.parse()
    assert expression.formula == formula
    assert [item.symbol for item in expression if isinstance(item, SymbolExpression)] == names
    assert not parser.tokens
    assert parser.symbols() == []
    for label in (set(), {names[0]}, {names[-1]}, set(names)):
        if operator == "&&":
            assert expression.check(label) == (len(label) == len(names))
            assert expression.distance(label) == len(names) - len(label)
        else:
            assert expression.check(label) == bool(label)
            assert expression.distance(label) == int(not label)
