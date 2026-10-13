"""Read-only standard-library readback for the V7 lifecycle/zero-cost run.

The reader consumes persisted bytes only.  It never imports the runner,
verifier, ROS, DDS, solver, or provider modules.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import signal


MODES = (
    "late_solver", "late_certificate", "late_logging", "late_delivery",
    "crash", "missing_result", "malformed_result", "crash_after_result",
    "watchdog",
)
TARGET = ("A-T1-M0-A-S-BRANCH", "FULL")
ARMS = ("reference", "ros2-v6", "ros2-v7")
PROOF_FIELDS = (
    "infeasibility_certificate_type", "infeasibility_proof_basis",
    "infeasibility_precision", "lower_precision_infeasibility",
)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class Audit:
    def __init__(self, output: Path):
        self.output = output
        self.errors: list[str] = []
        self.checked = 0

    def require(self, condition: bool, label: str) -> None:
        self.checked += 1
        if not condition:
            self.errors.append(label)

    def json(self, path: Path, label: str):
        self.require(path.is_file(), f"missing {label}: {path}")
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_bytes())
        except Exception as error:
            self.errors.append(f"invalid JSON {label}: {error!r}")
            return {}


def safe_child(root: Path, relative: str) -> Path:
    candidate = (root / Path(relative)).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"path escapes root: {relative}")
    return candidate


def check_plan_and_binding(audit: Audit, root: Path, label: str):
    plan = audit.json(root / "plan.json", f"{label} plan")
    binding_path = root / "backend_binding.json"
    binding = audit.json(binding_path, f"{label} backend binding")
    before = audit.json(root / "frozen_inputs_before.json",
                        f"{label} frozen inputs before")
    after = audit.json(root / "frozen_inputs_after.json",
                       f"{label} frozen inputs after")

    closure = plan.get("source_closure", {})
    content = dict(plan)
    execution = content.pop('execution_identity', None)
    audit.require(execution == str(plan.get('source_head')) + '+cmr-search-entry-' +
                  digest_bytes(canonical(content).encode())[:16],
                  f'{label} canonical execution identity')
    audit.require(isinstance(closure, dict) and len(closure) == 56,
                  f"{label} source closure has 56 files")
    for relative, expected in closure.items() if isinstance(closure, dict) else ():
        try:
            frozen = safe_child(root / "frozen_adapter", relative)
            audit.require(frozen.is_file(),
                          f"{label} frozen adapter exists: {relative}")
            if frozen.is_file():
                audit.require(digest(frozen) == expected,
                              f"{label} frozen adapter SHA: {relative}")
        except ValueError as error:
            audit.errors.append(str(error))

    binding_raw = binding_path.read_bytes() if binding_path.is_file() else b""
    binding_sha = digest_bytes(binding_raw)
    audit.require(binding_sha == plan.get("version_binding_sha256"),
                  f"{label} binding SHA matches plan")
    content = dict(binding) if isinstance(binding, dict) else {}
    binding_id = content.pop("binding_id", None)
    expected_id = "CMR_SEARCH_ENTRY_V1-" + digest_bytes(
        canonical(content).encode("utf-8"))[:16]
    audit.require(binding_id == expected_id, f"{label} binding canonical identity")
    audit.require(binding.get("binding_id") == plan.get("version_binding_id"),
                  f"{label} binding ID matches plan")
    audit.require(binding.get("source_closure") == closure,
                  f"{label} binding source closure matches plan")
    for key, expected in {
        "semantic_contract_id": "INITIAL_LABEL_V1",
        "objective": "prefix_cost + 10*suffix_cost",
        "nonempty_accepting_suffix": True,
        "full_ts_rebuild_every_round": True,
        "planner_budget_seconds": 180,
        "outer_watchdog_seconds": 195,
        "formal_campaign": False,
    }.items():
        audit.require(binding.get(key) == expected,
                      f"{label} binding semantic field: {key}")
    audit.require(before == after, f"{label} frozen inputs before/after unchanged")
    audit.require(isinstance(before, dict) and len(before) == 60,
                  f'{label} retains all 60 frozen inputs')
    return plan, binding


def check_no_claims(audit: Audit, value: dict, expected: str, label: str) -> None:
    row = value.get("row", {})
    transport = value.get("transport")
    audit.require(row.get("terminal_status") == expected, f"{label}: terminal status")
    audit.require(row.get("objective") is None and transport is None,
                  f"{label}: objective/transport cleared")
    audit.require(row.get("certificate_valid_for_terminal") is False,
                  f"{label}: certificate authority cleared")
    audit.require(row.get("certificate_verifier_status") == "NOT_AVAILABLE",
                  f"{label}: certificate verifier cleared")
    audit.require(row.get("certificate_path") == "NOT_AVAILABLE"
                  and row.get("certificate_hash") == "NOT_AVAILABLE"
                  and row.get("certificate_schema") == "NOT_AVAILABLE"
                  and row.get("certificate_objective") is None,
                  f"{label}: certificate fields cleared")
    audit.require(all(row.get(key) is None for key in PROOF_FIELDS),
                  f"{label}: proof fields cleared")
    audit.require(all(item.get("terminal_claim_valid") is False
                       and all(item.get(key) is None for key in PROOF_FIELDS)
                       for item in row.get("rounds") or []),
                  f"{label}: round claims cleared")
    audit.require(row.get("planner_budget_seconds") == 180
                  and row.get("outer_watchdog_seconds") == 195,
                  f"{label}: budgets")
    audit.require(row.get("right_censored") is (expected == "TIMEOUT"),
                  f"{label}: right censoring")
    try:
        elapsed = ((row["terminal_completion_ns"] - row["method_start_ns"])
                   / 1e9)
        audit.require(row.get("T_total") == elapsed, f"{label}: elapsed identity")
        if expected == 'TIMEOUT':
            audit.require(elapsed >= 180 and row.get('timing_status') == 'RIGHT_CENSORED',
                          f'{label}: timeout threshold and timing status')
        else:
            audit.require(elapsed < 180 and row.get('timing_status') == 'ANOMALY',
                          f'{label}: infrastructure timing status')
    except (KeyError, TypeError):
        audit.errors.append(f"{label}: elapsed fields missing")
    audit.require(value.get("worker_alive_after_cleanup") is False,
                  f"{label}: worker cleanup")


def check_lifecycle(audit: Audit, plan: dict, binding: dict) -> None:
    report = audit.json(audit.output / "lifecycle" / "lifecycle.json",
                        "lifecycle report")
    descriptor = dict(binding.get("backends", {}).get("ros2-v7", {}))
    descriptor.update(
        backend="ros2-v7",
        version_binding_id=binding.get("binding_id"),
        version_binding_sha256=plan.get("version_binding_sha256"),
    )
    audit.require(report.get("status") == "PASSED", "lifecycle report PASSED")
    audit.require(report.get("backend") == "ros2-v7", "lifecycle V7 backend")
    audit.require(tuple(report.get("target", ())) == TARGET,
                  "lifecycle fixed A/FULL target")
    cases = report.get("cases", [])
    audit.require(len(cases) == 9, "nine lifecycle cases")
    observed = {case.get("mode"): case for case in cases}
    audit.require(set(observed) == set(MODES), "all nine lifecycle modes")
    for mode in MODES:
        case = observed.get(mode, {})
        label = f"lifecycle/{mode}"
        audit.require(case.get("status") == "PASSED", f"{label}: case PASSED")
        value = case.get("result", {})
        row = value.get("row", {})
        audit.require(value.get("backend_binding") == descriptor,
                      f"{label}: V7 descriptor")
        audit.require(row.get("execution_commit") == plan.get("execution_identity"),
                      f"{label}: execution identity")
        expected = "TIMEOUT" if mode.startswith("late_") or mode == "watchdog" else "INFRASTRUCTURE_FAILURE"
        check_no_claims(audit, value, expected, label)
        persisted = audit.json(audit.output / "lifecycle" / mode / "result.json",
                                f"{label} result")
        audit.require(persisted.get("row") == row, f"{label}: persisted row")
        marker = audit.json(audit.output / "lifecycle" / mode / "fault_marker.json",
                            f"{label} marker")
        audit.require(marker.get("backend") == "ros2-v7"
                      and marker.get("backend_id") == descriptor.get("backend_id")
                      and marker.get("backend_sha256") == descriptor.get("backend_sha256")
                      and marker.get("version_binding_id") == descriptor.get("version_binding_id")
                      and marker.get("version_binding_sha256") == descriptor.get("version_binding_sha256"),
                      f"{label}: V7 marker identity")
        audit.require(marker.get("execution_identity") == plan.get("execution_identity")
                      and marker.get("planner_budget_seconds") == 180
                      and marker.get("outer_watchdog_seconds") == 195
                      and marker.get("formal_campaign") is False,
                      f"{label}: marker execution contract")
        module = str(marker.get("worker_module", "")).replace("\\", "/")
        audit.require(module.endswith("experiments/cmr_ros2_search_entry/runner.py"),
                      f"{label}: marker source is V7 runner")
        audit.require(marker.get("source_head") == plan.get("source_head"),
                      f"{label}: marker source head")
        if mode.startswith("late_"):
            fq = value.get("fault_qualification", {})
            audit.require(fq.get("simulated_clock") is True
                          and fq.get("injected_offset_ns") == 180_000_000_000,
                          f"{label}: simulated deadline marker")
        if mode == "watchdog":
            fq = value.get("fault_qualification", {})
            audit.require(fq.get("actual_wall_seconds", 0) >= 195,
                          f"{label}: measured 195 second watchdog")
            audit.require(value.get("worker_exitcode") == -getattr(signal, "SIGKILL", 9),
                          f"{label}: SIGKILL exit")
            audit.require(row.get("timeout_stage") == "outer_watchdog"
                          and row.get("T_total", 0) >= 195,
                          f"{label}: watchdog censoring")


def check_boundary(audit: Audit) -> None:
    boundary = audit.json(audit.output / "boundary.json", "boundary")
    audit.require(boundary.get("status") == "PASSED"
                  and boundary.get("simulated_clock") is True
                  and boundary.get("count") == 11
                  and boundary.get("solver_calls") == 0,
                  "eleven simulated boundary checks")
    audit.require(boundary.get("planner_budget_seconds") == 180
                  and boundary.get("outer_watchdog_seconds") == 195,
                  "boundary budgets")


def check_zero(audit: Audit, root: Path, plan: dict, binding: dict) -> dict:
    report_path = root / "zero_certificate.json"
    if not report_path.is_file() and (root / "zero" / "zero_certificate.json").is_file():
        report_path = root / "zero" / "zero_certificate.json"
    data_root = report_path.parent
    report = audit.json(report_path, "zero-cost report")
    audit.require(report.get("status") == "PASSED", "zero report PASSED")
    audit.require(report.get("population") == "SYNTHETIC_QUALIFICATION"
                  and report.get("core_instances") == 0
                  and report.get("formal_campaign") is False,
                  "zero synthetic population boundary")
    audit.require(report.get("source_head") == plan.get("source_head"),
                  "zero source head")
    audit.require(report.get("version_binding_id") == binding.get("binding_id")
                  and report.get("version_binding_sha256") == plan.get("version_binding_sha256"),
                  "zero binding identity")
    identity = str(report.get("execution_identity", ""))
    audit.require(identity.startswith(str(plan.get("source_head")) + "+synthetic-zero-"),
                  "zero synthetic execution identity")
    audit.require(report.get("process_watchdog_exercised") is False
                  and report.get("unified_candidate_isolated_exercised") is False
                  and report.get("provider_calls") == 0,
                  "zero did not exercise unified/watchdog/provider")
    audit.require(report.get("positive_independent_replays") == 6,
                  "six zero-cost independent replays")

    results = report.get("results", {})
    audit.require(set(results) == set(ARMS), "zero has exactly three arms")
    synthetic = report.get("synthetic_instance", {})
    record = next((item for item in plan.get("records", [])
                   if item.get("instance_id") == TARGET[0]), {})
    source_hash = report.get("source_instance_sha256")
    audit.require(source_hash == record.get("instance_sha256")
                  and synthetic.get("parent_instance_sha256") == source_hash,
                  "original Core source hash unchanged")
    for arm in ARMS:
        item = results.get(arm, {})
        directory = data_root / arm
        value = audit.json(directory / "result.json", f"zero/{arm} result")
        row = value.get("row", {})
        audit.require(row.get('execution_commit') == identity and
                      row.get('instance_id') == synthetic.get('instance_id'),
                      f'zero/{arm}: synthetic result identity')
        descriptor = dict(binding.get('backends', {}).get(arm, {}), backend=arm,
                          version_binding_id=plan.get('version_binding_id'),
                          version_binding_sha256=plan.get('version_binding_sha256'))
        audit.require(all(row.get(key) == expected for key, expected in descriptor.items()),
                      f'zero/{arm}: backend descriptor')
        audit.require(item.get("status") == "OPTIMALITY_CERTIFIED"
                      and row.get("terminal_status") == "OPTIMALITY_CERTIFIED",
                      f"zero/{arm}: certified")
        try:
            audit.require(Fraction(str(item.get("objective"))) == 0
                          and Fraction(str(row.get("objective"))) == 0
                          and Fraction(str(row.get("certificate_objective"))) == 0,
                          f"zero/{arm}: exact Fraction zero objective")
        except (ValueError, TypeError):
            audit.errors.append(f"zero/{arm}: invalid objective")
        audit.require(item.get("suffix_edges", 0) > 0,
                      f"zero/{arm}: nonempty suffix")
        row_without_hash = dict(row)
        result_hash = row_without_hash.pop("result_hash", None)
        audit.require(result_hash == digest_bytes(
            canonical(row_without_hash).encode("utf-8")),
                      f"zero/{arm}: result bytes/hash")
        cert_path = row.get("certificate_path")
        try:
            cert = safe_child(directory, "certificates/" + str(cert_path))
            cert_sha = digest(cert) if cert.is_file() else ""
            audit.require(cert_sha == row.get("certificate_hash") == item.get("certificate_hash"),
                          f"zero/{arm}: certificate bytes/hash")
        except ValueError as error:
            audit.errors.append(str(error))
        replay = audit.json(directory / "certificate_replay.json",
                            f"zero/{arm} certificate replay")
        try:
            audit.require(replay.get("status") == "PASS"
                          and Fraction(str(replay.get("objective"))) == 0
                          and replay.get("certificate_hash") == row.get("certificate_hash")
                          and item.get("replay") == replay,
                          f"zero/{arm}: replay PASS and zero objective")
        except (ValueError, TypeError):
            audit.errors.append(f"zero/{arm}: invalid replay objective")

    negatives = report.get("rejected_certificate_checks", [])
    audit.require({item.get("case") for item in negatives}
                  == {"objective_plus_one", "empty_suffix"}
                  and all(item.get("status") == "REJECTED" for item in negatives),
                  "two mutated certificates rejected")
    original_hash = next(iter(results.values()), {}).get("certificate_hash")
    for item in negatives:
        path = data_root / "negative_certificates" / (item.get("case", "") + ".json")
        actual = digest(path) if path.is_file() else ""
        audit.require(actual == item.get("sha256") and actual != original_hash,
                      f"negative certificate SHA: {item.get('case')}")
    return report


def main(output: Path, zero_output: Path | None = None) -> int:
    if not output.is_dir():
        raise SystemExit(f"output directory does not exist: {output}")
    audit = Audit(output)
    plan, binding = check_plan_and_binding(audit, output, "lifecycle")
    check_lifecycle(audit, plan, binding)
    check_boundary(audit)
    zero_root = zero_output or (output / "zero")
    independent_zero_plan = (zero_root / "plan.json").is_file()
    if independent_zero_plan:
        zero_plan, zero_binding = check_plan_and_binding(audit, zero_root, "zero")
        audit.require(zero_plan.get("source_closure") == plan.get("source_closure"),
                      "zero/lifecycle source closure bytes match")
    else:
        zero_plan, zero_binding = plan, binding
    zero_report = check_zero(audit, zero_root, zero_plan, zero_binding)
    report = {
        "schema": "cmr-search-entry-lifecycle-readback-v1",
        "status": "PASSED" if not audit.errors else "FAILED",
        "output": str(output),
        "zero_output": str(zero_root),
        "independent_zero_plan": independent_zero_plan,
        "lifecycle_source_head": plan.get("source_head"),
        "zero_source_head": zero_plan.get("source_head"),
        "lifecycle_execution_identity": plan.get("execution_identity"),
        "zero_plan_execution_identity": zero_plan.get("execution_identity"),
        "zero_execution_identity": zero_report.get("execution_identity"),
        "reader_sha256": digest(Path(__file__).resolve()),
        "checks": audit.checked,
        "failures": audit.errors,
        "lifecycle_modes": list(MODES),
        "target": list(TARGET),
        "arms": list(ARMS),
        "solver_provider_ros_calls": 0,
    }
    (output / "lifecycle_readback.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if not audit.errors else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zero-output", type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.output, args.zero_output))
