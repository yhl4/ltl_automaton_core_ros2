"""Pure demonstration-driven learning of the soft-task weight beta."""

from copy import deepcopy
from dataclasses import dataclass
from itertools import islice
import math

from .discrete_plan import dijkstra_plan_networkX


@dataclass(frozen=True)
class IRLLearningResult:
    """Result of one bounded beta-learning run."""

    beta: float
    beta_sequence: tuple
    match_scores: tuple
    demonstration: tuple


def _finite_nonnegative(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite and non-negative.")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(
            f"{name} must be finite and non-negative."
        ) from error
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{name} must be finite and non-negative.")
    return numeric


def _path_soft_distance(product, path):
    def distances():
        edges = None
        for source, target in zip(path, islice(path, 1, None)):
            if edges is None:
                edges = product.edges
            yield edges[source, target]["soft_task_dist"]

    return sum(distances())


def _validate_runs(product, possible_runs):
    try:
        candidates = list(possible_runs)
    except TypeError as error:
        raise ValueError("possible_runs must be a non-empty iterable.") from error
    if not candidates:
        raise ValueError("Cannot learn beta from an empty run set.")

    validated = []
    for candidate in candidates:
        try:
            path = tuple(candidate)
        except TypeError as error:
            raise ValueError("Every demonstration must be a node path.") from error
        if len(path) < 2:
            raise ValueError("Every demonstration must contain at least two nodes.")
        for node in path:
            if not product.has_node(node):
                raise ValueError(f"Demonstration references unknown node {node!r}.")
        for source, target in zip(path, islice(path, 1, None)):
            if not product.has_edge(source, target):
                raise ValueError(
                    "Demonstration contains a transition absent from Product."
                )
        validated.append(path)
    return validated


def _apply_margin(product, beta, margin_edges):
    product.graph["beta"] = beta
    for edge, non_demo in margin_edges:
        edge["weight"] = (
            edge["transition_cost"]
            + beta * edge["soft_task_dist"]
        )
        if non_demo:
            edge["weight"] += 1.0


def learn_beta(product, possible_runs, beta, gamma):
    """
    Learn a non-negative beta from validated Product demonstrations.

    The input Product is read-only for this operation.  All margin weights and
    beta updates are applied to one private deepcopy.
    """
    current_beta = _finite_nonnegative(beta, "beta")
    gamma = _finite_nonnegative(gamma, "gamma")
    demonstrations = _validate_runs(product, possible_runs)
    demonstration, demonstration_soft = min(
        (
            (path, _path_soft_distance(product, path))
            for path in demonstrations
        ),
        key=lambda item: item[1],
    )
    demonstration_edges = set(
        zip(demonstration, islice(demonstration, 1, None))
    )
    learning_product = deepcopy(product)
    margin_edges = tuple(
        (
            edge,
            (source, target) not in demonstration_edges,
        )
        for source, target, edge in learning_product.edges(data=True)
    )

    beta_sequence = []
    match_scores = []
    for iteration in range(20):
        _apply_margin(learning_product, current_beta, margin_edges)
        run, _ = dijkstra_plan_networkX(learning_product, gamma=gamma)
        if run is None:
            raise RuntimeError("IRL margin planning found no accepting run.")
        run_soft = _path_soft_distance(learning_product, run.suffix)
        gradient = demonstration_soft - run_soft
        step = 1.0 if iteration < 10 else 1.0 / (iteration + 1)
        updated_beta = max(0.0, current_beta - step * gradient)
        beta_sequence.append(updated_beta)
        match_scores.append(
            sum(
                left == right
                for left, right in zip(demonstration, run.suffix)
            )
        )
        if abs(updated_beta - current_beta) <= 0.3:
            current_beta = updated_beta
            break
        current_beta = updated_beta

    return IRLLearningResult(
        beta=current_beta,
        beta_sequence=tuple(beta_sequence),
        match_scores=tuple(match_scores),
        demonstration=demonstration,
    )
