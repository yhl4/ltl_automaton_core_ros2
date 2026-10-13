#!/usr/bin/env python3
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import subprocess
import sys
import time
import traceback

CLONE = Path("/tmp/cmr_v8_entry_source_111ae6c_20261013")
RUN = Path("/tmp/cmr_v8_entry_timing_20261013")
OUT = Path("/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v8_entry_timing_20261013")
for rel in ("ltl_automaton_execution", "ltl_automaton_planner",
            "ltl_automaton_planner_core", ""):
    sys.path.insert(0, str(CLONE / rel) if rel else str(CLONE))

def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def metric_rows(stats, predicate):
    calls = 0
    primitive = 0
    total = 0.0
    rows = []
    for key, values in stats.items():
        filename, line, func = key
        if predicate(str(filename), int(line), str(func)):
            cc, nc, tt, ct, callers = values
            calls += int(nc)
            primitive += int(cc)
            total += float(ct)
            rows.append({"file": str(filename), "line": int(line),
                         "function": str(func), "calls": int(nc),
                         "cumulative_seconds": float(ct)})
    rows.sort(key=lambda row: row["cumulative_seconds"], reverse=True)
    return {"calls": calls, "primitive_calls": primitive,
            "cumulative_seconds": total, "functions": rows[:20]}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = json.loads((RUN / "plan.json").read_bytes())
    binding_path = Path(plan["version_binding_path"])
    receipt = plan["authority_receipt"]
    kernel = Path("/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel")

    import experiments.cmr_ros2_backend.runner as original

    authority_started = time.perf_counter_ns()
    formal, bound, manifest, records = original.authority(plan, receipt, kernel)
    authority_elapsed = (time.perf_counter_ns() - authority_started) / 1e9

    profile_path = OUT / "preflight_profile.prof"
    profile = cProfile.Profile()
    preflight_started = time.perf_counter_ns()
    profile.enable()
    preflight_error = None
    observed = None
    try:
        observed = formal.preflight()
    except Exception as exc:
        preflight_error = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        profile.disable()
    preflight_elapsed = (time.perf_counter_ns() - preflight_started) / 1e9
    profile.dump_stats(str(profile_path))

    full_path = OUT / "preflight_profile_full.txt"
    with full_path.open("w", encoding="utf-8", newline="\n") as f:
        pstats.Stats(str(profile_path), stream=f).strip_dirs().sort_stats("cumulative").print_stats()
    top_path = OUT / "preflight_profile_top10.txt"
    with top_path.open("w", encoding="utf-8", newline="\n") as f:
        pstats.Stats(str(profile_path), stream=f).strip_dirs().sort_stats("cumulative").print_stats(10)

    stats = pstats.Stats(str(profile_path)).stats
    breakdown = {
        "path_resolve": metric_rows(
            stats, lambda file, line, fn: "pathlib.py" in file and fn == "resolve"),
        "source_hashing_read": metric_rows(
            stats, lambda file, line, fn: (
                fn in {"sha256_file", "sha256_bytes", "read_bytes", "openssl_sha256"}
                or ("io" in file and fn in {"read", "open"}))),
        "import_module": metric_rows(
            stats, lambda file, line, fn: (
                fn == "import_module" or "_find_and_load" in fn
                or "_call_with_frames_removed" in fn or fn == "exec_module")),
    }

    worker_timing = json.loads((RUN / "ros2-v8" / "worker_timing.json").read_bytes())
    result = json.loads((RUN / "ros2-v8" / "result.json").read_bytes())
    row = result["row"]
    core = worker_timing["core_timing"]
    selected_core = {}
    for name in ("certificate_canonical_record", "certificate__certificate_payload",
                 "certificate_sha256_file", "certificate_fsync",
                 "certificate_verify_bound_certificate"):
        selected_core[name] = core[name]

    diagnostics = {
        "status": "PASSED" if preflight_error is None else "FAILED",
        "probe_scope": {
            "authority_calls": 1,
            "formal_preflight_calls": 1,
            "configure_calls": 0,
            "run_one_calls": 0,
            "solver_execution_calls": 0,
            "worker_dispatches": 0,
            "verifier_calls": 0,
            "DDS_requests": 0,
            "provider_calls": 0,
            "preflight_is_additional_read_only_probe": True,
        },
        "source": {
            "clone": str(CLONE),
            "head": subprocess.check_output(
                ["git", "-C", str(CLONE), "rev-parse", "HEAD"], text=True).strip(),
            "clone_status": subprocess.check_output(
                ["git", "-C", str(CLONE), "status", "--short"], text=True),
            "plan": str(RUN / "plan.json"),
            "version_binding_path": str(binding_path),
            "version_binding_id": plan["version_binding_id"],
            "version_binding_sha256": plan["version_binding_sha256"],
            "execution_identity": plan["execution_identity"],
            "formal_module": str(getattr(formal, "__module__", "")),
        },
        "authority": {
            "elapsed_seconds": authority_elapsed,
            "manifest_binding_sha256": manifest.get("binding_sha256"),
            "record_count": len(records),
        },
        "preflight": {
            "elapsed_seconds": preflight_elapsed,
            "observed": observed,
            "error": preflight_error,
            "profile_calls": pstats.Stats(str(profile_path)).total_calls,
            "profile_primitive_calls": pstats.Stats(str(profile_path)).prim_calls,
            "breakdown": breakdown,
        },
        "v8_worker_persist_diagnostics": {
            "backend": "ros2-v8",
            "terminal_status": row["terminal_status"],
            "objective": row["objective"],
            "T_total": row["T_total"],
            "T_other": row["T_other"],
            "T_input_preprocess": row["T_input_preprocess"],
            "T_certification": row["T_certification"],
            "post_runner_delivery_seconds": row["post_runner_delivery_seconds"],
            "core_timing": selected_core,
            "run_one_code_preserved": core["original_function_code_preserved"]["run_one"],
            "persist_code_preserved": core["original_function_code_preserved"]["persist_and_verify_certificate"],
        },
        "artifact_hashes": {
            "worker_timing.json": sha(RUN / "ros2-v8" / "worker_timing.json"),
            "result.json": sha(RUN / "ros2-v8" / "result.json"),
            "profile": sha(profile_path),
        },
    }
    output = OUT / "preflight_diagnostics.json"
    output.write_text(json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps({"status": diagnostics["status"],
                      "authority_seconds": authority_elapsed,
                      "preflight_seconds": preflight_elapsed,
                      "profile": str(profile_path),
                      "diagnostics": str(output)}, sort_keys=True))
    print(top_path.read_text(encoding="utf-8"))
    if preflight_error is not None:
        raise SystemExit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise

