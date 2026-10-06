"""Focused tests for the pure beta-learning core."""

import math

import pytest
from networkx import DiGraph

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
