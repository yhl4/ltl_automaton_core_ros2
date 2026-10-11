"""Small isolated ROS2 transport loop for a CMR refinement request.

The server invokes the bound CMR runtime after receiving one JSON request, then
serves the public execution snapshot and drives the existing symbolic node.
It is intentionally a smoke harness, not a PlannerNode replacement.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any


SCHEMA = "cmr-ros2-integration-result-v1"
REQUEST_TOPIC = "/cmr_smoke/request"
RESULT_TOPIC = "/cmr_smoke/result"
OBSERVATION_TOPIC = "/planning_execution_observation"
SNAPSHOT_SERVICE = "/get_planning_graph_snapshot"
TS_TOPIC = "/ts_state"
COMMAND_TOPIC = "/next_move_cmd"
ProductKey = tuple[tuple[str, ...], str]
DOMAIN_IDS = {
    "cmr-cost-gap-apd": 216,
    "cmr-spurious-apd": 217,
    "cmr-base-full-timeout": 218,
}


def _now() -> int:
    """Return a monotonic timestamp for event artifacts."""
    return time.monotonic_ns()


def _sha256(path: Path) -> str:
    """Hash one imported source file for the runtime identity artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _event(events: list[dict[str, Any]], name: str, **fields: Any) -> None:
    """Append one timestamped transport event."""
    events.append({"event": name, "time_ns": _now(), **fields})


def _fraction(value: Any) -> Fraction:
    """Parse the exact cost spelling used by the CMR result contract."""
    if isinstance(value, bool):
        raise TypeError("boolean is not an exact cost")
    if isinstance(value, Fraction):
        return value
    if not isinstance(value, str):
        raise TypeError("CMR costs must be Fraction strings")
    return Fraction(value)


def _ts_values(state: Any) -> tuple[str, ...]:
    """Extract TS values from a CMR product-state spelling."""
    if isinstance(state, dict):
        for key in ("ts_state", "state", "source", "target"):
            if key in state:
                return _ts_values(state[key])
        raise TypeError("CMR state has no TS component")
    if isinstance(state, (list, tuple)):
        if len(state) == 2 and isinstance(state[0], (list, tuple)):
            state = state[0]
        if not state:
            raise ValueError("CMR TS state is empty")
        return tuple(str(value) for value in state)
    raise TypeError("CMR state must be a sequence or object")


def _product_state(state: Any) -> tuple[tuple[str, ...], str]:
    """Keep both TS values and Büchi identity for Product node allocation."""
    if isinstance(state, dict):
        if "buchi_state" in state:
            ts = state.get("ts_state", state.get("state"))
            return _ts_values(ts), str(state["buchi_state"])
        if "buchi" in state:
            ts = state.get("ts_state", state.get("state"))
            return _ts_values(ts), str(state["buchi"])
    if isinstance(state, (list, tuple)) and len(state) == 2:
        if isinstance(state[0], (list, tuple)):
            return _ts_values(state[0]), str(state[1])
    return _ts_values(state), ""


def _edge_endpoint(
    edge: dict[str, Any], name: str
) -> tuple[tuple[str, ...], str]:
    """Read one edge endpoint while keeping the adapter schema narrow."""
    if not isinstance(edge, dict) or name not in edge:
        raise TypeError(f"CMR edge lacks {name}")
    return _product_state(edge[name])


def _edge_action(edge: dict[str, Any]) -> str:
    """Read the required symbolic action from one edge."""
    action = edge.get("action") if isinstance(edge, dict) else None
    if not isinstance(action, str) or not action:
        raise TypeError("CMR edge action must be a non-empty string")
    return action


def _path(
    result: dict[str, Any], name: str
) -> tuple[list[ProductKey], list[dict[str, Any]]]:
    """Validate one concrete prefix/suffix path from a result."""
    lasso = result.get("concrete_lasso")
    if not isinstance(lasso, dict):
        raise ValueError("certified result has no concrete_lasso")
    states = lasso.get(name)
    edges = lasso.get(f"{name}_edges")
    if not isinstance(states, list) or not isinstance(edges, list):
        raise TypeError(f"concrete_lasso lacks {name} arrays")
    parsed_states = [_product_state(state) for state in states]
    parsed_edges = list(edges)
    for index, edge in enumerate(parsed_edges):
        source = _edge_endpoint(edge, "source")
        target = _edge_endpoint(edge, "target")
        if index < len(parsed_states) - 1:
            if source != parsed_states[index] or target != parsed_states[index + 1]:
                raise ValueError(f"{name} edge {index} does not match states")
        _edge_action(edge)
        _fraction(edge.get("cost"))
    if name == "prefix" and len(parsed_edges) != max(len(parsed_states) - 1, 0):
        raise ValueError("prefix edge/state length mismatch")
    if name == "suffix":
        if len(parsed_states) < 2 or parsed_states[-1] != parsed_states[0]:
            raise ValueError("suffix must include its repeated closing state")
        if len(parsed_edges) != len(parsed_states) - 1:
            raise ValueError("suffix edge/state length mismatch")
        if parsed_edges[-1].get("target") is None:
            raise ValueError("suffix closing edge is missing")
        parsed_states = parsed_states[:-1]
    return parsed_states, parsed_edges


def _snapshot_messages(result: dict[str, Any], identity: str):
    """Build an execution-only ROS snapshot from a certified CMR result."""
    from ltl_automaton_msgs.msg import PlanningGraphSnapshot
    from ltl_automaton_msgs.msg import BuchiGraphNode
    from ltl_automaton_msgs.msg import ProductGraphEdge, ProductGraphNode
    from ltl_automaton_msgs.msg import TransitionSystemState

    prefix_states, prefix_edges = _path(result, "prefix")
    suffix_states, suffix_edges = _path(result, "suffix")
    if not prefix_states or not suffix_states or prefix_states[-1] != suffix_states[0]:
        raise ValueError("prefix/suffix boundary is not shared")

    transitions = []
    for edge in prefix_edges + suffix_edges:
        transitions.append((
            _edge_endpoint(edge, "source"),
            _edge_endpoint(edge, "target"),
            _edge_action(edge),
            _fraction(edge.get("cost")),
        ))
    if transitions[-1][1] != suffix_states[0]:
        raise ValueError("suffix does not close to its first Product state")
    states = list(prefix_states) + [state for state in suffix_states[1:]]
    states.extend(source for source, target, _, _ in transitions if source not in states)
    states.extend(target for source, target, _, _ in transitions if target not in states)
    state_ids: dict[ProductKey, int] = {}
    for state in states:
        state_ids.setdefault(state, len(state_ids))

    snapshot = PlanningGraphSnapshot()
    snapshot.metadata.planner_instance_id = identity
    snapshot.metadata.planning_generation = 1
    snapshot.metadata.available = True
    snapshot.metadata.hard_task = str(result.get("hard_task", "cmr-smoke"))
    snapshot.metadata.soft_task = str(result.get("soft_task", "(true)"))
    snapshot.metadata.buchi_type = "CMR_INITIAL_LABEL_V1"

    dimensions = [f"factor{i}" for i in range(len(states[0][0]))]
    accepting_buchi = result.get("accepting_buchi_states")
    if not isinstance(accepting_buchi, list):
        raise ValueError("result lacks accepting_buchi_states")
    accepting_buchi = {str(state) for state in accepting_buchi}
    buchi_ids: dict[str, int] = {}
    for state, node_id in state_ids.items():
        buchi = state[1]
        buchi_id = buchi_ids.setdefault(buchi, len(buchi_ids))
        node = ProductGraphNode()
        node.id = node_id
        node.ts_state = TransitionSystemState()
        node.ts_state.state_dimension_names = dimensions
        node.ts_state.states = list(state[0])
        node.buchi_node_id = buchi_id
        node.initial = node_id == state_ids[prefix_states[0]]
        node.accepting = buchi in accepting_buchi
        snapshot.product_nodes.append(node)

    for label, node_id in buchi_ids.items():
        buchi_node = BuchiGraphNode()
        buchi_node.id = node_id
        buchi_node.display_label = label
        buchi_node.state = label
        buchi_node.acceptance_level = -1
        buchi_node.initial = label == prefix_states[0][1]
        buchi_node.accepting = any(
            node.buchi_node_id == node_id and node.accepting
            for node in snapshot.product_nodes
        )
        snapshot.buchi_nodes.append(buchi_node)
    if not any(
        snapshot.product_nodes[state_ids[state]].accepting
        for state in suffix_states
    ):
        raise ValueError("suffix has no accepting Product state")

    for source, target, action, cost in transitions:
        edge = ProductGraphEdge()
        edge.source_id = state_ids[source]
        edge.target_id = state_ids[target]
        edge.action = action
        edge.transition_cost = float(cost)
        edge.soft_task_distance = 0.0
        edge.total_weight = float(cost)
        snapshot.product_edges.append(edge)

    snapshot.accepted_run.prefix_product_node_ids = [state_ids[state] for state in prefix_states]
    snapshot.accepted_run.suffix_product_node_ids = [state_ids[state] for state in suffix_states]
    snapshot.accepted_run.prefix_cost = float(
        sum((_fraction(edge.get("cost")) for edge in prefix_edges), Fraction(0))
    )
    snapshot.accepted_run.suffix_cost = float(
        sum((_fraction(edge.get("cost")) for edge in suffix_edges), Fraction(0))
    )
    snapshot.accepted_run.total_cost = (
        snapshot.accepted_run.prefix_cost
        + 10.0 * snapshot.accepted_run.suffix_cost
    )
    snapshot.metadata.product_node_count = len(snapshot.product_nodes)
    snapshot.metadata.product_edge_count = len(snapshot.product_edges)
    snapshot.metadata.buchi_node_count = len(snapshot.buchi_nodes)
    return snapshot, transitions, state_ids


