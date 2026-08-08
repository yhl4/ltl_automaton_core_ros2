"""Tests for deterministic formal planning graph serialization."""

from pathlib import Path

from ltl_automaton_msgs.msg import BuchiGraphNode
from ltl_automaton_planner.planner_node import prepare_transition_system
from ltl_automaton_planner.planning_graph_snapshot import (
    build_planning_graph_snapshot,
    unavailable_planning_graph_snapshot,
)
from ltl_automaton_planner_core.ltl_tools.ltl_planner import LTLPlanner


MINIMAL_TS = """
state_dim:
  - region
state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to:
          r2: goto_r2
      r2:
        connected_to:
          r2: stay_r2
actions:
  goto_r2:
    guard: "1"
    weight: 2.0
  stay_r2:
    guard: "1"
    weight: 1.0
""".lstrip()


def build_planner(ts_yaml, hard_task, soft_task):
    """Build one real Core planner for serializer tests."""
    transition_system, active_hash = prepare_transition_system(ts_yaml)
    planner = LTLPlanner(
        transition_system,
        hard_task,
        soft_task,
        beta=1000.0,
        gamma=10.0,
    )
    assert planner.optimal(style="static")
    assert planner.run is not None
    return planner, active_hash


def buchi_identity(message):
    """Return a test-side semantic identity for one serialized node."""
    if message.state:
        return ("single", message.state)

    return (
        "safe",
        message.hard_state,
        message.soft_state,
        message.acceptance_level,
    )


def product_identity(message, buchi_nodes):
    """Return a test-side semantic identity for one Product node."""
    buchi = buchi_nodes[message.buchi_node_id]
    return (
        tuple(message.ts_state.states),
        buchi_identity(buchi),
    )


def core_buchi_identity(buchi, node):
    """Return the known Core identity without using repr or hash."""
    if buchi.graph["type"] == "safe_buchi":
        attributes = buchi.nodes[node]
        return (
            "safe",
            str(attributes["hard"]),
            str(attributes["soft"]),
            int(attributes["level"]),
        )

    return ("single", str(node))


def core_product_identity(product, node):
    """Return the structured identity of one real Core Product node."""
    attributes = product.nodes[node]
    buchi = product.graph["buchi"]
    ts_node = attributes["ts"]
    ts_values = ts_node if isinstance(ts_node, tuple) else (ts_node,)
    return (
        tuple(str(value) for value in ts_values),
        core_buchi_identity(buchi, attributes["buchi"]),
    )


def test_single_buchi_nodes_edges_and_membership_are_exact():
    """Export single Buchi identity, membership, and formal guards."""
    planner, active_hash = build_planner(MINIMAL_TS, "<> r2", "")
    snapshot = build_planning_graph_snapshot(planner, active_hash)
    buchi = planner.product.graph["buchi"]
    snapshot_by_identity = {
        buchi_identity(node): node
        for node in snapshot.buchi_nodes
    }

    assert snapshot.metadata.available
    assert snapshot.metadata.buchi_type == "single_buchi"
    assert snapshot.metadata.hard_task == "<> r2"
    assert snapshot.metadata.soft_task == ""
    assert snapshot.metadata.active_ts_sha256 == active_hash
    assert {
        buchi_identity(node)
        for node in snapshot.buchi_nodes
        if node.initial
    } == {
        core_buchi_identity(buchi, node)
        for node in buchi.graph["initial"]
    }
    assert {
        buchi_identity(node)
        for node in snapshot.buchi_nodes
        if node.accepting
    } == {
        core_buchi_identity(buchi, node)
        for node in buchi.graph["accept"]
    }
    assert all(
        node.acceptance_level == BuchiGraphNode.LEVEL_NOT_APPLICABLE
        and node.state
        and not node.hard_state
        and not node.soft_state
        for node in snapshot.buchi_nodes
    )

    for source, target, attributes in buchi.edges(data=True):
        source_id = snapshot_by_identity[
            core_buchi_identity(buchi, source)
        ].id
        target_id = snapshot_by_identity[
            core_buchi_identity(buchi, target)
        ].id
        assert any(
            edge.source_id == source_id
            and edge.target_id == target_id
            and edge.guard_formula == attributes["guard_formula"]
            and not edge.hard_guard_formula
            and not edge.soft_guard_formula
            for edge in snapshot.buchi_edges
        )


def test_safe_buchi_and_repeated_serialization_are_deterministic():
    """Export safe node fields and guards with repeatable IDs and order."""
    planner, active_hash = build_planner(
        MINIMAL_TS,
        "<> r2",
        "(r2 || ! r2)",
    )
    first = build_planning_graph_snapshot(planner, active_hash)
    second = build_planning_graph_snapshot(planner, active_hash)
    buchi = planner.product.graph["buchi"]

    assert first == second
    assert first.metadata.buchi_type == "safe_buchi"
    assert [node.id for node in first.buchi_nodes] == list(
        range(len(first.buchi_nodes))
    )
    assert all(
        not node.state
        and node.hard_state
        and node.soft_state
        and node.acceptance_level in {1, 2}
        and not node.display_label.startswith("(")
        for node in first.buchi_nodes
    )
    node_by_identity = {
        buchi_identity(node): node.id
        for node in first.buchi_nodes
    }

    for source, target, attributes in buchi.edges(data=True):
        source_id = node_by_identity[
            core_buchi_identity(buchi, source)
        ]
        target_id = node_by_identity[
            core_buchi_identity(buchi, target)
        ]
        assert any(
            edge.source_id == source_id
            and edge.target_id == target_id
            and edge.hard_guard_formula
            == attributes["hardguard"].formula
            and edge.soft_guard_formula
            == attributes["softguard"].formula
            and not edge.guard_formula
            for edge in first.buchi_edges
        )


def test_product_and_accepted_run_match_real_multidimensional_core():
    """Export multidimensional nodes, edge values, and the accepted run."""
    config_dir = Path(__file__).parents[1] / "config"
    ts_yaml = (config_dir / "kth_example_ts.yaml").read_text(
        encoding="utf-8"
    )
    planner, active_hash = build_planner(
        ts_yaml,
        "<> r3",
        "(r3 || ! r3)",
    )
    snapshot = build_planning_graph_snapshot(planner, active_hash)
    product = planner.product
    snapshot_ids = {
        product_identity(node, snapshot.buchi_nodes): node.id
        for node in snapshot.product_nodes
    }
    core_ids = {
        node: snapshot_ids[core_product_identity(product, node)]
        for node in product.nodes
    }

    assert [node.id for node in snapshot.product_nodes] == list(
        range(len(snapshot.product_nodes))
    )
    assert all(
        list(node.ts_state.state_dimension_names)
        == ["2d_pose_region", "turtlebot_load"]
        and len(node.ts_state.states) == 2
        for node in snapshot.product_nodes
    )
    assert {
        node.id for node in snapshot.product_nodes if node.initial
    } == {core_ids[node] for node in product.graph["initial"]}
    assert {
        node.id for node in snapshot.product_nodes if node.accepting
    } == {core_ids[node] for node in product.graph["accept"]}

    serialized_edges = {
        (edge.source_id, edge.target_id): edge
        for edge in snapshot.product_edges
    }

    for source, target, attributes in product.edges(data=True):
        edge = serialized_edges[(core_ids[source], core_ids[target])]
        assert edge.action == str(attributes["action"])
        assert edge.transition_cost == float(attributes["transition_cost"])
        assert edge.soft_task_distance == float(
            attributes["soft_task_dist"]
        )
        assert edge.total_weight == float(attributes["weight"])

    run = planner.run
    accepted = snapshot.accepted_run
    assert list(accepted.prefix_product_node_ids) == [
        core_ids[node] for node in run.prefix
    ]
    assert list(accepted.suffix_product_node_ids) == [
        core_ids[node] for node in run.suffix
    ]
    assert accepted.suffix_product_node_ids[-1] != (
        accepted.suffix_product_node_ids[0]
    ) or len(accepted.suffix_product_node_ids) == 1
    assert (
        accepted.suffix_product_node_ids[-1],
        accepted.suffix_product_node_ids[0],
    ) in serialized_edges
    assert accepted.prefix_cost == float(run.precost)
    assert accepted.suffix_cost == float(run.sufcost)
    assert accepted.total_cost == float(run.totalcost)


def test_unavailable_snapshot_is_an_atomic_empty_payload():
    """Never return partially serialized graph arrays on conversion failure."""
    planner, active_hash = build_planner(
        MINIMAL_TS,
        "<> r2",
        "(r2 || ! r2)",
    )
    snapshot = unavailable_planning_graph_snapshot(
        planner,
        active_hash,
        "controlled conversion failure",
    )

    assert not snapshot.metadata.available
    assert snapshot.metadata.unavailable_reason
    assert snapshot.metadata.product_node_count == len(planner.product)
    assert not snapshot.buchi_nodes
    assert not snapshot.buchi_edges
    assert not snapshot.product_nodes
    assert not snapshot.product_edges
    assert not snapshot.accepted_run.prefix_product_node_ids
    assert not snapshot.accepted_run.suffix_product_node_ids
