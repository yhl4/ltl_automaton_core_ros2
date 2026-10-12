"""Pure stdlib fixtures for the VerifiedEntry control-plane contract.

No ROS, planner, solver, DDS, network, or formal runner import is performed.
"""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from experiments.cmr_ros2_search_entry.entry import (
    BACKENDS,
    VERSION,
    VerifiedEntry,
    canonical,
    sha256_bytes,
    sha256_canonical,
)


def _binding_content(closure, receipt_sha="r" * 64,
                     original_sha="o" * 64, manifest_sha="m" * 64):
    return {
        "schema": "cmr-search-entry-binding-v1",
        "version": VERSION,
        "receipt_sha256": receipt_sha,
        "original_execution_binding_sha256": original_sha,
        "manifest_sha256": manifest_sha,
        "source_closure": dict(closure),
        "semantic_contract_id": "INITIAL_LABEL_V1",
        "objective": "prefix_cost + 10*suffix_cost",
        "nonempty_accepting_suffix": True,
        "full_ts_rebuild_every_round": True,
        "planner_budget_seconds": 180,
        "outer_watchdog_seconds": 195,
        "formal_campaign": False,
        "backends": {
            name: {"backend_id": f"id-{name}",
                   "backend_sha256": f"{name.replace('-', '')[:1] or 'x'}" * 64}
            for name in BACKENDS
        },
    }


def _with_id(content):
    return dict(content, binding_id=f"{VERSION}-{sha256_canonical(content)[:16]}")


def _plan(binding_path, binding_sha, closure):
    return {
        "version_binding_path": str(binding_path),
        "version_binding_sha256": binding_sha,
        "version_binding_id": None,
        "receipt_sha256": "r" * 64,
        "original_execution_binding_sha256": "o" * 64,
        "manifest_sha256": "m" * 64,
        "source_closure": dict(closure),
        "backends": list(BACKENDS),
        "qualification_id": "FIXTURE_QUALIFICATION",
        "scope": "FIXTURE_SCOPE",
        "execution_identity": "fixture-execution",
        "cells": [{
            "instance_id": "fixture-1",
            "method": "FULL",
            "source_cell_id": "cell-1",
            "canonical_instance_index": 0,
            "execution_index": 0,
            "method_order_position": 0,
            "expected_initial_S0": [],
        }],
    }


def _make(tmp: Path):
    closure = {"entry.py": "e" * 64}
    content = _binding_content(closure)
    value = _with_id(content)
    path = tmp / "binding.json"
    raw = (canonical(value) + "\n").encode()
    path.write_bytes(raw)
    plan = _plan(path, sha256_bytes(raw), closure)
    plan["version_binding_id"] = value["binding_id"]
    calls = []

    def source_closure():
        calls.append("closure")
        return dict(closure)

    def schema_factory(receipt, backend):
        calls.append(("schema", backend))
        return {"backend": backend, "receipt": copy.deepcopy(receipt)}

    return plan, source_closure, schema_factory, calls, path


def _raises(label, function):
    try:
        function()
    except (RuntimeError, ValueError, KeyError, TypeError):
        return {"name": label, "status": "REJECTED"}
    raise AssertionError(f"fixture accepted invalid input: {label}")


def run_fixtures() -> dict:
    checks = []
    with tempfile.TemporaryDirectory(prefix="cmr-entry-fixture-") as root:
        tmp = Path(root)
        plan, closure_fn, schema_factory, calls, binding_path = _make(tmp)
        entry = VerifiedEntry(plan, closure_fn, schema_factory)
        request = {
            **plan["cells"][0],
            **entry.describe("reference"),
            "qualification_id": plan["qualification_id"],
            "population": plan["scope"],
            "formal_campaign": False,
            "execution_identity": plan["execution_identity"],
            "planner_budget_seconds": 180,
            "outer_watchdog_seconds": 195,
        }
        entry.validate_request(request)

        descriptor = entry.describe("reference")
        descriptor["backend_id"] = "mutated"
        if entry.describe("reference")["backend_id"] == "mutated":
            raise AssertionError("descriptor leaked mutable state")
        checks.append({"name": "mutable_descriptor", "status": "PASSED"})

        receipt = {"receipt": "one", "nested": {"x": [1, 2]}}
        first_schema = entry.schema("reference", receipt)
        first_schema["receipt"]["nested"]["x"].append(3)
        if entry.schema("reference", receipt)["receipt"]["nested"]["x"] != [1, 2]:
            raise AssertionError("schema leaked mutable state")
        if entry.metrics["schema_builds"] != 1:
            raise AssertionError("schema cache built more than once")
        checks.append({"name": "schema_single_build", "status": "PASSED"})

        checks.extend([
            _raises("wrong_request_backend", lambda: entry.validate_request(
                {**request, "backend": "ros2-v7"})),
            _raises("wrong_request_cell", lambda: entry.validate_request(
                {**request, "instance_id": "other"})),
            _raises("wrong_request_budget", lambda: entry.validate_request(
                {**request, "planner_budget_seconds": 179})),
            _raises("receipt_cache_identity", lambda: entry.schema(
                "reference", {"receipt": "two"})),
        ])

        invalid_cases = []
        original = binding_path.read_bytes()
        invalid_cases.append(_raises("wrong_sha", lambda: VerifiedEntry(
            {**plan, "version_binding_sha256": "0" * 64}, closure_fn, schema_factory)))
        bad_id = json.loads(original)
        bad_id["binding_id"] = VERSION + "-" + "0" * 16
        binding_path.write_text(canonical(bad_id) + "\n", encoding="utf-8")
        bad_sha_plan = {**plan, "version_binding_sha256": sha256_bytes(binding_path.read_bytes())}
        invalid_cases.append(_raises("wrong_binding_id", lambda: VerifiedEntry(
            bad_sha_plan, closure_fn, schema_factory)))
        binding_path.write_bytes(original)
        invalid_cases.append(_raises("plan_version_binding_id_mismatch", lambda: VerifiedEntry(
            {**plan, "version_binding_id": VERSION + "-" + "f" * 16},
            closure_fn, schema_factory)))
        invalid_cases.append(_raises("release_binding_bytes_change", lambda: _release_with_changed_binding(
            plan, closure_fn, schema_factory, binding_path)))
        invalid_cases.append(_raises("release_source_change", lambda: _release_with_changed_source(
            plan, closure_fn, schema_factory, binding_path)))
        checks.extend(invalid_cases)

        if entry.metrics["binding_reads"] != 1:
            raise AssertionError(f"unexpected binding read count: {entry.metrics}")
        if entry.metrics["source_closure_checks"] != 1:
            raise AssertionError(f"unexpected closure count: {entry.metrics}")
        checks.append({"name": "metrics", "status": "PASSED",
                       "metrics": entry.metrics})
        # The failed release check above invalidates only its separate entry.
        entry.release_check()
        if (entry.metrics["binding_reads"] != 2
                or entry.metrics["source_closure_checks"] != 2):
            raise AssertionError(f"release metrics did not record revalidation: {entry.metrics}")
        checks.append({"name": "release_metrics", "status": "PASSED",
                       "metrics": entry.metrics})
        checks.append({"name": "release_pass", "status": "PASSED"})
    return {"status": "PASSED", "checks": checks}


def _release_with_changed_source(plan, closure_fn, schema_factory, path):
    current = {"entry.py": "changed" * 10 + "c" * 4}

    def changed_closure():
        return current

    entry = VerifiedEntry(plan, closure_fn, schema_factory)
    # Keep the verified binding bytes intact; only source closure changes at
    # release, which must invalidate the attempt.
    entry._source_closure_fn = changed_closure
    try:
        entry.release_check()
    except ValueError:
        try:
            entry.describe("reference")
        except RuntimeError:
            raise
        raise AssertionError("invalidated entry remained usable after release failure")


def _release_with_changed_binding(plan, closure_fn, schema_factory, path):
    entry = VerifiedEntry(plan, closure_fn, schema_factory)
    original = path.read_bytes()
    mutated = json.loads(original)
    mutated["backends"]["reference"]["backend_id"] = "mutated"
    path.write_text(canonical(mutated) + "\n", encoding="utf-8")
    try:
        entry.release_check()
    except ValueError:
        try:
            entry.describe("reference")
        except RuntimeError:
            raise
        raise AssertionError("invalidated entry remained usable after release failure")
    finally:
        path.write_bytes(original)


if __name__ == "__main__":
    print(json.dumps(run_fixtures(), sort_keys=True, indent=2))
