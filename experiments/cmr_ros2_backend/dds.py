"""Isolated DDS transport for the selected real CMR V6 backend cases.

The solver/qualification implementation lives in this directory's runner and
backend modules.  This file owns only the request/result transport and the
execution feedback checks; it does not provide a solver fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.cmr_ros2_integration import dds_smoke as transport


DOMAIN_ID = 219
SERVER_SECONDS = 205.0
TRANSPORT_SECONDS = 210.0
SCHEMA = transport.SCHEMA


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


def _descriptor(version_binding: str | Path) -> dict[str, str]:
    """Require the root-owned V6 descriptor; never substitute another backend."""
    module = importlib.import_module("experiments.cmr_ros2_backend.backends")
    value = module.describe(str(version_binding), "ros2-v6")
    if isinstance(value, Mapping):
        result = {name: value.get(name) for name in (
            "backend", "backend_id", "backend_sha256", "version_binding_id",
            "version_binding_sha256")}
    else:
        result = {name: getattr(value, name, None) for name in (
            "backend", "backend_id", "backend_sha256", "version_binding_id",
            "version_binding_sha256")}
    if any(not isinstance(value, str) or not value for value in result.values()):
        raise TypeError("V6 backend descriptor is incomplete")
    actual_binding_sha = _sha256(Path(version_binding).resolve())
    if result["version_binding_sha256"] != actual_binding_sha:
        raise ValueError("V6 version binding hash differs from descriptor")
    return result


def _event(events: list[dict[str, Any]], name: str, **fields: Any) -> None:
    events.append({"event": name, "time_ns": time.monotonic_ns(), **fields})


class V6Server(transport._Server):
    """Serve one exact request and one certified V6 execution snapshot."""

    def __init__(self, request, binding, kernel_root, work_dir,
                 version_binding, plan_path):
        super().__init__(request, binding, kernel_root, work_dir)
        self.version_binding = version_binding
        self.plan_path = plan_path
        self.identity = f"cmr-v6-{request['request_id']}"

    def _request(self, message) -> None:
        if self.done:
            return
        request = json.loads(message.data)
        _event(self.events, "request_received", request_id=request.get("request_id"),
               backend=request.get("backend"), backend_id=request.get("backend_id"),
               version_binding_id=request.get("version_binding_id"))
        if request != self.request:
            _event(self.events, "request_rejected", reason="request_mismatch")
            raise ValueError("DDS request differs from the frozen V6 envelope")
        self.done = True
        _event(self.events, "cmr_solver_started", backend_id=request["backend_id"])
        try:
            runner = importlib.import_module("experiments.cmr_ros2_backend.runner")
            plan = runner.load_plan(self.plan_path)
            cell = runner.make_request(
                plan, request["instance_id"], request["method"], request["backend"])
            if "request_id" in cell or "expected_terminal" in cell:
                raise ValueError("runner.make_request returned transport-only fields")
            expected_envelope = dict(cell, request_id=request["request_id"])
            if expected_envelope != request:
                raise ValueError("runner.make_request differs from DDS envelope")
            value = runner.run_isolated(
                cell, self.binding, self.kernel_root, self.version_binding,
                self.plan_path, self.work_dir / "cmr_attempt")
            row = value["row"]
            descriptor = value["backend_binding"]
            for key in ("backend_id", "backend_sha256", "version_binding_id",
                        "version_binding_sha256"):
                if descriptor.get(key) != request.get(key):
                    raise ValueError(f"runner backend identity differs for {key}")
            self.result = dict(row, schema=SCHEMA,
                               population=request["population"],
                               request_id=request["request_id"],
                               instance_id=request["instance_id"],
                               method=request["method"], backend=request["backend"],
                               variant="real", worker_pid=value["worker_pid"],
                               worker_exitcode=value["worker_exitcode"],
                               worker_alive_after_cleanup=value[
                                   "worker_alive_after_cleanup"],
                               backend_binding=descriptor)
            if value.get("transport") is not None:
                self.result.update(value["transport"])
            _event(self.events, "cmr_solver_completed",
                   status=row.get("terminal_status"),
                   backend_id=descriptor.get("backend_id"))
        except Exception as error:
            details = traceback.format_exc()
            descriptor = _descriptor(self.version_binding)
            self.result = {
                "schema": SCHEMA, "population": request["population"],
                "request_id": request["request_id"],
                "instance_id": request["instance_id"], "method": request["method"],
                "backend": request.get("backend"), "variant": "real",
                "terminal_status": "ERROR", "objective": None,
                "concrete_lasso": None, "error": repr(error),
                "backend_binding": descriptor, **descriptor,
                "certificate_valid_for_terminal": False,
                "certificate_verifier_status": "NOT_AVAILABLE",
                "right_censored": False,
            }
            (self.work_dir / "server_traceback.txt").write_text(details, encoding="utf-8")
            sys.stderr.write(details)
            _event(self.events, "cmr_solver_completed", status="ERROR")
        outgoing = json.dumps(self.result, sort_keys=True, separators=(",", ":"))
        self.result_pub.publish(self.String(data=outgoing))
        _event(self.events, "result_published",
               status=self.result.get("terminal_status"),
               backend_id=self.result.get("backend_binding", {}).get("backend_id"))
        if self.result.get("terminal_status") != "OPTIMALITY_CERTIFIED":
            self._grace_deadline = time.monotonic() + 0.5
            return
        self.snapshot, self.transitions, self.state_ids = transport._snapshot_messages(
            self.result, self.identity)
        self._publish_observation()


def _child(role: str, request_path: Path, work_dir: Path, seconds: float,
           binding: str | None = None, kernel_root: str | None = None,
           version_binding: str | None = None, plan_path: str | None = None) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    import rclpy

    rclpy.init()
    try:
        worker = (V6Server(request, binding, kernel_root, work_dir,
                           version_binding, plan_path)
                  if role == "server" else transport._Driver(request, work_dir))
        worker.run(seconds)
        return 0
    except Exception:
        details = traceback.format_exc()
        (work_dir / f"{role}_error.txt").write_text(details, encoding="utf-8")
        sys.stderr.write(details)
        return 1
    finally:
        rclpy.shutdown()


def _wait_processes(processes: Mapping[str, subprocess.Popen], deadline: float) -> None:
    """Wait in bounded chunks while retaining a single 210-second deadline."""
    while time.monotonic() < deadline and any(p.poll() is None for p in processes.values()):
        for process in processes.values():
            if process.poll() is None:
                remaining = max(0.0, deadline - time.monotonic())
                if not remaining:
                    break
                try:
                    process.wait(timeout=min(60.0, remaining))
                except subprocess.TimeoutExpired:
                    pass
                if time.monotonic() >= deadline:
                    break


def _run_case(request: dict[str, Any], args, case_dir: Path, descriptor: dict[str, str]) -> dict:
    case_dir.mkdir(parents=True, exist_ok=False)
    request_path = case_dir / "request.json"
    _write_json(request_path, request)
    env = dict(os.environ, ROS_DOMAIN_ID=str(DOMAIN_ID), ROS_LOCALHOST_ONLY="1",
               PYTHONDONTWRITEBYTECODE="1")
    processes = {}
    streams = []
    pending_error = None
    try:
        for role in ("server", "driver"):
            stdout = (case_dir / f"{role}.stdout").open("w", encoding="utf-8")
            stderr = (case_dir / f"{role}.stderr").open("w", encoding="utf-8")
            streams.extend((stdout, stderr))
            command = [sys.executable, "-B", str(Path(__file__).resolve()),
                       "--role", role, "--request", str(request_path),
                       "--work-dir", str(case_dir), "--seconds", str(SERVER_SECONDS),
                       "--binding", str(args.binding), "--kernel-root", str(args.kernel_root),
                       "--version-binding", str(args.version_binding),
                       "--plan", str(args.plan)]
            processes[role] = subprocess.Popen(command, env=env, stdout=stdout, stderr=stderr)
        _wait_processes(processes, time.monotonic() + TRANSPORT_SECONDS)
    except Exception as error:
        pending_error = error
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1.0)
        for stream in streams:
            stream.close()
        for role, process in processes.items():
            (case_dir / f"{role}.rc").write_text(
                str(process.returncode) + "\n", encoding="utf-8")
    if pending_error is not None:
        raise pending_error
    artifact = {
        "schema": "cmr-ros2-v6-dds-case-v1", "status": "RUNNING",
        "domain_id": DOMAIN_ID, "ros_localhost_only": True,
        "request_topic": transport.REQUEST_TOPIC, "result_topic": transport.RESULT_TOPIC,
        "observation_topic": transport.OBSERVATION_TOPIC,
        "snapshot_service": transport.SNAPSHOT_SERVICE, "ts_topic": transport.TS_TOPIC,
        "command_topic": transport.COMMAND_TOPIC, "request": request,
        "descriptor": descriptor,
        "server_pid": processes["server"].pid, "driver_pid": processes["driver"].pid,
        "server_rc": processes["server"].returncode,
        "driver_rc": processes["driver"].returncode,
        "server": json.loads((case_dir / "server_events.json").read_text())
        if (case_dir / "server_events.json").exists() else {},
        "driver": json.loads((case_dir / "driver_events.json").read_text())
        if (case_dir / "driver_events.json").exists() else {},
        "module": str(Path(__file__).resolve()),
    }
    _write_json(case_dir / "dds_artifact.json", artifact)
    return artifact


def _validate_case(
    case: dict[str, Any], artifact: dict[str, Any], descriptor: dict[str, str]
) -> None:
    request = case
    driver = artifact.get("driver", {})
    server = artifact.get("server", {})
    result = driver.get("result")
    if artifact.get("server_rc") != 0 or artifact.get("driver_rc") != 0:
        raise AssertionError("DDS child failure")
    server_pid = artifact.get("server_pid")
    driver_pid = artifact.get("driver_pid")
    worker_pid = result.get("worker_pid") if isinstance(result, dict) else None
    error_case = request["expected_terminal"] == "ERROR"
    pids = (server_pid, driver_pid) if error_case else (server_pid, driver_pid, worker_pid)
    if not all(isinstance(pid, int) and pid > 0 for pid in pids):
        raise AssertionError("server, driver, and worker PIDs are required")
    if len(set(pids)) != len(pids):
        raise AssertionError("server, driver, and worker PIDs must be distinct")
    if not isinstance(result, dict):
        raise AssertionError("DDS result missing")
    for name in ("schema", "request_id", "instance_id", "method", "backend"):
        expected = SCHEMA if name == "schema" else request[name]
        if result.get(name) != expected:
            raise AssertionError(f"result {name} mismatch")
    if result.get("population") != request["population"]:
        raise AssertionError("real population mismatch")
    if result.get("backend_binding") != descriptor:
        raise AssertionError("result backend identity mismatch")
    expected_exitcode = 23 if request["expected_terminal"] == "INFRASTRUCTURE_FAILURE" else 0
    if (not error_case and (result.get("worker_exitcode") != expected_exitcode
            or result.get("worker_alive_after_cleanup") is not False)):
        raise AssertionError("worker did not terminate cleanly")
    server_events = server.get("events", [])
    names = [event.get("event") for event in server_events]
    required = ["request_received", "cmr_solver_started", "cmr_solver_completed",
                "result_published"]
    if any(names.count(name) != 1 for name in required):
        raise AssertionError("server event count mismatch")
    positions = [names.index(name) for name in required]
    if positions != sorted(positions):
        raise AssertionError("server event order mismatch")
    received = server_events[positions[0]]
    if (received.get("request_id") != request["request_id"]
            or received.get("backend_id") != descriptor["backend_id"]
            or received.get("version_binding_id") != descriptor["version_binding_id"]):
        raise AssertionError("server request identity mismatch")
    if driver.get("module_identity_match") is not True:
        raise AssertionError("execution module identity mismatch")
    if request["expected_terminal"] == "OPTIMALITY_CERTIFIED":
        if result.get("terminal_status") != "OPTIMALITY_CERTIFIED":
            raise AssertionError("certified success status mismatch")
        if result.get("certificate_verifier_status") != "PASS":
            raise AssertionError("certificate verifier did not pass")
        if not isinstance(result.get("concrete_lasso"), dict):
            raise AssertionError("certified result lacks lasso")
        lasso = result["concrete_lasso"]
        prefix_edges = lasso.get("prefix_edges")
        suffix_edges = lasso.get("suffix_edges")
        if not isinstance(prefix_edges, list) or not isinstance(suffix_edges, list):
            raise AssertionError("certified lasso edge lists are required")
        if (not suffix_edges
                or suffix_edges[-1].get("target") != suffix_edges[0].get("source")):
            raise AssertionError("certified suffix is not one closed nonempty cycle")
        expected = driver.get("expected_actions") or []
        if not expected or driver.get("commands") != expected:
            raise AssertionError("success action sequence mismatch")
        if driver.get("execution_counts_match") is not True:
            raise AssertionError("success feedback counts mismatch")
        if not any(event.get("event") == "snapshot_served" for event in server_events):
            raise AssertionError("success snapshot was not served")
        dispatches = [event for event in driver.get("events", [])
                      if event.get("event") == "dispatch"]
        if [event.get("action") for event in dispatches] != expected:
            raise AssertionError("dispatch/action mismatch")
        if ([event.get("source_state") for event in dispatches]
                != driver.get("expected_sources")):
            raise AssertionError("dispatch source mismatch")
        if ([event.get("target_state") for event in dispatches]
                != driver.get("expected_targets")):
            raise AssertionError("dispatch target mismatch")
        if ([event.get("execution_step_seq") for event in dispatches]
                != list(range(len(expected)))):
            raise AssertionError("dispatch step sequence mismatch")
        # The unchanged driver intentionally publishes generation 0 after the
        # first accepted generation-1 dispatch. Require it to be ignored, as
        # in the original DDS qualification; reception is not acceptance.
        events = driver.get("events", [])
        wrong = [event for event in events
                 if event.get("event") == "wrong_generation_published"]
        if (len(wrong) != 1 or wrong[0].get("generation") != 0
                or wrong[0].get("accepted_generation") != 1
                or wrong[0].get("invalid_generation") is not True
                or events.index(dispatches[0]) >= events.index(wrong[0])):
            raise AssertionError("old-generation injection authority/order mismatch")
        received = [event for event in events
                    if event.get("event") == "observation_received"]
        stale = [event for event in received if event.get("generation") == 0]
        current = [event for event in received if event.get("generation") == 1]
        if (len(stale) != 1 or stale[0].get("step") != 0
                or len(received) != len(stale) + len(current)
                or [event.get("step") for event in current] != list(range(len(expected) + 1))):
            raise AssertionError("accepted observation progression or stale reception mismatch")
        if driver.get("ts_state_receive_count") != len(expected):
            raise AssertionError("TS feedback count mismatch")
        observations = [event for event in driver.get("events", [])
                        if event.get("event") == "observation_received"]
        if (not observations or observations[-1].get("has_next_action")
                or observations[-1].get("step") != len(expected)):
            raise AssertionError("final no-action observation mismatch")
    elif request["expected_terminal"] in ("INFEASIBLE_CERTIFIED", "TIMEOUT", "INFRASTRUCTURE_FAILURE", "ERROR"):
        if result.get("terminal_status") != request["expected_terminal"]:
            raise AssertionError("non-executable terminal status mismatch")
        if result.get("objective") is not None or result.get("concrete_lasso") is not None:
            raise AssertionError("infeasible result contains an executable payload")
        if (request["expected_terminal"] == "INFEASIBLE_CERTIFIED"
                and result.get("infeasibility_certificate_type") != "REDUCED_PRODUCT_EXACT_EMPTY"):
            raise AssertionError("infeasible proof type mismatch")
        if request["expected_terminal"] != "INFEASIBLE_CERTIFIED":
            if any(result.get(k) is not None for k in runner_proof_fields()):
                raise AssertionError("failure retained exact-empty proof claims")
            if result.get("certificate_valid_for_terminal") is not False:
                raise AssertionError("failure authorized a certificate")
            if result.get("right_censored") != (request["expected_terminal"] == "TIMEOUT"):
                raise AssertionError("failure censoring rule changed")
        if result.get("certificate_verifier_status") != "NOT_AVAILABLE":
            raise AssertionError("infeasible certificate status changed")
        if result.get("transport") is not None:
            raise AssertionError("infeasible result contains transport payload")
        if driver.get("commands") or driver.get("completion_count") != 0:
            raise AssertionError("infeasible case dispatched execution")
        if (driver.get("observer_feedback_count") != 0
                or driver.get("abstraction_feedback_count") != 0):
            raise AssertionError("infeasible case produced execution feedback")
        late = 1 if request["expected_terminal"] == "TIMEOUT" else 0
        if driver.get("ts_state_receive_count") != late:
            raise AssertionError("infeasible case received TS feedback")
        if any(event.get("event") == "observation_received"
               for event in driver.get("events", [])):
            raise AssertionError("infeasible case received execution observation")
        if any(event.get("event") == "snapshot_served" for event in server_events):
            raise AssertionError("infeasible case served a snapshot")
    else:
        raise ValueError("unknown expected terminal status")


def runner_proof_fields():
    return ("infeasibility_certificate_type", "infeasibility_proof_basis",
            "infeasibility_precision", "lower_precision_infeasibility")


def run_dds(args, plan: dict[str, Any], output: Path) -> dict[str, Any]:
    """Run exactly the two frozen DDS cases, preserving every artifact on failure."""
    descriptor = _descriptor(args.version_binding)
    if not isinstance(plan.get("dds_cases"), list) or len(plan["dds_cases"]) != 2:
        raise ValueError("plan must contain exactly two dds_cases")
    if not isinstance(plan.get("execution_identity"), str) or not plan["execution_identity"]:
        raise ValueError("plan execution identity is required")
    expected_cases = (
        ("C1-T1", "AP-D", "OPTIMALITY_CERTIFIED"),
        ("D1-1", "FULL", "INFEASIBLE_CERTIFIED"),
    )
    for case, expected in zip(plan["dds_cases"], expected_cases):
        if not isinstance(case, dict):
            raise TypeError("each DDS case must be an object")
        if (case.get("instance_id"), case.get("method"), case.get("backend"),
                case.get("expected_terminal")) != (expected[0], expected[1],
                                                     "ros2-v6", expected[2]):
            raise ValueError("DDS case differs from the frozen two-case plan")
        if not isinstance(case.get("request_id"), str) or not case["request_id"]:
            raise ValueError("DDS case request_id is required")
    runner = importlib.import_module("experiments.cmr_ros2_backend.runner")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "cmr-ros2-v6-dds-report-v1", "status": "RUNNING",
              "domain_id": DOMAIN_ID, "transport_seconds": TRANSPORT_SECONDS,
              "cases": [], "descriptor": descriptor}
    for case in plan["dds_cases"]:
        case_dir = output / case["request_id"]
        request = None
        artifact = {"schema": "cmr-ros2-v6-dds-case-v1", "status": "FAILED",
                    "request": None, "descriptor": descriptor}
        try:
            cell = runner.make_request(
                plan, case["instance_id"], case["method"], "ros2-v6")
            if "request_id" in cell or "expected_terminal" in cell:
                raise ValueError("runner.make_request returned transport-only fields")
            request = dict(cell, request_id=case["request_id"])
            for key, expected in descriptor.items():
                if key not in request or request[key] != expected:
                    raise ValueError(f"runner envelope differs for {key}")
            if request.get("execution_identity") != plan["execution_identity"]:
                raise ValueError("runner envelope differs for execution_identity")
            artifact["request"] = request
            artifact = _run_case(request, args, case_dir, descriptor)
            _validate_case({**case, **request}, artifact, descriptor)
            artifact["status"] = "PASSED"
        except Exception as error:
            artifact["status"] = "FAILED"
            artifact["error"] = repr(error)
            artifact["traceback"] = traceback.format_exc()
            case_dir.mkdir(parents=True, exist_ok=True)
            _write_json(case_dir / "dds_artifact.json", artifact)
        report["cases"].append(artifact)
    report["status"] = ("PASSED" if all(case.get("status") == "PASSED"
                                         for case in report["cases"])
                         else "FAILED")
    _write_json(output / "dds_report.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("server", "driver"), required=True)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--seconds", required=True, type=float)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--kernel-root", required=True)
    parser.add_argument("--version-binding", required=True)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args(argv)
    return _child(args.role, args.request, args.work_dir, args.seconds,
                  args.binding, args.kernel_root, args.version_binding, args.plan)


if __name__ == "__main__":
    raise SystemExit(main())
