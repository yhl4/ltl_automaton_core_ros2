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
