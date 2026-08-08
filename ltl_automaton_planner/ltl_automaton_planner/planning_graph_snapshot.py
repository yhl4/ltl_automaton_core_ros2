"""Deterministically serialize one accepted planner graph snapshot."""

from ltl_automaton_msgs.msg import (
    AcceptedRunSnapshot,
    BuchiGraphEdge,
    BuchiGraphNode,
    PlanningGraphMetadata,
    PlanningGraphSnapshot,
    ProductGraphEdge,
    ProductGraphNode,
    TransitionSystemState,
)


def _flatten_dimension_names(raw_names) -> list[str]:
    """Flatten the TS state format retained by single or composed models."""
    dimension_names = []

    for name in raw_names:
        if isinstance(name, (list, tuple)):
            dimension_names.extend(str(item) for item in name)
        else:
            dimension_names.append(str(name))

    return dimension_names


def _membership(graph, key: str) -> set:
    """Normalize a known NetworkX graph membership attribute."""
    if key not in graph.graph:
        raise ValueError(f"Buchi/Product graph has no {key!r} set.")

    value = graph.graph[key]

    try:
        if value in graph:
            return {value}
    except TypeError:
        pass

    if isinstance(value, (set, list, tuple)):
        return set(value)

    raise ValueError(f"Buchi/Product graph {key!r} is not a membership set.")


def _buchi_type(buchi) -> str:
    """Return the stable public type for a supported Core Buchi graph."""
    graph_type = buchi.graph.get("type")

    if graph_type == "safe_buchi":
        return "safe_buchi"

    if graph_type in {"hard_buchi", "soft_buchi"}:
        return "single_buchi"

    raise ValueError(f"Unsupported Buchi graph type: {graph_type!r}.")


