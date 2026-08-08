"""Validate the generated ROS 2 planning contract types."""

from ltl_automaton_msgs.action import PlanLTL
from ltl_automaton_msgs.msg import AcceptedRunSnapshot
from ltl_automaton_msgs.msg import BuchiGraphEdge
from ltl_automaton_msgs.msg import BuchiGraphNode
from ltl_automaton_msgs.msg import PlannerStatus
from ltl_automaton_msgs.msg import PlanningGraphMetadata
from ltl_automaton_msgs.msg import PlanningGraphSnapshot
from ltl_automaton_msgs.msg import ProductGraphEdge
from ltl_automaton_msgs.msg import ProductGraphNode
from ltl_automaton_msgs.srv import LoadTransitionSystem
from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot


def test_planner_status_contract():
    """Expose only the approved lifecycle constants and fields."""
    message = PlannerStatus()

    assert message.get_fields_and_field_types() == {
        "state": "uint8",
        "message": "string",
    }
    assert PlannerStatus.UNINITIALIZED == 0
    assert PlannerStatus.READY == 1
    assert PlannerStatus.PLANNING == 2
    assert PlannerStatus.ACTIVE == 3


def test_load_transition_system_contract():
    """Generate the approved transition-system loading service."""
    request = LoadTransitionSystem.Request()
    response = LoadTransitionSystem.Response()

    assert list(request.get_fields_and_field_types()) == [
        "transition_system_yaml",
    ]
    assert list(response.get_fields_and_field_types()) == [
        "success",
        "message",
        "active_ts_sha256",
    ]


def test_plan_ltl_contract():
    """Generate the approved planning action goal, result, and feedback."""
    goal = PlanLTL.Goal()
    result = PlanLTL.Result()
    feedback = PlanLTL.Feedback()

    assert list(goal.get_fields_and_field_types()) == [
        "hard_task",
        "soft_task",
        "initial_state",
        "beta",
        "gamma",
    ]
    assert list(result.get_fields_and_field_types()) == [
        "success",
        "error_code",
        "message",
        "prefix_plan",
        "suffix_plan",
        "total_cost",
        "planning_time",
    ]
    assert list(feedback.get_fields_and_field_types()) == ["message"]

    assert PlanLTL.Result.ERROR_NONE == 0
    assert PlanLTL.Result.ERROR_INVALID_GOAL == 1
    assert PlanLTL.Result.ERROR_NOT_READY == 2
    assert PlanLTL.Result.ERROR_NO_ACCEPTING_PLAN == 3
    assert PlanLTL.Result.ERROR_INTERNAL == 4


def test_planning_graph_metadata_contract():
    """Generate snapshot identity, consistency, size, and availability."""
    metadata = PlanningGraphMetadata()
    metadata.planning_generation = 7
    metadata.active_ts_sha256 = "a" * 64
    metadata.hard_task = "<> goal"
    metadata.soft_task = "[] safe"
    metadata.buchi_type = "safe_buchi"
    metadata.buchi_node_count = 4
    metadata.buchi_edge_count = 6
    metadata.product_node_count = 24
    metadata.product_edge_count = 44
    metadata.available = False
    metadata.unavailable_reason = "Snapshot exceeds the configured limit."

    assert list(metadata.get_fields_and_field_types()) == [
        "planning_generation",
        "active_ts_sha256",
        "hard_task",
        "soft_task",
        "buchi_type",
        "buchi_node_count",
        "buchi_edge_count",
        "product_node_count",
        "product_edge_count",
        "available",
        "unavailable_reason",
    ]
    assert metadata.planning_generation == 7
    assert metadata.product_edge_count == 44
    assert not metadata.available
    assert metadata.unavailable_reason