class _Server:
    """Solve one request and serve its execution snapshot."""

    def __init__(
        self,
        request: dict[str, Any],
        binding: str,
        kernel_root: str,
        work_dir: Path,
    ):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        from std_msgs.msg import String
        from ltl_automaton_msgs.msg import PlanningExecutionObservation
        from ltl_automaton_msgs.msg import TransitionSystemStateStamped
        from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot

        self.rclpy = rclpy
        self.String = String
        self.PlanningExecutionObservation = PlanningExecutionObservation
        self.TransitionSystemStateStamped = TransitionSystemStateStamped
        self.GetPlanningGraphSnapshot = GetPlanningGraphSnapshot
        self.events: list[dict[str, Any]] = []
        self.request = request
        self.binding = binding
        self.kernel_root = kernel_root
        self.work_dir = work_dir
        self.transitions = []
        self.cursor = 0
        self.done = False
        self._grace_deadline = None
        self.identity = f"cmr-smoke-{request['request_id']}"
        self.snapshot = None
        self.state_ids = {}
        self.node = rclpy.create_node("cmr_smoke_server")
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
        command_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.result_pub = self.node.create_publisher(String, RESULT_TOPIC, command_qos)
        self.command_pub = self.node.create_publisher(String, COMMAND_TOPIC, command_qos)
        self.observation_pub = self.node.create_publisher(
            PlanningExecutionObservation, OBSERVATION_TOPIC, command_qos
        )
        self.request_sub = self.node.create_subscription(
            String, REQUEST_TOPIC, self._request, qos
        )
        self.state_sub = self.node.create_subscription(
            TransitionSystemStateStamped, TS_TOPIC, self._state, 10
        )
        self.snapshot_srv = self.node.create_service(
            GetPlanningGraphSnapshot, SNAPSHOT_SERVICE, self._snapshot
        )
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        _event(
            self.events,
            "server_ready",
            pid=os.getpid(),
            module=inspect.getfile(type(self).__init__),
        )

    def _request(self, message) -> None:
        """Run the real isolated solver exactly once after request receipt."""
        if self.done:
            return
        request = json.loads(message.data)
        _event(self.events, "request_received", request_id=request.get("request_id"))
        if request != self.request:
            _event(self.events, "request_rejected", reason="request_mismatch")
            return
        self.done = True
        attempt_dir = self.work_dir / "cmr_attempt"
        try:
            from runtime import run_isolated

            _event(self.events, "cmr_solver_started")
            result = run_isolated(
                request, self.binding, self.kernel_root, attempt_dir
            )
            _event(
                self.events,
                "cmr_solver_completed",
                status=result.get("terminal_status"),
            )
        except Exception as error:
            details = traceback.format_exc()
            result = {
                "schema": SCHEMA,
                "population": "SYNTHETIC_SMOKE",
                "request_id": self.request["request_id"],
                "method": self.request.get("method"),
                "variant": self.request.get("variant"),
                "terminal_status": "ERROR",
                "objective": None,
                "concrete_lasso": None,
                "error": repr(error),
            }
            (self.work_dir / "server_traceback.txt").write_text(
                details, encoding="utf-8"
            )
            sys.stderr.write(details)
        self.result = result
        outgoing = json.dumps(result, sort_keys=True, separators=(",", ":"))
        self.result_pub.publish(self.String(data=outgoing))
        _event(self.events, "result_published", status=result.get("terminal_status"))
        if result.get("terminal_status") != "OPTIMALITY_CERTIFIED":
            self._grace_deadline = time.monotonic() + 0.5
            return
        self.snapshot, self.transitions, self.state_ids = _snapshot_messages(
            result, self.identity
        )
        self._publish_observation()

    def _snapshot(self, _request, response):
        """Return the execution-only snapshot; costs remain authoritative in JSON."""
        if self.snapshot is None:
            response.success = False
            response.message = "No certified CMR snapshot is available."
            return response
        response.success = True
        response.message = "CMR smoke execution snapshot"
        response.snapshot = self.snapshot
        _event(self.events, "snapshot_served")
        return response

    def _publish_observation(self) -> None:
        """Publish the current action authority or its terminal no-action state."""
        message = self.PlanningExecutionObservation()
        message.planner_instance_id = self.identity
        message.planning_generation = 1
        message.execution_step_seq = self.cursor
        if self.cursor < len(self.transitions):
            source, _, action, _ = self.transitions[self.cursor]
            message.possible_product_node_ids = [self.state_ids[source]]
            message.has_next_action = True
            message.next_action = action
        else:
            message.possible_product_node_ids = []
            message.has_next_action = False
            message.next_action = ""
        self.observation_pub.publish(message)
        if message.has_next_action:
            self.command_pub.publish(self.String(data=message.next_action))
            _event(self.events, "command_published", action=message.next_action)
        _event(self.events, "observation_published", step=self.cursor, action=message.next_action)

    def _state(self, message) -> None:
        """Advance only on expected observed TS state, never on backend completion."""
        observed = tuple(message.ts_state.states)
        _event(self.events, "ts_state_received", state=list(observed), step=self.cursor)
        if self.snapshot is None or self.cursor >= len(self.transitions):
            _event(self.events, "late_state_ignored", state=list(observed))
            return
        _, target, _, _ = self.transitions[self.cursor]
        if observed == target[0]:
            self.cursor += 1
            self._publish_observation()
            return
        if self.cursor and observed == self.transitions[self.cursor - 1][1][0]:
            _event(self.events, "duplicate_ts_ignored", state=list(observed))
            return
        _event(
            self.events,
            "unexpected_ts_state",
            expected=list(target[0]),
            state=list(observed),
        )

    def run(self, seconds: float) -> None:
        """Spin until the bounded smoke window ends."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.done and self.snapshot is not None and self.cursor >= len(self.transitions):
                break
            if self.done and self.snapshot is None and self._grace_deadline is not None:
                if time.monotonic() >= self._grace_deadline:
                    break
            self.executor.spin_once(timeout_sec=0.05)
        artifact = {"pid": os.getpid(), "events": self.events}
        (self.work_dir / "server_events.json").write_text(
            json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
        )
        self.node.destroy_node()
        self.executor.shutdown()


class _Driver:
    """Run the existing execution node and one CMR transport request."""

    def __init__(self, request: dict[str, Any], work_dir: Path):
        import rclpy
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
        from std_msgs.msg import String
        from ltl_automaton_msgs.msg import PlanningExecutionObservation
        from ltl_automaton_msgs.msg import TransitionSystemStateStamped
        from ltl_automaton_execution.execution_node import ExecutionManagerNode
        from ltl_automaton_execution.fake_runtime import FakeBackend, FakePlant
        from ltl_automaton_execution.fake_runtime import FakeStateAbstraction, FakeStateObserver
        from ltl_automaton_execution.models import ExecutionCompletion

        self.rclpy = rclpy
        self.String = String
        self.PlanningExecutionObservation = PlanningExecutionObservation
        self.TransitionSystemStateStamped = TransitionSystemStateStamped
        self.ExecutionCompletion = ExecutionCompletion
        self.module_paths = {
            "execution_node": inspect.getfile(ExecutionManagerNode),
            "fake_runtime": inspect.getfile(FakeBackend),
            "execution_models": inspect.getfile(ExecutionCompletion),
        }
        self.module_sha256 = {
            name: _sha256(Path(path).resolve())
            for name, path in self.module_paths.items()
        }
        self.module_resolved_paths = {
            name: str(Path(path).resolve())
            for name, path in self.module_paths.items()
        }
        repo_root = Path(__file__).resolve().parents[2]
        expected_paths = {
            "execution_node": repo_root / "ltl_automaton_execution"
            / "ltl_automaton_execution" / "execution_node.py",
            "fake_runtime": repo_root / "ltl_automaton_execution"
            / "ltl_automaton_execution" / "fake_runtime.py",
            "execution_models": repo_root / "ltl_automaton_execution"
            / "ltl_automaton_execution" / "models.py",
        }
        self.module_identity_match = all(
            Path(self.module_paths[name]).resolve() == path.resolve()
            and self.module_sha256[name] == _sha256(path)
            for name, path in expected_paths.items()
        )
        self.events: list[dict[str, Any]] = []
        self.request = request
        self.work_dir = work_dir
        self.result = None
        self.ts_states: list[tuple[str, ...]] = []
        self.observer_states: list[tuple[str, ...]] = []
        self.abstraction_states: list[tuple[str, ...]] = []
        self.commands: list[str] = []
        self.expected_actions: list[str] | None = None
        self.expected_sources: list[tuple[str, ...]] | None = None
        self.expected_targets: list[tuple[str, ...]] | None = None
        self.done = False
        self._wrong_generation_sent = False
        self.node = rclpy.create_node("cmr_smoke_driver")
        self.plant = FakePlant()
        self.backend = None
        holder: dict[str, Any] = {}

        class RecordingBackend(FakeBackend):
            def execute(inner, step, completion):
                _event(
                    self.events,
                    "dispatch",
                    execution_step_seq=step.execution_step_seq,
                    action=step.action,
                    source_state=list(step.source_state.states),
                    target_state=list(step.target_state.states),
                    source_product_node_ids=list(step.source_product_node_ids),
                    target_product_node_ids=list(step.target_product_node_ids),
                )
                if (
                    step.execution_step_seq == 0
                    and not self._wrong_generation_sent
                ):
                    wrong = self.PlanningExecutionObservation()
                    wrong.planner_instance_id = step.planner_instance_id
                    wrong.planning_generation = 0
                    wrong.execution_step_seq = step.execution_step_seq
                    wrong.possible_product_node_ids = list(
                        step.source_product_node_ids
                    )
                    wrong.has_next_action = True
                    wrong.next_action = step.action
                    self.wrong_obs_pub.publish(wrong)
                    self._wrong_generation_sent = True
                    _event(
                        self.events,
                        "wrong_generation_published",
                        generation=0,
                        invalid_generation=True,
                        accepted_generation=step.planning_generation,
                        execution_step_seq=step.execution_step_seq,
                        action=step.action,
                    )

                def wrapped(value):
                    _event(
                        self.events,
                        "backend_completion",
                        success=value.success,
                        execution_step_seq=step.execution_step_seq,
                        action=step.action,
                        source_state=list(step.source_state.states),
                        target_state=list(step.target_state.states),
                        source_product_node_ids=list(step.source_product_node_ids),
                        target_product_node_ids=list(step.target_product_node_ids),
                    )
                    completion(value)

                return super(RecordingBackend, inner).execute(step, wrapped)

        class RecordingObserver(FakeStateObserver):
            def start(inner, on_observation):
                def observed(value):
                    state = tuple(value.state.states)
                    self.observer_states.append(state)
                    _event(self.events, "observer_feedback", state=list(state))
                    on_observation(value)

                return super(RecordingObserver, inner).start(observed)

        class RecordingAbstraction(FakeStateAbstraction):
            def abstract(inner, observation):
                value = super(RecordingAbstraction, inner).abstract(observation)
                if value is not None:
                    state = tuple(value.states)
                    self.abstraction_states.append(state)
                    _event(
                        self.events,
                        "abstraction_feedback",
                        state=list(state),
                    )
                return value

        self.backend = RecordingBackend(
            self.plant,
            lambda delay, callback: holder["execution"]._schedule(
                delay, callback
            ),
            0.01,
        )
        self.execution = ExecutionManagerNode(
            backend=self.backend,
            fake_plant=self.plant,
            state_observer=RecordingObserver(self.plant),
            state_abstraction=RecordingAbstraction(),
            execution_delay_sec=0.01,
        )
        holder["execution"] = self.execution
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE)
        command_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.request_pub = self.node.create_publisher(String, REQUEST_TOPIC, qos)
        self.late_state_pub = self.node.create_publisher(
            TransitionSystemStateStamped, TS_TOPIC, qos
        )
        self.wrong_obs_pub = self.node.create_publisher(
            PlanningExecutionObservation, OBSERVATION_TOPIC, command_qos
        )
        self.node.create_subscription(String, RESULT_TOPIC, self._result, command_qos)
        self.node.create_subscription(
            PlanningExecutionObservation, OBSERVATION_TOPIC, self._observation, command_qos
        )
        self.node.create_subscription(
            TransitionSystemStateStamped, TS_TOPIC, self._state, 10
        )
        self.node.create_subscription(String, COMMAND_TOPIC, self._command, command_qos)
        self.executor = MultiThreadedExecutor(num_threads=4)
        self.executor.add_node(self.node)
        self.executor.add_node(self.execution)
        _event(
            self.events,
            "driver_ready",
            pid=os.getpid(),
            execution_module=inspect.getfile(ExecutionManagerNode),
        )

    def _result(self, message) -> None:
        self.result = json.loads(message.data)
        _event(self.events, "result_received", status=self.result.get("terminal_status"))
        lasso = self.result.get("concrete_lasso")
        if isinstance(lasso, dict):
            edges = [
                edge
                for name in ("prefix_edges", "suffix_edges")
                for edge in lasso.get(name, [])
            ]
            self.expected_actions = [edge["action"] for edge in edges]
            self.expected_sources = [_ts_values(edge["source"]) for edge in edges]
            self.expected_targets = [_ts_values(edge["target"]) for edge in edges]
        if self.result.get("terminal_status") != "OPTIMALITY_CERTIFIED":
            if self.result.get("terminal_status") == "TIMEOUT":
                late = self.TransitionSystemStateStamped()
                late.ts_state.state_dimension_names = ["factor0", "factor1"]
                late.ts_state.states = ["0", "0"]
                self.late_state_pub.publish(late)
                _event(self.events, "late_state_published")
            self.done = True

    def _observation(self, message) -> None:
        _event(
            self.events,
            "observation_received",
            generation=message.planning_generation,
            step=message.execution_step_seq,
            has_next_action=message.has_next_action,
            action=message.next_action,
        )
        if not message.has_next_action:
            self.done = True

    def _state(self, message) -> None:
        state = tuple(message.ts_state.states)
        self.ts_states.append(state)
        _event(self.events, "ts_state_received", state=list(state))

    def _command(self, message) -> None:
        self.commands.append(message.data)
        _event(self.events, "command_received", action=message.data)

    def run(self, seconds: float) -> None:
        """Wait for discovery, publish exactly one request, and collect events."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and self.request_pub.get_subscription_count() < 1:
            self.executor.spin_once(timeout_sec=0.05)
        if self.request_pub.get_subscription_count() < 1:
            _event(self.events, "request_not_discovered")
        else:
            payload = json.dumps(self.request, sort_keys=True, separators=(",", ":"))
            self.request_pub.publish(self.String(data=payload))
            _event(self.events, "request_published", request_id=self.request["request_id"])
        while time.monotonic() < deadline and not self.done:
            self.executor.spin_once(timeout_sec=0.05)
        if self.done:
            drain_deadline = time.monotonic() + 0.2
            while time.monotonic() < drain_deadline:
                self.executor.spin_once(timeout_sec=0.02)
        artifact = {
            "pid": os.getpid(),
            "events": self.events,
            "commands": self.commands,
            "observed_ts_states": [list(item) for item in self.ts_states],
            "result": self.result,
            "expected_actions": self.expected_actions,
            "expected_sources": (
                None
                if self.expected_sources is None
                else [list(state) for state in self.expected_sources]
            ),
            "expected_targets": (
                None
                if self.expected_targets is None
                else [list(state) for state in self.expected_targets]
            ),
            "commands_match": (
                None
                if self.expected_actions is None
                else self.commands == self.expected_actions
            ),
            "completion_count": sum(
                event["event"] == "backend_completion"
                for event in self.events
            ),
            "observer_feedback_count": len(self.observer_states),
            "abstraction_feedback_count": len(self.abstraction_states),
            "ts_state_receive_count": len(self.ts_states),
            "observer_feedback_states": [
                list(item) for item in self.observer_states
            ],
            "abstraction_feedback_states": [
                list(item) for item in self.abstraction_states
            ],
            "module_paths": self.module_paths,
            "module_resolved_paths": self.module_resolved_paths,
            "module_sha256": self.module_sha256,
            "module_identity_match": self.module_identity_match,
        }
        if self.expected_actions is None:
            artifact["execution_counts_match"] = None
        else:
            artifact["execution_counts_match"] = (
                artifact["completion_count"] == len(self.expected_actions)
                and artifact["observer_feedback_count"] == len(self.expected_actions)
                and artifact["abstraction_feedback_count"] == len(self.expected_actions)
                and self.observer_states == self.expected_targets
                and self.abstraction_states == self.expected_targets
                and self.ts_states == self.expected_targets
            )
        (self.work_dir / "driver_events.json").write_text(
            json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
        )
        self.execution.destroy_node()
        self.node.destroy_node()
        self.executor.shutdown()


def _child(
    role: str,
    request_path: Path,
    work_dir: Path,
    seconds: float,
    binding: str | None = None,
    kernel_root: str | None = None,
) -> int:
    """Run one child role; subprocess boundaries provide DDS isolation."""
    request = json.loads(request_path.read_text(encoding="utf-8"))
    import rclpy

    rclpy.init()
    try:
        worker = (
            _Server(request, binding, kernel_root, work_dir)
            if role == "server"
            else _Driver(request, work_dir)
        )
        worker.run(seconds)
        return 0
    except Exception as error:
        details = traceback.format_exc()
        (work_dir / f"{role}_error.txt").write_text(
            details, encoding="utf-8"
        )
        sys.stderr.write(details)
        return 1
    finally:
        rclpy.shutdown()


def _event_count(events: list[dict[str, Any]], name: str) -> int:
    """Count one named event in a child artifact."""
    return sum(event.get("event") == name for event in events)


def _require(condition: bool, message: str) -> None:
    """Raise a strict smoke assertion without converting failure to success."""
    if not condition:
        raise AssertionError(message)


def _validate_case(request: dict[str, Any], artifact: dict[str, Any]) -> None:
    """Validate one case's request/result, transport order, and execution loop."""
    driver = artifact.get("driver", {})
    server = artifact.get("server", {})
    result = driver.get("result")
    _require(artifact.get("server_rc") == 0, "server child failed")
    _require(artifact.get("driver_rc") == 0, "driver child failed")
    _require(
        isinstance(artifact.get("server_pid"), int)
        and isinstance(artifact.get("driver_pid"), int),
        "child PID missing",
    )
    _require(artifact.get("server_pid") != artifact.get("driver_pid"), "PID collision")
    _require(isinstance(result, dict), "result was not received")
    _require(result.get("schema") == SCHEMA, "result schema mismatch")
    _require(result.get("population") == "SYNTHETIC_SMOKE", "population mismatch")
    _require(result.get("request_id") == request["request_id"], "result request mismatch")
    _require(result.get("method") == request["method"], "result method mismatch")
    _require(result.get("variant") == request["variant"], "result variant mismatch")
    server_events = server.get("events", [])
    driver_events = driver.get("events", [])
    names = [event.get("event") for event in server_events]
    required = [
        "request_received", "cmr_solver_started", "cmr_solver_completed",
        "result_published",
    ]
    _require(
        all(_event_count(server_events, name) == 1 for name in required),
        "server event count mismatch",
    )
    received = next(
        event for event in server_events if event.get("event") == "request_received"
    )
    _require(
        received.get("request_id") == request["request_id"],
        "server request identity mismatch",
    )
    positions = [names.index(name) for name in required]
    _require(positions == sorted(positions), "server event order changed")
    times = [server_events[index]["time_ns"] for index in positions]
    _require(times == sorted(times), "server event time order changed")
    _require(_event_count(driver_events, "result_received") == 1, "result receive count")
    _require(_event_count(driver_events, "request_published") == 1, "request send count")
    _require(isinstance(result.get("worker_pid"), int), "worker PID missing")
    _require(result.get("worker_pid") not in {
        artifact.get("server_pid"), artifact.get("driver_pid")
    }, "worker PID is not independent")
    _require(driver.get("module_identity_match") is True, "overlay module mismatch")

    if request["variant"] == "cost_gap":
        _require(result.get("terminal_status") == "OPTIMALITY_CERTIFIED", "cost gap status")
        _require(result.get("objective") == "30", "cost gap objective")
        _require(result.get("refinement_rounds") == 1, "cost gap refinement count")
        _require(len(result.get("rounds", [])) == 2, "cost gap round count")
        _require(
            _event_count(server_events, "snapshot_served") >= 1,
            "snapshot not served",
        )
        expected = driver.get("expected_actions") or []
        _require(
            expected and driver.get("commands_match") is True,
            "action sequence mismatch",
        )
        _require(driver.get("execution_counts_match") is True, "execution count mismatch")
        _require(
            driver.get("completion_count") == len(expected),
            "completion count mismatch",
        )
        _require(
            driver.get("observer_feedback_count") == len(expected),
            "feedback count mismatch",
        )
        _require(
            _event_count(driver_events, "dispatch") == len(expected),
            "dispatch count mismatch",
        )
        _require(
            _event_count(driver_events, "observer_feedback") == len(expected),
            "observer count mismatch",
        )
        _require(
            _event_count(driver_events, "abstraction_feedback") == len(expected),
            "abstraction count mismatch",
        )
        _require(
            _event_count(driver_events, "wrong_generation_published") == 1,
            "wrong generation missing",
        )
        dispatch_positions = [
            index for index, event in enumerate(driver_events)
            if event.get("event") == "dispatch"
        ]
        wrong_events = [
            event for event in driver_events
            if event.get("event") == "wrong_generation_published"
        ]
        _require(
            dispatch_positions and dispatch_positions[0] < driver_events.index(
                wrong_events[0]
            ),
            "wrong generation preceded real dispatch",
        )
        _require(
            wrong_events[0].get("generation") == 0
            and wrong_events[0].get("invalid_generation") is True
            and wrong_events[0].get("accepted_generation") == 1,
            "wrong generation identity mismatch",
        )
        _require(
            driver.get("expected_targets") == driver.get("observer_feedback_states"),
            "observer targets mismatch",
        )
        _require(
            driver.get("expected_targets") == driver.get("abstraction_feedback_states"),
            "abstraction targets mismatch",
        )
        _require(
            driver.get("expected_targets") == driver.get("observed_ts_states"),
            "TS feedback targets mismatch",
        )
        dispatches = [
            event for event in driver_events if event.get("event") == "dispatch"
        ]
        observers = [
            event for event in driver_events
            if event.get("event") == "observer_feedback"
        ]
        abstractions = [
            event for event in driver_events
            if event.get("event") == "abstraction_feedback"
        ]
        completions = [
            event for event in driver_events
            if event.get("event") == "backend_completion"
        ]
        expected_targets = driver.get("expected_targets")
        _require(
            [event.get("action") for event in dispatches] == expected,
            "dispatch action mismatch",
        )
        _require(
            [event.get("execution_step_seq") for event in dispatches]
            == list(range(len(expected))),
            "dispatch step mismatch",
        )
        _require(
            [event.get("source_state") for event in dispatches]
            == driver.get("expected_sources"),
            "dispatch source mismatch",
        )
        _require(
            [event.get("target_state") for event in dispatches] == expected_targets,
            "dispatch target mismatch",
        )
        _require(
            [event.get("state") for event in observers] == expected_targets,
            "observer state mismatch",
        )
        _require(
            [event.get("state") for event in abstractions] == expected_targets,
            "abstraction state mismatch",
        )
        _require(
            all(event.get("success") is True for event in completions),
            "backend completion failed",
        )
        _require(
            [event.get("action") for event in completions] == expected,
            "completion action mismatch",
        )
        _require(
            [event.get("execution_step_seq") for event in completions]
            == list(range(len(expected))),
            "completion step mismatch",
        )
        _require(
            [event.get("source_state") for event in completions]
            == driver.get("expected_sources"),
            "completion source mismatch",
        )
        _require(
            [event.get("target_state") for event in completions] == expected_targets,
            "completion target mismatch",
        )
        observer_positions = [
            index for index, event in enumerate(driver_events)
            if event.get("event") == "observer_feedback"
        ]
        abstraction_positions = [
            index for index, event in enumerate(driver_events)
            if event.get("event") == "abstraction_feedback"
        ]
        _require(
            all(
                dispatch < observer < abstraction
                for dispatch, observer, abstraction in zip(
                    dispatch_positions, observer_positions, abstraction_positions
                )
            ),
            "dispatch/observer/abstraction order mismatch",
        )
        terminal = [
            event for event in driver_events
            if event.get("event") == "observation_received"
            and not event.get("has_next_action")
        ]
        _require(
            terminal and terminal[-1].get("step") == len(expected),
            "terminal step mismatch",
        )
    elif request["variant"] == "spurious":
        _require(result.get("terminal_status") == "INFEASIBLE_CERTIFIED", "spurious status")
        _require(result.get("refinement_rounds") == 1, "spurious refinement count")
        _require(len(result.get("rounds", [])) == 2, "spurious round count")
        _require(not driver.get("commands"), "spurious command executed")
        _require(_event_count(driver_events, "dispatch") == 0, "spurious dispatch observed")
        _require(driver.get("completion_count") == 0, "spurious completion observed")
        _require(driver.get("observer_feedback_count") == 0, "spurious observer feedback")
        _require(driver.get("abstraction_feedback_count") == 0, "spurious abstraction feedback")
    else:
        _require(result.get("terminal_status") == "TIMEOUT", "timeout status")
        _require(result.get("right_censored") is True, "timeout censoring")
        _require(result.get("objective") is None, "timeout objective")
        _require(not driver.get("commands"), "timeout command executed")
        _require(_event_count(driver_events, "dispatch") == 0, "timeout dispatch observed")
        _require(driver.get("completion_count") == 0, "timeout completion observed")
        _require(driver.get("observer_feedback_count") == 0, "timeout observer feedback")
        _require(driver.get("abstraction_feedback_count") == 0, "timeout abstraction feedback")
        _require(driver.get("ts_state_receive_count") == 1, "timeout TS receive count")
        _require(
            driver.get("observed_ts_states") == [["0", "0"]],
            "timeout late TS state missing",
        )
        _require(_event_count(driver_events, "late_state_published") == 1, "late state missing")
        _require(_event_count(server_events, "late_state_ignored") == 1, "late state advanced")


