"""Export certified concrete occurrences to the existing symbolic executor."""
from dataclasses import dataclass
from fractions import Fraction
from math import isfinite

from ltl_automaton_execution.models import (
    AcceptedRun, ExecutionObservation, PlanningSnapshot, ProductEdge,
    ProductNode, SymbolicState,
)


class CapabilityError(ValueError):
    """An existing public contract cannot carry the exact CMR result."""


@dataclass(frozen=True)
class OccurrenceProjection:
    """Finite run occurrences keep separate IDs and formal Product states."""
    snapshot: PlanningSnapshot
    product_states: tuple
    exact_edges: tuple


def build_occurrence_projection(lasso, dimension_names, value_names=None,
                                planner_instance_id="cmr", planning_generation=1):
    """Keep repetitions and action identity; omit only terminal loop closure."""
    prefix, suffix = lasso.prefix, lasso.suffix
    if (not prefix or len(suffix) < 2 or not lasso.suffix_edges
            or prefix[-1] != suffix[0] or suffix[0] != suffix[-1]
            or len(prefix) != len(lasso.prefix_edges) + 1
            or len(suffix) != len(lasso.suffix_edges) + 1):
        raise CapabilityError("Invalid nonempty concrete closed-walk shape.")
    for states, edges, cost in ((prefix, lasso.prefix_edges, lasso.prefix_cost),
                                (suffix, lasso.suffix_edges, lasso.suffix_cost)):
        if (any(e.source != states[i] or e.target != states[i + 1]
                for i, e in enumerate(edges))
                or sum((e.cost for e in edges), Fraction(0)) != cost):
            raise CapabilityError("Concrete edge identity or exact cost mismatch.")
    names = tuple(dimension_names)
    if value_names is not None and len(value_names) != len(names):
        raise CapabilityError("One value domain is required per dimension.")
    if value_names is not None:
        for domain in value_names:
            if (not domain or any(not isinstance(value, str) or not value.strip()
                                  for value in domain)
                    or len(set(domain)) != len(domain)):
                raise CapabilityError("Symbolic domains must have unique nonempty strings.")
    states = tuple(prefix) + tuple(suffix[1:-1])
    nodes = []
    for identifier, (state, _) in enumerate(states):
        if len(state) != len(names):
            raise CapabilityError("Concrete and symbolic dimension counts differ.")
        if value_names is not None and any(
                type(v) is not int or v < 0 or v >= len(value_names[i])
                for i, v in enumerate(state)):
            raise CapabilityError("Concrete value has no lossless symbolic index.")
        try:
            values = tuple(str(v) for v in state) if value_names is None else tuple(
                value_names[i][v] for i, v in enumerate(state))
        except (IndexError, KeyError, TypeError) as error:
            raise CapabilityError("Concrete value has no symbolic encoding.") from error
        nodes.append(ProductNode(identifier, SymbolicState(names, values)))
    prefix_ids = tuple(range(len(prefix)))
    suffix_ids = (prefix_ids[-1],) + tuple(range(len(prefix), len(states)))
    pairs = tuple(zip(prefix_ids, prefix_ids[1:])) + tuple(
        zip(suffix_ids, suffix_ids[1:])) + ((suffix_ids[-1], suffix_ids[0]),)
    exact_edges = tuple(lasso.prefix_edges) + tuple(lasso.suffix_edges)
    edges = tuple(ProductEdge(source, target, edge.action)
                  for (source, target), edge in zip(pairs, exact_edges))
    snapshot = PlanningSnapshot(planner_instance_id, planning_generation,
                                tuple(nodes), edges,
                                AcceptedRun(prefix_ids, suffix_ids))
    return OccurrenceProjection(snapshot, states, exact_edges)


def build_execution_snapshot(lasso, dimension_names, value_names=None,
                             planner_instance_id="cmr", planning_generation=1):
    """Return the cost-free, lossless existing Python execution contract."""
    return build_occurrence_projection(lasso, dimension_names, value_names,
                                       planner_instance_id, planning_generation).snapshot


def certified_execution_snapshot(result, model, dimension_names, value_names=None,
                                 planner_instance_id="cmr", planning_generation=1):
    """Validate the certified witness against the model before Python dispatch."""
    if result.status != "OPTIMALITY_CERTIFIED" or result.lasso is None:
        raise CapabilityError("Only a certified concrete lasso is executable.")
    from .engine import validate_concrete_lasso
    validate_concrete_lasso(model, result.lasso)
    if result.cost != result.lasso.upper_bound:
        raise CapabilityError("Certified and concrete objectives disagree.")
    return build_execution_snapshot(result.lasso, dimension_names, value_names,
                                    planner_instance_id, planning_generation)


def public_exact_float(value):
    """Check float64 capability after certification, never during search."""
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise CapabilityError("A public CMR cost must start as int/Fraction.")
    try:
        converted = float(value)
    except (ValueError, OverflowError) as error:
        raise CapabilityError("Exact cost exceeds ROS float64 capability.") from error
    if not isfinite(converted) or Fraction.from_float(converted) != value:
        raise CapabilityError(
            f"ROS float64 cannot losslessly carry exact cost {value}; "
            "use the exact JSON result or Python symbolic execution adapter.")
    return converted