def test_buchi_graph_contract():
    """Generate typed single/safe nodes and stable formula-only edges."""
    single_node = BuchiGraphNode()
    single_node.id = 1
    single_node.display_label = "accept_all"
    single_node.initial = False
    single_node.accepting = True
    single_node.state = "accept_all"
    single_node.acceptance_level = (
        BuchiGraphNode.LEVEL_NOT_APPLICABLE
    )

    safe_node = BuchiGraphNode()
    safe_node.id = 2
    safe_node.display_label = "T0_init × accept_init [1]"
    safe_node.initial = True
    safe_node.accepting = False
    safe_node.hard_state = "T0_init"
    safe_node.soft_state = "accept_init"
    safe_node.acceptance_level = 1

    edge = BuchiGraphEdge()
    edge.source_id = 1
    edge.target_id = 2
    edge.guard_formula = "(goal)"
    edge.hard_guard_formula = "(goal)"
    edge.soft_guard_formula = "(!danger)"

    assert BuchiGraphNode.LEVEL_NOT_APPLICABLE == -1
    assert single_node.state == "accept_all"
    assert single_node.acceptance_level == -1
    assert safe_node.hard_state == "T0_init"
    assert safe_node.soft_state == "accept_init"
    assert safe_node.acceptance_level == 1
    assert edge.source_id == 1
    assert edge.target_id == 2
    assert edge.hard_guard_formula == "(goal)"


def test_product_graph_contract():
    """Generate structured multidimensional nodes and weighted edges."""
    node = ProductGraphNode()
    node.id = 3
    node.ts_state.states = ["r2", "loaded"]
    node.ts_state.state_dimension_names = [
        "2d_pose_region",
        "turtlebot_load",
    ]
    node.buchi_node_id = 2
    node.initial = False
    node.accepting = True

    edge = ProductGraphEdge()
    edge.source_id = 3
    edge.target_id = 4
    edge.action = "drop"
    edge.transition_cost = 10.0
    edge.soft_task_distance = 1.0
    edge.total_weight = 1010.0

    assert list(node.ts_state.states) == ["r2", "loaded"]
    assert list(node.ts_state.state_dimension_names) == [
        "2d_pose_region",
        "turtlebot_load",
    ]
    assert node.buchi_node_id == 2
    assert node.accepting
    assert edge.action == "drop"
    assert edge.transition_cost == 10.0
    assert edge.soft_task_distance == 1.0
    assert edge.total_weight == 1010.0


def test_accepted_run_snapshot_contract():
    """Generate explicit prefix and non-repeated suffix product runs."""
    run = AcceptedRunSnapshot()
    run.prefix_product_node_ids = [1, 3, 5]
    run.suffix_product_node_ids = [5, 7]
    run.prefix_cost = 12.0
    run.suffix_cost = 4.0
    run.total_cost = 52.0

    assert list(run.prefix_product_node_ids) == [1, 3, 5]
    assert list(run.suffix_product_node_ids) == [5, 7]
    assert run.prefix_cost == 12.0
    assert run.suffix_cost == 4.0
    assert run.total_cost == 52.0


def test_planning_graph_snapshot_contract():
    """Compose all formal graph arrays under one metadata generation."""
    snapshot = PlanningGraphSnapshot()
    snapshot.metadata.planning_generation = 9
    snapshot.metadata.available = True
    snapshot.buchi_nodes = [BuchiGraphNode(id=1)]
    snapshot.buchi_edges = [BuchiGraphEdge(source_id=1, target_id=1)]
    snapshot.product_nodes = [ProductGraphNode(id=2, buchi_node_id=1)]
    snapshot.product_edges = [
        ProductGraphEdge(source_id=2, target_id=2, action="stay")
    ]
    snapshot.accepted_run.prefix_product_node_ids = [2]
    snapshot.accepted_run.suffix_product_node_ids = [2]

    assert snapshot.metadata.planning_generation == 9
    assert snapshot.metadata.available
    assert snapshot.buchi_nodes[0].id == 1
    assert snapshot.buchi_edges[0].target_id == 1
    assert snapshot.product_nodes[0].buchi_node_id == 1
    assert snapshot.product_edges[0].action == "stay"
    assert list(snapshot.accepted_run.suffix_product_node_ids) == [2]


def test_get_planning_graph_snapshot_service_contract():
    """Generate an empty request and one typed snapshot response."""
    request = GetPlanningGraphSnapshot.Request()
    response = GetPlanningGraphSnapshot.Response()
    response.success = False
    response.message = "No active planning snapshot is available."
    response.snapshot.metadata.planning_generation = 0
    response.snapshot.metadata.available = False
    response.snapshot.metadata.unavailable_reason = response.message

    assert request.get_fields_and_field_types() == {}
    assert list(response.get_fields_and_field_types()) == [
        "success",
        "message",
        "snapshot",
    ]
    assert not response.success
    assert response.snapshot.metadata.unavailable_reason == response.message
