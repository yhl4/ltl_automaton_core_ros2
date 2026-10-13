#!/usr/bin/env python3
import cProfile
import functools
import hashlib
import json
import os
from pathlib import Path
import pstats
import sys
import time
import traceback

CLONE = Path("/tmp/cmr_v8_ap_ts_source_db82366_20261013")
RUN = Path("/tmp/cmr_v8_ap_ts_reuse_20261013")
OUT = Path("/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v8_entry_timing_20261013")
TARGET = RUN / "ros2-v8"

sys.path.insert(0, str(CLONE / "ltl_automaton_execution"))
sys.path.insert(0, str(CLONE / "ltl_automaton_planner"))
sys.path.insert(0, str(CLONE / "ltl_automaton_planner_core"))
sys.path.insert(0, str(CLONE))

def load_json(path):
    return json.loads(Path(path).read_bytes())

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def phase_seconds(row, key):
    interval = (row.get("phase_intervals_ns") or {}).get(key)
    if not interval:
        return None
    return (int(interval[1]) - int(interval[0])) / 1e9

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = load_json(RUN / "plan.json")
    binding_path = Path(plan["version_binding_path"])
    receipt_path = Path(plan["authority_receipt"])
    receipt = load_json(receipt_path)

    import experiments.cmr_ros2_ap_ts_reuse.runner as v8

    calls = {}
    originals = []

    def wrap(obj, attr, label):
        original = getattr(obj, attr)
        originals.append((obj, attr, original))
        @functools.wraps(original)
        def timed(*args, **kwargs):
            start = time.perf_counter_ns()
            item = calls.setdefault(label, {"count": 0, "elapsed_seconds": 0.0,
                                            "elapsed_ns": 0, "exceptions": 0})
            item["count"] += 1
            try:
                return original(*args, **kwargs)
            except Exception:
                item["exceptions"] += 1
                raise
            finally:
                elapsed = time.perf_counter_ns() - start
                item["elapsed_ns"] += elapsed
                item["elapsed_seconds"] += elapsed / 1e9
        setattr(obj, attr, timed)

    wrap(v8, "load_binding", "load_binding")
    wrap(v8, "source_closure", "source_closure")
    wrap(v8, "implementations", "implementations")
    wrap(v8, "describe", "describe")
    wrap(v8, "schema_for", "schema_for")
    wrap(v8.backend, "identity", "v8.backend.identity")
    wrap(v8.v7, "identity", "v7.identity")

    worker_wrapper = load_json(TARGET / "worker_result.json")
    worker_row = worker_wrapper["row"]
    final_wrapper = load_json(TARGET / "result.json")
    final_row = final_wrapper["row"]
    raw_row = load_json(TARGET / "runner_raw_result.json")

    profile_path = OUT / "control_plane.prof"
    profile = cProfile.Profile()
    profile.enable()
    phases = {}
    try:
        start = time.perf_counter_ns()
        descriptor = v8.describe(binding_path, "ros2-v8")
        phases["describe_seconds"] = (time.perf_counter_ns() - start) / 1e9

        start = time.perf_counter_ns()
        worker_schema = v8.schema_for(receipt, "ros2-v8")
        phases["schema_for_worker_seconds"] = (time.perf_counter_ns() - start) / 1e9
        start = time.perf_counter_ns()
        worker_schema.validate_result(worker_row)
        phases["validate_worker_seconds"] = (time.perf_counter_ns() - start) / 1e9

        start = time.perf_counter_ns()
        final_schema = v8.schema_for(receipt, "ros2-v8")
        phases["schema_for_final_seconds"] = (time.perf_counter_ns() - start) / 1e9
        start = time.perf_counter_ns()
        final_schema.validate_result(final_row)
        phases["validate_final_seconds"] = (time.perf_counter_ns() - start) / 1e9
    finally:
        profile.disable()
        profile.dump_stats(str(profile_path))
        for obj, attr, original in reversed(originals):
            setattr(obj, attr, original)

    profile_full = OUT / "control_plane_profile_full.txt"
    with profile_full.open("w", encoding="utf-8", newline="\n") as f:
        stats = pstats.Stats(str(profile_path), stream=f)
        stats.strip_dirs().sort_stats("cumulative").print_stats()
    profile_top = OUT / "control_plane_profile_top10.txt"
    with profile_top.open("w", encoding="utf-8", newline="\n") as f:
        stats = pstats.Stats(str(profile_path), stream=f)
        stats.strip_dirs().sort_stats("cumulative").print_stats(10)

    metrics = {
        "profile_scope": {
            "run_one": 0,
            "verifier": 0,
            "DDS": 0,
            "provider": 0,
            "schema_validation_is_independent_P2E": False,
        },
        "source": {
            "clone": str(CLONE),
            "head": "db8236614c8ce4c876844127c8ce9df01c5d8507",
            "run": str(RUN),
            "binding_path": str(binding_path),
            "binding_sha256": sha(binding_path),
            "authority_receipt": str(receipt_path),
        },
        "control_plane": {
            "backend": "ros2-v8",
            "descriptor": descriptor,
            "phases_seconds": phases,
            "calls": calls,
        },
        "schema_validation": {
            "worker_result": {"status": "PASS", "row_result_hash": worker_row.get("result_hash")},
            "final_result": {"status": "PASS", "row_result_hash": final_row.get("result_hash")},
            "schema_binding_ids": [
                getattr(worker_schema, "binding_id", None),
                getattr(final_schema, "binding_id", None),
            ],
        },
        "timing_from_persisted_rows": {
            "raw_runner_result": {
                "T_other": raw_row.get("T_other"),
                "T_total": raw_row.get("T_total"),
                "T_certification": raw_row.get("T_certification"),
            },
            "worker_result": {
                "T_other": worker_row.get("T_other"),
                "T_total": worker_row.get("T_total"),
                "T_certification": worker_row.get("T_certification"),
            },
            "final_result": {
                "T_other": final_row.get("T_other"),
                "T_total": final_row.get("T_total"),
                "post_runner_delivery_seconds": final_row.get("post_runner_delivery_seconds"),
                "ROS_result_delivery_seconds": phase_seconds(final_row, "ROS_result_delivery"),
                "T_certification": final_row.get("T_certification"),
                "T_logging": final_row.get("T_logging"),
            },
            "derived": {
                "core_T_other_from_runner_raw_result": raw_row.get("T_other"),
                "worker_minus_core_T_other": (
                    worker_row.get("T_other") - raw_row.get("T_other")
                    if isinstance(worker_row.get("T_other"), (int, float))
                    and isinstance(raw_row.get("T_other"), (int, float)) else None),
                "final_minus_core_T_other": (
                    final_row.get("T_other") - raw_row.get("T_other")
                    if isinstance(final_row.get("T_other"), (int, float))
                    and isinstance(raw_row.get("T_other"), (int, float)) else None),
                "post_runner_delivery_seconds": final_row.get("post_runner_delivery_seconds"),
                "ROS_result_delivery_seconds": phase_seconds(final_row, "ROS_result_delivery"),
                "cert_external_interval_seconds": phase_seconds(final_row, "T_certification_external"),
            },
        },
        "raw_files": {
            "runner_raw_result.json": sha(TARGET / "runner_raw_result.json"),
            "worker_result.json": sha(TARGET / "worker_result.json"),
            "result.json": sha(TARGET / "result.json"),
        },
    }
    (OUT / "control_plane_timing.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "status": "PASSED",
        "top10_profile": str(profile_top),
        "phases_seconds": phases,
        "calls": calls,
        "timing": metrics["timing_from_persisted_rows"]["derived"],
    }, sort_keys=True))
    print(profile_top.read_text(encoding="utf-8"))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise

