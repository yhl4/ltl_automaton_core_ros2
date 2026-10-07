"""Focused tests for the pure beta-learning core."""

import math
from types import SimpleNamespace

import pytest
from networkx import DiGraph

from ltl_automaton_planner_core.ltl_tools import irl
from ltl_automaton_planner_core.ltl_tools.irl import IRLLearningResult
from ltl_automaton_planner_core.ltl_tools.irl import learn_beta
from ltl_automaton_planner_core.ltl_tools.product import ProdAut


def _margin_product():
    ts = DiGraph(initial={"hub"})
    ts.add_nodes_from((name, {"label": set()}) for name in ("hub", "bad", "good"))
    ts_edges = (
        ("hub", "bad", 0.0, "to_bad"),
        ("bad", "hub", 0.0, "from_bad"),
        ("hub", "good", 4.0, "to_good"),
        ("good", "hub", 0.0, "from_good"),
    )
    for source, target, weight, action in ts_edges:
        ts.add_edge(source, target, weight=weight, action=action)

    buchi = DiGraph(initial={"q0"}, accept={"q0"})
    product = ProdAut(ts, buchi)
    product_nodes = {
        name: (name, "q0") for name in ("hub", "bad", "good")
    }
    product.add_nodes_from(
        (node, {"ts": name, "buchi": "q0"})
        for name, node in product_nodes.items()
    )
    product.graph["initial"] = {product_nodes["hub"]}
    product.graph["accept"] = {product_nodes["hub"]}
    product.graph["accept_with_cycle"] = {product_nodes["hub"]}
    product.possible_states = set(product.graph["initial"])
    for source, target, transition_cost, action in ts_edges:
        soft_task_dist = 1.0 if target == "bad" else 0.0
        product.add_edge(
            product_nodes[source],
            product_nodes[target],
            transition_cost=transition_cost,
            soft_task_dist=soft_task_dist,
            weight=transition_cost,
            action=action,
        )
    return product, product_nodes


@pytest.mark.parametrize(
    "beta, transition_cost, soft_distance",
    [
        (0.0, 0.0, 1.0),
        (0.1, 0.2, 0.3),
        (3.0, 4.0, 1.0),
        (1.0, 1e16, 1.0),
    ],
)
def test_margin_replaces_weights_without_accumulating(
    beta, transition_cost, soft_distance,
):
    """Keep canonical arithmetic and add margin only to non-demo edges."""
    product, nodes = _margin_product()
    demonstration_edges = {
        (nodes["hub"], nodes["good"]),
        (nodes["good"], nodes["hub"]),
    }
    for edge in product.edges.values():
        edge["transition_cost"] = transition_cost
        edge["soft_task_dist"] = soft_distance
        edge["weight"] = -99.0
    original = {pair: dict(edge) for pair, edge in product.edges.items()}
    margin_edges = tuple(
        (edge, pair not in demonstration_edges)
        for pair, edge in product.edges.items()
    )

    for next_beta in (beta, beta + 2.0, beta + 2.0):
        irl._apply_margin(product, next_beta, margin_edges)

        assert product.graph["beta"] == next_beta
        for pair, edge in product.edges.items():
            expected = dict(original[pair])
            weight = transition_cost + next_beta * soft_distance
            if pair not in demonstration_edges:
                weight += 1.0
            expected["weight"] = weight
            assert edge == expected


def test_learn_beta_margin_updates_private_copy_and_matches_hand_fixture():
    product, nodes = _margin_product()
    demonstration = (
        nodes["hub"],
        nodes["good"],
        nodes["hub"],
    )
    before_edges = {
        edge: dict(data) for edge, data in product.edges.items()
    }
    before_initial = set(product.graph["initial"])
    before_possible = set(product.possible_states)
    before_beta = product.graph["beta"]

    result = learn_beta(product, {demonstration}, beta=0, gamma=1)

    assert isinstance(result, IRLLearningResult)
    assert result.demonstration == demonstration
    assert result.beta in (2.0, 3.0)
    assert result.beta_sequence[0:2] == (1.0, 2.0)
    assert result.beta_sequence[-1] == result.beta
    assert result.match_scores
    assert product.graph["beta"] == before_beta
    assert product.graph["initial"] == before_initial
    assert product.possible_states == before_possible
    assert {
        edge: dict(data) for edge, data in product.edges.items()
    } == before_edges


