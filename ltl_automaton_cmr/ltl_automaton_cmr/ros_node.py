"""Isolated ROS 2 boundary for the frozen Office8 CMR experiment.

Only exact-certified concrete occurrences receive execution authority. Service
planning is synchronous: run separately from time-sensitive robot nodes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from ltl_automaton_execution.models import SymbolicState
from ltl_automaton_msgs.msg import (
    PlanningExecutionObservation, PlanningGraphSnapshot,
    TransitionSystemStateStamped,
)
from ltl_automaton_msgs.srv import GetPlanningGraphSnapshot, TaskPlanning
from .engine import CertificationError, plan
from .execution_adapter import (
    CapabilityError, ExecutionCursor, build_execution_snapshot, to_ros_snapshot,
)
from .office import ASSET_SHA256, OFFICE8_QUERY_IDS, SOURCE_COMMIT, load_office_query

COMMAND_QOS = QoSProfile(
    depth=1, reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)
ROUND_QOS = QoSProfile(
    depth=100, reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)


def normalize_office_feedback(state_message, query):
    """Validate the entire named state before canonicalizing any dimension."""
    names = tuple(state_message.state_dimension_names)
    values = tuple(state_message.states)
    if (not names or len(names) != len(values)
            or any(type(name) is not str or not name.strip() for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("TS feedback dimensions must be nonempty, unique and aligned.")
    mapping = dict(zip(names, values))
    if set(mapping) != set(query.dimension_names):
        raise ValueError("TS feedback must name all Office dimensions exactly.")
    canonical = []
    for name, domain in zip(query.dimension_names, query.value_names):
        value = mapping[name]
        if type(value) is not str or value not in domain:
            raise ValueError(f"TS feedback value is outside the domain of {name}.")
        canonical.append(value)
    return dict(zip(query.dimension_names, canonical)), SymbolicState(
        tuple(query.dimension_names), tuple(canonical))


def feedback_stamp_ns(message):
    """Use ROS feedback evidence, never command or completion timestamps."""
    sec = message.header.stamp.sec
    nanosec = message.header.stamp.nanosec
    if type(sec) is not int or type(nanosec) is not int or sec < 0 or not 0 <= nanosec < 10**9:
        raise ValueError("TS feedback requires a valid nonnegative ROS timestamp.")
    return sec * 10**9 + nanosec


def resolve_office_query(hard_task, formula_to_query):
    """Accept a manifest ID or exact frozen formula, without LTL rewriting."""
    text = hard_task.strip()
    if text in OFFICE8_QUERY_IDS:
        return text
    if text in formula_to_query:
        return formula_to_query[text]
    raise ValueError("Only Office8 D1..D8 IDs or their exact frozen hard formulas are supported.")


class CMRPlannerNode(Node):
    """Explicit planning and feedback authority, isolated from the old planner."""

    def __init__(self, **kwargs):
        kwargs.setdefault("namespace", "/cmr")
        super().__init__("cmr_planner", **kwargs)
        descriptor = ParameterDescriptor(read_only=True)
        for name, default in (
            ("arm", "AP"), ("query_id", "D2"), ("family_prior_json", ""),
            ("initial_state_json", ""), ("records_directory", ""),
        ):
            self.declare_parameter(name, default, descriptor=descriptor)
        self._arm = self.get_parameter("arm").value.upper()
        if self._arm not in {"FULL", "AP", "FAMILY"}:
            raise ValueError("arm must be FULL, AP or FAMILY.")
        query_id = self.get_parameter("query_id").value
        initial_text = self.get_parameter("initial_state_json").value
        initial = json.loads(initial_text) if initial_text else None
        self._query = load_office_query(query_id, initial_state=initial)
        self._state_mapping = self._query.initial_named_state
        prior_text = self.get_parameter("family_prior_json").value
        self._family_prior = None
        if prior_text:
            prior = json.loads(prior_text)
            if (not isinstance(prior, list)
                    or any(type(item) is not int for item in prior)
                    or len(set(prior)) != len(prior)
                    or not set(prior) <= set(self._query.model.dimensions)):
                raise ValueError("family_prior_json must be unique integer dimension IDs.")
            self._family_prior = frozenset(prior)
        self._records_directory = self.get_parameter("records_directory").value
        self._formula_to_query = {
            load_office_query(identifier).hard_task: identifier
            for identifier in OFFICE8_QUERY_IDS
        }
        self._instance_id = "cmr-" + str(uuid.uuid4())
        self._generation = 0
        self._request_seq = 0
        self._execution_step_seq = 0
        self._feedback_stamp = None
        self._cursor = None
        self._ros_snapshot = None
        self._unavailable_reason = "No explicit planning request has been certified."
        self._last_exact_record = None
        self.observation_publisher = self.create_publisher(
            PlanningExecutionObservation, "planning_execution_observation", COMMAND_QOS)
        self.next_move_publisher = self.create_publisher(String, "next_move_cmd", COMMAND_QOS)
        self.result_publisher = self.create_publisher(String, "cmr_plan_result", COMMAND_QOS)
        self.round_publisher = self.create_publisher(String, "cmr_round_log", ROUND_QOS)
        self.planning_service = self.create_service(
            TaskPlanning, "replanning", self._planning_callback)
        self.snapshot_service = self.create_service(
            GetPlanningGraphSnapshot, "get_planning_graph_snapshot", self._snapshot_callback)
        self.state_subscription = self.create_subscription(
            TransitionSystemStateStamped, "ts_state", self._state_callback, 10)
        self._publish_authority()
        self.get_logger().info(
            f"Office8 CMR ready in {self.get_namespace()}, arm={self._arm}; "
            "waiting for an explicit replanning request.")

    def _publish_authority(self):
        if self._cursor is None:
            message = PlanningExecutionObservation(
                planner_instance_id=self._instance_id, planning_generation=self._generation,
                execution_step_seq=self._execution_step_seq, possible_product_node_ids=[],
                has_next_action=False, next_action="")
        else:
            observation = self._cursor.observation()
            self._execution_step_seq = observation.execution_step_seq
            message = PlanningExecutionObservation(
                planner_instance_id=observation.planner_instance_id,
                planning_generation=observation.planning_generation,
                execution_step_seq=observation.execution_step_seq,
                possible_product_node_ids=list(observation.possible_product_node_ids),
                has_next_action=observation.has_next_action,
                next_action=observation.next_action)
        self.observation_publisher.publish(message)
        # Structured observation is authoritative. Empty legacy String clears
        # a retained command; String has no generation or step identity.
        self.next_move_publisher.publish(String(data=message.next_action))

    def _revoke(self, reason):
        self._cursor = None
        self._ros_snapshot = None
        self._unavailable_reason = reason
        self._publish_authority()

    def _publish_record(self, record):
        record = dict(record)
        record.setdefault("schema", "ltl-automaton-cmr-plan-v1")
        record.setdefault("execution_available", False)
        record.update(planner_instance_id=self._instance_id, request_seq=self._request_seq,
                      planning_generation=self._generation)
        self._last_exact_record = record
        self.result_publisher.publish(String(data=json.dumps(record, sort_keys=True)))
        for row in record.get("rounds", ()):
            self.round_publisher.publish(String(data=json.dumps({
                "schema": "ltl-automaton-cmr-round-v1", "query_id": record.get("query_id"),
                "planner_instance_id": self._instance_id, "request_seq": self._request_seq,
                "planning_generation": self._generation, **row,
            }, sort_keys=True)))
        if self._records_directory:
            try:
                directory = Path(self._records_directory)
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / f"{self._instance_id}-{self._request_seq:06d}.json"
                with path.open("x", encoding="utf-8") as stream:
                    json.dump(record, stream, sort_keys=True, indent=2)
                    stream.write("\n")
            except OSError as error:
                self.get_logger().error(f"Could not persist CMR record: {error}")

    def _planning_callback(self, request, response):
        self._request_seq += 1
        # Revoke before blocking search: unsuccessful replacement cannot execute
        # the old plan. Only complete certification and conversion can commit.
        self._revoke("Planning request pending.")
        query = None
        record = None
        try:
            if request.soft_task.strip():
                raise ValueError("CMR Office8 has no soft-task adapter; nonempty soft_task is unsupported.")
            query_id = resolve_office_query(request.hard_task, self._formula_to_query)
            query = load_office_query(query_id, initial_state=dict(self._state_mapping))
            prior = query.family_prior if self._family_prior is None else self._family_prior
            result = plan(query.model, arm=self._arm, family_prior=prior)
            record = result.to_dict()
            record.update(query_id=query.query_id, hard_task=query.hard_task,
                          dimensions=list(query.dimension_names),
                          initial_state=query.initial_named_state,
                          execution_available=False)
            if result.status != "OPTIMALITY_CERTIFIED":
                self._unavailable_reason = result.infeasibility_reason or result.status
                response.success = False
            else:
                fingerprint = hashlib.sha256(json.dumps({
                    "source_commit": SOURCE_COMMIT, "assets": ASSET_SHA256,
                    "query_id": query.query_id, "hard_task": query.hard_task,
                    "initial_state": query.initial_named_state,
                }, sort_keys=True).encode("utf-8")).hexdigest()
                generation = self._generation + 1
                snapshot = to_ros_snapshot(
                    result, query.model, query.dimension_names, query.value_names,
                    self._instance_id, generation, fingerprint, query.hard_task)
                execution = build_execution_snapshot(
                    result.lasso, query.dimension_names, query.value_names,
                    self._instance_id, generation)
                cursor = ExecutionCursor(execution, minimum_stamp=self._feedback_stamp)
                self._query = query
                self._generation = generation
                self._execution_step_seq = 0
                self._ros_snapshot = snapshot
                self._cursor = cursor
                self._unavailable_reason = ""
                record.update(execution_available=True, active_ts_sha256=fingerprint)
                response.success = True
        except CertificationError as error:
            record = error.to_dict()
            self._unavailable_reason = str(error)
            response.success = False
        except CapabilityError as error:
            if record is None:
                record = {"status": "ROS_CAPABILITY_LIMIT"}
            record.update(execution_available=False, capability_error=str(error))
            self._unavailable_reason = str(error)
            response.success = False
        except Exception as error:
            record = {"status": "REJECTED", "error": str(error), "rounds": [],
                      "execution_available": False}
            self._unavailable_reason = str(error)
            response.success = False
        if query is not None:
            record.setdefault("query_id", query.query_id)
            record.setdefault("hard_task", query.hard_task)
        if not response.success:
            self.get_logger().warning(self._unavailable_reason)
        self._publish_record(record)
        self._publish_authority()
        return response

    def _snapshot_callback(self, request, response):
        del request
        if self._ros_snapshot is not None:
            response.success = True
            response.message = "Certified retained concrete lasso occurrences."
            response.snapshot = deepcopy(self._ros_snapshot)
        else:
            response.success = False
            response.message = self._unavailable_reason
            snapshot = PlanningGraphSnapshot()
            snapshot.metadata.planner_instance_id = self._instance_id
            snapshot.metadata.planning_generation = self._generation
            snapshot.metadata.available = False
            snapshot.metadata.unavailable_reason = self._unavailable_reason
            response.snapshot = snapshot
        return response

    def _state_callback(self, message):
        try:
            stamp = feedback_stamp_ns(message)
            if self._feedback_stamp is not None and stamp <= self._feedback_stamp:
                return
            mapping, state = normalize_office_feedback(message.ts_state, self._query)
        except (ValueError, TypeError) as error:
            self._revoke(f"Invalid TS feedback: {error}")
            self.get_logger().warning(self._unavailable_reason)
            return
        # Invalid or stale data never partially updates the replan source.
        self._feedback_stamp = stamp
        self._state_mapping = mapping
        if self._cursor is None:
            return
        if not self._cursor.accept_feedback(state, stamp):
            self._revoke("Unexpected observed TS state; explicit replanning is required.")
            self.get_logger().warning(self._unavailable_reason)
            return
        self._publish_authority()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = CMRPlannerNode()
        rclpy.spin(node)
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()
