#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import traceback

import experiments.cmr_ros2_ap_ts_reuse.runner as v8
from experiments.cmr_ros2_real import runner as real_runner

OUT = Path("/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v8_entry_timing_20261013")
CHECKS = []

def check(name, condition, detail):
    CHECKS.append({"name": name, "status": "PASS" if condition else "FAIL",
                   "detail": detail})

def synthetic_optimal_row(start):
    row = {
        "schema_version": "synthetic-hook-row-v1",
        "terminal_status": "OPTIMALITY_CERTIFIED",
        "canonical_status": "OPTIMALITY_CERTIFIED",
        "exact_status": "OPTIMAL",
        "objective": "12",
        "method_start_ns": start,
        "terminal_completion_ns": start + 1,
        "phase_intervals_ns": {},
        "right_censored": False,
        "timing_status": "UNCENSORED",
        "timeout_stage": "none",
        "certificate_verifier_status": "PASS",
        "certificate_path": "synthetic.json",
        "certificate_hash": "synthetic-hash",
        "certificate_schema": "synthetic-cert",
        "certificate_objective": "12",
        "certificate_valid_for_terminal": True,
        "rounds": [{}],
    }
    for name in ("T_input_preprocess", "T_initialization", "T_full_ts",
                 "T_reduction", "T_product", "T_search", "T_concretization",
                 "T_certification", "T_refinement", "T_logging"):
        row[name] = 0.0
    return row

def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # Exercise the new checked_delivery hook with a fake monotonic clock.
    entry = object.__new__(v8.AttemptEntry)
    entry.timing = {}
    clock = {"value": 1_000}
    original_clock = v8.time.perf_counter_ns
    original_delivery = v8.original.terminal_delivery
    captured = {}

    def fake_clock():
        value = clock["value"]
        clock["value"] += 1
        return value

    def fake_release():
        clock["value"] += 180_000_000_000
        return None

    def fake_delivery(row, completion, *, outer_start, forced_timeout=False):
        captured.update(completion=completion, outer_start=outer_start,
                        forced_timeout=forced_timeout)
        return {"delegated": True}

    v8.time.perf_counter_ns = fake_clock
    v8.original.terminal_delivery = fake_delivery
    entry.release_check = fake_release
    try:
        delegated = entry.checked_delivery(
            {"terminal_status": "OPTIMALITY_CERTIFIED"}, 75,
            outer_start=50, forced_timeout=True)
    finally:
        v8.time.perf_counter_ns = original_clock
        v8.original.terminal_delivery = original_delivery

    checkpoint = entry.timing["delivery_checkpoint"]
    check("checked_delivery_uses_release_completion",
          delegated == {"delegated": True}
          and captured["completion"] == checkpoint["release_completed_ns"]
          and captured["completion"] > 75
          and checkpoint["release_completed_ns"] > checkpoint["release_started_ns"],
          {"captured": captured, "checkpoint": checkpoint})
    check("checked_delivery_preserves_outer_arguments",
          captured.get("outer_start") == 50 and captured.get("forced_timeout") is True,
          captured)

    # Exercise the unchanged real classifier with a synthetic row whose
    # release completion crosses 180 seconds. No sleeping or worker is used.
    start = 1_000_000_000
    row = synthetic_optimal_row(start)
    completion = start + 180_000_001_000
    timeout_row = real_runner.terminal_delivery(
        row, completion, outer_start=77, forced_timeout=False)
    check("synthetic_release_crossing_180s_is_right_censored",
          timeout_row["terminal_status"] == "TIMEOUT"
          and timeout_row["objective"] is None
          and timeout_row["right_censored"] is True
          and timeout_row["timing_status"] == "RIGHT_CENSORED"
          and timeout_row["timeout_stage"] == "planner"
          and timeout_row["certificate_verifier_status"] == "NOT_AVAILABLE"
          and timeout_row["T_total"] == 180.000001,
          {key: timeout_row.get(key) for key in (
              "terminal_status", "objective", "right_censored",
              "timing_status", "timeout_stage",
              "certificate_verifier_status", "T_total")})

    result = {
        "status": "PASSED" if all(c["status"] == "PASS" for c in CHECKS) else "FAILED",
        "scope": {
            "solver": 0,
            "workers": 0,
            "real_waiting_seconds": 0,
            "DDS": 0,
            "provider": 0,
            "formal_run_one": 0,
        },
        "checks": CHECKS,
        "notes": [
            "The first check uses only a fake clock, fake release_check, and fake classifier delegate.",
            "The timeout check uses the original terminal_delivery on a synthetic row; no real 180-second wait.",
            "The existing 111ae6c three-worker outputs were not modified or rerun.",
        ],
    }
    out = OUT / "hook_check.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "checks": len(CHECKS),
                      "output": str(out)}, sort_keys=True))
    if result["status"] != "PASSED":
        raise SystemExit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise

