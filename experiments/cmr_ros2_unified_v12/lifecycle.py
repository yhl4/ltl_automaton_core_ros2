"""Test-only unified V12 worker lifecycle fault harness.

This module exercises the qualified original delivery predicates through V12.
It is deliberately separate from the production runner and
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

# Reuse the qualified terminal-claim predicate for the unchanged result schema.
from experiments.cmr_ros2_backend.lifecycle import MODES, OffsetClock, no_claims

REAL_TIME = time
REAL_POPEN = subprocess.Popen
MODES = tuple(MODES) + ("watchdog_cooperative",)


def _v12_runner():
    from experiments.cmr_ros2_unified_v12 import runner
    return runner


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def _request(plan, entry, cell):
    runner = _v12_runner()
    request = runner.request_for(plan, entry, cell, "ros2-v12")
    request["request_id"] = "v12-lifecycle-" + cell["instance_id"] + "-" + cell["method"]
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
    """Install V12-only hooks, then let V12's worker perform the attempt."""
    runner = _v12_runner()
    plan = runner.load_plan(args.plan)
    request = json.loads(args.request.read_bytes())
    entry = runner.AttemptEntry(args.plan)
    entry.validate(plan, {k: v for k, v in request.items() if k != "request_id"}, "ros2-v12")
    if request.get("backend") != "ros2-v12" or args.backend != "ros2-v12":
        raise ValueError("fault harness accepts only the V12 backend")

    clock = OffsetClock(mode)

    def configure(self, formal, *configure_args, **configure_kwargs):
        capture = original_configure(self, formal, *configure_args, **configure_kwargs)
        formal.time = clock
        # AttemptEntry instruments run_one using private copied globals. Bind
        # the fault there so the original bytecode observes the injected phase.
        one_globals = formal.run_one.__globals__
        one_globals['time'] = clock
        if mode == "late_solver":
            original = one_globals['run_method_local']

            def late_solver(*call_args, **call_kwargs):
                answer = original(*call_args, **call_kwargs)
                clock.offset_ns = 180_000_000_000
                return answer

            one_globals['run_method_local'] = late_solver
        elif mode == "late_certificate":
            original = one_globals['persist_and_verify_certificate']

            def late_certificate(*call_args, **call_kwargs):
                answer = original(*call_args, **call_kwargs)
                clock.offset_ns = 180_000_000_000
                return answer

            one_globals['persist_and_verify_certificate'] = late_certificate
        return capture

    descriptor = entry.describe(args.version_binding, "ros2-v12")
    worker_module = str(Path(runner.__file__).resolve())

    # Pre-dispatch modes must still pass V12 authority/configuration
    # checks before injecting the failure.  No formal run is called here.
    if mode in ("crash", "missing_result", "malformed_result", "watchdog", "watchdog_cooperative"):
        formal, _, manifest, _ = runner.authority(
            plan, args.binding, args.kernel_root)
        entry.configure(formal, "ros2-v12", args.version_binding)
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
        signal.signal(signal.SIGTERM,
                       (lambda _signum, _frame: sys.exit(0))
                       if mode == "watchdog_cooperative" else signal.SIG_IGN)
        while True:
            REAL_TIME.sleep(1)

    # Late modes execute the original worker/formal run under the V12 adapter.
    _write(args.output / "fault_marker.json",
           _fault_marker(plan, request, descriptor, mode, os.getpid(),
                         worker_module))
    runner.AttemptEntry.configure = configure
    try:
        original_worker(args)
    finally:
        runner.AttemptEntry.configure = original_configure
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
    runner = _v12_runner()
    original_worker = runner.worker
    original_configure = runner.AttemptEntry.configure

    def worker(args):
        return _fault_child_worker(args, mode, original_worker, original_configure)

    runner.worker = worker
    try:
        return runner.main()
    finally:
        runner.worker = original_worker
        runner.AttemptEntry.configure = original_configure


@contextmanager
def _parent_hooks(mode: str, clock: OffsetClock, output: Path | None = None):
    """Patch only the V6 clone source before candidate construction."""
    runner = _v12_runner()
    old_runner = runner.original
    old_time = old_runner.time
    old_popen = old_runner.subprocess.Popen
    old_checked = runner.AttemptEntry.checked_delivery
    worker_path = str((runner.HERE / "runner.py").resolve())
    harness_path = str((HERE / "lifecycle.py").resolve())

    def popen(command, **kwargs):
        command = list(command)
        if worker_path not in command:
            return REAL_POPEN(command, **kwargs)
        command[command.index(worker_path)] = harness_path
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

    # candidate_isolated clones the original run_isolated after these hooks.
    old_runner.time = clock
    old_runner.subprocess.Popen = popen
    runner.AttemptEntry.checked_delivery = runner.adapter._clone_function(
        runner.base.AttemptEntry.checked_delivery, {"time": clock})
    try:
        yield dict(worker_path=worker_path, harness_path=harness_path,
                   old_time=old_time, old_popen=old_popen)
    finally:
        old_runner.time = old_time
        old_runner.subprocess.Popen = old_popen
        runner.AttemptEntry.checked_delivery = old_checked


