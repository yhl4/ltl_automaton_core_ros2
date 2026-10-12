"""Read back one isolated CMR search-entry qualification.

This module is deliberately independent of ROS, Spot, and the formal runner.
It only reads persisted JSON/bytes and checks the frozen evidence contract.
Failure artifacts are left untouched for diagnosis.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
ARMS = ("reference", "ros2-v6", "ros2-v7")
TARGETS = (
    ("A-T1-M0-A-S-BRANCH", "FULL"),
    ("B-D-BRANCH-S2", "FULL"),
    ("C3-T4", "AP-D"),
)
WSL_PREFIX = None
SEARCH_COUNTERS = (
    "queue_pushes", "queue_pops", "prefix_settled", "lower_bound_settled",
    "suffix_settled", "candidate_entries", "exact_entry_searches",
    "bound_pruned_entries",
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest(path):
    return sha256_bytes(path.read_bytes())


def read(path):
    return json.loads(path.read_bytes())


def checked(condition, message):
    if not condition:
        raise AssertionError(message)


def native_path(value):
    """Resolve Windows, UNC, and WSL /mnt paths without external tools."""
    text = str(value)
    match = re.match(r"^/mnt/([A-Za-z])/(.*)$", text)
    if match:
        text = match.group(1).upper() + ":/" + match.group(2)
    if text.startswith("/tmp/") and WSL_PREFIX:
        text = str(WSL_PREFIX / "tmp" / text[5:])
    path = Path(text)
    return path if path.is_absolute() else (ROOT / path)


def normalized(value):
    """Copy runner.normalized without importing the ROS/formal runner."""
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items() if not
                (key.startswith("T_") or key.endswith("_ns") or
                 key.endswith("_sha256") or "backend" in key or
                 key in ("result_hash", "row_hash", "execution_commit",
                         "certificate_path", "certificate_hash",
                         "certificate_objective", "search_counter_basis",
                         "qualification_scope", "population",
                         "version_binding_id", "version_binding_sha256"))}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def check_binding(output, plan):
    binding_path = native_path(plan["version_binding_path"])
    raw = binding_path.read_bytes()
    checked(digest(binding_path) == plan["version_binding_sha256"],
            "version binding file SHA256 matches plan")
    binding = read(binding_path)
    checked(binding["schema"] == "cmr-search-entry-binding-v1",
            "search-entry binding schema")
    body = dict(binding)
    binding_id = body.pop("binding_id", None)
    expected_id = "CMR_SEARCH_ENTRY_V1-" + sha256_bytes(
        canonical(body).encode("utf-8"))[:16]
    checked(binding_id == expected_id == plan["version_binding_id"],
            "binding canonical identity and plan binding id")
    checked(binding["source_closure"] == plan["source_closure"],
            "binding source closure")
    for key in ("receipt_sha256", "original_execution_binding_sha256",
                "manifest_sha256"):
        checked(binding[key] == plan[key], "binding/plan " + key)
    checked(set(binding["backends"]) == set(ARMS), "binding backend set")
    for arm in ARMS:
        descriptor = binding["backends"][arm]
        checked(isinstance(descriptor.get("backend_id"), str) and
                isinstance(descriptor.get("backend_sha256"), str),
                "binding backend descriptor")
    return binding


def check_current_binding(current):
    path = native_path(current["version_binding_path"])
    checked(digest(path) == current["version_binding_sha256"],
            "current V6 binding file SHA256")
    value = read(path)
    body = dict(value)
    binding_id = body.pop("binding_id", None)
    expected = "CMR_UNIFIED_BACKENDS_V2-" + sha256_bytes(
        canonical(body).encode("utf-8"))[:16]
    checked(binding_id == expected == current["version_binding_id"],
            "current V6 binding canonical identity")
    checked(set(value["backends"]) == {"reference", "ros2-v6"},
            "current V6 binding backend set")


def check_source_closure(output, plan):
    for name, expected in plan["source_closure"].items():
        frozen = output / "frozen_adapter" / name
        current = ROOT / name
        checked(frozen.is_file() and digest(frozen) == expected,
                "frozen source bytes: " + name)
        checked(current.is_file() and digest(current) == expected,
                "current source bytes: " + name)


def check_row(value, report_value, cell, identity_plan, directory):
    checked(value["row"] == report_value["row"],
            "persisted row/report row identity")
    row = value["row"]
    checked(row["instance_id"] == cell["instance_id"] and
            row["method"] == cell["method"], "result cell identity")
    checked(row["execution_commit"] == identity_plan["execution_identity"],
            "result execution identity")
    checked(row["version_binding_id"] == identity_plan["version_binding_id"] and
            row["version_binding_sha256"] == identity_plan["version_binding_sha256"],
            "result binding identity")
    checked(row["initial_S0"] == cell["expected_initial_S0"],
            "exact initial S0")
    checked(value["worker_exitcode"] == 0 and
            value["worker_alive_after_cleanup"] is False,
            "worker exited cleanly")
    rc = directory / "worker.rc"
    checked(rc.is_file() and rc.read_text(encoding="utf-8").strip() == "0",
            "worker rc=0")
    checked(row["terminal_status"] == "OPTIMALITY_CERTIFIED" and
            row["right_censored"] is False and
            row["timing_status"] == "UNCENSORED",
            "uncensored certified result")
    checked(row["planner_budget_seconds"] == 180 and
            row["outer_watchdog_seconds"] == 195,
            "frozen budgets")
    checked(row["T_total"] ==
            (row["terminal_completion_ns"] - row["method_start_ns"]) / 1e9,
            "T_total tied to terminal completion")
    checked(row["T_total"] < 180, "completed within planner budget")
    checked(row["llm_calls"] == row["experimental_llm_calls"] ==
            row["api_key_reads"] == 0, "no provider calls")
    return row


def check_v7_against_v6(v6_value, v7_value, rounds):
    checked(v6_value["transport"] == v7_value["transport"],
            "V6/V7 concrete transport identity")
    checked(normalized(v6_value["row"]["rounds"]) ==
            normalized(v7_value["row"]["rounds"]),
            "V6/V7 normalized scientific rounds")
    v6_search = v6_value["search_work"]
    v7_search = v7_value["search_work"]
    checked(len(v6_search) == len(v7_search) == len(rounds),
            "one V6/V7 search record per round")
    integer_edges = 0
    for old, new, round_row in zip(v6_search, v7_search, rounds):
        checked(new.get("tracemalloc_enabled") is True,
                "V7 tracemalloc enabled")
        checked(new.get("precision") == round_row["S_k"] and
                new.get("completed") is True and
                not new.get("deadline_observed_exceeded"),
                "V7 qualified search")
        for key in SEARCH_COUNTERS:
            checked(key in old and key in new and old[key] == new[key],
                    "V6/V7 search counter: " + key)
        integer_edges += int(new.get("integer_weight_edges", 0))
    checked(integer_edges > 0, "V7 integer weighted edges exercised")


def check_v7_entry(v7_value, rounds):
    metrics = v7_value.get("entry_metrics")
    checked(isinstance(metrics, dict), "V7 worker entry metrics present")
    checked(metrics.get("binding_reads") == 2 and
            metrics.get("source_closure_checks") == 2 and
            metrics.get("schema_builds") == 1,
            "V7 entry binding/closure/schema metrics")
    builds = v7_value.get("build_work")
    checked(len(builds) == len(rounds), "one V7 build per round")
    for build, round_row in zip(builds, rounds):
        checked(build.get("completed") is True and
                build.get("full_ts_rebuild_calls") == 1 and
                build.get("precision") == round_row["S_k"],
                "V7 completed full TS rebuild")


def check_cell(output, plan, current, cell, item):
    checked(item.get("status") == "PASSED", "cell status")
    checked(item["instance_id"] == cell["instance_id"] and
            item["method"] == cell["method"], "report cell identity")
    directory = output / (cell["instance_id"] + "_" + cell["method"])
    values = {}
    rows = {}
    for arm in ARMS:
        attempt = directory / arm
        value = read(attempt / "result.json")
        report_value = item["arms"][arm]
        values[arm] = value
        identity_plan = current if arm in ("reference", "ros2-v6") else plan
        rows[arm] = check_row(value, report_value, cell, identity_plan, attempt)
        checked(value["backend_binding"] == report_value["backend_binding"],
                "persisted backend descriptor")
        cert_path = attempt / "certificates" / rows[arm]["certificate_path"]
        checked(cert_path.is_file() and
                digest(cert_path) == rows[arm]["certificate_hash"],
                "certificate bytes SHA256")
        replay = item["certificate_replays"][arm]
        checked(replay.get("status") == "PASS",
                "independent certificate replay")
    checked(len({tuple(row["initial_S0"]) for row in rows.values()}) == 1,
            "three-arm exact initial S0")
    checked(len({Fraction(row["objective"]) for row in rows.values()}) == 1,
            "three-arm exact objective")
    check_v6_v7 = check_v7_against_v6(values["ros2-v6"], values["ros2-v7"],
                                       rows["ros2-v7"]["rounds"])
    check_v7_entry(values["ros2-v7"], rows["ros2-v7"]["rounds"])
    metrics_path = directory / "ros2-v7" / "entry_metrics.json"
    metrics_file = read(metrics_path)
    for label, metrics in (("worker", values["ros2-v7"]["entry_metrics"]),
                           ("parent", item["arms"]["ros2-v7"]["parent_entry_metrics"])):
        checked(metrics_file[label]["binding_reads"] == metrics["binding_reads"] and
                metrics_file[label]["source_closure_checks"] == metrics["source_closure_checks"] and
                metrics_file[label]["schema_builds"] == metrics["schema_builds"],
                "V7 " + label + " entry metrics artifact")
        checked(metrics["binding_reads"] == 2 and
                metrics["source_closure_checks"] == 2 and
                metrics["schema_builds"] == 1,
                "V7 " + label + " entry metrics 2/2/1")
    return check_v6_v7


def check_continued_controls(output, plan, report):
    expected = {("A-T1-M0-A-S-BRANCH", "FULL", "reference"),
                ("A-T1-M0-A-S-BRANCH", "FULL", "ros2-v6")}
    controls = plan.get("continued_controls")
    checked(isinstance(controls, list) and len(controls) == 2,
            "two carried V6 controls")
    observed = set()
    for control in controls:
        key = (control["instance_id"], control["method"], control["backend"])
        checked(key in expected and key not in observed,
                "fixed continued control identity")
        observed.add(key)
        source = native_path(control["directory"])
        destination = output / (control["instance_id"] + "_" + control["method"]) / control["backend"]
        checked(digest(source.parent.parent / "plan.json") == control["original_plan_sha256"],
                "continued original plan SHA256")
        for name, expected_sha in control["files"].items():
            checked(digest(source / name) == expected_sha and
                    digest(destination / name) == expected_sha,
                    "continued file bytes: " + name)
        arm_value = next(item["arms"][control["backend"]] for item in report["cells"]
                         if item["instance_id"] == control["instance_id"] and
                         item["method"] == control["method"])
        continuation = arm_value.get("continuation")
        checked(continuation and continuation["new_worker_dispatched"] is False and
                continuation["original_directory"] == control["directory"] and
                continuation["original_plan_sha256"] == control["original_plan_sha256"],
                "continued control metadata")
    checked(observed == expected, "complete continued control set")
    count = sum(1 for item in report["cells"] for arm in ARMS
                if item["arms"][arm].get("continuation") is not None)
    checked(count == 2, "exactly two continued rows and seven new workers")


def main(output):
    global WSL_PREFIX
    output_text = str(output)
    unc = re.match(r"^(\\\\wsl(?:\.localhost)?\\[^\\/]+)(?:[\\/]tmp[\\/])",
                   output_text, re.IGNORECASE)
    if unc:
        WSL_PREFIX = Path(unc.group(1))
    output = native_path(output)
    plan = read(output / "plan.json")
    current = read(output / "current" / "plan.json")
    report = read(output / "comparison.json")
    checked(report["status"] == "PASSED", "comparison status PASSED")
    checked(report["plan"] == plan, "comparison plan identity")
    checked([(cell["instance_id"], cell["method"]) for cell in plan["cells"]] == list(TARGETS) and
            len(plan["cells"]) == 3 and
            plan["backends"] == list(ARMS) and
            plan["expected_method_workers"] == 9 and
            plan["attempts_per_cell_backend"] == 1 and
            plan["formal_campaign"] is False and
            plan["planner_budget_seconds"] == 180 and
            plan["outer_watchdog_seconds"] == 195,
            "fixed three-cell/nine-worker protocol")
    checked(len(report["cells"]) == 3, "three report cells")
    check_binding(output, plan)
    check_current_binding(current)
    check_source_closure(output, plan)
    checked(read(output / "frozen_inputs_before.json") ==
            read(output / "frozen_inputs_after.json") and
            len(read(output / "frozen_inputs_before.json")) == 60,
            "frozen inputs before/after unchanged")
    checked(read(output / "fixtures.json")["status"] == "PASSED",
            "offline fixtures passed")
    for cell, item in zip(plan["cells"], report["cells"]):
        check_cell(output, plan, current, cell, item)
    check_continued_controls(output, plan, report)
    total_build_rounds = sum(len(item["arms"][arm]["row"]["rounds"])
                             for item in report["cells"] for arm in ARMS)
    checked(total_build_rounds == 24, "24 accepted V7 rebuild rounds")
    result = {
        "schema": "cmr-search-entry-native-readback-v1",
        "status": "PASSED", "cells": 3, "workers": 9,
        "qualified_rows": 9, "new_workers": 7, "continued_controls": 2,
        "certificate_replays": 9, "accepted_rebuild_rounds": total_build_rounds,
        "frozen_inputs": 60,
        "planner_imported": False,
        "version_binding_id": plan["version_binding_id"],
        "version_binding_sha256": plan["version_binding_sha256"],
    }
    (output / "native_readback.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    main(parser.parse_args().output)
