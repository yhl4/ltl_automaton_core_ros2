"""ROS-generated contract tests with small real exact models, not Office runs."""
from fractions import Fraction
import json
from types import SimpleNamespace

import pytest

rclpy = pytest.importorskip("rclpy", reason="ROS 2 overlay is needed for generated-message tests")
pytest.importorskip("ltl_automaton_msgs.msg", reason="Build ltl_automaton_msgs first")
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from ltl_automaton_msgs.msg import (
    PlanningExecutionObservation, TransitionSystemState, TransitionSystemStateStamped,
)
from ltl_automaton_msgs.srv import TaskPlanning, GetPlanningGraphSnapshot
from std_msgs.msg import String

import ltl_automaton_cmr.ros_node as module
from ltl_automaton_cmr.engine import CertificationError
from ltl_automaton_cmr.office import load_office_query
from ltl_automaton_cmr.vendor.ecc_p1 import (
    BuchiAutomaton, FormalAction, FormalFactorizedModel,
)


def tiny_query(identifier="D2", initial_state=None, cost=1, feasible=True):
    """Two-state toggle certifies with real engine and occurrence exporter."""
    value = 0 if initial_state is None else {"zero": 0, "one": 1}[initial_state["x"]]
    action = FormalAction("toggle", frozenset({0}), frozenset({0}), frozenset(),
                          lambda state: feasible, lambda state: (1 - state[0],),
                          lambda source, target: cost)
    model = FormalFactorizedModel(
        (0,), ((0, 1),), frozenset({(value,)}), (action,),
        lambda state: frozenset(),
        BuchiAutomaton("q", frozenset({"q"}), lambda q, label: (q,)),
        task_ap=frozenset(), task_support={},
    )
    return SimpleNamespace(
        model=model, query_id=identifier, hard_task="formula-" + identifier,
        dimension_names=("x",), value_names=(("zero", "one"),),
        family_prior=frozenset({0}), initial_named_state={"x": "zero" if value == 0 else "one"},
    )


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "load_office_query", tiny_query)
    context = Context()
    rclpy.init(context=context)
    node = module.CMRPlannerNode(
        context=context,
        parameter_overrides=[Parameter("records_directory", value=str(tmp_path))],
    )
    client_node = rclpy.create_node("cmr_contract_client", context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(node)
    executor.add_node(client_node)
    try:
        yield SimpleNamespace(node=node, context=context, client=client_node,
                              executor=executor, records=tmp_path)
    finally:
        executor.remove_node(client_node)
        executor.remove_node(node)
        client_node.destroy_node()
        node.destroy_node()
        executor.shutdown()
        rclpy.shutdown(context=context)


def request_plan(node, hard="D2", soft=""):
    return node._planning_callback(TaskPlanning.Request(hard_task=hard, soft_task=soft),
                                   TaskPlanning.Response())


def feedback(value, seconds=1, names=("x",)):
    message = TransitionSystemStateStamped()
    message.header.stamp.sec = seconds
    message.ts_state = TransitionSystemState(
        state_dimension_names=list(names), states=[value])
    return message


def snapshot(node):
    return node._snapshot_callback(GetPlanningGraphSnapshot.Request(),
                                   GetPlanningGraphSnapshot.Response())


def test_no_startup_plan_and_readonly_parameters(runtime):
    node = runtime.node
    assert node.get_namespace() == "/cmr"
    assert node._cursor is None and node._generation == 0
    assert not snapshot(node).success
    for name in ("arm", "query_id", "family_prior_json", "initial_state_json", "records_directory"):
        assert node.describe_parameter(name).read_only
    result = node.set_parameters([Parameter("arm", value="FULL")])[0]
    assert not result.successful
    assert node.get_parameter("arm").value == "AP"


@pytest.mark.parametrize("hard,soft", [("", ""), ("G arbitrary", ""), ("D2", "F extra")])
def test_unknown_general_ltl_and_soft_task_fail_closed(runtime, hard, soft):
    node = runtime.node
    assert request_plan(node).success
    assert not request_plan(node, hard, soft).success
    assert node._cursor is None and not snapshot(node).success
    assert node._last_exact_record["status"] == "REJECTED"


def test_exact_formula_commit_round_json_and_occurrence_closure(runtime):
    node = runtime.node
    assert request_plan(node, "formula-D2").success
    response = snapshot(node)
    assert response.success and response.snapshot.metadata.available
    assert node._generation == 1
    # Concrete closed suffix final repeated state is represented by closure
    # edge into its entry occurrence, as required by the existing executor.
    run = response.snapshot.accepted_run
    ids = list(run.suffix_product_node_ids)
    assert len(ids) == 2
    assert response.snapshot.product_edges[-1].target_id == ids[0]
    record = node._last_exact_record
    assert record["status"] == "OPTIMALITY_CERTIFIED"
    assert record["objective"]["numerator"] == 20
    assert record["rounds"][-1]["lower_bound_exact"] == record["rounds"][-1]["upper_bound_exact"]
    assert record["execution_available"] is True
    files = list(runtime.records.glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text())["objective"] == record["objective"]
    # Snapshot callers cannot mutate the retained active graph.
    response.snapshot.product_nodes[0].ts_state.states[0] = "one"
    assert snapshot(node).snapshot.product_nodes[0].ts_state.states[0] == "zero"


def test_expected_new_feedback_advances_and_stale_does_not(runtime):
    node = runtime.node
    node._state_callback(feedback("zero", 3))
    assert request_plan(node).success
    assert node._cursor.step_seq == 0
    node._state_callback(feedback("one", 3))
    assert node._cursor.step_seq == 0 and node._state_mapping == {"x": "zero"}
    node._state_callback(feedback("one", 4))
    assert node._cursor.step_seq == 1
    node._state_callback(feedback("zero", 4))
    assert node._cursor.step_seq == 1 and node._state_mapping == {"x": "one"}
    node._state_callback(feedback("zero", 5))
    assert node._cursor.step_seq == 2


def test_unexpected_state_revokes_monotonic_authority_and_replan_uses_observation(runtime):
    node = runtime.node
    observations = []
    node.observation_publisher = SimpleNamespace(publish=observations.append)
    assert request_plan(node).success
    node._state_callback(feedback("one", 1))
    assert node._cursor.step_seq == 1
    node._state_callback(feedback("one", 2))  # next toggle expects zero
    assert node._cursor is None and node._state_mapping == {"x": "one"}
    assert not observations[-1].has_next_action
    assert observations[-1].execution_step_seq == 1
    assert not snapshot(node).success
    assert request_plan(node).success
    assert node._generation == 2 and node._cursor.step_seq == 0
    assert node._last_exact_record["initial_state"] == {"x": "one"}
    assert snapshot(node).snapshot.product_nodes[0].ts_state.states == ["one"]


def test_malformed_new_feedback_revokes_without_contaminating_state(runtime):
    node = runtime.node
    assert request_plan(node).success
    before = dict(node._state_mapping)
    node._state_callback(feedback("bad-value", 8))
    assert node._cursor is None and node._state_mapping == before
    assert node._feedback_stamp is None
    node._state_callback(feedback("one", 9, names=("wrong",)))
    assert node._state_mapping == before


def test_float64_capability_failure_retains_exact_certificate(runtime, monkeypatch):
    monkeypatch.setattr(module, "load_office_query", lambda identifier, initial_state=None:
                        tiny_query(identifier, initial_state, cost=Fraction(1, 3)))
    node = runtime.node
    assert not request_plan(node).success
    record = node._last_exact_record
    assert record["status"] == "OPTIMALITY_CERTIFIED"
    assert record["objective"] == {"text": "20/3", "numerator": 20, "denominator": 3}
    assert "float64" in record["capability_error"]
    assert not record["execution_available"] and node._cursor is None
    assert node._generation == 0 and not snapshot(node).success


def test_infeasible_and_uncertified_results_cannot_commit(runtime, monkeypatch):
    node = runtime.node
    monkeypatch.setattr(module, "load_office_query", lambda identifier, initial_state=None:
                        tiny_query(identifier, initial_state, feasible=False))
    assert not request_plan(node).success
    assert node._last_exact_record["status"] == "INFEASIBLE"
    assert node._generation == 0 and node._cursor is None

    def uncertified(*args, **kwargs):
        raise CertificationError("full precision LB differs from UB", [{"round": 0}])
    monkeypatch.setattr(module, "plan", uncertified)
    assert not request_plan(node).success
    assert node._last_exact_record["status"] == "FULL_PRECISION_NOT_CERTIFIED"
    assert node._generation == 0 and node._cursor is None


def test_office_feedback_requires_all_ten_dimensions_and_reorders():
    query = load_office_query("D2")
    mapping = query.initial_named_state
    names = tuple(reversed(query.dimension_names))
    message = TransitionSystemState(state_dimension_names=list(names),
                                    states=[mapping[name] for name in names])
    normalized, state = module.normalize_office_feedback(message, query)
    assert normalized == mapping and state.dimension_names == query.dimension_names
    message.state_dimension_names.pop()
    message.states.pop()
    with pytest.raises(ValueError, match="all Office"):
        module.normalize_office_feedback(message, query)


def test_real_ros_service_and_retained_observation(runtime):
    node = runtime.node
    observations = []
    records = []
    runtime.client.create_subscription(PlanningExecutionObservation,
                                      "/cmr/planning_execution_observation",
                                      observations.append, module.COMMAND_QOS)
    runtime.client.create_subscription(String, "/cmr/cmr_plan_result", records.append,
                                      module.COMMAND_QOS)
    client = runtime.client.create_client(TaskPlanning, "/cmr/replanning")
    assert client.wait_for_service(timeout_sec=3.0)
    future = client.call_async(TaskPlanning.Request(hard_task="D2", soft_task=""))
    runtime.executor.spin_until_future_complete(future, timeout_sec=5.0)
    assert future.done() and future.result().success
    for _ in range(30):
        if observations and observations[-1].has_next_action and records:
            break
        runtime.executor.spin_once(timeout_sec=0.1)
    assert observations[-1].has_next_action and observations[-1].next_action == "toggle"
    assert observations[-1].planning_generation == 1
    assert json.loads(records[-1].data)["status"] == "OPTIMALITY_CERTIFIED"


def test_existing_fake_executor_observes_states_and_advances_cmr_cursor(runtime):
    """Real DDS snapshot/observation/feedback loop across both ROS nodes."""
    from time import monotonic
    from ltl_automaton_execution.execution_node import ExecutionManagerNode
    from ltl_automaton_execution.fake_runtime import FakePlant
    from ltl_automaton_execution.models import SymbolicState

    plant = FakePlant(SymbolicState(("x",), ("zero",)))
    executor_node = ExecutionManagerNode(
        context=runtime.context, namespace="/cmr", fake_plant=plant,
        execution_delay_sec=0.02,
    )
    runtime.executor.add_node(executor_node)
    try:
        client = runtime.client.create_client(TaskPlanning, "/cmr/replanning")
        assert client.wait_for_service(timeout_sec=3.0)
        future = client.call_async(TaskPlanning.Request(hard_task="D2", soft_task=""))
        runtime.executor.spin_until_future_complete(future, timeout_sec=5.0)
        assert future.done() and future.result().success
        deadline = monotonic() + 7.0
        while monotonic() < deadline:
            cursor = runtime.node._cursor
            if cursor is not None and cursor.step_seq >= 4:
                break
            runtime.executor.spin_once(timeout_sec=0.05)
        assert runtime.node._cursor is not None
        assert runtime.node._cursor.step_seq >= 4
        assert runtime.node._feedback_stamp is not None
        assert runtime.node._state_mapping["x"] == plant.current_state.states[0]
        assert executor_node._manager._active_generation == 1
        assert executor_node._latest_observation.next_action == "toggle"
    finally:
        runtime.executor.remove_node(executor_node)
        executor_node.destroy_node()


def test_selfloop_requires_fresh_observation_and_republication_never_advances(runtime, monkeypatch):
    from dataclasses import replace

    def stutter(identifier, initial_state=None):
        query = tiny_query(identifier, initial_state)
        action = replace(query.model.actions[0], effect=lambda state: state)
        query.model = replace(query.model, actions=(action,))
        return query

    monkeypatch.setattr(module, "load_office_query", stutter)
    node = runtime.node
    node._state_callback(feedback("zero", 4))
    assert request_plan(node).success
    node._publish_authority()
    node._publish_authority()
    assert node._cursor.step_seq == 0
    node._state_callback(feedback("zero", 4))
    assert node._cursor.step_seq == 0
    node._state_callback(feedback("zero", 5))
    assert node._cursor.step_seq == 1
    node._state_callback(feedback("zero", 5))
    assert node._cursor.step_seq == 1
