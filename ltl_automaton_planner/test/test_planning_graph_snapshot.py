"""Tests for deterministic formal planning graph serialization."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from networkx import DiGraph
import pytest

from ltl_automaton_msgs.msg import BuchiGraphNode
from ltl_automaton_planner.planner_node import serialize_planning_graph
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
    built = build_planning_graph_snapshot(planner, active_hash)
    snapshot = built.snapshot
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
    first_snapshot = first.snapshot
    second_snapshot = second.snapshot
    buchi = planner.product.graph["buchi"]

    assert first_snapshot == second_snapshot
    assert first.product_node_ids == second.product_node_ids
    assert first_snapshot.metadata.buchi_type == "safe_buchi"
    assert [node.id for node in first_snapshot.buchi_nodes] == list(
        range(len(first_snapshot.buchi_nodes))
    )
    assert all(
        not node.state
        and node.hard_state
        and node.soft_state
        and node.acceptance_level in {1, 2}
        and not node.display_label.startswith("(")
        for node in first_snapshot.buchi_nodes
    )
    node_by_identity = {
        buchi_identity(node): node.id
        for node in first_snapshot.buchi_nodes
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
            for edge in first_snapshot.buchi_edges
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
    built = build_planning_graph_snapshot(planner, active_hash)
    snapshot = built.snapshot
    product = planner.product
    snapshot_ids = {
        product_identity(node, snapshot.buchi_nodes): node.id
        for node in snapshot.product_nodes
    }
    core_ids = dict(built.product_node_ids)

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
    assert core_ids == {
        node: snapshot_ids[core_product_identity(product, node)]
        for node in product.nodes
    }
    with pytest.raises(TypeError):
        built.product_node_ids[next(iter(product.nodes))] = 999


def test_product_state_shape_mismatch_remains_a_conversion_failure():
    """Reject Product state values that do not match TS dimensions."""
    planner, active_hash = build_planner(MINIMAL_TS, "<> r2", "")
    product_node = next(iter(planner.product.nodes))
    planner.product.nodes[product_node]["ts"] = ("r1", "extra")

    with pytest.raises(
        ValueError,
        match="Product TS state does not match ts_state_format",
    ):
        build_planning_graph_snapshot(planner, active_hash)


@pytest.mark.parametrize("soft_task", ["", "(r2 || ! r2)"])
def test_reused_ts_values_keep_message_state_arrays_independent(soft_task):
    """Editing one returned node must not alter sibling or subsequent state values."""
    planner, active_hash = build_planner(MINIMAL_TS, "<> r2", soft_task)
    first = build_planning_graph_snapshot(planner, active_hash)
    expected = deepcopy(first.snapshot)
    nodes = [
        node for node in first.snapshot.product_nodes
        if list(node.ts_state.states) == ["r1"]
    ]
    assert len(nodes) > 1
    nodes[0].ts_state.states[0] = "changed-only-in-this-message"
    assert all(list(node.ts_state.states) == ["r1"] for node in nodes[1:])
    second = build_planning_graph_snapshot(planner, active_hash)
    assert second.snapshot == expected
    assert second.product_node_ids == first.product_node_ids


def test_new_build_reads_updated_buchi_identity_without_stale_cache():
    """Each conversion must reflect graph attributes and preserve earlier messages."""
    planner, active_hash = build_planner(MINIMAL_TS, "<> r2", "(r2 || ! r2)")
    first = build_planning_graph_snapshot(planner, active_hash)
    expected_first = deepcopy(first.snapshot)
    buchi = planner.product.graph["buchi"]
    node = next(iter(buchi.nodes))
    buchi.nodes[node]["hard"] = "changed-hard-identity"
    second = build_planning_graph_snapshot(planner, active_hash)
    assert {buchi_identity(node) for node in second.snapshot.buchi_nodes} == {
        core_buchi_identity(buchi, node) for node in buchi.nodes
    }
    snapshot_ids = {
        product_identity(node, second.snapshot.buchi_nodes): node.id
        for node in second.snapshot.product_nodes
    }
    assert dict(second.product_node_ids) == {
        node: snapshot_ids[core_product_identity(planner.product, node)]
        for node in planner.product.nodes
    }
    assert first.snapshot == expected_first
    assert second.snapshot != first.snapshot


def test_product_id_view_is_private_per_build_and_refreshes_with_graph_order():
    """Expose each build's fresh Product IDs through an immutable view."""
    planner = _control_planner()
    first = build_planning_graph_snapshot(planner, "control-hash")
    first_snapshot = deepcopy(first.snapshot)
    first_ids = dict(first.product_node_ids)

    planner.product.graph["ts"].add_node("r-1", label={"r-1"})
    planner.product.add_node(
        "p_early",
        ts="r-1",
        buchi="q0",
        marker="isolated",
    )
    planner.product.graph["accept"].add("p_early")

    second = build_planning_graph_snapshot(planner, "control-hash")
    assert first.snapshot == first_snapshot
    assert dict(first.product_node_ids) == first_ids
    assert second.snapshot != first_snapshot
    assert second.product_node_ids is not first.product_node_ids
    assert dict(second.product_node_ids) != first_ids
    assert second.product_node_ids["p_early"] == 0
    assert list(second.snapshot.accepted_run.prefix_product_node_ids) == [
        second.product_node_ids[node] for node in planner.run.prefix
    ]
    assert list(second.snapshot.accepted_run.suffix_product_node_ids) == [
        second.product_node_ids[node] for node in planner.run.suffix
    ]
    for product_ids in (first.product_node_ids, second.product_node_ids):
        with pytest.raises(TypeError):
            product_ids["cannot-write"] = 99

    planner.product.remove_node("p_early")
    planner.product.graph["ts"].remove_node("r-1")
    planner.product.graph["accept"].remove("p_early")

    third = build_planning_graph_snapshot(planner, "control-hash")
    assert third.snapshot == first_snapshot
    assert dict(third.product_node_ids) == first_ids
    assert third.product_node_ids is not first.product_node_ids


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


def _control_planner():
    """Build a small valid Product/run fixture for run-boundary checks."""
    ts = DiGraph(initial={"r0"}, ts_state_format=("region",))
    for state in ("r0", "r1", "r2"):
        ts.add_node(state, label={state})
    ts.add_edge("r0", "r1", action="move", weight=1)
    ts.add_edge("r1", "r2", action="advance", weight=1)
    ts.add_edge("r2", "r1", action="close", weight=1)

    buchi = DiGraph(
        type="hard_buchi",
        initial={"q0"},
        accept={"q0"},
        symbols=set(),
    )
    buchi.add_edge(
        "q0",
        "q0",
        guard_formula="1",
    )

    product = DiGraph(
        ts=ts,
        buchi=buchi,
        initial={"p0"},
        accept={"p0", "p1", "p2"},
        accept_with_cycle={"p1", "p2"},
        type="ProdAut",
    )
    for node, ts_state in (
        ("p0", "r0"),
        ("p1", "r1"),
        ("p2", "r2"),
    ):
        product.add_node(
            node,
            ts=ts_state,
            buchi="q0",
            marker="visited",
        )
    product.add_edge(
        "p0",
        "p1",
        action="move",
        transition_cost=1,
        soft_task_dist=0,
        weight=1,
    )
    product.add_edge(
        "p1",
        "p2",
        action="advance",
        transition_cost=1,
        soft_task_dist=0,
        weight=1,
    )
    product.add_edge(
        "p2",
        "p1",
        action="close",
        transition_cost=1,
        soft_task_dist=0,
        weight=1,
    )
    run = SimpleNamespace(
        prefix=["p0", "p1"],
        suffix=["p1", "p2"],
        precost=1,
        sufcost=2,
        totalcost=21,
    )
    return SimpleNamespace(
        product=product,
        run=run,
        hard_spec="1",
        soft_spec="",
    )


def _control_graph_state(product):
    """Copy Product/TS graph fields used by the serializer fixture."""
    ts = product.graph["ts"]
    return (
        tuple((node, deepcopy(dict(data)))
              for node, data in product.nodes(data=True)),
        tuple((source, target, deepcopy(dict(data)))
              for source, target, data in product.edges(data=True)),
        tuple((node, deepcopy(dict(data)))
              for node, data in ts.nodes(data=True)),
        tuple((source, target, deepcopy(dict(data)))
              for source, target, data in ts.edges(data=True)),
        {
            name: set(product.graph[name])
            for name in ("initial", "accept", "accept_with_cycle")
        },
    )


def _control_run_state(run):
    """Copy run fields without relying on object identity."""
    return (
        tuple(run.prefix),
        tuple(run.suffix),
        run.precost,
        run.sufcost,
        run.totalcost,
    )


@pytest.mark.parametrize("container", [list, tuple])
@pytest.mark.parametrize("single_node", [False, True])
def test_accepted_run_path_order_and_single_node_cycle(container, single_node):
    """Serialize repeated paths and a one-node accepted self-loop."""
    planner = _control_planner()
    if single_node:
        planner.product.add_edge(
            "p1",
            "p1",
            action="stay",
            transition_cost=0,
            soft_task_dist=0,
            weight=0,
        )
        prefix = ["p1"]
        suffix = ["p1"]
        expected_prefix_cost = 0
        expected_suffix_cost = 0
        expected_total_cost = 0
    else:
        prefix = ["p0", "p1", "p2", "p1", "p2", "p1"]
        suffix = ["p1", "p2", "p1", "p2"]
        expected_prefix_cost = 5
        expected_suffix_cost = 4
        expected_total_cost = 45

    planner.run.prefix = container(prefix)
    planner.run.suffix = container(suffix)
    planner.run.precost = expected_prefix_cost
    planner.run.sufcost = expected_suffix_cost
    planner.run.totalcost = expected_total_cost
    graph_before = _control_graph_state(planner.product)
    run_before = _control_run_state(planner.run)

    result = build_planning_graph_snapshot(planner, "control-hash")
    product_ids = result.product_node_ids
    assert list(result.snapshot.accepted_run.prefix_product_node_ids) == [
        product_ids[node] for node in prefix
    ]
    assert list(result.snapshot.accepted_run.suffix_product_node_ids) == [
        product_ids[node] for node in suffix
    ]
    assert result.snapshot.accepted_run.prefix_cost == expected_prefix_cost
    assert result.snapshot.accepted_run.suffix_cost == expected_suffix_cost
    assert result.snapshot.accepted_run.total_cost == expected_total_cost
    assert _control_graph_state(planner.product) == graph_before
    assert _control_run_state(planner.run) == run_before


@pytest.mark.parametrize(
    "prefix,suffix,expected",
    [
        (
            [],
            ["p1", "p2"],
            "The accepted run has no prefix nodes.",
        ),
        (
            ["p0", "p2"],
            ["p1", "p2"],
            "The accepted prefix and suffix do not share their boundary node.",
        ),
        (
            ["p0", "p2", "p1"],
            ["p1", "p2"],
            "The accepted prefix references a missing Product edge.",
        ),
        (
            ["p0", "p2", "p1"],
            ["p1", "p0", "p2"],
            "The accepted prefix references a missing Product edge.",
        ),
        (
            ["p0", "p1"],
            ["p1", "p0", "p2"],
            "The accepted suffix references a missing Product edge.",
        ),
    ],
)
def test_damaged_accepted_run_is_unavailable_and_recoverable(
    prefix,
    suffix,
    expected,
):
    """Reject malformed accepted runs without mutating the valid fixture."""
    planner = _control_planner()
    healthy = build_planning_graph_snapshot(planner, "control-hash")
    assert healthy.snapshot.accepted_run.prefix_cost == 1
    assert healthy.snapshot.accepted_run.suffix_cost == 2
    assert healthy.snapshot.accepted_run.total_cost == 21
    expected_snapshot = deepcopy(healthy.snapshot)
    graph_before = _control_graph_state(planner.product)
    run_before = _control_run_state(planner.run)

    planner.run.prefix = list(prefix)
    planner.run.suffix = list(suffix)
    with pytest.raises(ValueError) as error:
        build_planning_graph_snapshot(planner, "control-hash")
    assert str(error.value) == expected

    unavailable = serialize_planning_graph(planner, "control-hash")
    assert unavailable.snapshot.metadata.unavailable_reason == (
        "Planning graph snapshot conversion failed: " + expected
    )
    assert not unavailable.snapshot.metadata.available
    assert unavailable.product_node_ids is None
    assert not unavailable.snapshot.buchi_nodes
    assert not unavailable.snapshot.buchi_edges
    assert not unavailable.snapshot.product_nodes
    assert not unavailable.snapshot.product_edges
    assert not unavailable.snapshot.accepted_run.prefix_product_node_ids
    assert not unavailable.snapshot.accepted_run.suffix_product_node_ids
    assert _control_graph_state(planner.product) == graph_before
    assert _control_run_state(planner.run) == (
        tuple(prefix), tuple(suffix), 1, 2, 21,
    )

    planner.run.prefix = ["p0", "p1"]
    planner.run.suffix = ["p1", "p2"]
    restored = build_planning_graph_snapshot(planner, "control-hash")
    assert restored.snapshot == expected_snapshot
    assert _control_graph_state(planner.product) == graph_before
    assert _control_run_state(planner.run) == run_before


@pytest.mark.parametrize(
    "missing,expected_fields",
    [
        (("weight",), "weight"),
        (
            ("action", "transition_cost", "soft_task_dist", "weight"),
            "action, soft_task_dist, transition_cost, weight",
        ),
    ],
)
def test_missing_product_edge_fields_are_reported_and_recoverable(
    missing, expected_fields
):
    """Report missing edge fields in order without mutating the Product."""
    planner = _control_planner()
    healthy = build_planning_graph_snapshot(planner, "control-hash")
    expected_snapshot = deepcopy(healthy.snapshot)
    edge = planner.product["p0"]["p1"]
    edge_before = deepcopy(dict(edge))
    for field in missing:
        del edge[field]
    damaged_graph = _control_graph_state(planner.product)
    expected = f"Product edge is missing fields: {expected_fields}."

    with pytest.raises(ValueError, match=f"^{expected}$") as error:
        build_planning_graph_snapshot(planner, "control-hash")
    assert str(error.value) == expected
    assert _control_graph_state(planner.product) == damaged_graph

    unavailable = serialize_planning_graph(planner, "control-hash")
    assert unavailable.snapshot.metadata.unavailable_reason == (
        "Planning graph snapshot conversion failed: " + expected
    )
    assert not unavailable.snapshot.metadata.available
    assert unavailable.product_node_ids is None
    assert not unavailable.snapshot.buchi_nodes
    assert not unavailable.snapshot.buchi_edges
    assert not unavailable.snapshot.product_nodes
    assert not unavailable.snapshot.product_edges
    assert not unavailable.snapshot.accepted_run.prefix_product_node_ids
    assert not unavailable.snapshot.accepted_run.suffix_product_node_ids
    assert _control_graph_state(planner.product) == damaged_graph

    edge.update(edge_before)
    restored = build_planning_graph_snapshot(planner, "control-hash")
    assert restored.snapshot == expected_snapshot
    assert restored.product_node_ids == healthy.product_node_ids
