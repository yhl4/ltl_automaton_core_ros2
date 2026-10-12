"""Bounded recovery of failed lifecycle fault cases.

Only cases recorded as failed by the original lifecycle report are rerun.  A
successful case is retained by reference in the aggregate report, while each
replacement is written to a fresh recovery directory under the new binding.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import signal
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from experiments.cmr_ros2_backend import backends, runner


DIRECT_MODES = ("crash", "missing_result", "malformed_result", "crash_after_result", "watchdog")
ALL_DIRECT_MODES = (
    "late_solver", "late_certificate", "late_logging", "late_delivery", *DIRECT_MODES
)


def read(path):
    return json.loads(Path(path).read_bytes())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())


def _closure_diff(old, new):
    if set(old) != set(new):
        raise ValueError("source closure key set changed")
    return {key: (old[key], new[key]) for key in old if old[key] != new[key]}


def _old_lifecycle(original):
    relative = str((HERE / "lifecycle.py").relative_to(HERE.parents[1]))
    candidates = [original / "frozen_adapter" / relative,
                  original / relative,
                  original / "lifecycle.py"]
    for path in candidates:
        if path.is_file():
            return path
    raise ValueError("original lifecycle source snapshot is missing")


def _popen_functions(tree):
    return [node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "popen"]


def _strip_popen(tree):
    tree = copy.deepcopy(tree)
    for node in _popen_functions(tree):
        node.body = [ast.Pass()]
    ast.fix_missing_locations(tree)
    return ast.dump(tree, include_attributes=False)


def _expected_guard(filename):
    tree = ast.parse("""def popen(command, **kwargs):
    if str(HERE / FILENAME) not in command:
        return REAL_POPEN(command, **kwargs)
""".replace("FILENAME", repr(filename)))
    return ast.dump(tree.body[0].body[0], include_attributes=False)


def source_guard_evidence(original, plan_old, plan_new):
    old_closure = plan_old.get("source_closure", {})
    new_closure = plan_new.get("source_closure", {})
    closure_diff = _closure_diff(old_closure, new_closure)
    allowed = [key for key in closure_diff if key.endswith("/lifecycle.py") or key.endswith("\\lifecycle.py")]
    if set(closure_diff) != set(allowed):
        raise ValueError("r2 to r3 changed sources outside lifecycle.py: " + repr(sorted(closure_diff)))
    old_path = _old_lifecycle(Path(original))
    current_path = HERE / "lifecycle.py"
    old_sha = digest(old_path)
    current_sha = digest(current_path)
    if old_sha == current_sha:
        raise ValueError("r2 to r3 lifecycle source did not change")
    old_tree = ast.parse(old_path.read_text(encoding="utf-8"), filename=str(old_path))
    current_tree = ast.parse(current_path.read_text(encoding="utf-8"), filename=str(current_path))
    if _strip_popen(old_tree) != _strip_popen(current_tree):
        raise ValueError("lifecycle AST outside nested Popen guards changed")
    current_popen = _popen_functions(current_tree)
    if len(current_popen) != 2:
        raise ValueError("expected exactly two lifecycle Popen wrappers")
    guards = []
    for node in current_popen:
        candidates = [statement for statement in node.body if isinstance(statement, ast.If)]
        if not candidates:
            raise ValueError("Popen wrapper lacks the required forwarding guard")
        guard = candidates[0]
        guards.append(ast.dump(guard, include_attributes=False))
    expected = {_expected_guard("runner.py"), _expected_guard("dds.py")}
    if set(guards) != expected:
        raise ValueError("lifecycle forwarding guards differ from the two approved guards")
    return {"old_path": str(old_path), "current_path": str(current_path),
            "old_sha256": old_sha, "current_sha256": current_sha,
            "closure_diff": closure_diff, "outside_popen_ast_equal": True,
            "approved_guard_count": len(guards), "approved_guards": True}


def _case_map(report, key):
    return {case["mode"]: case for case in report.get(key, [])}


def _failed_cases(original_report):
    direct = _case_map(original_report, "cases")
    if set(direct) != set(ALL_DIRECT_MODES):
        raise ValueError("original report does not contain the complete direct fault matrix")
    failed_direct = {mode for mode, case in direct.items() if case.get("status") == "FAILED"}
    if not failed_direct.issubset(set(DIRECT_MODES)):
        raise ValueError("original report contains an unexpected failed direct mode")
    dds = _case_map(original_report, "dds_cases")
    if set(dds) != {"none", "late_delivery", "crash", "server_error"}:
        raise ValueError("original report does not contain the complete DDS fault matrix")
    failed_dds = {mode for mode, case in dds.items() if case.get("status") == "FAILED"}
    if not failed_dds.issubset({"crash"}):
        raise ValueError("original report contains an unexpected failed DDS mode")
    return direct, dds, failed_direct, failed_dds


def _frozen_phase_records(original, plan):
    old_before = original / "frozen_inputs_before.json"
    old_after = original / "frozen_inputs_after.json"
    if not old_before.is_file() or not old_after.is_file():
        raise ValueError("original frozen input phase records are missing")
    before = read(old_before)
    after = read(old_after)
    if before != after:
        raise ValueError("original frozen inputs changed across phases")
    from experiments.cmr_ros2_backend import qualification
    current_before = qualification.frozen_inputs(plan)
    return before, current_before


def _run_direct(mode, plan, plan_path, receipt, kernel_root, version, output):
    from experiments.cmr_ros2_backend import lifecycle
    request = runner.make_request(plan, "C2-T3", "FULL", "ros2-v6")
    directory = Path(output) / "lifecycle" / mode
    directory.parent.mkdir(parents=True, exist_ok=True)
    value = lifecycle.run_fault(request, receipt, kernel_root, version, plan_path, directory, mode)
    expected = "TIMEOUT" if mode == "watchdog" else "INFRASTRUCTURE_FAILURE"
    lifecycle.no_claims(value, expected)
    if mode == "watchdog":
        if value["fault_qualification"]["actual_wall_seconds"] < 195:
            raise AssertionError("watchdog recovery used less than the frozen 195 seconds")
        if value["row"]["timeout_stage"] != "outer_watchdog" or value["worker_exitcode"] != -signal.SIGKILL:
            raise AssertionError("watchdog recovery termination contract changed")
    return {"mode": mode, "status": "PASSED", "version_binding_id": plan["version_binding_id"],
            "version_binding_sha256": plan["version_binding_sha256"], "result": value}


def _run_dds_crash(plan, plan_path, receipt, kernel_root, version, output):
    from experiments.cmr_ros2_backend import dds, lifecycle
    request = runner.make_request(plan, "C2-T3", "FULL", "ros2-v6")
    envelope = dict(request, request_id="cmr-v2-recovery-dds-crash")
    directory = Path(output) / "lifecycle" / "dds_crash"
    directory.parent.mkdir(parents=True, exist_ok=True)
    descriptor = backends.describe(version, "ros2-v6")
    old_popen = dds.subprocess.Popen

    def popen(command, **kwargs):
        command = list(command)
        if str(HERE / "dds.py") not in command:
            return lifecycle.REAL_POPEN(command, **kwargs)
        command[command.index(str(HERE / "dds.py"))] = str(HERE / "lifecycle.py")
        command.extend(["--dds-fault", "crash"])
        return lifecycle.REAL_POPEN(command, **kwargs)

    dds.subprocess.Popen = popen
    try:
        args = argparse.Namespace(binding=receipt, kernel_root=kernel_root,
                                  version_binding=version, plan=plan_path)
        artifact = dds._run_case(envelope, args, directory, descriptor)
    finally:
        dds.subprocess.Popen = old_popen
    dds._validate_case(dict(envelope, expected_terminal="INFRASTRUCTURE_FAILURE"), artifact, descriptor)
    return {"mode": "crash", "status": "PASSED", "version_binding_id": plan["version_binding_id"],
            "version_binding_sha256": plan["version_binding_sha256"], "artifact": artifact}


def qualify(original, output, receipt, kernel_root):
    original = Path(original).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "recovery.json").exists() or (output / "qualified_recovery.json").exists():
        raise ValueError("recovery output already contains a completed recovery")
    old_plan = read(original / "plan.json")
    plan = read(output / "plan.json")
    old_identity = str(old_plan.get("execution_identity", ""))
    new_identity = str(plan.get("execution_identity", ""))
    old_prefix, _, old_suffix = old_identity.partition("+")
    new_prefix, _, new_suffix = new_identity.partition("+")
    if not old_prefix or old_prefix != new_prefix or not old_suffix or not new_suffix:
        raise ValueError("recovery plan changed the frozen campaign identity")
    if old_identity == new_identity:
        raise ValueError("recovery plan did not record the lifecycle source update")
    if old_plan.get("version_binding_id") == plan.get("version_binding_id") or old_plan.get("version_binding_sha256") == plan.get("version_binding_sha256"):
        raise ValueError("recovery plan did not introduce a fresh version binding")
    source_evidence = source_guard_evidence(original, old_plan, plan)
    old_lifecycle = read(original / "lifecycle" / "lifecycle.json")
    direct, dds, failed_direct, failed_dds = _failed_cases(old_lifecycle)
    if not failed_direct and not failed_dds:
        raise ValueError("original report has no failed recovery scope")
    before, current_before = _frozen_phase_records(original, plan)
    prepared_before = output / "frozen_inputs_before.json"
    if prepared_before.exists() and read(prepared_before) != current_before:
        raise ValueError("prepared r3 frozen input record differs before recovery")
    write(prepared_before, current_before)
    from experiments.cmr_ros2_backend import fixtures
    fixture_result = fixtures.run(output / "plan.json", receipt, kernel_root, output / "fixtures.json")
    previous_offline = original / "offline_chain" / "offline_chain_evidence.json"
    if not previous_offline.is_file():
        raise ValueError("previous offline 510 evidence is missing")
    offline = read(previous_offline)
    if offline.get("status") != "PASSED" or offline.get("committed") not in (None, 510):
        raise ValueError("previous offline 510 qualification is not a passed record")
    recovery_cases = []
    for mode in DIRECT_MODES:
        if mode not in failed_direct:
            continue
        print(json.dumps({"recovery": mode, "status": "RUNNING"}), flush=True)
        result = _run_direct(mode, plan, output / "plan.json", receipt, kernel_root,
                             Path(plan["version_binding_path"]), output)
        recovery_cases.append(dict(kind="direct", **result))
        print(json.dumps({"recovery": mode, "status": "PASSED"}), flush=True)
    if "crash" in failed_dds:
        print(json.dumps({"recovery": "dds_crash", "status": "RUNNING"}), flush=True)
        result = _run_dds_crash(plan, output / "plan.json", receipt, kernel_root,
                                Path(plan["version_binding_path"]), output)
        recovery_cases.append(dict(kind="dds", **result))
        print(json.dumps({"recovery": "dds_crash", "status": "PASSED"}), flush=True)
    current_after = _frozen_phase_records(original, plan)[1]
    write(output / "frozen_inputs_after.json", current_after)
    if current_before != current_after or before != current_before:
        raise ValueError("frozen input records changed during recovery")
    recovery = {"schema": "cmr-v6-recovery-v1", "status": "PASSED",
                "scope": {"direct_failed_replaced": sorted(failed_direct),
                          "dds_failed_replaced": sorted(failed_dds),
                          "successful_modes_rerun": [], "formal_campaign_workers": 0,
                          "provider_calls": 0, "dds_calls": 1 if failed_dds else 0},
                "version_binding_id": plan["version_binding_id"],
                "version_binding_sha256": plan["version_binding_sha256"],
                "source_guard": source_evidence, "fixtures": fixture_result,
                "previous_offline_510": {"path": str(previous_offline), "sha256": digest(previous_offline),
                                         "status": offline.get("status"), "committed": offline.get("committed", 510)},
                "cases": recovery_cases}
    write(output / "recovery.json", recovery)
    aggregate_cases = []
    for mode, case in direct.items():
        replacement = next((item for item in recovery_cases if item["kind"] == "direct" and item["mode"] == mode), None)
        aggregate_cases.append({"kind": "direct", "mode": mode,
                                "source": "RECOVERY" if replacement else "ORIGINAL",
                                "original_status": case.get("status"),
                                "record": replacement or case,
                                "version_binding_id": (replacement or case).get("version_binding_id", old_plan.get("version_binding_id")),
                                "version_binding_sha256": (replacement or case).get("version_binding_sha256", old_plan.get("version_binding_sha256"))})
    for mode, case in dds.items():
        replacement = next((item for item in recovery_cases if item["kind"] == "dds" and item["mode"] == mode), None)
        aggregate_cases.append({"kind": "dds", "mode": mode,
                                "source": "RECOVERY" if replacement else "ORIGINAL",
                                "original_status": case.get("status"),
                                "record": replacement or case,
                                "version_binding_id": (replacement or case).get("version_binding_id", old_plan.get("version_binding_id")),
                                "version_binding_sha256": (replacement or case).get("version_binding_sha256", old_plan.get("version_binding_sha256"))})
    aggregate = {"schema": "cmr-v6-qualified-recovery-v1", "status": "PASSED",
                 "original_output": str(original), "recovery_output": str(output),
                 "old_version_binding_id": old_plan["version_binding_id"],
                 "old_version_binding_sha256": old_plan["version_binding_sha256"],
                 "new_version_binding_id": plan["version_binding_id"],
                 "new_version_binding_sha256": plan["version_binding_sha256"],
                 "cases": aggregate_cases, "successful_modes_rerun": [],
                 "formal_campaign_workers": 0, "provider_calls": 0,
                 "source_guard": source_evidence,
                 "frozen_inputs_equal": True,
                 "original_records_preserved": True}
    write(output / "qualified_recovery.json", aggregate)
    return recovery


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--kernel-root", required=True)
    args = parser.parse_args()
    try:
        result = qualify(args.original, args.output, args.binding, args.kernel_root)
        print(json.dumps({"status": result["status"], "cases": len(result["cases"]),
                          "formal_campaign_workers": 0, "provider_calls": 0}), flush=True)
    except Exception:
        args.output.mkdir(parents=True, exist_ok=True)
        write(args.output / "recovery_error.json", {"status": "FAILED", "traceback": traceback.format_exc()})
        raise


if __name__ == "__main__":
    main()
