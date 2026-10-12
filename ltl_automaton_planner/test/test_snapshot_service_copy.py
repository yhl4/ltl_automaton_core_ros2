"""Check snapshot copy isolation and atomic capture during worker commits."""

from copy import deepcopy
from threading import Event, RLock, Thread
from types import SimpleNamespace

import pytest

from ltl_automaton_msgs.msg import BuchiGraphEdge, BuchiGraphNode
from ltl_automaton_msgs.msg import PlanningGraphSnapshot
from ltl_automaton_msgs.msg import ProductGraphEdge, ProductGraphNode
from ltl_automaton_msgs.msg import TransitionSystemState
from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot
import ltl_automaton_planner.planner_node as planner_module
from ltl_automaton_planner.planner_node import PlannerNode, PlanningGraphSerialization


def _snapshot(available, state, active_hash):
    snapshot = PlanningGraphSnapshot()
    snapshot.metadata.available = available
    snapshot.metadata.active_ts_sha256 = active_hash
    snapshot.metadata.hard_task = "1"
    snapshot.metadata.buchi_type = "single_buchi"
    snapshot.metadata.buchi_node_count = 1
    snapshot.metadata.buchi_edge_count = 1
    snapshot.metadata.product_node_count = 1
    snapshot.metadata.product_edge_count = 1
    if not available:
        snapshot.metadata.unavailable_reason = "Controlled conversion unavailability."
        return snapshot
    snapshot.buchi_nodes = [BuchiGraphNode(
        id=0, state="q0", initial=True, accepting=True,
        acceptance_level=BuchiGraphNode.LEVEL_NOT_APPLICABLE,
    )]
    snapshot.buchi_edges = [BuchiGraphEdge(source_id=0, target_id=0, guard_formula="1")]
    snapshot.product_nodes = [ProductGraphNode(
        id=0, buchi_node_id=0, initial=True, accepting=True,
        ts_state=TransitionSystemState(state_dimension_names=["region"], states=[state]),
    )]
    snapshot.product_edges = [ProductGraphEdge(source_id=0, target_id=0, action="wait")]
    snapshot.accepted_run.prefix_product_node_ids = [0]
    snapshot.accepted_run.suffix_product_node_ids = [0]
    return snapshot


@pytest.mark.parametrize("available", [None, False, True])
def test_copy_allows_commit_but_returns_one_captured_generation(available, monkeypatch):
    """A worker can commit during copying without mixing or exposing either snapshot."""
    retained = None if available is None else _snapshot(available, "r1", "hash-a")
    if retained is not None:
        retained.metadata.planner_instance_id = "planner-instance"
        retained.metadata.planning_generation = 7
    expected = deepcopy(retained)
    host = SimpleNamespace(
        _state_lock=RLock(), _active_planning_graph_snapshot=retained,
        _active_ts_sha256="hash-a", _planner_instance_id="planner-instance",
        _planning_generation=7, _execution_step_seq=4, _active_product_node_ids=None,
    )
    copy_entered = Event()
    release_copy = Event()
    responses = []
    errors = []

    def paused_copy(value):
        if value is retained:
            copy_entered.set()
            if not release_copy.wait(timeout=3.0):
                raise RuntimeError("Test did not release snapshot copying.")
        return deepcopy(value)

    monkeypatch.setattr(planner_module, "deepcopy", paused_copy)

    def read_snapshot():
        try:
            responses.append(PlannerNode._get_planning_graph_snapshot_callback(
                host, GetPlanningGraphSnapshot.Request(), GetPlanningGraphSnapshot.Response(),
            ))
        except Exception as error:
            errors.append(error)

    reader = Thread(target=read_snapshot)
    reader.start()
    acquired = False
    replacement_hash = "hash-b" if available is None else "hash-a"
    replacement = _snapshot(True, "r2", replacement_hash)
    try:
        assert copy_entered.wait(timeout=3.0)
        acquired = host._state_lock.acquire(blocking=False)
        assert acquired, "Snapshot copying still holds the planner state lock."
        PlannerNode._commit_planning_graph_snapshot(host, PlanningGraphSerialization(
            snapshot=replacement, product_node_ids={("r2", "q0"): 0},
        ))
        host._active_ts_sha256 = replacement_hash
    finally:
        if acquired:
            host._state_lock.release()
        release_copy.set()
        reader.join(timeout=3.0)
    assert not reader.is_alive()
    assert errors == []
    response, = responses
    assert response.success is bool(available)
    if expected is None:
        assert not response.snapshot.metadata.available
        assert response.snapshot.metadata.active_ts_sha256 == "hash-a"
        assert not response.snapshot.product_nodes
    else:
        assert response.snapshot == expected
        assert response.snapshot is not retained
        assert retained == expected
    current = host._active_planning_graph_snapshot
    assert current.metadata.planning_generation == 8
    assert current.metadata.active_ts_sha256 == replacement_hash
    assert current.product_nodes[0].ts_state.states == ["r2"]
    assert host._execution_step_seq == 0
    assert replacement.metadata.planning_generation == 0
    response.snapshot.metadata.hard_task = "caller mutation"
    if response.snapshot.product_nodes:
        response.snapshot.product_nodes[0].ts_state.states[0] = "caller mutation"
    assert current.metadata.hard_task == "1"
    assert current.product_nodes[0].ts_state.states == ["r2"]
    if expected is not None:
        assert retained == expected
