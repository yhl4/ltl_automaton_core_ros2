"""Real ROS node-boundary tests for execution and observed state separation."""

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