def run_fault(request, receipt, kernel_root, version_path, plan_path, output,
              mode):
    if mode not in MODES:
        raise ValueError("unknown lifecycle mode")
    runner = _v12_runner()
    plan = runner.load_plan(plan_path)
    clock = OffsetClock(mode)
    wall_start = REAL_TIME.perf_counter_ns()
    args = SimpleNamespace(binding=receipt, kernel_root=kernel_root,
                            version_binding=version_path,
                            plan=plan_path, output=Path(plan_path).parent)
    cell = next(c for c in plan["cells"]
                if (c["instance_id"], c["method"]) ==
                   (request["instance_id"], request["method"]))
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
    """Small deterministic check of the unchanged 180/195 second boundaries."""
    from experiments.cmr_ros2_unified_v12.runner import original
    samples = []
    with zipfile.ZipFile(HERE.parent / 'cmr_ros2_backend/evidence/20261012/raw_attempts.zip') as zipped:
        for member in ('D1-1_FULL/ros2-v6/result.json',):
            samples.append(json.loads(zipped.read(member))['row'])
    checks = []
    start = 1_000_000_000
    for sample in samples:
        for elapsed in (179_999_999_999, 180_000_000_000,
                        180_000_000_001, 195_000_000_000):
            row = copy.deepcopy(sample)
            row.update(method_start_ns=start, terminal_completion_ns=start+100,
                       qualified_runner_completion_ns=start+100)
            original.terminal_delivery(row, start+elapsed, outer_start=start)
            if elapsed >= 180_000_000_000:
                no_claims(dict(row=row, transport=None), 'TIMEOUT')
            elif row['terminal_status'] != sample['terminal_status']:
                raise AssertionError('on-time archived verdict changed')
            checks.append(dict(name=str(elapsed), status='PASSED'))
    report = dict(status='PASSED', checks=checks, count=len(checks),
                  archived_controls=['D1-1_FULL/ros2-v6/result.json'],
                  simulated_clock=True, solver_calls=0,
                  planner_budget_seconds=180, outer_watchdog_seconds=195)
    _write(Path(output), report)
    return report


def run(args, plan, output):
    """Run common faults on one cell and late-solver faults across its methods."""
    runner = _v12_runner()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan = runner.load_plan(args.plan)
    available = {(c['instance_id'], c['method']) for c in plan['cells']}
    targets = [(args.instance_id, method) for method in runner.METHODS
               if (args.instance_id, method) in available]
    if args.method:
        targets = [(args.instance_id, args.method)]
    report = {"schema": "cmr-unified-v12-lifecycle-v1", "status": "RUNNING",
              "backend": "ros2-v12", "targets": [list(x) for x in targets],
              "cases": [], "planner_budget_seconds": 180,
              "outer_watchdog_seconds": 195,
              "source_head": plan['source_head'],
              "execution_identity": plan['execution_identity'],
              "version_binding_id": plan['version_binding_id'],
              "version_binding_sha256": plan['version_binding_sha256'],
              "harness_sha256": runner.v7.digest(Path(__file__))}
    failures = []
    for target in targets:
        cell = next(c for c in plan["cells"] if (c["instance_id"], c["method"]) == target)
        entry = runner.AttemptEntry(args.plan)
        descriptor = entry.describe(args.version_binding, "ros2-v12")
        request = _request(plan, entry, cell)
        modes = MODES if target == targets[0] else ("late_solver",)
        for mode in modes:
            label = target[0] + "_" + target[1] + "_" + mode
            directory = output / label
            try:
                value = run_fault(request, args.binding, args.kernel_root,
                                  args.version_binding, args.plan, directory, mode)
                if value.get("backend_binding") != descriptor:
                    raise AssertionError("V12 result backend identity mismatch")
                if value.get("row", {}).get("execution_commit") != plan["execution_identity"]:
                    raise AssertionError("V12 result execution identity mismatch")
                marker = json.loads((directory / "fault_marker.json").read_bytes())
                if (marker.get("backend") != "ros2-v12"
                        or marker.get("version_binding_id") != descriptor["version_binding_id"]
                        or marker.get("version_binding_sha256") != descriptor["version_binding_sha256"]):
                    raise AssertionError("fault marker did not originate from V12 worker")
                expected = "TIMEOUT" if mode.startswith("late_") or mode.startswith("watchdog") else "INFRASTRUCTURE_FAILURE"
                no_claims(value, expected)
                if value.get("worker_alive_after_cleanup") is not False:
                    raise AssertionError("worker survived cleanup")
                if mode.startswith("watchdog"):
                    if value["fault_qualification"]["actual_wall_seconds"] < 195:
                        raise AssertionError("watchdog returned before 195 seconds")
                    expected_rc = 0 if mode == "watchdog_cooperative" else -signal.SIGKILL
                    if (value["row"]["timeout_stage"] != "outer_watchdog"
                            or value["worker_exitcode"] != expected_rc):
                        raise AssertionError("watchdog termination predicate mismatch")
                report["cases"].append({"target": list(target), "mode": mode,
                                        "status": "PASSED", "result": value})
            except Exception:
                failures.append(label)
                report["cases"].append({"target": list(target), "mode": mode,
                                        "status": "FAILED", "traceback": traceback.format_exc()})
            _write(output / "lifecycle.json", report)
            print(json.dumps(dict(target=target, mode=mode,
                                  status=report['cases'][-1]['status'])), flush=True)
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
    raise ValueError("V12 lifecycle is a qualification harness, not a worker entry")


if __name__ == "__main__":
    raise SystemExit(main())
