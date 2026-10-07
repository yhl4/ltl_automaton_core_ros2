"""Real ROS node-boundary tests for execution and observed state separation."""

import time
from types import SimpleNamespace
import warnings

import pytest
import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.task import Future
from rcl_interfaces.srv import DescribeParameters, SetParameters, SetParametersAtomically

from ltl_automaton_msgs.msg import PlanningExecutionObservation
from ltl_automaton_msgs.msg import ProductGraphEdge
from ltl_automaton_msgs.msg import ProductGraphNode
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot
from ltl_automaton_execution.execution_node import COMMAND_QOS
from ltl_automaton_execution.execution_node import ExecutionManagerNode
from ltl_automaton_execution.fake_runtime import FakePlant
from ltl_automaton_execution.models import ExecutionCompletion
from ltl_automaton_execution.models import SymbolicState


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def execute(self, step, completion):
        self.calls.append((step, completion))
        return True


class RecordingObserver:
    def __init__(self):
        self.callback = None

    def start(self, on_observation):
        self.callback = on_observation

    def stop(self):
        self.callback = None

    def emit(self, observation):
        self.callback(observation)


class RecordingAbstraction:
    def abstract(self, observation):
        if observation == "unsupported":
            return None
        return observation


class MalformedState:
    dimension_names = ("region", "region")
    states = ("r1", "r2")


class UnhashableString(str):
    __hash__ = None


class DelayedSnapshotClient:
    """Return one controllable Future for a delayed snapshot response."""

    def __init__(self):
        self.future = Future()
        self.ready = True

    def service_is_ready(self):
        return self.ready

    def call_async(self, _request):
        return self.future


class RetrySnapshotClient:
    """Return a fresh controllable Future for every snapshot request."""

    def __init__(self):
        self.futures = []
        self.ready = True
        self.sync_error = None

    def service_is_ready(self):
        return self.ready

    def call_async(self, _request):
        if self.sync_error is not None:
            raise self.sync_error
        future = Future()
        self.futures.append(future)
        return future


def _fill_snapshot(snapshot, generation):
    snapshot.metadata.planner_instance_id = "planner-a"
    snapshot.metadata.planning_generation = generation
    snapshot.metadata.available = True
    first = ProductGraphNode()
    first.id = 1
    first.ts_state.state_dimension_names = ["region", "load"]
    first.ts_state.states = ["r1", "empty"]
    second = ProductGraphNode()
    second.id = 2
    second.ts_state.state_dimension_names = ["region", "load"]
    second.ts_state.states = ["r2", "empty"]
    move = ProductGraphEdge()
    move.source_id = 1
    move.target_id = 2
    move.action = "move"
    wait = ProductGraphEdge()
    wait.source_id = 2
    wait.target_id = 2
    wait.action = "wait"
    snapshot.product_nodes = [first, second]
    snapshot.product_edges = [move, wait]
    snapshot.accepted_run.prefix_product_node_ids = [1, 2]
    snapshot.accepted_run.suffix_product_node_ids = [2]


def _observation(generation, sequence=0, instance="planner-a"):
    message = PlanningExecutionObservation()
    message.planner_instance_id = instance
    message.planning_generation = generation
    message.execution_step_seq = sequence
    message.possible_product_node_ids = [1]
    message.has_next_action = True
    message.next_action = "move"
    return message


