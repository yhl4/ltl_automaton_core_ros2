#!/usr/bin/env python3
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import traceback
from types import SimpleNamespace

import experiments.cmr_ros2_ap_ts_reuse.runner as v8

OUT = Path("/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v8_entry_timing_20261013")
CHECKS = []
FACTORY_CALLS = []
ORIGINALS = {}

def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()

def record(name, passed, detail):
    CHECKS.append({"name": name, "status": "PASS" if passed else "FAIL",
                   "detail": detail})

def expect(name, function, expected_message=None):
    try:
        function()
    except Exception as exc:
        ok = expected_message is None or expected_message in str(exc)
        record(name, ok, {"exception": type(exc).__name__, "message": str(exc)})
        return ok
    record(name, False, {"unexpected": "no exception"})
    return False

def fake_load_plan(path):
    return copy.deepcopy(FAKE_PLAN)

def fake_source_closure():
    return {"entry_checks_source": "fixed-source"}

def fake_digest(path):
    return sha_bytes(Path(path).read_bytes())

def fake_schema_factory(receipt, name):
    FACTORY_CALLS.append({"receipt": copy.deepcopy(receipt), "name": name})
    class FakeSchema:
        binding_id = "FAKE_SCHEMA"
        source_hashes = {"fake": "source"}
        def __init__(self):
            self.validation_calls = 0
        def validate_result(self, row):
            self.validation_calls += 1
            if not isinstance(row, dict):
                raise ValueError("row must be dict")
    return FakeSchema()

# These globals intentionally exercise the cloned run_one's global lookup.
BACKEND_ID = "before-configure"
run_method_local = lambda: "before-configure"

def preflight(*args, **kwargs):
    return "preflight"

def load_instance(*args, **kwargs):
    return "instance"

def _payload_for_ai(*args, **kwargs):
    return "payload"

def canonical_record(*args, **kwargs):
    return b"record"

def _certificate_payload(*args, **kwargs):
    return b"certificate"

def sha256_file(*args, **kwargs):
    return "sha"

def verify_bound_certificate(*args, **kwargs):
    return True

def fake_persist(*args, **kwargs):
    return "persisted"

ORIGINAL_RUN_CALLS = []

def fake_run_one(*args, **kwargs):
    ORIGINAL_RUN_CALLS.append({"args": len(args), "kwargs": sorted(kwargs)})
    return {"backend_id": BACKEND_ID, "method_local": run_method_local()}