def _run_case(
    request: dict[str, Any], binding: str, kernel_root: str, work_dir: Path
) -> dict[str, Any]:
    """Run one request/result transport attempt in a fresh domain."""
    work_dir.mkdir(parents=True, exist_ok=False)
    request_path = work_dir / "request.json"
    request_path.write_text(
        json.dumps(request, indent=2, sort_keys=True), encoding="utf-8"
    )
    try:
        domain_id = DOMAIN_IDS[request["request_id"]]
    except KeyError as error:
        raise ValueError("DDS smoke request lacks a fixed domain mapping") from error
    seconds = max(15.0, float(request["outer_watchdog_seconds"]))
    env = os.environ.copy()
    env.update({
        "ROS_DOMAIN_ID": str(domain_id),
        "ROS_LOCALHOST_ONLY": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    command = [sys.executable, "-B", str(Path(__file__).resolve())]
    server_stdout = (work_dir / "server.stdout").open("w", encoding="utf-8")
    server_stderr = (work_dir / "server.stderr").open("w", encoding="utf-8")
    driver_stdout = (work_dir / "driver.stdout").open("w", encoding="utf-8")
    driver_stderr = (work_dir / "driver.stderr").open("w", encoding="utf-8")
    server = None
    driver = None
    try:
        server = subprocess.Popen(
            command + [
                "--role", "server", "--request", str(request_path),
                "--work-dir", str(work_dir), "--seconds", str(seconds),
                "--binding", binding, "--kernel-root", kernel_root,
            ],
            env=env, stdout=server_stdout, stderr=server_stderr,
        )
        driver = subprocess.Popen(
            command + [
                "--role", "driver", "--request", str(request_path),
                "--work-dir", str(work_dir), "--seconds", str(seconds),
            ],
            env=env, stdout=driver_stdout, stderr=driver_stderr,
        )
        driver.wait(timeout=seconds + 2.0)
        server.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        if driver is not None and driver.poll() is None:
            driver.kill()
            driver.wait(timeout=3.0)
        if server is not None and server.poll() is None:
            server.terminate()
            server.wait(timeout=3.0)
    finally:
        for process in (driver, server):
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=3.0)
        for stream in (
            server_stdout, server_stderr, driver_stdout, driver_stderr
        ):
            stream.close()
    server_rc_path = work_dir / "server.rc"
    driver_rc_path = work_dir / "driver.rc"
    server_rc_path.write_text(str(server.returncode), encoding="utf-8")
    driver_rc_path.write_text(str(driver.returncode), encoding="utf-8")
    driver_path = work_dir / "driver_events.json"
    server_path = work_dir / "server_events.json"
    artifact = {
        "schema": "cmr-ros2-dds-smoke-v1",
        "domain_id": domain_id,
        "domain_mapping": DOMAIN_IDS,
        "ros_localhost_only": True,
        "request_topic": REQUEST_TOPIC,
        "result_topic": RESULT_TOPIC,
        "observation_topic": OBSERVATION_TOPIC,
        "snapshot_service": SNAPSHOT_SERVICE,
        "ts_topic": TS_TOPIC,
        "command_topic": COMMAND_TOPIC,
        "request": request,
        "server_pid": server.pid,
        "driver_pid": driver.pid,
        "server_rc": server.returncode,
        "driver_rc": driver.returncode,
        "server_rc_file": str(server_rc_path),
        "driver_rc_file": str(driver_rc_path),
        "driver": (
            json.loads(driver_path.read_text(encoding="utf-8"))
            if driver_path.exists() else {}
        ),
        "server": (
            json.loads(server_path.read_text(encoding="utf-8"))
            if server_path.exists() else {}
        ),
        "dds_smoke_module": str(Path(__file__).resolve()),
    }
    (work_dir / "dds_artifact.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
    )
    return artifact


def run_dds_smoke(binding: str, kernel_root: str, work_dir: Path) -> dict[str, Any]:
    """Run the three fixed CMR requests in separate isolated DDS attempts."""
    requests = (
        {
            "request_id": "cmr-cost-gap-apd",
            "method": "AP-D",
            "variant": "cost_gap",
            "planner_budget_seconds": 10,
            "outer_watchdog_seconds": 12,
        },
        {
            "request_id": "cmr-spurious-apd",
            "method": "AP-D",
            "variant": "spurious",
            "planner_budget_seconds": 10,
            "outer_watchdog_seconds": 12,
        },
        {
            "request_id": "cmr-base-full-timeout",
            "method": "FULL",
            "variant": "base",
            "planner_budget_seconds": 0,
            "outer_watchdog_seconds": 2,
        },
    )
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    report = {"schema": "cmr-ros2-dds-report-v1", "status": "RUNNING", "cases": cases}

    def write_report() -> None:
        (root / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )

    write_report()
    try:
        for request in requests:
            case_dir = root / request["request_id"]
            try:
                artifact = _run_case(request, binding, kernel_root, case_dir)
            except Exception as error:
                cases.append({
                    "request_id": request["request_id"],
                    "artifact": str(case_dir / "dds_artifact.json"),
                    "status": "FAILED",
                    "error": repr(error),
                })
                report["status"] = "FAILED"
                report["error"] = repr(error)
                write_report()
                raise
            case = {
                "request_id": request["request_id"],
                "artifact": str(case_dir / "dds_artifact.json"),
                "server_rc": artifact["server_rc"],
                "driver_rc": artifact["driver_rc"],
                "result": artifact["driver"].get("result"),
                "status": "RUNNING",
            }
            cases.append(case)
            write_report()
            try:
                _validate_case(request, artifact)
            except Exception as error:
                case["status"] = "FAILED"
                case["error"] = repr(error)
                artifact["validation_status"] = "FAILED"
                artifact["validation_error"] = repr(error)
                (case_dir / "dds_artifact.json").write_text(
                    json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
                )
                report["status"] = "FAILED"
                report["error"] = repr(error)
                write_report()
                raise
            case["status"] = "PASSED"
            artifact["validation_status"] = "PASSED"
            (case_dir / "dds_artifact.json").write_text(
                json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
            )
            write_report()
    except Exception as error:
        if report.get("status") != "FAILED":
            report["status"] = "FAILED"
            report["error"] = repr(error)
            write_report()
        raise
    report["status"] = "PASSED"
    write_report()
    return report


def main() -> int:
    """Run one internal server or driver child."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("server", "driver"), required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--binding")
    parser.add_argument("--kernel-root")
    args = parser.parse_args()
    return _child(
        args.role,
        args.request,
        args.work_dir,
        args.seconds,
        args.binding,
        args.kernel_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