def to_ros_snapshot(result, model, dimension_names, value_names=None,
                    planner_instance_id="cmr", planning_generation=1,
                    source_sha256="", hard_task=""):
    """Build a retained-occurrence snapshot after exact certification."""
    if result.status != "OPTIMALITY_CERTIFIED" or result.lasso is None:
        raise CapabilityError("Only a certified concrete lasso is executable.")
    from .engine import validate_concrete_lasso
    lasso = result.lasso
    validate_concrete_lasso(model, lasso)
    if result.cost != lasso.upper_bound:
        raise CapabilityError("Certified and concrete objectives disagree.")
    costs = tuple(public_exact_float(e.cost) for e in
                  lasso.prefix_edges + lasso.suffix_edges)
    totals = tuple(public_exact_float(v) for v in
                   (lasso.prefix_cost, lasso.suffix_cost, result.cost))
    projection = build_occurrence_projection(lasso, dimension_names, value_names,
                                             planner_instance_id, planning_generation)
    from ltl_automaton_msgs.msg import (
        BuchiGraphNode, PlanningGraphSnapshot, ProductGraphEdge,
        ProductGraphNode, TransitionSystemState,
    )
    output = PlanningGraphSnapshot()
    meta = output.metadata
    meta.planner_instance_id = planner_instance_id
    meta.planning_generation = planning_generation
    meta.active_ts_sha256 = source_sha256
    meta.hard_task = hard_task
    meta.buchi_type = "cmr_retained_occurrences"
    meta.available = True
    q_names = sorted({q for _, q in projection.product_states})
    q_ids = {q: i for i, q in enumerate(q_names)}
    output.buchi_nodes = [BuchiGraphNode(id=q_ids[q], state=q, display_label=q,
                                       initial=q == model.buchi.initial,
                                       accepting=q in model.buchi.accepting)
                          for q in q_names]
    output.product_nodes = [ProductGraphNode(
        id=node.node_id,
        ts_state=TransitionSystemState(state_dimension_names=list(node.ts_state.dimension_names),
                                       states=list(node.ts_state.states)),
        buchi_node_id=q_ids[projection.product_states[node.node_id][1]],
        initial=node.node_id == 0,
        accepting=projection.product_states[node.node_id][1] in model.buchi.accepting,
    ) for node in projection.snapshot.product_nodes]
    output.product_edges = [ProductGraphEdge(source_id=e.source_id, target_id=e.target_id,
                                            action=e.action, transition_cost=cost,
                                            total_weight=cost)
                            for e, cost in zip(projection.snapshot.product_edges, costs)]
    meta.buchi_node_count = len(output.buchi_nodes)
    meta.product_node_count = len(output.product_nodes)
    meta.product_edge_count = len(output.product_edges)
    output.accepted_run.prefix_product_node_ids = list(projection.snapshot.accepted_run.prefix_node_ids)
    output.accepted_run.suffix_product_node_ids = list(projection.snapshot.accepted_run.suffix_node_ids)
    output.accepted_run.prefix_cost, output.accepted_run.suffix_cost, output.accepted_run.total_cost = totals
    return output


class ExecutionCursor:
    """Advance occurrences only on expected, newly stamped TS feedback."""
    def __init__(self, snapshot, minimum_stamp=None):
        self.snapshot = snapshot
        run = snapshot.accepted_run
        self._prefix = run.prefix_node_ids
        self._suffix = run.suffix_node_ids
        self._prefix_index = 0
        self._suffix_index = 0
        self._in_suffix = len(self._prefix) == 1
        self.step_seq = 0
        self._last_stamp = minimum_stamp
        self._nodes = {n.node_id: n for n in snapshot.product_nodes}
        self._edges = {(e.source_id, e.target_id): e for e in snapshot.product_edges}

    def current_pair(self):
        if self._in_suffix:
            return (self._suffix[self._suffix_index],
                    self._suffix[(self._suffix_index + 1) % len(self._suffix)])
        return self._prefix[self._prefix_index:self._prefix_index + 2]

    def observation(self):
        source, target = self.current_pair()
        edge = self._edges[(source, target)]
        return ExecutionObservation(self.snapshot.planner_instance_id,
                                    self.snapshot.planning_generation, self.step_seq,
                                    (source,), True, edge.action)

    def accept_feedback(self, state, stamp):
        if self._last_stamp is not None and stamp <= self._last_stamp:
            return False
        self._last_stamp = stamp
        _, target = self.current_pair()
        if state != self._nodes[target].ts_state:
            return False
        if self._in_suffix:
            self._suffix_index = (self._suffix_index + 1) % len(self._suffix)
        else:
            self._prefix_index += 1
            if self._prefix_index == len(self._prefix) - 1:
                self._in_suffix = True
        self.step_seq += 1
        return True