def _spin_until(executor, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        executor.spin_once(timeout_sec=0.02)
    return predicate()


def _delayed_execution(context):
    backend = RecordingBackend()
    execution = ExecutionManagerNode(
        backend=backend,
        state_observer=RecordingObserver(),
        context=context,
    )
    client = DelayedSnapshotClient()
    execution._snapshot_client = client
    return execution, backend, client


def _complete_snapshot(client, generation=1):
    response = GetPlanningGraphSnapshot.Response()
    response.success = True
    _fill_snapshot(response.snapshot, generation)
    client.future.set_result(response)


def _successful_response(generation=1):
    response = GetPlanningGraphSnapshot.Response()
    response.success = True
    _fill_snapshot(response.snapshot, generation)
    return response


def test_snapshot_conversion_preserves_repeated_states_and_input_order():
    """Convert repeated TS values without changing the ROS message."""
    response = _successful_response()
    first, second = response.snapshot.product_nodes
    second.id = 7
    second.ts_state.states = list(first.ts_state.states)
    response.snapshot.product_nodes = [second, first]
    before = [
        (node.id, list(node.ts_state.state_dimension_names),
         list(node.ts_state.states))
        for node in response.snapshot.product_nodes
    ]
    before_metadata = (
        response.snapshot.metadata.planner_instance_id,
        response.snapshot.metadata.planning_generation,
        response.snapshot.metadata.available,
        response.snapshot.metadata.unavailable_reason,
    )
    before_edges = [
        (edge.source_id, edge.target_id, edge.action)
        for edge in response.snapshot.product_edges
    ]
    before_run = (
        list(response.snapshot.accepted_run.prefix_product_node_ids),
        list(response.snapshot.accepted_run.suffix_product_node_ids),
    )

    snapshot = ExecutionManagerNode._snapshot_from_message(response.snapshot)

    assert [node.node_id for node in snapshot.product_nodes] == [7, 1]
    assert [
        (node.ts_state.dimension_names, node.ts_state.states)
        for node in snapshot.product_nodes
    ] == [
        (tuple(before[0][1]), tuple(before[0][2])),
        (tuple(before[1][1]), tuple(before[1][2])),
    ]
    assert [
        (node.id, list(node.ts_state.state_dimension_names),
         list(node.ts_state.states))
        for node in response.snapshot.product_nodes
    ] == before
    assert (
        response.snapshot.metadata.planner_instance_id,
        response.snapshot.metadata.planning_generation,
        response.snapshot.metadata.available,
        response.snapshot.metadata.unavailable_reason,
    ) == before_metadata
    assert [
        (edge.source_id, edge.target_id, edge.action)
        for edge in response.snapshot.product_edges
    ] == before_edges
    assert (
        list(response.snapshot.accepted_run.prefix_product_node_ids),
        list(response.snapshot.accepted_run.suffix_product_node_ids),
    ) == before_run


def test_snapshot_conversion_does_not_reuse_state_between_messages():
    """A later message cannot mutate a previously converted snapshot."""
    response = _successful_response()
    first = ExecutionManagerNode._snapshot_from_message(response.snapshot)

    response.snapshot.product_nodes[0].ts_state.states[0] = "changed"
    second = ExecutionManagerNode._snapshot_from_message(response.snapshot)

    assert first.product_nodes[0].ts_state.states == ("r1", "empty")
    assert second.product_nodes[0].ts_state.states == ("changed", "empty")


@pytest.mark.parametrize(
    ("dimension_names", "states"),
    [
        (["region"], [UnhashableString("r1")]),
        ([UnhashableString("region")], ["r1"]),
    ],
)
def test_snapshot_conversion_accepts_unhashable_string_subclass(
    dimension_names, states,
):
    """A valid unhashable string value follows normal SymbolicState checks."""
    node = SimpleNamespace(
        id=1,
        ts_state=SimpleNamespace(
            state_dimension_names=dimension_names,
            states=states,
        ),
    )
    message = SimpleNamespace(
        metadata=SimpleNamespace(
            available=True,
            planner_instance_id="planner-a",
            planning_generation=1,
            unavailable_reason="",
        ),
        product_nodes=[node],
        product_edges=[],
        accepted_run=SimpleNamespace(
            prefix_product_node_ids=[],
            suffix_product_node_ids=[],
        ),
    )

    snapshot = ExecutionManagerNode._snapshot_from_message(message)

    assert (
        snapshot.product_nodes[0].ts_state.dimension_names[0].__class__
        is dimension_names[0].__class__
    )
    assert (
        snapshot.product_nodes[0].ts_state.states[0].__class__
        is states[0].__class__
    )
    assert snapshot.product_nodes[0].ts_state.dimension_names == tuple(
        dimension_names
    )
    assert snapshot.product_nodes[0].ts_state.states == (
        states[0],
    )


@pytest.mark.parametrize(
    ("dimensions", "states", "expected"),
    (
        ([[]], [[]], "Symbolic state dimensions must be non-empty."),
        (
            ["region", "region"],
            [[], []],
            "Symbolic state dimensions must be unique.",
        ),
        (["region"], [[]], "Symbolic state values must be non-empty."),
    ),
)
def test_snapshot_conversion_preserves_validation_order_for_malformed_input(
    dimensions, states, expected
):
    """Node IDs and malformed state values retain their original errors."""
    message = SimpleNamespace(
        metadata=SimpleNamespace(
            available=True,
            planner_instance_id="planner-a",
            planning_generation=1,
            unavailable_reason="",
        ),
        product_nodes=[
            SimpleNamespace(
                id=1,
                ts_state=SimpleNamespace(
                    state_dimension_names=dimensions,
                    states=states,
                ),
            ),
        ],
        product_edges=[],
        accepted_run=SimpleNamespace(
            prefix_product_node_ids=[],
            suffix_product_node_ids=[],
        ),
    )

    with pytest.raises(ValueError) as raised:
        ExecutionManagerNode._snapshot_from_message(message)
    assert str(raised.value) == expected

    message.product_nodes[0].id = "not-an-int"
    with pytest.raises(ValueError) as raised:
        ExecutionManagerNode._snapshot_from_message(message)
    assert str(raised.value).startswith("invalid literal for int()")


def test_repeated_suffix_start_snapshot_cannot_dispatch():
    """Reject a malformed ROS suffix and accept a later valid generation."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        execution, backend, client = _delayed_execution(context)
        diagnostics = []
        execution._manager._diagnostic = diagnostics.append
        execution._on_observation(_observation(1))
        response = _successful_response(1)
        response.snapshot.accepted_run.suffix_product_node_ids = [2, 2]
        client.future.set_result(response)

        assert backend.calls == []
        assert not execution._manager.in_flight
        assert diagnostics[-1] == "Accepted suffix repeats its start node at the end."

        replacement_client = DelayedSnapshotClient()
        execution._snapshot_client = replacement_client
        execution._on_observation(_observation(2))
        _complete_snapshot(replacement_client, generation=2)
        assert len(backend.calls) == 1
        assert backend.calls[0][0].planning_generation == 2
        assert backend.calls[0][0].action == "move"
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


@pytest.mark.parametrize("delay", [0.5, -1.0])
def test_falsey_backend_receives_formal_step_without_fake_delay_validation(delay):
    """An explicitly supplied backend owns scheduling regardless of its truth value."""
    class FalseyBackend(RecordingBackend):
        def __bool__(self):
            return False

    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        backend = FalseyBackend()
        execution = ExecutionManagerNode(
            backend=backend, state_observer=RecordingObserver(),
            execution_delay_sec=delay, context=context,
        )
        client = DelayedSnapshotClient()
        execution._snapshot_client = client
        execution._on_observation(_observation(1))
        _complete_snapshot(client)
        assert len(backend.calls) == 1
        assert backend.calls[0][0].action == "move"
        assert not execution._execution_timers
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


@pytest.mark.parametrize("component", ["observer", "abstraction"])
def test_falsey_observation_component_delivers_independent_state(component):
    """Valid custom observation components must retain their callback and conversion."""
    class FalseyObserver(RecordingObserver):
        def __bool__(self):
            return False

    class FalseyAbstraction(RecordingAbstraction):
        def __bool__(self):
            return False

    context = Context()
    rclpy.init(context=context)
    execution = None
    observer = FalseyObserver() if component == "observer" else RecordingObserver()
    abstraction = (
        FalseyAbstraction() if component == "abstraction" else RecordingAbstraction()
    )
    try:
        execution = ExecutionManagerNode(
            backend=RecordingBackend(), state_observer=observer,
            state_abstraction=abstraction, context=context,
        )
        reported = []
        execution._publish_state = reported.append
        observed = SymbolicState(("region",), ("external",))
        assert observer.callback is not None
        observer.emit(observed)
        assert reported == [observed]
        assert not execution._manager.in_flight
        execution.destroy_node()
        assert observer.callback is None
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


def test_falsey_fake_plant_is_shared_by_default_backend_and_observer(monkeypatch):
    """Default fake execution must update and observe the explicitly provided plant."""
    class FalseyPlant(FakePlant):
        def __bool__(self):
            return False

    callbacks = []

    def schedule(_node, _delay, callback):
        callbacks.append(callback)
        return True

    monkeypatch.setattr(ExecutionManagerNode, "_schedule", schedule)
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        plant = FalseyPlant(SymbolicState(("region", "load"), ("r1", "empty")))
        execution = ExecutionManagerNode(fake_plant=plant, context=context)
        reported = []
        execution._publish_state = reported.append
        client = DelayedSnapshotClient()
        execution._snapshot_client = client
        execution._on_observation(_observation(1))
        _complete_snapshot(client)
        assert len(callbacks) == 1
        callbacks[0]()
        expected = SymbolicState(("region", "load"), ("r2", "empty"))
        assert plant.current_state == expected
        assert reported == [expected]
        assert not execution._manager.in_flight
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


def test_command_survives_delayed_snapshot_service_discovery():
    """Execute a retained command when its snapshot service appears later."""
    context = Context()
    rclpy.init(context=context)
    backend = RecordingBackend()
    execution = ExecutionManagerNode(
        backend=backend, state_observer=RecordingObserver(), context=context,
    )
    driver = rclpy.create_node("late_snapshot_service_test", context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(execution)
    executor.add_node(driver)
    service = None
    try:
        assert not execution._snapshot_client.service_is_ready()
        execution._on_observation(_observation(1))

        def snapshot_callback(_request, response):
            response.success = True
            _fill_snapshot(response.snapshot, 1)
            return response

        service = driver.create_service(
            GetPlanningGraphSnapshot, "get_planning_graph_snapshot", snapshot_callback,
        )
        assert _spin_until(executor, lambda: len(backend.calls) == 1)
    finally:
        if service is not None:
            driver.destroy_service(service)
        executor.remove_node(driver)
        executor.remove_node(execution)
        driver.destroy_node()
        execution.destroy_node()
        executor.shutdown()
        rclpy.shutdown(context=context)


@pytest.mark.parametrize("failure", ["exception", "none", "false"])
def test_failed_snapshot_response_is_retried(failure):
    """Retry a failed request with the latest same-authority observation."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        backend = RecordingBackend()
        execution = ExecutionManagerNode(
            backend=backend,
            state_observer=RecordingObserver(),
            context=context,
        )
        client = RetrySnapshotClient()
        execution._snapshot_client = client
        execution._on_observation(_observation(1))
        latest = _observation(1, sequence=1)
        latest.possible_product_node_ids = [2]
        latest.next_action = "wait"
        execution._on_observation(latest)

        assert len(client.futures) == 1
        if failure == "exception":
            client.futures[0].set_exception(
                RuntimeError("temporary snapshot exception")
            )
        elif failure == "none":
            client.futures[0].set_result(None)
        else:
            response = GetPlanningGraphSnapshot.Response()
            response.success = False
            response.message = "temporary snapshot failure"
            client.futures[0].set_result(response)

        assert execution._pending_snapshot_observation is not None
        execution._retry_snapshot_discovery()
        assert len(client.futures) == 2
        client.futures[1].set_result(_successful_response())
        assert len(backend.calls) == 1
        assert backend.calls[0][0].execution_step_seq == 1
        assert backend.calls[0][0].action == "wait"
        assert backend.calls[0][0].source_product_node_ids == (2,)
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


def test_synchronous_snapshot_request_failure_is_retried():
    """Retry when the ROS client rejects call_async synchronously."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        backend = RecordingBackend()
        execution = ExecutionManagerNode(
            backend=backend,
            state_observer=RecordingObserver(),
            context=context,
        )
        client = RetrySnapshotClient()
        client.sync_error = RuntimeError("client unavailable")
        execution._snapshot_client = client
        execution._on_observation(_observation(1))

        assert client.futures == []
        assert execution._pending_snapshot_observation is not None
        client.sync_error = None
        execution._retry_snapshot_discovery()
        assert len(client.futures) == 1
        client.futures[0].set_result(_successful_response())
        assert len(backend.calls) == 1
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


@pytest.mark.parametrize("outcome", ["success", "failure", "exception"])
def test_late_snapshot_completion_after_destroy_is_ignored(outcome):
    """Late snapshot callbacks do not touch a destroyed node."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        backend = RecordingBackend()
        execution = ExecutionManagerNode(
            backend=backend,
            state_observer=RecordingObserver(),
            context=context,
        )
        client = DelayedSnapshotClient()
        execution._snapshot_client = client
        execution._on_observation(_observation(1))
        execution.destroy_node()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            execution._retry_snapshot_discovery()
            if outcome == "success":
                client.future.set_result(_successful_response())
            elif outcome == "failure":
                response = GetPlanningGraphSnapshot.Response()
                response.success = False
                response.message = "late failure"
                client.future.set_result(response)
            else:
                client.future.set_exception(RuntimeError("late exception"))

        assert not any(
            "Destroyable" in str(warning.message) for warning in caught
        )
        assert execution._pending_snapshot_observation is None
        assert not execution._snapshot_requests
        assert backend.calls == []
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


def test_failed_snapshot_no_action_suppresses_retry():
    """A newer no-action observation cancels a failed request retry."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        backend = RecordingBackend()
        execution = ExecutionManagerNode(
            backend=backend,
            state_observer=RecordingObserver(),
            context=context,
        )
        client = RetrySnapshotClient()
        execution._snapshot_client = client
        execution._on_observation(_observation(1))
        latest = _observation(1, sequence=1)
        latest.has_next_action = False
        latest.next_action = ""
        latest.possible_product_node_ids = []
        execution._on_observation(latest)

        response = GetPlanningGraphSnapshot.Response()
        response.success = False
        response.message = "temporary snapshot failure"
        client.futures[0].set_result(response)

        assert execution._pending_snapshot_observation is None
        execution._retry_snapshot_discovery()
        assert len(client.futures) == 1
        assert backend.calls == []
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


@pytest.mark.parametrize("generation, instance", [(2, "planner-a"), (1, "planner-b")])
def test_stale_failed_snapshot_cannot_replace_new_authority(
    generation, instance
):
    """A failed old request cannot queue a newer generation or instance."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        backend = RecordingBackend()
        execution = ExecutionManagerNode(
            backend=backend,
            state_observer=RecordingObserver(),
            context=context,
        )
        client = RetrySnapshotClient()
        execution._snapshot_client = client
        execution._on_observation(_observation(1))
        execution._on_observation(
            _observation(generation, instance=instance)
        )
        assert len(client.futures) == 2

        response = GetPlanningGraphSnapshot.Response()
        response.success = False
        response.message = "old request failed"
        client.futures[0].set_result(response)

        assert execution._pending_snapshot_observation is None
        execution._retry_snapshot_discovery()
        assert len(client.futures) == 2
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


def test_delayed_snapshot_dispatches_latest_same_generation_observation():
    """Use the newest Product belief and action when a snapshot catches up."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        execution, backend, client = _delayed_execution(context)
        execution._on_observation(_observation(1))
        latest = _observation(1, sequence=1)
        latest.possible_product_node_ids = [2]
        latest.next_action = "wait"
        execution._on_observation(latest)

        _complete_snapshot(client)

        assert len(backend.calls) == 1
        assert backend.calls[0][0].action == "wait"
        assert backend.calls[0][0].source_product_node_ids == (2,)
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


def test_delayed_snapshot_latest_no_action_suppresses_old_dispatch():
    """A newer no-action observation must suppress the captured command."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        execution, backend, client = _delayed_execution(context)
        execution._on_observation(_observation(1))
        latest = _observation(1, sequence=1)
        latest.possible_product_node_ids = []
        latest.has_next_action = False
        latest.next_action = ""
        execution._on_observation(latest)

        _complete_snapshot(client)

        assert backend.calls == []
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


def test_busy_observation_retries_latest_sequence_after_completion():
    """Use the latest queued step after the previous backend call finishes."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        execution, backend, client = _delayed_execution(context)
        execution._on_observation(_observation(1))
        _complete_snapshot(client)
        assert len(backend.calls) == 1

        latest = _observation(1, sequence=1)
        latest.possible_product_node_ids = [2]
        latest.next_action = "wait"
        execution._on_observation(latest)
        assert len(backend.calls) == 1

        newest = _observation(1, sequence=2)
        newest.possible_product_node_ids = [2]
        newest.next_action = "wait"
        execution._on_observation(newest)
        execution._on_observation(latest)
        client.ready = False

        backend.calls[0][1](ExecutionCompletion(True, "done"))
        execution._retry_snapshot_discovery()

        assert len(backend.calls) == 2
        assert backend.calls[1][0].execution_step_seq == 2
        assert backend.calls[1][0].action == "wait"
        assert backend.calls[1][0].source_product_node_ids == (2,)
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


def test_delayed_snapshot_stale_generation_cannot_restore_old_command():
    """A newer generation keeps an older delayed snapshot from dispatching."""
    context = Context()
    rclpy.init(context=context)
    execution = None
    try:
        execution, backend, client = _delayed_execution(context)
        execution._on_observation(_observation(1))
        execution._on_observation(_observation(2))

        _complete_snapshot(client, generation=1)

        assert backend.calls == []
    finally:
        if execution is not None:
            execution.destroy_node()
        rclpy.shutdown(context=context)


def test_r1_through_r9_and_a10_observation_pipeline_contract():
    """Cover independent completion, observation, schema, and authority."""
    context = Context()
    rclpy.init(context=context)
    backend = RecordingBackend()
    observer = RecordingObserver()
    plant = FakePlant(SymbolicState(("region", "load"), ("r1", "empty")))
    execution = ExecutionManagerNode(
        backend=backend,
        state_observer=observer,
        state_abstraction=RecordingAbstraction(),
        fake_plant=plant,
        context=context,
    )
    driver = rclpy.create_node("execution_node_test", context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(execution)
    executor.add_node(driver)
    current_generation = [1]
    service_calls = []

    def snapshot_callback(_request, response):
        service_calls.append(current_generation[0])
        response.success = True
        response.message = "available"
        _fill_snapshot(response.snapshot, current_generation[0])
        return response

    service = driver.create_service(
        GetPlanningGraphSnapshot,
        "get_planning_graph_snapshot",
        snapshot_callback,
    )
    publisher = driver.create_publisher(
        PlanningExecutionObservation,
        "planning_execution_observation",
        COMMAND_QOS,
    )
    states = []
    subscription = driver.create_subscription(
        TransitionSystemStateStamped,
        "ts_state",
        states.append,
        10,
    )

    try:
        assert _spin_until(
            executor,
            lambda: publisher.get_subscription_count() == 1
            and execution._snapshot_client.service_is_ready(),
        )
        publisher.publish(_observation(1))
        publisher.publish(_observation(1))
        assert _spin_until(executor, lambda: len(backend.calls) == 1)
        assert service_calls == [1]

        current_generation[0] = 2
        publisher.publish(_observation(2))
        executor.spin_once(timeout_sec=0.05)
        assert len(backend.calls) == 1

        backend.calls[0][1](ExecutionCompletion(True, "generation 1 done"))
        executor.spin_once(timeout_sec=0.05)
        assert states == []

        observer.emit(SymbolicState(
            ("load", "region"), ("empty", "r2")
        ))
        assert _spin_until(executor, lambda: len(states) == 1)
        assert list(states[0].ts_state.state_dimension_names) == [
            "region", "load"
        ]
        assert list(states[0].ts_state.states) == ["r2", "empty"]
        assert states[0].header.stamp.sec or states[0].header.stamp.nanosec

        observer.emit(SymbolicState(
            ("load", "region"), ("empty", "r2")
        ))
        assert _spin_until(executor, lambda: len(states) == 2)
        observer.emit("unsupported")
        observer.emit(MalformedState())
        observer.emit(SymbolicState(("unknown",), ("value",)))
        executor.spin_once(timeout_sec=0.05)
        assert len(states) == 2

        publisher.publish(_observation(2))
        assert _spin_until(executor, lambda: len(backend.calls) == 2)
        assert service_calls == [1, 2]
        backend.calls[1][1](ExecutionCompletion(False, "controller failed"))
        executor.spin_once(timeout_sec=0.05)
        assert plant.current_state == SymbolicState(
            ("region", "load"), ("r1", "empty")
        )
        assert len(states) == 2

        observer.emit(SymbolicState(
            ("region", "load"), ("external", "holding")
        ))
        assert _spin_until(executor, lambda: len(states) == 3)
        assert list(states[-1].ts_state.states) == ["external", "holding"]

        current_generation[0] = 2
        publisher.publish(_observation(3))
        assert _spin_until(executor, lambda: len(service_calls) == 3)
        executor.spin_once(timeout_sec=0.05)
        assert len(backend.calls) == 2
        assert len(states) == 3
    finally:
        executor.remove_node(driver)
        executor.remove_node(execution)
        driver.destroy_subscription(subscription)
        driver.destroy_publisher(publisher)
        driver.destroy_service(service)
        driver.destroy_node()
        execution.destroy_node()
        executor.shutdown()
        rclpy.shutdown(context=context)


@pytest.mark.parametrize("field", ["dimensions", "values"])
def test_custom_abstraction_rejects_bytes_and_recovers_valid_observation(field):
    """Keep invalid custom state out of generated ROS messages and accept later feedback."""
    class ConstructingAbstraction:
        def abstract(self, observation):
            return SymbolicState(*observation)

    context = Context()
    rclpy.init(context=context)
    observer = RecordingObserver()
    backend = RecordingBackend()
    execution = ExecutionManagerNode(
        backend=backend, state_observer=observer,
        state_abstraction=ConstructingAbstraction(), context=context,
    )
    published = []
    execution._state_publisher = SimpleNamespace(publish=published.append)
    try:
        observer.emit((("region", "load"), ("r1", "empty")))
        assert len(published) == 1
        assert published[0].ts_state.state_dimension_names == ["region", "load"]
        assert published[0].ts_state.states == ["r1", "empty"]
        dimensions = ("region", b"load") if field == "dimensions" else ("region", "load")
        values = ("r1", b"empty") if field == "values" else ("r1", "empty")

        observer.emit((dimensions, values))

        assert len(published) == 1
        assert backend.calls == []
        observer.emit((("region", "load"), ("r2", "holding")))
        assert len(published) == 2
        assert published[1].ts_state.state_dimension_names == ["region", "load"]
        assert published[1].ts_state.states == ["r2", "holding"]
        assert published[0].ts_state.states == ["r1", "empty"]
        assert backend.calls == []
    finally:
        execution.destroy_node()
        rclpy.shutdown(context=context)


@pytest.mark.parametrize("unhashable", ["observed", "expected", "both"])
def test_state_observation_accepts_unhashable_dimensions_and_recovers(
    unhashable,
):
    """Match reversed dimensions without hashing string subclasses."""
    class ConstructingAbstraction:
        def abstract(self, observation):
            return SymbolicState(*observation)

    context = Context()
    rclpy.init(context=context)
    observer = RecordingObserver()
    backend = RecordingBackend()
    execution = ExecutionManagerNode(
        backend=backend,
        state_observer=observer,
        state_abstraction=ConstructingAbstraction(),
        context=context,
    )
    published = []
    execution._state_publisher = SimpleNamespace(publish=published.append)
    expected = (
        UnhashableString("region") if unhashable in ("expected", "both")
        else "region",
        "load",
    )
    observed = (
        UnhashableString("load") if unhashable in ("observed", "both")
        else "load",
        "region",
    )
    try:
        execution._expected_dimensions = expected
        observer.emit((observed, ("empty", "r1")))
        assert len(published) == 1
        observer.emit((("unknown", "region"), ("x", "r1")))
        assert len(published) == 1
        observer.emit((observed, ("holding", "r2")))

        assert [message.ts_state.state_dimension_names for message in published] == [
            ["region", "load"],
            ["region", "load"],
        ]
        assert [message.ts_state.states for message in published] == [
            ["r1", "empty"],
            ["r2", "holding"],
        ]
        assert execution._manager.in_flight is False
        assert backend.calls == []
    finally:
        execution.destroy_node()
        rclpy.shutdown(context=context)


def test_queued_state_observation_is_ignored_after_node_teardown():
    """A saved observer callback must not touch abstraction or destroyed ROS entities."""
    class TrackingAbstraction(RecordingAbstraction):
        def __init__(self):
            self.calls = []

        def abstract(self, observation):
            self.calls.append(observation)
            return super().abstract(observation)

    context = Context()
    rclpy.init(context=context)
    observer = RecordingObserver()
    abstraction = TrackingAbstraction()
    execution = ExecutionManagerNode(
        backend=RecordingBackend(), state_observer=observer,
        state_abstraction=abstraction, context=context,
    )
    try:
        active = SymbolicState(("region",), ("r1",))
        observer.emit(active)
        assert abstraction.calls == [active]
        queued_callback = observer.callback
        execution.destroy_node()
        assert observer.callback is None
        queued_callback(SymbolicState(("region",), ("r2",)))
        queued_callback("unsupported")
        assert abstraction.calls == [active]
    finally:
        execution.destroy_node()
        rclpy.shutdown(context=context)


def test_public_parameter_services_reject_unused_startup_updates():
    """Keep reported startup configuration equal to the live cached values."""
    context = Context()
    rclpy.init(context=context)
    execution = ExecutionManagerNode(
        context=context,
        parameter_overrides=[
            Parameter("snapshot_request_timeout", value=0.75),
            Parameter("execution_delay_sec", value=0.25),
        ],
    )
    driver = rclpy.create_node("execution_parameter_contract_test", context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(execution)
    executor.add_node(driver)
    describe = driver.create_client(
        DescribeParameters, "ltl_execution_manager/describe_parameters",
    )
    update = driver.create_client(SetParameters, "ltl_execution_manager/set_parameters")
    atomic = driver.create_client(
        SetParametersAtomically, "ltl_execution_manager/set_parameters_atomically",
    )
    try:
        for client in (describe, update, atomic):
            assert client.wait_for_service(timeout_sec=2.0)
        names = ["snapshot_request_timeout", "execution_delay_sec", "use_sim_time"]
        future = describe.call_async(DescribeParameters.Request(names=names))
        assert _spin_until(executor, future.done)
        assert [item.read_only for item in future.result().descriptors] == [True, True, False]
        assert execution._snapshot_request_timeout == 0.75
        assert execution._manager._backend._delay == 0.25

        future = update.call_async(SetParameters.Request(parameters=[
            Parameter("snapshot_request_timeout", value=0.1).to_parameter_msg(),
            Parameter("execution_delay_sec", value=1.0).to_parameter_msg(),
            Parameter("use_sim_time", value=True).to_parameter_msg(),
        ]))
        assert _spin_until(executor, future.done)
        assert [item.successful for item in future.result().results] == [False, False, True]
        assert execution.get_parameter("snapshot_request_timeout").value == 0.75
        assert execution.get_parameter("execution_delay_sec").value == 0.25
        assert execution.get_parameter("use_sim_time").value is True
        assert execution._snapshot_request_timeout == 0.75
        assert execution._manager._backend._delay == 0.25

        future = atomic.call_async(SetParametersAtomically.Request(parameters=[
            Parameter("snapshot_request_timeout", value=0.1).to_parameter_msg(),
            Parameter("use_sim_time", value=False).to_parameter_msg(),
        ]))
        assert _spin_until(executor, future.done)
        assert not future.result().result.successful
        assert execution.get_parameter("snapshot_request_timeout").value == 0.75
        assert execution.get_parameter("use_sim_time").value is True
    finally:
        for client in (describe, update, atomic):
            driver.destroy_client(client)
        executor.remove_node(driver)
        executor.remove_node(execution)
        driver.destroy_node()
        execution.destroy_node()
        executor.shutdown()
        rclpy.shutdown(context=context)
