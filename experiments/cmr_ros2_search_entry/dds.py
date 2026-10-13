"""V7 ROS2 transport adapter for the three fixed qualification cells.

The transport is deliberately separate from the V6 DDS module.  It reuses the
existing ROS smoke server/driver and validation rules, but the server invokes
the V7 candidate entry and never routes a request through the V6 solver.
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
from types import SimpleNamespace
from typing import Any, Mapping

from experiments.cmr_ros2_integration import dds_smoke as transport
from experiments.cmr_ros2_backend.dds import _validate_case, _wait_processes


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOMAIN_ID = 227
SERVER_SECONDS = 205.0
TRANSPORT_SECONDS = 210.0
SCHEMA = transport.SCHEMA
TARGETS = (
    ("A-T1-M0-A-S-BRANCH", "FULL"),
    ("B-D-BRANCH-S2", "FULL"),
    ("C3-T4", "AP-D"),
)
EXPECTED_TERMINAL = {target: "OPTIMALITY_CERTIFIED" for target in TARGETS}
FAILURE_SCOPE = 'CMR_SEARCH_ENTRY_DDS_FAILURE_QUALIFICATION'
FAILURE_TARGETS = (('A-T1-M0-A-S-BRANCH', 'FULL'), ('D1-1', 'FULL'))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


def _event(events: list[dict[str, Any]], name: str, **fields: Any) -> None:
    events.append({"event": name, "time_ns": time.monotonic_ns(), **fields})


def _fixed_cells(plan: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    targets = FAILURE_TARGETS if plan.get('scope') == FAILURE_SCOPE else TARGETS
    cells = plan.get("cells")
    observed = ([(cell.get("instance_id"), cell.get("method")) for cell in cells]
                if isinstance(cells, list) else None)
    if observed != list(targets):
        raise ValueError("V7 DDS plan cells differ from its fixed qualification scope")
    if (plan.get("formal_campaign") is not False
            or plan.get("planner_budget_seconds") != 180
            or plan.get("outer_watchdog_seconds") != 195):
        raise ValueError("V7 DDS plan budget or campaign contract changed")
    return {(cell["instance_id"], cell["method"]): cell for cell in cells}


def _request_envelope(cell: Mapping[str, Any], descriptor: Mapping[str, Any],
                      qualification_id: str, population: str,
                      execution_identity: str, request_id: str) -> dict[str, Any]:
    """Build the exact public request envelope without importing ROS code."""
    value = dict(cell)
    value.update(descriptor, qualification_id=qualification_id,
                 population=population, formal_campaign=False,
                 execution_identity=execution_identity,
                 planner_budget_seconds=180, outer_watchdog_seconds=195,
                 request_id=request_id)
    return value


def _require_exact_envelope(request: Mapping[str, Any],
                            expected: Mapping[str, Any]) -> None:
    if dict(request) != dict(expected):
        raise ValueError("DDS request differs from the frozen V7 envelope")
    if request.get("backend") != "ros2-v7":
        raise ValueError("DDS request is not bound to ros2-v7")
    if request.get("planner_budget_seconds") != 180 or request.get(
            "outer_watchdog_seconds") != 195:
        raise ValueError("DDS request budget differs from the frozen contract")


def _request_cell(plan: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    key = (request.get("instance_id"), request.get("method"))
    cells = _fixed_cells(plan)
    if key not in cells:
        raise ValueError("DDS request cell is outside the fixed V7 scope")
    return cells[key]


class V7Server(transport._Server):
    """Serve one exact request and one certified V7 execution snapshot."""

    def __init__(self, request: dict[str, Any], binding: str,
                 kernel_root: str, work_dir: Path,
                 version_binding: str, plan_path: str | Path):
        super().__init__(request, binding, kernel_root, work_dir)
        self.binding = binding
        self.kernel_root = kernel_root
        self.version_binding = version_binding
        self.plan_path = Path(plan_path).resolve()
        self.identity = f"cmr-ros2-v7-{request['request_id']}"

    def _request(self, message) -> None:
        if self.done:
            return
        request = json.loads(message.data)
        _event(self.events, "request_received", request_id=request.get("request_id"),
               backend=request.get("backend"), backend_id=request.get("backend_id"),
               version_binding_id=request.get("version_binding_id"))
        if request != self.request:
            _event(self.events, "request_rejected", reason="request_mismatch")
            raise ValueError("DDS request differs from the frozen V7 envelope")
        self.done = True
        _event(self.events, "cmr_solver_started", backend_id=request["backend_id"])
        try:
            runner = importlib.import_module("experiments.cmr_ros2_search_entry.runner")
            plan = runner.load_plan(self.plan_path)
            cell = _request_cell(plan, request)
            entry = runner.VerifiedEntry(plan, runner.source_closure, runner.schema_for)
            expected = dict(runner.request_for(plan, entry, cell, "ros2-v7"),
                            request_id=request["request_id"])
            _require_exact_envelope(request, expected)
            args = SimpleNamespace(binding=self.binding,
                                   kernel_root=self.kernel_root,
                                   output=self.plan_path.parent)
            attempt = self.work_dir / "cmr_attempt"
            value = runner.candidate_isolated(args, plan, cell, attempt)
            row = value["row"]
            descriptor = value["backend_binding"]
            for key in ("backend", "backend_id", "backend_sha256",
                        "version_binding_id", "version_binding_sha256"):
                if descriptor.get(key) != request.get(key):
                    raise ValueError(f"V7 result identity differs for {key}")
            self.result = dict(
                row, schema=SCHEMA, population=request["population"],
                request_id=request["request_id"],
                instance_id=request["instance_id"], method=request["method"],
                backend=request["backend"], variant="real",
                worker_pid=value["worker_pid"],
                worker_exitcode=value["worker_exitcode"],
                worker_alive_after_cleanup=value["worker_alive_after_cleanup"],
                backend_binding=descriptor,
            )
            if value.get("transport") is not None:
                self.result.update(value["transport"])
            _write_json(attempt / "dds_result.json", self.result)
            _event(self.events, "cmr_solver_completed",
                   status=row.get("terminal_status"), backend_id=descriptor["backend_id"])
        except Exception as error:
            details = traceback.format_exc()
            descriptor = {key: request.get(key) for key in (
                "backend", "backend_id", "backend_sha256",
                "version_binding_id", "version_binding_sha256")}
            self.result = {
                "schema": SCHEMA, "population": request["population"],
                "request_id": request["request_id"],
                "instance_id": request["instance_id"],
                "method": request["method"], "backend": request.get("backend"),
                "variant": "real", "terminal_status": "ERROR",
                "objective": None, "concrete_lasso": None,
                "error": repr(error), "backend_binding": descriptor,
                **descriptor, "certificate_valid_for_terminal": False,
                "certificate_verifier_status": "NOT_AVAILABLE",
                "right_censored": False,
            }
            (self.work_dir / "server_traceback.txt").write_text(details, encoding="utf-8")
            sys.stderr.write(details)
            _event(self.events, "cmr_solver_completed", status="ERROR")
        outgoing = json.dumps(self.result, sort_keys=True, separators=(",", ":"))
        self.result_pub.publish(self.String(data=outgoing))
        _event(self.events, "result_published", status=self.result.get("terminal_status"),
               backend_id=self.result.get("backend_binding", {}).get("backend_id"))
        if self.result.get("terminal_status") != "OPTIMALITY_CERTIFIED":
            self._grace_deadline = time.monotonic() + 0.5
            return
        self.snapshot, self.transitions, self.state_ids = transport._snapshot_messages(
            self.result, self.identity)
        self._publish_observation()


def _child(role: str, request_path: Path, work_dir: Path, seconds: float,
           binding: str, kernel_root: str, version_binding: str,
           plan_path: str) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    import rclpy
    rclpy.init()
    try:
        worker = (V7Server(request, binding, kernel_root, work_dir,
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


def _run_case(request: dict[str, Any], args, case_dir: Path,
              descriptor: dict[str, str]) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=False)
    request_path = case_dir / "request.json"
    _write_json(request_path, request)
    env = dict(os.environ, ROS_DOMAIN_ID=str(DOMAIN_ID), ROS_LOCALHOST_ONLY="1",
               PYTHONDONTWRITEBYTECODE="1")
    processes: dict[str, subprocess.Popen] = {}
    streams = []
    pending_error = None
    try:
        for role in ("server", "driver"):
            stdout = (case_dir / f"{role}.stdout").open("w", encoding="utf-8")
            stderr = (case_dir / f"{role}.stderr").open("w", encoding="utf-8")
            streams.extend((stdout, stderr))
            command = [sys.executable, "-B", str(HERE / "dds.py"),
                       "--role", role, "--request", str(request_path),
                       "--work-dir", str(case_dir), "--seconds", str(SERVER_SECONDS),
                       "--binding", str(args.binding), "--kernel-root", str(args.kernel_root),
                       "--version-binding", str(args.version_binding),
                       "--plan", str(args.plan)]
            processes[role] = subprocess.Popen(command, env=env,
                                               stdout=stdout, stderr=stderr)
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
    attempt = case_dir / "cmr_attempt"
    replay = json.loads((attempt / "certificate_replay.json").read_bytes()) \
        if (attempt / "certificate_replay.json").exists() else None
    artifact = {
        "schema": "cmr-search-entry-v7-dds-case-v1", "status": "RUNNING",
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
        "certificate_replay": replay,
        "module": str(HERE / "dds.py"),
    }
    _write_json(case_dir / "dds_artifact.json", artifact)
    return artifact


def run_dds(args, plan: dict[str, Any], output: Path) -> dict[str, Any]:
    """Run only the fixed V7 DDS cases, retaining every failure artifact."""
    runner = importlib.import_module("experiments.cmr_ros2_search_entry.runner")
    plan = runner.load_plan(args.plan)
    if plan['scope'] != runner.SCOPE:
        raise ValueError('failure plans use the dedicated failure_dds harness')
    if _sha256(Path(args.version_binding).resolve()) != plan["version_binding_sha256"]:
        raise ValueError("V7 version binding argument differs from the frozen plan")
    cells = _fixed_cells(plan)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "cmr-search-entry-v7-dds-report-v1", "status": "RUNNING",
              "domain_id": DOMAIN_ID, "transport_seconds": TRANSPORT_SECONDS,
              "cases": [], "targets": [list(target) for target in TARGETS]}
    descriptor = None
    for instance_id, method in TARGETS:
        request_id = f"cmr-v7-{instance_id}-{method}".replace("/", "-")
        case = {"instance_id": instance_id, "method": method,
                "backend": "ros2-v7", "expected_terminal": EXPECTED_TERMINAL[(instance_id, method)],
                "request_id": request_id}
        case_dir = output / request_id
        artifact = {"schema": "cmr-search-entry-v7-dds-case-v1", "status": "FAILED",
                    "request": None}
        try:
            entry = runner.VerifiedEntry(plan, runner.source_closure, runner.schema_for)
            cell = cells[(instance_id, method)]
            descriptor = entry.describe("ros2-v7")
            request = runner.request_for(plan, entry, cell, "ros2-v7")
            request["request_id"] = request_id
            _require_exact_envelope(request, _request_envelope(
                cell, descriptor, plan["qualification_id"], plan["scope"],
                plan["execution_identity"], request_id))
            artifact["request"] = request
            artifact = _run_case(request, args, case_dir, descriptor)
            _validate_case({**case, **request}, artifact, descriptor)
            if artifact["driver"]["result"].get("terminal_status") == "OPTIMALITY_CERTIFIED":
                old_runner = importlib.import_module("experiments.cmr_ros2_backend.runner")
                attempt = case_dir / "cmr_attempt"
                value = json.loads((attempt / "result.json").read_bytes())
                replay = old_runner.replay(plan, args.binding, args.kernel_root,
                                            value, attempt)
                _write_json(attempt / "certificate_replay.json", replay)
                artifact["certificate_replay"] = replay
                if replay.get("status") != "PASS":
                    raise ValueError("V7 independent certificate replay failed")
            artifact["status"] = "PASSED"
        except Exception as error:
            artifact["status"] = "FAILED"
            artifact["error"] = repr(error)
            artifact["traceback"] = traceback.format_exc()
        case_dir.mkdir(parents=True, exist_ok=True)
        _write_json(case_dir / "dds_artifact.json", artifact)
        report["cases"].append(artifact)
    report["descriptor"] = descriptor
    report["status"] = ("PASSED" if all(case.get("status") == "PASSED"
                                         for case in report["cases"]) else "FAILED")
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