def test_nonnegative_projection_handles_reverse_gradient():
    product, nodes = _margin_product()
    bad = (nodes["hub"], nodes["bad"], nodes["hub"])
    product[nodes["hub"]][nodes["bad"]]["transition_cost"] = 4.0
    product[nodes["bad"]][nodes["hub"]]["transition_cost"] = 0.0
    product[nodes["hub"]][nodes["good"]]["transition_cost"] = 0.0

    result = learn_beta(product, [bad], beta=0.0, gamma=1.0)

    assert result.beta == 0.0
    assert result.beta_sequence == (0.0,)


def test_learning_keeps_all_twenty_margin_updates_on_one_private_product(monkeypatch):
    """Preserve bounded large-gradient updates and reset every edge's margin."""
    product, nodes = _margin_product()
    product.edges[nodes["hub"], nodes["bad"]]["soft_task_dist"] = 10.0
    demonstration = (nodes["hub"], nodes["good"], nodes["hub"])
    demonstration_edges = set(zip(demonstration, demonstration[1:]))
    before = {pair: dict(edge) for pair, edge in product.edges.items()}
    products = []
    planned_betas = []

    def fixed_large_gradient(candidate, gamma):
        assert candidate is not product
        assert gamma == 1.0
        products.append(candidate)
        planned_betas.append(candidate.graph["beta"])
        for pair, edge in candidate.edges.items():
            expected = before[pair]["transition_cost"] + candidate.graph["beta"] * (
                before[pair]["soft_task_dist"]
            )
            if pair not in demonstration_edges:
                expected += 1.0
            assert edge["weight"] == expected
        return SimpleNamespace(suffix=[nodes["hub"], nodes["bad"], nodes["hub"]]), None

    monkeypatch.setattr(irl, "dijkstra_plan_networkX", fixed_large_gradient)
    result = learn_beta(product, [demonstration], beta=0, gamma=1)

    assert len(planned_betas) == len(result.beta_sequence) == 20
    assert all(candidate is products[0] for candidate in products)
    assert tuple(planned_betas) == (0.0,) + result.beta_sequence[:-1]
    assert result.beta_sequence[:10] == tuple(float(value) for value in range(10, 101, 10))
    expected_tail = []
    expected_beta = 100.0
    for denominator in range(11, 21):
        expected_beta += 10.0 / denominator
        expected_tail.append(expected_beta)
    assert result.beta_sequence[10:] == tuple(expected_tail)
    assert result.beta == expected_beta
    assert result.match_scores == (2,) * 20
    assert result.demonstration == demonstration
    assert {pair: dict(edge) for pair, edge in product.edges.items()} == before
    assert product.graph["beta"] == 1000


def test_learning_reads_changed_product_edges_on_the_next_call():
    """Rebuild learning weights after changing the source Product between calls."""
    product, nodes = _margin_product()
    demonstration = (nodes["hub"], nodes["good"], nodes["hub"])
    first = learn_beta(product, [demonstration], beta=0, gamma=1)
    assert first.beta_sequence[:2] == (1.0, 2.0)

    edge = product.edges[nodes["hub"], nodes["good"]]
    edge["transition_cost"] = 0.0
    edge["weight"] = 99.0
    before = {pair: dict(data) for pair, data in product.edges.items()}
    second = learn_beta(product, [demonstration], beta=0, gamma=1)

    assert second.beta == 0.0
    assert second.beta_sequence == (0.0,)
    assert second.demonstration == demonstration
    assert {pair: dict(data) for pair, data in product.edges.items()} == before


@pytest.mark.parametrize(
    "value",
    [-1, math.inf, math.nan, True, False],
)
def test_beta_and_gamma_must_be_finite_nonnegative_numbers(value):
    product, nodes = _margin_product()
    path = (nodes["hub"], nodes["good"])
    with pytest.raises(ValueError):
        learn_beta(product, [path], beta=value, gamma=1.0)
    with pytest.raises(ValueError):
        learn_beta(product, [path], beta=0.0, gamma=value)


