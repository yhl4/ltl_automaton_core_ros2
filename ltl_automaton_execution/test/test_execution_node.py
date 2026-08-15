"""Real ROS node-boundary tests for the execution manager."""

import time

import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor

from ltl_automaton_msgs.msg import PlanningExecutionObservation
from ltl_automaton_msgs.msg import ProductGraphEdge
from ltl_automaton_msgs.msg import ProductGraphNode
from ltl_automaton_msgs.msg import TransitionSystemStateStamped
from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot
from ltl_automaton_execution.execution_node import COMMAND_QOS
from ltl_automaton_execution.execution_node import ExecutionManagerNode
from ltl_automaton_execution.models import ExecutionResult


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def execute(self, step, completion):
        self.calls.append((step, completion))
        return True


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


def _observation(generation):
    message = PlanningExecutionObservation()
    message.planner_instance_id = "planner-a"
    message.planning_generation = generation
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


def test_r1_through_r9_execution_node_contract():
    """Cover fetch, dedupe, busy, publication, failure, and replacement."""
    context = Context()
    rclpy.init(context=context)
    backend = RecordingBackend()
    execution = ExecutionManagerNode(backend=backend, context=context)
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
        assert backend.calls[0][0].action == "move"

        current_generation[0] = 2
        publisher.publish(_observation(2))
        executor.spin_once(timeout_sec=0.05)
        assert len(backend.calls) == 1

        backend.calls[0][1](ExecutionResult(
            True,
            backend.calls[0][0].target_state,
            "generation 1 completed",
        ))
        assert _spin_until(executor, lambda: len(states) == 1)
        assert list(states[0].ts_state.state_dimension_names) == [
            "region", "load"
        ]
        assert list(states[0].ts_state.states) == ["r2", "empty"]
        assert states[0].header.stamp.sec or states[0].header.stamp.nanosec

        publisher.publish(_observation(2))
        assert _spin_until(executor, lambda: len(backend.calls) == 2)
        assert service_calls == [1, 2]
        backend.calls[1][1](ExecutionResult(False, None, "controller failed"))
        executor.spin_once(timeout_sec=0.05)
        assert len(states) == 1

        current_generation[0] = 2
        publisher.publish(_observation(3))
        assert _spin_until(executor, lambda: len(service_calls) == 3)
        executor.spin_once(timeout_sec=0.05)
        assert len(backend.calls) == 2
        assert len(states) == 1
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
