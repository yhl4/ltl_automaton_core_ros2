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


@pytest.mark.parametrize("operator", ["&&", "||"])
@pytest.mark.parametrize(
    "label_kind",
    ["none", "first", "last", "all"],
)
def test_large_flat_guards_balance_without_changing_formula_semantics(
    operator, label_kind
):
    """Balance 2048 operands while retaining formula text and leaf order."""
    names = [f"p{index}" for index in range(2048)]
    formula = f" {operator} ".join(names)
    labels = {
        "none": set(),
        "first": {names[0]},
        "last": {names[-1]},
        "all": set(names),
    }
    label = labels[label_kind]

    expression = parse(formula)
    negated = parse(f"!({formula})")

    def depth(root):
        maximum = 0
        stack = [(root, 1)]
        while stack:
            node, node_depth = stack.pop()
            maximum = max(maximum, node_depth)
            stack.extend((child, node_depth + 1) for child in node.children())
        return maximum

    assert expression.formula == formula
    assert negated.formula == f"!({formula})"
    assert [item.symbol for item in expression if hasattr(item, "symbol")] == names
    assert [item.symbol for item in negated if hasattr(item, "symbol")] == names
    assert depth(expression) <= 12
    assert depth(negated) <= 12

    if operator == "&&":
        expected_truth = len(label) == len(names)
        expected_distance = len(names) - len(label)
        expected_negated_truth = not expected_truth
        expected_negated_distance = int(expected_truth)
    else:
        expected_truth = bool(label)
        expected_distance = int(not label)
        expected_negated_truth = not expected_truth
        expected_negated_distance = len(label)

    assert expression.check(label) is expected_truth
    assert expression.distance(label) == expected_distance
    assert negated.check(label) is expected_negated_truth
    assert negated.distance(label) == expected_negated_distance


class CountingLabel(set):
    """Count stable membership checks without changing their results."""

    def __init__(self, values=()):
        super().__init__(values)
        self.contains_count = 0

    def __contains__(self, value):
        self.contains_count += 1
        return super().__contains__(value)


@pytest.mark.parametrize(
    "label_values, expected_distance, expected_contains",
    [
        ("first", 0, 1),
        ("last", 0, 256),
        ("none", 1, 256),
    ],
)
def test_or_distance_short_circuits_only_at_zero(
    label_values, expected_distance, expected_contains
):
    """Stop OR distance traversal at a zero lower bound."""
    names = [f"p{index}" for index in range(256)]
    expression = parse(" || ".join(names))
    values = {
        "first": {names[0]},
        "last": {names[-1]},
        "none": set(),
    }[label_values]
    label = CountingLabel(values)

    assert expression.distance(label) == expected_distance
    assert label.contains_count == expected_contains


def test_distance_constants_and_nested_and_keep_hand_values():
    """Keep constant, infinite, zero, and nested AND distances unchanged."""
    assert parse("1 || a").distance(set()) == 0
    assert parse("!1 || a").distance(set()) == 1
    assert parse("!1 || !1").distance(set()) == float("inf")
    assert parse("a && (!b || c)").distance({"a"}) == 0
    assert parse("a && (!b || c)").distance({"a", "b"}) == 1
    assert parse("!1 && a").distance(set()) == float("inf")