def _buchi_identity(buchi, node) -> tuple:
    """Return a structured, deterministic identity for a Buchi node."""
    graph_type = _buchi_type(buchi)

    if graph_type == "single_buchi":
        if not isinstance(node, str):
            raise ValueError("A single Buchi node must be a string.")

        return ("single", node)

    attributes = buchi.nodes[node]

    try:
        hard_state = str(attributes["hard"])
        soft_state = str(attributes["soft"])
        level = int(attributes["level"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "A safe Buchi node must define hard, soft, and level."
        ) from error

    return ("safe", hard_state, soft_state, level)


def _formula(expression, field_name: str) -> str:
    """Read formal text from a parsed Boolean expression."""
    try:
        formula = expression.formula
    except AttributeError as error:
        raise ValueError(
            f"Buchi edge {field_name!r} has no formula text."
        ) from error

    if not isinstance(formula, str):
        raise ValueError(
            f"Buchi edge {field_name!r} formula must be a string."
        )

    return formula


def _serialize_buchi(buchi):
    """Serialize Buchi nodes and edges with snapshot-local IDs."""
    graph_type = _buchi_type(buchi)
    initial = _membership(buchi, "initial")
    accepting = _membership(buchi, "accept")
    ordered_nodes = sorted(
        buchi.nodes,
        key=lambda node: _buchi_identity(buchi, node),
    )
    node_ids = {
        node: identifier
        for identifier, node in enumerate(ordered_nodes)
    }
    messages = []

    for node in ordered_nodes:
        identity = _buchi_identity(buchi, node)
        message = BuchiGraphNode()
        message.id = node_ids[node]
        message.initial = node in initial
        message.accepting = node in accepting

        if graph_type == "single_buchi":
            message.display_label = identity[1]
            message.state = identity[1]
            message.acceptance_level = (
                BuchiGraphNode.LEVEL_NOT_APPLICABLE
            )
        else:
            message.hard_state = identity[1]
            message.soft_state = identity[2]
            message.acceptance_level = identity[3]
            message.display_label = (
                f"{identity[1]} | {identity[2]} | level {identity[3]}"
            )

        messages.append(message)

    edge_messages = []

    for source, target, attributes in buchi.edges(data=True):
        message = BuchiGraphEdge()
        message.source_id = node_ids[source]
        message.target_id = node_ids[target]

        if graph_type == "single_buchi":
            formula = attributes.get("guard_formula")

            if formula is None:
                formula = _formula(attributes.get("guard"), "guard")

            if not isinstance(formula, str):
                raise ValueError("Buchi guard_formula must be a string.")

            message.guard_formula = formula
        else:
            message.hard_guard_formula = _formula(
                attributes.get("hardguard"),
                "hardguard",
            )
            message.soft_guard_formula = _formula(
                attributes.get("softguard"),
                "softguard",
            )

        edge_messages.append(message)

    edge_messages.sort(
        key=lambda edge: (
            edge.source_id,
            edge.target_id,
            edge.guard_formula,
            edge.hard_guard_formula,
            edge.soft_guard_formula,
        )
    )
    return graph_type, node_ids, messages, edge_messages


def _ts_values(ts_node) -> list[str]:
    """Return one Core TS node as ordered string dimensions."""
    values = ts_node if isinstance(ts_node, tuple) else (ts_node,)
    return [str(value) for value in values]


def _serialize_product(product, buchi, buchi_ids):
    """Serialize Product nodes and edges with structured ordering."""
    transition_system = product.graph["ts"]
    dimension_names = _flatten_dimension_names(
        transition_system.graph["ts_state_format"]
    )
    initial = _membership(product, "initial")
    accepting = _membership(product, "accept")

    def product_identity(node):
        attributes = product.nodes[node]
        ts_node = attributes["ts"]
        buchi_node = attributes["buchi"]
        return (
            tuple(_ts_values(ts_node)),
            _buchi_identity(buchi, buchi_node),
        )

    ordered_nodes = sorted(product.nodes, key=product_identity)
    node_ids = {
        node: identifier
        for identifier, node in enumerate(ordered_nodes)
    }
    messages = []

    for node in ordered_nodes:
        attributes = product.nodes[node]
        ts_values = _ts_values(attributes["ts"])

        if len(ts_values) != len(dimension_names):
            raise ValueError(
                "Product TS state does not match ts_state_format."
            )

        state = TransitionSystemState()
        state.states = ts_values
        state.state_dimension_names = dimension_names
        message = ProductGraphNode()
        message.id = node_ids[node]
        message.ts_state = state
        message.buchi_node_id = buchi_ids[attributes["buchi"]]
        message.initial = node in initial
        message.accepting = node in accepting
        messages.append(message)

    edge_messages = []

    for source, target, attributes in product.edges(data=True):
        required = {
            "action",
            "transition_cost",
            "soft_task_dist",
            "weight",
        }
        missing = required.difference(attributes)

        if missing:
            fields = ", ".join(sorted(missing))
            raise ValueError(f"Product edge is missing fields: {fields}.")

        message = ProductGraphEdge()
        message.source_id = node_ids[source]
        message.target_id = node_ids[target]
        message.action = str(attributes["action"])
        message.transition_cost = float(attributes["transition_cost"])
        message.soft_task_distance = float(attributes["soft_task_dist"])
        message.total_weight = float(attributes["weight"])
        edge_messages.append(message)

    edge_messages.sort(
        key=lambda edge: (
            edge.source_id,
            edge.target_id,
            edge.action,
            edge.transition_cost,
            edge.soft_task_distance,
            edge.total_weight,
        )
    )
    return node_ids, messages, edge_messages


def _serialize_run(planner, product, product_ids):
    """Serialize the complete accepted prefix-suffix Product run."""
    run = planner.run

    if run is None:
        raise ValueError("The planner has no accepted run.")

    try:
        prefix_ids = [product_ids[node] for node in run.prefix]
        suffix_ids = [product_ids[node] for node in run.suffix]
    except KeyError as error:
        raise ValueError(
            "The accepted run references a node outside the Product graph."
        ) from error

    if not suffix_ids:
        raise ValueError("The accepted run has no suffix cycle.")

    if len(run.suffix) > 1 and run.suffix[-1] == run.suffix[0]:
        raise ValueError(
            "The accepted suffix repeats its start node at the end."
        )

    if not product.has_edge(run.suffix[-1], run.suffix[0]):
        raise ValueError("The accepted suffix does not close in the Product graph.")

    message = AcceptedRunSnapshot()
    message.prefix_product_node_ids = prefix_ids
    message.suffix_product_node_ids = suffix_ids
    message.prefix_cost = float(run.precost)
    message.suffix_cost = float(run.sufcost)
    message.total_cost = float(run.totalcost)
    return message


def build_planning_graph_snapshot(
    planner,
    active_ts_sha256: str,
) -> PlanningGraphSnapshot:
    """Build a complete deterministic snapshot from one accepted planner."""
    if planner is None or planner.product is None or planner.run is None:
        raise ValueError("No accepted planner is available for serialization.")

    product = planner.product
    buchi = product.graph["buchi"]
    (
        graph_type,
        buchi_ids,
        buchi_nodes,
        buchi_edges,
    ) = _serialize_buchi(buchi)
    product_ids, product_nodes, product_edges = _serialize_product(
        product,
        buchi,
        buchi_ids,
    )
    accepted_run = _serialize_run(planner, product, product_ids)

    metadata = PlanningGraphMetadata()
    metadata.active_ts_sha256 = active_ts_sha256
    metadata.hard_task = str(planner.hard_spec)
    metadata.soft_task = str(planner.soft_spec)
    metadata.buchi_type = graph_type
    metadata.buchi_node_count = len(buchi_nodes)
    metadata.buchi_edge_count = len(buchi_edges)
    metadata.product_node_count = len(product_nodes)
    metadata.product_edge_count = len(product_edges)
    metadata.available = True

    snapshot = PlanningGraphSnapshot()
    snapshot.metadata = metadata
    snapshot.buchi_nodes = buchi_nodes
    snapshot.buchi_edges = buchi_edges
    snapshot.product_nodes = product_nodes
    snapshot.product_edges = product_edges
    snapshot.accepted_run = accepted_run
    return snapshot


def unavailable_planning_graph_snapshot(
    planner,
    active_ts_sha256: str,
    reason: str,
) -> PlanningGraphSnapshot:
    """Build an atomic empty payload describing conversion unavailability."""
    metadata = PlanningGraphMetadata()
    metadata.active_ts_sha256 = active_ts_sha256
    metadata.available = False
    metadata.unavailable_reason = reason

    if planner is not None:
        metadata.hard_task = str(getattr(planner, "hard_spec", ""))
        metadata.soft_task = str(getattr(planner, "soft_spec", ""))
        product = getattr(planner, "product", None)

        if product is not None:
            metadata.product_node_count = product.number_of_nodes()
            metadata.product_edge_count = product.number_of_edges()
            buchi = product.graph.get("buchi")

            if buchi is not None:
                metadata.buchi_node_count = buchi.number_of_nodes()
                metadata.buchi_edge_count = buchi.number_of_edges()

                try:
                    metadata.buchi_type = _buchi_type(buchi)
                except ValueError:
                    pass

    snapshot = PlanningGraphSnapshot()
    snapshot.metadata = metadata
    return snapshot
