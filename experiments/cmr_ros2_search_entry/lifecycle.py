"""Test-only V7 worker lifecycle fault harness.

This module exercises the qualified V6 delivery predicates through the V7
candidate entry.  It is deliberately separate from the production runner and
does not add a solver or DDS execution path.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

# These are the frozen V6 predicates.  The child and candidate below remain V7.
from experiments.cmr_ros2_backend.lifecycle import MODES, OffsetClock, no_claims

REAL_TIME = time
REAL_POPEN = subprocess.Popen


def _v7_runner():
    from experiments.cmr_ros2_search_entry import runner
    return runner


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def _request(plan, entry, cell):
    runner = _v7_runner()
    request = runner.request_for(plan, entry, cell, "ros2-v7")
    request["request_id"] = "v7-lifecycle-" + cell["instance_id"] + "-" + cell["method"]
    return request


def _fault_marker(plan, request, descriptor, mode, pid, worker_module):
    return {
        "mode": mode,
        "backend": request["backend"],
        "backend_id": descriptor["backend_id"],
        "backend_sha256": descriptor["backend_sha256"],
        "version_binding_id": descriptor["version_binding_id"],
        "version_binding_sha256": descriptor["version_binding_sha256"],
        "source_head": plan["source_head"],
        "execution_identity": plan["execution_identity"],
        "planner_budget_seconds": 180,
        "outer_watchdog_seconds": 195,
        "formal_campaign": False,
        "pid": pid,
        "worker_module": worker_module,
    }


def _fault_child_worker(args, mode, original_worker, original_configure):
    """Install V7-only hooks, then let V7's worker perform the attempt."""
    runner = _v7_runner()
    plan = runner.load_plan(args.plan)
    request = json.loads(args.request.read_bytes())
    entry = runner.VerifiedEntry(plan, runner.source_closure, runner.schema_for)
    entry.validate_request(request)
    if request.get("backend") != "ros2-v7" or args.backend != "ros2-v7":
        raise ValueError("fault harness accepts only the V7 backend")

    clock = OffsetClock(mode)

    def configure(formal, *configure_args, **configure_kwargs):
        capture = original_configure(formal, *configure_args, **configure_kwargs)
        formal.time = clock
        if mode == "late_solver":
            original = formal.run_method_local

            def late_solver(*call_args, **call_kwargs):
                answer = original(*call_args, **call_kwargs)
                clock.offset_ns = 180_000_000_000
                return answer

            formal.run_method_local = late_solver
        elif mode == "late_certificate":
            original = formal.persist_and_verify_certificate

            def late_certificate(*call_args, **call_kwargs):
                answer = original(*call_args, **call_kwargs)
                clock.offset_ns = 180_000_000_000
                return answer

            formal.persist_and_verify_certificate = late_certificate
        return capture

    descriptor = entry.describe("ros2-v7")
    worker_module = str(Path(runner.__file__).resolve())

    # The four pre-dispatch modes must still pass V7 authority/configuration
    # checks before injecting the failure.  No formal run is called here.
    if mode in ("crash", "missing_result", "malformed_result", "watchdog"):
        formal, _, manifest, _ = runner.old_runner.authority(
            plan, args.binding, args.kernel_root)
        runner.configure(formal, "ros2-v7", descriptor)
        _write(args.output / "fault_preflight.json", manifest)
        _write(args.output / "fault_marker.json",
               _fault_marker(plan, request, descriptor, mode, os.getpid(),
                             worker_module))
        if mode == "crash":
            os._exit(23)
        if mode == "missing_result":
            return
        if mode == "malformed_result":
            (args.output / "worker_result.json").write_text(
                "{broken", encoding="utf-8")
            return
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            REAL_TIME.sleep(1)

    # Late modes must execute the unchanged V7 worker/formal run.  The V7
    # configure hook above is the only place where the formal clock is altered.
    _write(args.output / "fault_marker.json",
           _fault_marker(plan, request, descriptor, mode, os.getpid(),
                         worker_module))
    runner.configure = configure
    try:
        original_worker(args)
    finally:
        runner.configure = original_configure
    _write(args.output / "fault_clock.json", {
        "mode": mode,
        "offset_ns": clock.offset_ns,
        "simulated_clock": mode.startswith("late_"),
        "measurement": "simulated deadline predicate; not wall runtime",
    })
    if mode == "crash_after_result":
        os._exit(23)
    return None


def fault_child(mode: str) -> int:
    runner = _v7_runner()
    original_worker = runner.worker
    original_configure = runner.configure

    def worker(args):
        return _fault_child_worker(args, mode, original_worker, original_configure)

    runner.worker = worker
    try:
        return runner.main()
    finally:
        runner.worker = original_worker
        runner.configure = original_configure


@contextmanager
def _parent_hooks(mode: str, clock: OffsetClock, output: Path | None = None):
    """Patch only the V6 clone source before candidate construction."""
    runner = _v7_runner()
    old_runner = runner.old_runner
    old_time = old_runner.time
    old_popen = old_runner.subprocess.Popen
    v7_path = str((runner.HERE / "runner.py").resolve())
    harness_path = str((HERE / "lifecycle.py").resolve())

    def popen(command, **kwargs):
        command = list(command)
        if v7_path not in command:
            return REAL_POPEN(command, **kwargs)
        command[command.index(v7_path)] = harness_path
        command.extend(["--fault-child", mode])
        process = REAL_POPEN(command, **kwargs)
        original_wait = process.wait

        def wait(*wait_args, **wait_kwargs):
            result = original_wait(*wait_args, **wait_kwargs)
            if output is not None:
                clock_path = Path(output) / "fault_clock.json"
                if clock_path.exists():
                    clock.offset_ns = json.loads(clock_path.read_bytes())["offset_ns"]
            if mode == "late_delivery":
                clock.offset_ns = 180_000_000_000
            return result

        process.wait = wait
        return process

    # candidate_isolated clones old_runner.run_isolated immediately after this
    # assignment, so the cloned global `time` is this clock object.
    old_runner.time = clock
    old_runner.subprocess.Popen = popen
    try:
        yield dict(v7_path=v7_path, harness_path=harness_path,
                   old_time=old_time, old_popen=old_popen)
    finally:
        old_runner.time = old_time
        old_runner.subprocess.Popen = old_popen


def run_fault(request, receipt, kernel_root, version_path, plan_path, output,
              mode):
    if mode not in MODES:
        raise ValueError("unknown lifecycle mode")
    runner = _v7_runner()
    plan = runner.load_plan(plan_path)
    clock = OffsetClock(mode)
    wall_start = REAL_TIME.perf_counter_ns()
    args = SimpleNamespace(binding=receipt, kernel_root=kernel_root,
                            version_binding=version_path,
                            plan=plan_path, output=Path(plan_path).parent)
    cell = {"instance_id": request["instance_id"], "method": request["method"]}
    cell.update({key: request[key] for key in request
                 if key not in ("request_id", "backend", "backend_id",
                                "backend_sha256", "version_binding_id",
                                "version_binding_sha256", "qualification_id",
                                "population", "formal_campaign",
                                "execution_identity", "planner_budget_seconds",
                                "outer_watchdog_seconds")})
    with _parent_hooks(mode, clock, Path(output)):
        value = runner.candidate_isolated(args, plan, cell, Path(output))
    value["fault_qualification"] = {
        "mode": mode,
        "simulated_clock": mode.startswith("late_"),
        "actual_wall_seconds": (REAL_TIME.perf_counter_ns() - wall_start) / 1e9,
        "injected_offset_ns": clock.offset_ns,
        "planner_budget_seconds": 180,
        "outer_watchdog_seconds": 195,
    }
    _write(Path(output) / "fault_qualification.json", value["fault_qualification"])
    return value


def boundary_checks(args, plan, output):
    """Offline deadline predicates on copied archived rows; no solver call."""
    runner = _v7_runner()
    samples = []
    sources = (
        (HERE / 'evidence/20261013_audit_real/raw_attempts.zip',
         '3626a630cccaae0d3f4e765455ddc43cb220a47c149ed84ab89cfce4bcb505d6',
         'A-T1-M0-A-S-BRANCH_FULL/ros2-v7/result.json'),
        (HERE.parent / 'cmr_ros2_backend/evidence/20261012/raw_attempts.zip',
         '3df72515303b01ff95a31070f053d3547a8bcb7b878d322b401739c8ef385022',
         'D1-1_FULL/ros2-v6/result.json'),
    )
    provenance = []
    for path, digest, member in sources:
        if runner.digest(path) != digest:
            raise AssertionError('archived deadline control changed')
        with zipfile.ZipFile(path) as zipped:
            row = json.loads(zipped.read(member))['row']
        samples.append(row)
        provenance.append(dict(archive_sha256=digest, member=member,
                               original_execution_identity=row['execution_commit']))
    checks = []
    start = 1_000_000_000
    for sample in samples:
        for elapsed in (179_999_999_999, 180_000_000_000,
                        180_000_000_001, 195_000_000_000):
            row = copy.deepcopy(sample)
            row.update(method_start_ns=start, terminal_completion_ns=start+100,
                       qualified_runner_completion_ns=start+100)
            runner.old_runner.terminal_delivery(row, start+elapsed, outer_start=start)
            if elapsed >= 180_000_000_000:
                no_claims(dict(row=row, transport=None), 'TIMEOUT')
            elif row['terminal_status'] != sample['terminal_status']:
                raise AssertionError('on-time archived verdict changed')
            checks.append(dict(name=sample['terminal_status']+'_'+str(elapsed),
                               status='PASSED'))
    formal, _, _, _ = runner.old_runner.authority(plan, args.binding, args.kernel_root)
    entry = runner.VerifiedEntry(plan, runner.source_closure, runner.schema_for)
    runner.configure(formal, 'ros2-v7', entry.describe('ros2-v7'))
    cell = runner.request_for(plan, entry, plan['cells'][0], 'ros2-v7')
    for stage, elapsed in (('planner', 180_000_000_000),
                           ('outer_watchdog', 195_000_000_000), ('infrastructure', 100)):
        row = formal.timeout_serialization(cell, stage, method_start_ns=start,
                                            terminal_completion_ns=start+elapsed)
        runner.old_runner.terminal_delivery(row, start+elapsed, outer_start=start,
                                            forced_timeout=stage=='outer_watchdog')
        no_claims(dict(row=row, transport=None),
                  'INFRASTRUCTURE_FAILURE' if stage=='infrastructure' else 'TIMEOUT')
        if row['backend_id'] != runner.ID:
            raise AssertionError('serializer did not use V7 configuration')
        checks.append(dict(name='v7_'+stage+'_serialization', status='PASSED'))
    entry.release_check()
    report = dict(status='PASSED', checks=checks, count=len(checks),
                  archived_controls=provenance, simulated_clock=True, solver_calls=0,
                  planner_budget_seconds=180, outer_watchdog_seconds=195)
    _write(Path(output), report)
    return report


def run(args, plan, output):
    """Run one V7 A/FULL cell through each fault mode, retaining failures."""
    runner = _v7_runner()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan = runner.load_plan(args.plan)
    cell = next(cell for cell in plan["cells"]
                if (cell["instance_id"], cell["method"]) == runner.TARGETS[0])
    entry = runner.VerifiedEntry(plan, runner.source_closure, runner.schema_for)
    descriptor = entry.describe("ros2-v7")
    request = _request(plan, entry, cell)
    report = {"schema": "cmr-search-entry-v7-lifecycle-v1", "status": "RUNNING",
              "backend": "ros2-v7", "target": [runner.TARGETS[0][0], runner.TARGETS[0][1]],
              "cases": [], "planner_budget_seconds": 180,
              "outer_watchdog_seconds": 195,
              "source_head": plan['source_head'],
              "execution_identity": plan['execution_identity'],
              "version_binding_id": plan['version_binding_id'],
              "version_binding_sha256": plan['version_binding_sha256'],
              "harness_sha256": runner.digest(Path(__file__))}
    failures = []
    for mode in MODES:
        directory = output / mode
        try:
            value = run_fault(request, args.binding, args.kernel_root,
                              args.version_binding, args.plan, directory, mode)
            if value.get("backend_binding") != descriptor:
                raise AssertionError("V7 result backend identity mismatch")
            if value.get("row", {}).get("execution_commit") != plan["execution_identity"]:
                raise AssertionError("V7 result execution identity mismatch")
            marker = json.loads((directory / "fault_marker.json").read_bytes())
            if (marker.get("backend") != "ros2-v7"
                    or marker.get("worker_module") != str(Path(runner.__file__).resolve())
                    or marker.get("version_binding_id") != descriptor["version_binding_id"]
                    or marker.get("version_binding_sha256") != descriptor["version_binding_sha256"]):
                raise AssertionError("fault marker did not originate from V7 worker")
            expected = ("TIMEOUT" if mode.startswith("late_") or mode == "watchdog"
                        else "INFRASTRUCTURE_FAILURE")
            no_claims(value, expected)
            try:
                os.kill(value["worker_pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("worker survived cleanup")
            if mode == "watchdog":
                if value["fault_qualification"]["actual_wall_seconds"] < 195:
                    raise AssertionError("watchdog returned before 195 seconds")
                if (value["row"]["timeout_stage"] != "outer_watchdog"
                        or value["worker_exitcode"] != -signal.SIGKILL):
                    raise AssertionError("watchdog termination predicate mismatch")
            report["cases"].append({"mode": mode, "status": "PASSED", "result": value})
        except Exception:
            failures.append(mode)
            report["cases"].append({"mode": mode, "status": "FAILED",
                                    "traceback": traceback.format_exc()})
        _write(output / "lifecycle.json", report)
        print(json.dumps(dict(mode=mode, status=report['cases'][-1]['status'])), flush=True)
    report.update(status="FAILED" if failures else "PASSED", failures=failures,
                  formal_campaign_workers=0, provider_calls=0)
    _write(output / "lifecycle.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fault-child")
    special, remaining = parser.parse_known_args(argv)
    if special.fault_child in MODES:
        original_argv = sys.argv
        sys.argv = [original_argv[0]] + remaining
        try:
            return fault_child(special.fault_child)
        finally:
            sys.argv = original_argv
    raise ValueError("V7 lifecycle is a qualification harness, not a worker entry")


if __name__ == "__main__":
    raise SystemExit(main())