@pytest.mark.parametrize("name", ["beta", "gamma"])
@pytest.mark.parametrize("sign", [1, -1], ids=["positive", "negative"])
def test_overflowing_learning_weights_preserve_product_before_planning(name, sign, monkeypatch):
    """Reject overflowing input before copying, reweighting or margin planning."""
    product, nodes = _margin_product()
    path = (nodes["hub"], nodes["good"])
    before_edges = [(source, target, dict(data)) for source, target, data
                    in product.edges(data=True)]
    before_beta = product.graph["beta"]

    def unexpected_work(*args, **kwargs):
        raise AssertionError("Invalid IRL weights must fail before planning or copying.")

    monkeypatch.setattr(irl, "deepcopy", unexpected_work)
    monkeypatch.setattr(irl, "dijkstra_plan_networkX", unexpected_work)
    weights = {"beta": 0.0, "gamma": 1.0}
    weights[name] = sign * 10**400
    with pytest.raises(ValueError) as caught:
        learn_beta(product, [path], **weights)
    assert str(caught.value) == f"{name} must be finite and non-negative."
    assert isinstance(caught.value.__cause__, OverflowError)
    assert list(product.edges(data=True)) == before_edges
    assert product.graph["beta"] == before_beta
    assert product.graph["initial"] == product.possible_states == {nodes["hub"]}


@pytest.mark.parametrize(
    "demonstrations",
    [
        [],
        [("unknown", "node")],
    ],
)
def test_invalid_demonstrations_are_rejected(demonstrations):
    product, nodes = _margin_product()
    if demonstrations == [("unknown", "node")]:
        demonstrations = [(nodes["hub"], "unknown")]
    with pytest.raises(ValueError):
        learn_beta(product, demonstrations, beta=0.0, gamma=1.0)


def test_missing_demonstration_edge_is_rejected():
    product, nodes = _margin_product()
    path = (nodes["hub"], nodes["good"], nodes["bad"])
    with pytest.raises(ValueError, match="absent"):
        learn_beta(product, [path], beta=0.0, gamma=1.0)


def test_no_accepting_run_is_a_learning_error():
    product, nodes = _margin_product()
    product.graph["accept_with_cycle"] = set()
    path = (nodes["hub"], nodes["good"])
    with pytest.raises(RuntimeError, match="no accepting run"):
        learn_beta(product, [path], beta=0.0, gamma=1.0)


@pytest.mark.parametrize("path_type", [list, tuple])
def test_path_soft_distance_counts_only_listed_edges(path_type):
    """Count repeated/self-loop edges without adding an implicit closure edge."""
    product, nodes = _margin_product()
    product.add_edge(
        nodes["hub"], nodes["hub"],
        soft_task_dist=1.0, transition_cost=0.0, weight=0.0,
    )
    product.edges[nodes["hub"], nodes["good"]]["soft_task_dist"] = 1e16
    product.edges[nodes["good"], nodes["hub"]]["soft_task_dist"] = 1.0
    before_edges = {
        pair: dict(data) for pair, data in product.edges.items()
    }
    cases = (
        ((), 0),
        ((nodes["hub"],), 0),
        ((nodes["hub"], nodes["bad"], nodes["hub"]), 1.0),
        ((nodes["hub"], nodes["bad"], nodes["hub"], nodes["bad"]), 2.0),
        ((nodes["hub"], nodes["hub"], nodes["hub"]), 2.0),
        ((nodes["hub"], nodes["good"], nodes["hub"], nodes["hub"]), 1e16),
    )

    for values, expected in cases:
        path = path_type(values)
        original_path = tuple(path)
        assert irl._path_soft_distance(product, path) == expected
        assert tuple(path) == original_path
    assert {
        pair: dict(data) for pair, data in product.edges.items()
    } == before_edges


@pytest.mark.parametrize("path_type", [list, tuple])
def test_validate_runs_preserves_repeated_paths_and_unknown_priority(path_type):
    """Validate repeated edges while reporting unknown nodes before edges."""
    product, nodes = _margin_product()
    repeated = path_type(
        (nodes["hub"], nodes["bad"], nodes["hub"], nodes["bad"])
    )
    before_edges = {
        pair: dict(data) for pair, data in product.edges.items()
    }

    validated = irl._validate_runs(product, [repeated])
    assert validated == [tuple(repeated)]
    assert tuple(repeated) == (
        nodes["hub"], nodes["bad"], nodes["hub"], nodes["bad"]
    )
    assert {
        pair: dict(data) for pair, data in product.edges.items()
    } == before_edges

    unknown = path_type((nodes["good"], nodes["bad"], "unknown"))
    with pytest.raises(
        ValueError,
        match="Demonstration references unknown node 'unknown'",
    ):
        irl._validate_runs(product, [unknown])
    assert tuple(unknown) == (nodes["good"], nodes["bad"], "unknown")