def main():
    global FAKE_PLAN, ORIGINALS, BACKEND_ID, run_method_local
    with tempfile.TemporaryDirectory(prefix="v8_entry_checks_") as td:
        root = Path(td)
        binding_path = root / "backend_binding.json"
        authority_path = root / "authority.json"
        binding = {
            "backends": {
                "reference": {"backend_id": "ref-id", "backend_sha256": "ref-sha"},
                "ros2-v7": {"backend_id": "v7-id", "backend_sha256": "v7-sha"},
                "ros2-v8": {"backend_id": "v8-id", "backend_sha256": "v8-sha"},
            }
        }
        binding_bytes = (json.dumps(binding, sort_keys=True, separators=(",", ":")) + "\n").encode()
        binding_path.write_bytes(binding_bytes)
        authority_bytes = b'{"authority":"fixed"}\n'
        authority_path.write_bytes(authority_bytes)
        FAKE_PLAN = {
            "version_binding_path": str(binding_path),
            "version_binding_sha256": sha_bytes(binding_bytes),
            "version_binding_id": "FAKE-BINDING-V1",
            "cells": [{"instance_id": "I0", "method": "AP-D"}],
            "records": [{"instance_id": "I0", "instance_sha256": "instance-sha"}],
            "qualification_id": "Q0",
            "scope": "FAKE-SCOPE",
            "source_closure": {"entry_checks_source": "fixed-source"},
            "formal_campaign": False,
            "execution_identity": "fake-execution",
            "authority_receipt": str(authority_path),
            "receipt_sha256": sha_bytes(authority_bytes),
        }

        ORIGINALS = {
            "load_plan": v8.load_plan,
            "source_closure": v8.source_closure,
            "digest": v8.v7.digest,
            "schema_for": v8.schema_for,
            "backend_configure": v8.backend.configure,
        }
        v8.load_plan = fake_load_plan
        v8.source_closure = fake_source_closure
        v8.v7.digest = fake_digest

        entry = v8.AttemptEntry(root / "plan.json")
        descriptor = entry.describe(binding_path, "ros2-v8")
        request = entry.request("ros2-v8")
        descriptor["backend_id"] = "mutated"
        request["instance_id"] = "mutated"
        request["nested_added"] = {"changed": True}
        fresh = entry.request("ros2-v8")
        record("descriptor_and_request_deepcopy_isolation",
               fresh["backend_id"] == "v8-id" and fresh["instance_id"] == "I0"
               and "nested_added" not in fresh,
               {"fresh_backend_id": fresh["backend_id"],
                "fresh_instance_id": fresh["instance_id"]})
        original_plan = copy.deepcopy(FAKE_PLAN)
        FAKE_PLAN["cells"][0]["instance_id"] = "changed-outside-entry"
        record("plan_deepcopy_isolation",
               entry.request("ros2-v8")["instance_id"] == "I0",
               {"entry_instance_id": entry.request("ros2-v8")["instance_id"]})
        FAKE_PLAN = original_plan

        # Schema cache: one factory, two real validations, changed receipt rejected.
        v8.schema_for = fake_schema_factory
        receipt_one = {"receipt": "one", "version": 1}
        schema_one = entry.schema(receipt_one, "reference")
        schema_one.validate_result({"row": 1})
        schema_one_again = entry.schema({"version": 1, "receipt": "one"}, "reference")
        schema_one_again.validate_result({"row": 2})
        record("schema_single_build_two_validations",
               schema_one is schema_one_again and len(FACTORY_CALLS) == 1
               and schema_one.validation_calls == 2
               and entry.metrics["schema_builds"] == 1
               and entry.metrics["schema_requests"] == 2
               and entry.timing["schema_validate_result"]["calls"] == 2,
               {"factory_calls": len(FACTORY_CALLS),
                "validation_calls": schema_one.validation_calls,
                "metrics": entry.metrics,
                "timing": entry.timing})
        expect("receipt_identity_change_rejected",
               lambda: entry.schema({"receipt": "two", "version": 1}, "reference"),
               "entry receipt changed")

        # Release checks are each isolated to one changed input.
        entry.release_check()
        record("release_baseline_passes", True, dict(entry.metrics))
        original_source = v8.source_closure
        v8.source_closure = lambda: {"entry_checks_source": "changed"}
        expect("release_source_change_rejected", entry.release_check,
               "source changed before publication")
        v8.source_closure = original_source

        fresh_entry = v8.AttemptEntry(root / "plan.json")
        binding_path.write_bytes(binding_bytes + b"tamper")
        expect("release_binding_change_rejected", fresh_entry.release_check,
               "binding changed before publication")
        binding_path.write_bytes(binding_bytes)

        fresh_entry = v8.AttemptEntry(root / "plan.json")
        authority_path.write_bytes(b'{"authority":"tampered"}\n')
        expect("release_authority_change_rejected", fresh_entry.release_check,
               "authority receipt changed")
        authority_path.write_bytes(authority_bytes)

        # Configure after backend selection, then clone and call the original
        # function body exactly once without a solver.
        def fake_backend_configure(formal):
            fake_run_one.__globals__["BACKEND_ID"] = "selected-v8"
            fake_run_one.__globals__["run_method_local"] = lambda: "selected-local"
            return {"backend_id": "v8-id", "backend_sha256": "v8-sha"}
        v8.backend.configure = fake_backend_configure
        formal = SimpleNamespace(run_one=fake_run_one,
                                 persist_and_verify_certificate=fake_persist)
        ORIGINAL_RUN_CALLS.clear()
        capture = fresh_entry.configure(formal, "ros2-v8", binding_path)
        fake_result = formal.run_one("stub-request")
        code_preserved = fresh_entry.core_timing.get(
            "original_function_code_preserved", {})
        record("configure_then_instrument_selected_globals",
               capture["backend_id"] == "v8-id"
               and fake_result == {"backend_id": "selected-v8",
                                   "method_local": "selected-local"}
               and len(ORIGINAL_RUN_CALLS) == 1
               and code_preserved.get("run_one") is True
               and code_preserved.get("persist_and_verify_certificate") is True,
               {"capture": capture, "fake_result": fake_result,
                "original_calls": len(ORIGINAL_RUN_CALLS),
                "core_timing": fresh_entry.core_timing})

        # Restore imported module attributes before writing results.
        v8.load_plan = ORIGINALS["load_plan"]
        v8.source_closure = ORIGINALS["source_closure"]
        v8.v7.digest = ORIGINALS["digest"]
        v8.schema_for = ORIGINALS["schema_for"]
        v8.backend.configure = ORIGINALS["backend_configure"]

    failed = [c for c in CHECKS if c["status"] != "PASS"]
    result = {
        "status": "PASSED" if not failed else "FAILED",
        "profile_scope": {
            "load_plan": "mocked",
            "source_closure": "mocked except mutation checks",
            "authority": "temporary file digest only",
            "run_one": 0,
            "solver": 0,
            "provider": 0,
            "DDS": 0,
        },
        "checks": CHECKS,
        "factory_calls": FACTORY_CALLS,
        "notes": [
            "All files used by the checks were temporary files.",
            "configure used a fake backend and fake formal; no frozen authority or run_one was invoked.",
            "The cloned fake run_one body was called once as a no-solver stub.",
        ],
    }
    out = OUT / "entry_checks.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "checks": len(CHECKS),
                      "failed": len(failed), "output": str(out)}, sort_keys=True))
    if failed:
        raise SystemExit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise

