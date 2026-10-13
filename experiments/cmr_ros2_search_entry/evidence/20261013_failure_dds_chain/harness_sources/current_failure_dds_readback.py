"""Read back the isolated V7 DDS failure qualification.

This reader is intentionally stdlib-only.  It does not import the runner,
ROS, DDS, solver, provider, or certificate verifier; it checks only the
persisted plan, artifacts, result envelopes, and synthetic offline evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SOURCE_HEAD = "6f60801afaed3da950c8d9d0646669f7777a6623"
EXPECTED_OLD_SOURCE_HEAD = "8da048a6efc4061230ae8f2f0f1ee1211e6dfdbd"
EXPECTED_BINDING_ID = "CMR_SEARCH_ENTRY_V1-2325092433cf5abc"
ARMS = ("reference", "ros2-v6", "ros2-v7")
CASES = {
    "late_delivery": "TIMEOUT",
    "crash": "INFRASTRUCTURE_FAILURE",
    "server_error": "ERROR",
    "none": "INFEASIBLE_CERTIFIED",
}
FAILURE_CELLS = (("A-T1-M0-A-S-BRANCH", "FULL"), ("D1-1", "FULL"))
PROOF_FIELDS = (
    "infeasibility_certificate_type", "infeasibility_proof_basis",
    "infeasibility_precision", "lower_precision_infeasibility",
)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"cannot read JSON: {path}") from exc


def checked(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


WSL_PREFIX: Path | None = None


def native_path(value: str | Path) -> Path:
    text = str(value)
    match = re.match(r"^/mnt/([A-Za-z])/(.*)$", text)
    if match:
        text = match.group(1).upper() + ":/" + match.group(2)
    if text.startswith("/tmp/") and WSL_PREFIX is not None:
        text = str(WSL_PREFIX / "tmp" / text[5:])
    path = Path(text)
    return path if path.is_absolute() else (ROOT / path)


def check_plan(output: Path, expected_source_head: str = EXPECTED_SOURCE_HEAD,
               check_current_source: bool = True) -> tuple[dict[str, Any], dict[str, Any], Path]:
    plan = read(output / "plan.json")
    checked(plan.get("schema") == "cmr-search-entry-plan-v1", "plan schema")
    checked(plan.get("scope") == "CMR_SEARCH_ENTRY_DDS_FAILURE_QUALIFICATION",
            "DDS failure scope")
    checked(plan.get("source_head") == expected_source_head, "source head")
    checked(plan.get("formal_campaign") is False, "formal campaign disabled")
    checked(plan.get("planner_budget_seconds") == 180 and
            plan.get("outer_watchdog_seconds") == 195, "plan budgets")
    checked(plan.get("backends") == list(ARMS), "plan backend set")
    checked(plan.get("expected_method_workers") == 4 and
            plan.get("attempts_per_cell_backend") == 1, "failure worker count")
    checked([(c.get("instance_id"), c.get("method")) for c in plan.get("cells", [])]
            == list(FAILURE_CELLS), "fixed failure cells")
    checked(len(plan.get("records", [])) == 6, "five original plus D1 record bindings")

    body = dict(plan)
    execution = body.pop("execution_identity", None)
    expected_execution = str(plan.get("source_head")) + "+cmr-search-entry-" + sha256_bytes(
        canonical(body).encode("utf-8"))[:16]
    checked(execution == expected_execution, "canonical execution identity")

    binding_path = native_path(plan.get("version_binding_path", ""))
    checked(binding_path.is_file(), "version binding exists")
    binding_raw = binding_path.read_bytes()
    checked(sha256_bytes(binding_raw) == plan.get("version_binding_sha256"),
            "version binding SHA matches plan")
    binding = read(binding_path)
    binding_body = dict(binding)
    binding_id = binding_body.pop("binding_id", None)
    expected_binding = "CMR_SEARCH_ENTRY_V1-" + sha256_bytes(
        canonical(binding_body).encode("utf-8"))[:16]
    checked(binding_id == expected_binding == plan.get("version_binding_id") == EXPECTED_BINDING_ID,
            "binding canonical identity")
    checked(binding.get("schema") == "cmr-search-entry-binding-v1", "binding schema")
    checked(binding.get("source_closure") == plan.get("source_closure"),
            "plan/binding source closure")
    for key in ("receipt_sha256", "original_execution_binding_sha256", "manifest_sha256"):
        checked(binding.get(key) == plan.get(key), "binding authority field: " + key)
    checked(len(plan.get("source_closure", {})) == 56, "56-file source closure")
    for arm in ARMS:
        row = binding.get("backends", {}).get(arm)
        checked(isinstance(row, dict) and isinstance(row.get("backend_id"), str)
                and isinstance(row.get("backend_sha256"), str),
                "backend descriptor: " + arm)

    before = read(output / "frozen_inputs_before.json")
    after = read(output / "frozen_inputs_after.json")
    checked(before == after and len(before) == 61, "61 frozen inputs before/after")
    frozen_root = output / "frozen_adapter"
    for relative, expected in plan["source_closure"].items():
        frozen = frozen_root / relative
        checked(frozen.is_file() and digest(frozen) == expected,
                "frozen source bytes: " + relative)
        if check_current_source:
            current = ROOT / relative
            checked(current.is_file() and digest(current) == expected,
                    "current source bytes: " + relative)
    return plan, binding, binding_path


def check_descriptor(descriptor: dict[str, Any], binding: dict[str, Any],
                     plan: dict[str, Any], arm: str) -> None:
    declared = binding["backends"][arm]
    checked(descriptor.get("backend") == arm, "descriptor backend: " + arm)
    checked(descriptor.get("backend_id") == declared["backend_id"] and
            descriptor.get("backend_sha256") == declared["backend_sha256"],
            "descriptor implementation: " + arm)
    checked(descriptor.get("version_binding_id") == plan["version_binding_id"] and
            descriptor.get("version_binding_sha256") == plan["version_binding_sha256"],
            "descriptor binding identity: " + arm)


def check_reference(reference: dict[str, Any], binding: dict[str, Any],
                    plan: dict[str, Any]) -> dict[str, Any]:
    checked(reference.get("backend_binding", {}).get("backend") == "reference",
            "D1 reference backend")
    descriptor = reference["backend_binding"]
    check_descriptor(descriptor, binding, plan, "reference")
    checked(str(descriptor.get("backend_id", "")).startswith("ECC"),
            "D1 original ECC backend identity")
    row = reference.get("row")
    checked(isinstance(row, dict), "D1 reference row")
    checked(row.get("instance_id") == "D1-1" and row.get("method") == "FULL",
            "D1 reference cell")
    checked(row.get("terminal_status") == "INFEASIBLE_CERTIFIED",
            "D1 reference verdict")
    checked(reference.get("transport") is None and row.get("transport") is None,
            "D1 reference transport absent")
    checked(row.get("execution_commit") == plan["execution_identity"],
            "D1 reference execution identity")
    return row


def _result_from_case(case_dir: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    driver = artifact.get("driver", {})
    result = driver.get("result")
    checked(isinstance(result, dict), "persistent driver result")
    dds_result = case_dir / "cmr_attempt" / "dds_result.json"
    if dds_result.is_file():
        checked(read(dds_result) == result, "DDS result/driver result bytes")
    return result


CASE_CELLS = {
    "late_delivery": ("A-T1-M0-A-S-BRANCH", "FULL"),
    "crash": ("A-T1-M0-A-S-BRANCH", "FULL"),
    "server_error": ("A-T1-M0-A-S-BRANCH", "FULL"),
    "none": ("D1-1", "FULL"),
}


def check_case(output: Path, wrapper: dict[str, Any], descriptor: dict[str, Any],
               plan: dict[str, Any], reference_row: dict[str, Any],
               case_plan: dict[str, Any]) -> None:
    mode = wrapper.get("mode")
    expected = CASES.get(mode)
    checked(expected is not None and wrapper.get("expected_terminal") == expected,
            "fixed DDS failure case: " + str(mode))
    artifact = wrapper.get("artifact")
    checked(isinstance(artifact, dict) and artifact.get("status") == "PASSED",
            "case status: " + str(mode))
    request = artifact.get("request")
    checked(isinstance(request, dict), "case request: " + str(mode))
    instance_id, method = CASE_CELLS[mode]
    checked(request.get("instance_id") == instance_id and request.get("method") == method and
            request.get("backend") == "ros2-v7", "D1 failure request envelope")
    checked(request.get("execution_identity") == case_plan["execution_identity"] and
            request.get("planner_budget_seconds") == 180 and
            request.get("outer_watchdog_seconds") == 195 and
            request.get("formal_campaign") is False, "failure request identity/budget")
    checked(artifact.get("descriptor") == descriptor, "case V7 descriptor")
    check_descriptor(artifact.get("descriptor", {}), descriptor_to_binding(descriptor),
                     plan, "ros2-v7")
    case_dir = output / ("dds_" + mode)
    checked(case_dir.is_dir(), "case directory: " + mode)
    persisted_artifact = read(case_dir / "dds_artifact.json")
    checked(persisted_artifact == artifact, "persisted DDS artifact: " + mode)
    result = _result_from_case(case_dir, artifact)
    checked(result.get("instance_id") == instance_id and result.get("method") == method and
            result.get("backend") == "ros2-v7" and
            result.get("terminal_status") == expected, "D1 failure result envelope")
    checked(result.get("backend_binding") == descriptor, "D1 V7 result descriptor")
    checked(result.get("transport") is None and result.get("target") is None,
            "D1 failure target/transport absent")
    checked(result.get("objective") is None and result.get("concrete_lasso") is None,
            "failure result has no executable payload")
    checked(result.get("certificate_verifier_status") == "NOT_AVAILABLE" and
            result.get("certificate_valid_for_terminal") is False,
            "failure result certificate state")
    checked(result.get("right_censored") is (expected == "TIMEOUT"),
            "failure right censoring")
    if expected != 'ERROR':
        checked(result.get('planner_budget_seconds') == 180 and
                result.get('outer_watchdog_seconds') == 195, 'result budgets')
        elapsed = (result['terminal_completion_ns'] - result['method_start_ns']) / 1e9
        checked(result.get('T_total') == elapsed, 'result observed elapsed identity')
        if expected == 'TIMEOUT':
            checked(elapsed >= 180 and result.get('timing_status') == 'RIGHT_CENSORED',
                    'timeout threshold and timing status')
        else:
            checked(0 <= elapsed < 180 and result.get('timing_status') ==
                    ('ANOMALY' if expected=='INFRASTRUCTURE_FAILURE' else 'UNCENSORED'),
                    'on-time or infrastructure timing status')
    if expected in ("TIMEOUT", "INFRASTRUCTURE_FAILURE", "ERROR"):
        for field in PROOF_FIELDS:
            checked(result.get(field) is None, "failure proof field cleared: " + field)
        checked(all(r.get('terminal_claim_valid') is False and
                    all(r.get(field) is None for field in PROOF_FIELDS)
                    for r in result.get('rounds') or []), 'failure round claims cleared')

    server_pid, driver_pid = artifact.get("server_pid"), artifact.get("driver_pid")
    checked(all(isinstance(pid, int) and pid > 0 for pid in (server_pid, driver_pid))
            and server_pid != driver_pid, "independent server/driver PIDs")
    checked(artifact.get("server_rc") == 0 and artifact.get("driver_rc") == 0,
            "server/driver cleanup return codes")
    worker_pid = result.get("worker_pid")
    if expected == "ERROR":
        checked(worker_pid is None and result.get("worker_exitcode") is None,
                "server error dispatched no worker")
    else:
        checked(isinstance(worker_pid, int) and worker_pid > 0 and
                worker_pid not in (server_pid, driver_pid), "independent worker PID")
        checked(result.get("worker_alive_after_cleanup") is False, "worker cleanup")
        checked(result.get("worker_exitcode") == (23 if expected == "INFRASTRUCTURE_FAILURE" else 0),
                "worker exit code")
    driver = artifact.get("driver", {})
    checked(driver.get("module_identity_match") is True, "DDS driver module identity")
    module_path = artifact.get("module")
    if isinstance(module_path, str):
        module_file = native_path(module_path)
        checked(module_file.name == "dds.py" and module_file.is_file() and
                digest(module_file) == digest(ROOT / "experiments/cmr_ros2_search_entry/dds.py"),
                "DDS module source SHA")
    checked(driver.get("completion_count") == 0 and
            driver.get("observer_feedback_count") == 0 and
            driver.get("abstraction_feedback_count") == 0, "failure feedback counts")
    checked(driver.get("ts_state_receive_count") == (1 if expected == "TIMEOUT" else 0),
            "failure TS feedback count")
    checked(not any(event.get("event") == "snapshot_served"
                    for event in artifact.get("server", {}).get("events", [])),
            "failure snapshot not served")
    checked(not driver.get("commands"), "failure command dispatch")

    marker = case_dir / "cmr_attempt" / "fault_marker.json"
    if mode in ("late_delivery", "crash"):
        checked(marker.is_file(), "V7 fault marker: " + mode)
        marker_value = read(marker)
        checked(marker_value.get("backend") == "ros2-v7" and
                marker_value.get("execution_identity") == case_plan["execution_identity"] and
                marker_value.get("version_binding_id") == case_plan["version_binding_id"],
                "V7 fault marker identity: " + mode)
    if mode == "late_delivery":
        clock = case_dir / "cmr_attempt" / "fault_clock.json"
        checked(clock.is_file(), "late delivery fault clock")
        clock_value = read(clock)
        qualification = read(case_dir / "cmr_attempt" / "fault_qualification.json")
        checked(clock_value.get("simulated_clock") is True and
                (clock_value.get("offset_ns") == 180_000_000_000 or
                 qualification.get("injected_offset_ns") == 180_000_000_000),
                "late delivery offset")

    if expected == "INFEASIBLE_CERTIFIED":
        for field in PROOF_FIELDS:
            checked(result.get(field) == reference_row.get(field),
                    "V7/reference D1 proof field: " + field)
        checked(result.get("infeasibility_certificate_type") ==
                "REDUCED_PRODUCT_EXACT_EMPTY", "D1 exact-empty proof")


def descriptor_to_binding(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Adapt a V7 descriptor to the binding shape used by check_descriptor."""
    return {"backends": {"ros2-v7": {
        "backend_id": descriptor.get("backend_id"),
        "backend_sha256": descriptor.get("backend_sha256")}},
            "binding_id": descriptor.get("version_binding_id")}


def check_continuation(output: Path, dds_root: Path, report: dict[str, Any],
                       plan: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    continuation = report.get("continuation")
    checked(isinstance(continuation, dict), "continuation metadata")
    checked(continuation.get("method_workers") == 2 and
            continuation.get("dds_cases") == 2, "continuation worker/case counts")
    old_root = native_path(continuation.get("original_root", ""))
    checked(old_root.is_dir(), "continuation original root")
    old_plan_path = old_root / "plan.json"
    checked(digest(old_plan_path) == continuation.get("original_plan_sha256"),
            "continuation original plan SHA")
    old_plan, old_binding, _ = check_plan(
        old_root, expected_source_head=EXPECTED_OLD_SOURCE_HEAD,
        check_current_source=False)
    checked(old_plan["source_closure"] == plan["source_closure"] and
            len(old_plan["source_closure"]) == 56,
            "old/new source closure identity")
    checked(old_plan["execution_identity"] != plan["execution_identity"],
            "old/new execution identities remain distinct")
    checked(old_binding.get("binding_id") == binding.get("binding_id") == EXPECTED_BINDING_ID and
            old_plan.get("version_binding_sha256") == plan.get("version_binding_sha256"),
            "continuation binding identity")
    files = continuation.get("files")
    checked(isinstance(files, dict) and files, "continuation file ledger")
    for relative, expected in files.items():
        old_file = old_root / relative
        new_file = output.parent / relative if output.name == "dds_failures" else output / relative
        checked(old_file.is_file() and digest(old_file) == expected,
                "old continuation bytes: " + relative)
        checked(new_file.is_file() and digest(new_file) == expected,
                "copied continuation bytes: " + relative)
    old_report_path = old_root / "dds_failures" / "failure_dds_report.json"
    old_report = read(old_report_path)
    checked(old_report.get("status") == "FAILED", "original continuation report failed")
    old_passed = {case.get("mode") for case in old_report.get("cases", [])
                  if case.get("artifact", {}).get("status") == "PASSED"}
    checked(old_passed == {"server_error", "none"},
            "original continuation passed modes")
    checked(old_report.get("descriptor") == report.get("descriptor"),
            "continuation descriptor")
    return old_plan


def check_offline_chain(output: Path, plan: dict[str, Any], descriptor: dict[str, Any]) -> dict[str, Any]:
    reports = list(output.rglob("offline_chain_evidence.json"))
    checked(reports, "offline_chain_evidence.json present")
    report_path = reports[0]
    report = read(report_path)
    checked(report.get("schema") == "cmr-search-entry-v7-offline-chain-qualification-v1" and
            report.get("status") == "PASSED" and report.get("v7_synthetic") is True,
            "V7 synthetic offline status")
    checked(report.get("real_results") == 0 and report.get("certificate_worker_calls") == 0 and
            report.get("provider_calls") == 0 and report.get("formal_campaign") is False,
            "synthetic/real/provider boundary")
    checked(report.get("provenance_kind") == "SYNTHETIC_OFFLINE_ONLY" and
            report.get("analysis", {}).get("synthetic_label") ==
            "SYNTHETIC_ANALYSIS_PIPELINE_VALIDATION_ONLY" and
            report.get("version_binding", {}).get("binding_id") == plan["version_binding_id"] and
            report.get("version_binding", {}).get("sha256") == plan["version_binding_sha256"],
            "synthetic V7 descriptor binding")
    v7_meta = report.get("v7_metadata", {})
    checked(v7_meta.get("scope") == "CMR_SEARCH_ENTRY_OFFLINE_CHAIN_V7" and
            v7_meta.get("backend") == "ros2-v7" and
            v7_meta.get("provenance") == "SYNTHETIC_SEARCH_ENTRY_V7_OFFLINE_ONLY" and
            v7_meta.get("version_binding_id") == plan["version_binding_id"],
            "independent V7 offline metadata")
    frozen_markers = report.get("frozen_synthetic_markers", {})
    checked(frozen_markers.get("fixture_label") ==
            "SYNTHETIC_ANALYSIS_PIPELINE_VALIDATION_ONLY" and
            frozen_markers.get("provenance_kind") == "SYNTHETIC_OFFLINE_ONLY",
            "frozen synthetic markers")
    checked(report.get("source_rebinding", {}).get("replacement_count") == 6 and
            report.get("source_rebinding", {}).get("backend_literal_count") == 5 and
            report.get("source_rebinding", {}).get("scope_literal_count") == 1,
            "synthetic AST rebinding count")
    closure = report.get("runtime_source_closure", {})
    checked(closure.get("files") == 56 and closure.get("before_after_equal") is True,
            "synthetic source closure before/after")
    formal = report.get("actual_formal_driver_commit_chain", {})
    checked(formal.get("formal_execution") == "UNRUN" and
            formal.get("publication_probe", {}).get("status") == "UNRUN" and
            formal.get("publication_probe", {}).get("full_campaign_chain") == "UNVERIFIED",
            "formal/publication probe boundary")
    schedule = report.get("schedule", {})
    checked(schedule.get("cells") == 510 and schedule.get("unique_keys") == 510 and
            set(schedule.get("methods", [])) == {"FULL", "AP-D", "DEP-D"},
            "synthetic 510 schedule")
    checked(report.get("result_chain", {}).get("committed") == 510,
            "synthetic ledger committed count")
    ledger_files = [report_path.parent / "result_chain" / "ledger.json"]
    ledger_files.extend(path for path in report_path.parent.rglob("ledger.json")
                        if path not in ledger_files)
    ledger_files = [path for path in ledger_files if path.is_file()]
    checked(ledger_files, "synthetic result-chain ledger present")
    ledger = read(ledger_files[0])
    committed = ledger.get("committed")
    checked(isinstance(committed, dict) and len(committed) == 510 and
            len(set(committed)) == 510, "synthetic ledger committed 510 records")
    for key, record in committed.items():
        checked(record.get("key") == key and
                record.get("method") in {"FULL", "AP-D", "DEP-D"} and
                record.get("backend") == "ros2-v7" and
                record.get("provenance_kind") == "SYNTHETIC_OFFLINE_ONLY" and
                record.get("version_binding_id") == plan["version_binding_id"],
                "synthetic ledger record identity")
    row_files = list(report_path.parent.rglob("synthetic_results.jsonl"))
    checked(row_files, "synthetic results JSONL present")
    rows = [json.loads(line) for line in row_files[0].read_text(encoding="utf-8").splitlines()
            if line.strip()]
    checked(len(rows) == 510, "510 synthetic rows")
    keys = {(row.get("instance_id"), row.get("method")) for row in rows}
    checked(len(keys) == 510 and all(row.get("backend") == "ros2-v7" for row in rows),
            "synthetic unique rows/V7 backend")
    for row in rows:
        checked(row.get("fixture_label") == "SYNTHETIC_ANALYSIS_PIPELINE_VALIDATION_ONLY" and
                row.get("provenance_kind") == "SYNTHETIC_OFFLINE_ONLY" and
                row.get("v7_scope") == "CMR_SEARCH_ENTRY_OFFLINE_CHAIN_V7" and
                row.get("v7_provenance") == "SYNTHETIC_SEARCH_ENTRY_V7_OFFLINE_ONLY" and
                row.get("v7_version_binding_id") == plan["version_binding_id"] and
                row.get("formal_campaign") is False and row.get("provider_calls") == 0,
                "synthetic row provenance")
        claimed = row.get("result_hash")
        checked(isinstance(claimed, str), "synthetic row result_hash")
        body = dict(row)
        body.pop("result_hash", None)
        checked(claimed == sha256_bytes(canonical(body).encode("utf-8")),
                "synthetic row canonical result_hash")
    return {"path": str(report_path), "rows": 510, "ledger_committed": 510}


def main(output_value: str | Path) -> dict[str, Any]:
    global WSL_PREFIX
    raw = str(output_value)
    unc = re.match(r"^(\\\\wsl(?:\.localhost)?\\[^\\/]+)(?:[\\/]tmp[\\/])",
                   raw, re.IGNORECASE)
    if unc:
        WSL_PREFIX = Path(unc.group(1))
    output = native_path(output_value)
    checked(output.is_dir(), "failure DDS output directory")
    plan, binding, _ = check_plan(output)
    v7_descriptor = {
        "backend": "ros2-v7",
        "backend_id": binding["backends"]["ros2-v7"]["backend_id"],
        "backend_sha256": binding["backends"]["ros2-v7"]["backend_sha256"],
        "version_binding_id": plan["version_binding_id"],
        "version_binding_sha256": plan["version_binding_sha256"],
    }
    dds_roots = [output / "dds_failures", output]
    dds_root = next((root for root in dds_roots
                     if (root / "failure_dds_report.json").is_file()), None)
    checked(dds_root is not None, "failure_dds_report.json present")
    report = read(dds_root / "failure_dds_report.json")
    checked(report.get("status") == "PASSED", "failure DDS report status")
    checked(report.get("source_head") == plan["source_head"] and
            report.get("execution_identity") == plan["execution_identity"] and
            report.get("planner_budget_seconds") == 180 and
            report.get("outer_watchdog_seconds") == 195 and
            report.get("formal_campaign") is False and
            report.get("provider_calls") == 0, "failure report identity/budget")
    checked(report.get("expected_method_workers") == 4 and
            report.get("method_workers") == 4 and
            report.get("new_method_workers") == 2 and
            report.get("new_dds_cases") == 2 and
            report.get("dds_cases") == 4, "continuation worker/case totals")
    check_descriptor(report.get("descriptor", {}), binding, plan, "ros2-v7")
    old_plan = check_continuation(output, dds_root, report, plan, binding)
    reference_row = check_reference(report.get("reference", {}), binding, old_plan)
    wrappers = {case.get("mode"): case for case in report.get("cases", [])}
    checked(set(wrappers) == set(CASES) and len(wrappers) == 4, "four fixed DDS cases")
    for mode in CASES:
        case_plan = old_plan if mode in {"server_error", "none"} else plan
        check_case(dds_root, wrappers[mode], v7_descriptor, case_plan,
                   reference_row, case_plan)
    offline = check_offline_chain(output, plan, v7_descriptor)
    result = {
        "schema": "cmr-search-entry-v7-failure-dds-readback-v1",
        "status": "PASSED", "source_head": plan["source_head"],
        "execution_identity": plan["execution_identity"],
        "version_binding_id": plan["version_binding_id"],
        "source_closure_files": 56, "frozen_inputs": 61,
        "dds_cases": 4, "offline_synthetic_rows": offline["rows"],
        "offline_real_results": 0, "provider_calls": 0,
    }
    (output / "failure_dds_readback.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    main(parser.parse_args().output)
