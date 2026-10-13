"""V7-only synthetic 510-cell offline validation.

This module executes an in-memory AST-specialized copy of the frozen offline
chain.  It never imports the formal runner, solver, ROS, DDS, or provider
modules.  The generated rows are explicitly synthetic and cannot authorize a
real V7 result or a formal campaign.

CLI inputs retain the old offline-chain naming for the authority receipt:

    --binding <authority receipt>
    --version-binding <V7 backend_binding.json>
    --plan <V7 plan.json>
    --output <fresh output directory>

The V7 plan and binding are checked against current source bytes before the
specialized chain is allowed to run.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE_PATH = ROOT / "experiments" / "cmr_ros2_backend" / "offline_chain.py"
V7_SCOPE = "CMR_SEARCH_ENTRY_OFFLINE_CHAIN_V7"
V7_LABEL = "SYNTHETIC_SEARCH_ENTRY_V7_VALIDATION_ONLY"
V7_PROVENANCE = "SYNTHETIC_SEARCH_ENTRY_V7_OFFLINE_ONLY"
V7_BACKENDS = ("reference", "ros2-v6", "ros2-v7")
V7_BINDING_PREFIX = "CMR_SEARCH_ENTRY_V1-"


class QualificationError(ValueError):
    """Fail-closed V7 input or synthetic-chain rejection."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot read JSON metadata: {path}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"metadata must be an object: {path}")
    return value


def native_path(value: str | os.PathLike[str]) -> Path:
    """Resolve drive-letter paths from authority metadata without adapters."""
    raw = str(value)
    if os.name != "nt" and len(raw) >= 3 and raw[1] == ":" and raw[2] in ("\\", "/"):
        return Path("/mnt") / raw[0].lower() / raw[3:].replace("\\", "/")
    return Path(raw)


def _specialize_base() -> tuple[ModuleType, dict[str, Any]]:
    """Load offline_chain.py in memory with the exact V7 constant rebinding."""
    raw = BASE_PATH.read_bytes()
    source = raw.decode("utf-8")
    tree = ast.parse(source, filename=str(BASE_PATH))
    replacements: list[dict[str, Any]] = []

    class Rebind(ast.NodeTransformer):
        def visit_Constant(self, node):  # type: ignore[no-untyped-def]
            if node.value == "ros2-v6":
                replacements.append({
                    "kind": "backend_literal",
                    "from": "ros2-v6",
                    "to": "ros2-v7",
                    "line": node.lineno,
                })
                return ast.copy_location(ast.Constant("ros2-v7"), node)
            if node.value == "CMR_UNIFIED_BACKEND_OFFLINE_CHAIN_V6":
                replacements.append({
                    "kind": "scope_literal",
                    "from": "CMR_UNIFIED_BACKEND_OFFLINE_CHAIN_V6",
                    "to": V7_SCOPE,
                    "line": node.lineno,
                })
                return ast.copy_location(ast.Constant(V7_SCOPE), node)
            return node

    tree = Rebind().visit(tree)
    ast.fix_missing_locations(tree)
    backend_count = sum(item["kind"] == "backend_literal" for item in replacements)
    scope_count = sum(item["kind"] == "scope_literal" for item in replacements)
    if backend_count != 5 or scope_count != 1 or len(replacements) != 6:
        raise QualificationError(
            "offline_chain AST rebinding changed: expected 5 backend literals and 1 scope"
        )
    module = ModuleType("cmr_search_entry_offline_chain_v7_base")
    module.__file__ = str(BASE_PATH)
    module.__package__ = "experiments.cmr_ros2_backend"
    exec(compile(tree, str(BASE_PATH), "exec"), module.__dict__)
    # Functions in the exec-created module resolve this global at call time.
    # Use the wrapper type so rejection checks catch the same exception class.
    module.QualificationError = QualificationError
    return module, {
        "source_path": str(BASE_PATH),
        "source_sha256": sha256_bytes(raw),
        "replacements": replacements,
        "replacement_count": len(replacements),
        "backend_literal_count": backend_count,
        "scope_literal_count": scope_count,
    }


class _V7Backends:
    """No-kernel metadata shim required by the reused offline chain."""

    def __init__(self, binding_path: Path):
        self.binding_path = binding_path.resolve()
        self.binding = read_json(self.binding_path)
        self.v6 = SimpleNamespace(adapter=SimpleNamespace(_native_path=native_path))

    def describe(self, path: Path | str, backend: str) -> dict[str, str]:
        actual = Path(path).resolve()
        if actual != self.binding_path:
            raise QualificationError("V7 descriptor path differs from version binding")
        if backend not in V7_BACKENDS:
            raise QualificationError("unknown V7 offline backend")
        row = self.binding.get("backends", {}).get(backend)
        if not isinstance(row, Mapping):
            raise QualificationError(f"missing V7 descriptor: {backend}")
        result = {
            "backend": backend,
            "backend_id": row.get("backend_id"),
            "backend_sha256": row.get("backend_sha256"),
            "version_binding_id": self.binding.get("binding_id"),
            "version_binding_sha256": sha256_file(self.binding_path),
        }
        if any(not isinstance(value, str) or not value for value in result.values()):
            raise QualificationError(f"incomplete V7 descriptor: {backend}")
        return result


def _check_plan_and_binding(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_path = Path(args.plan).resolve()
    binding_path = Path(args.version_binding).resolve()
    plan = read_json(plan_path)
    binding = read_json(binding_path)
    if plan.get("schema") != "cmr-search-entry-plan-v1":
        raise QualificationError("V7 plan schema mismatch")
    if plan.get("formal_campaign") is not False:
        raise QualificationError("V7 synthetic chain cannot be campaign-authorized")
    if plan.get("planner_budget_seconds") != 180 or plan.get("outer_watchdog_seconds") != 195:
        raise QualificationError("V7 plan budget contract mismatch")
    declared_path = Path(plan.get("version_binding_path", "")).resolve()
    if declared_path != binding_path:
        raise QualificationError("V7 plan/version binding path mismatch")
    binding_raw = binding_path.read_bytes()
    binding_sha = sha256_bytes(binding_raw)
    if binding_sha != plan.get("version_binding_sha256"):
        raise QualificationError("V7 plan/version binding SHA mismatch")
    content = dict(binding)
    binding_id = content.pop("binding_id", None)
    expected_id = V7_BINDING_PREFIX + sha256_bytes(canonical(content).encode("utf-8"))[:16]
    if binding_id != expected_id or binding_id != plan.get("version_binding_id"):
        raise QualificationError("V7 canonical binding identity mismatch")
    if binding.get("schema") != "cmr-search-entry-binding-v1":
        raise QualificationError("V7 binding schema mismatch")
    closure = plan.get("source_closure")
    if not isinstance(closure, dict) or len(closure) != 56:
        raise QualificationError("V7 source closure must contain 56 files")
    if binding.get("source_closure") != closure:
        raise QualificationError("V7 plan/binding source closure mismatch")
    root = Path(args.repo_root).resolve() if getattr(args, "repo_root", None) else ROOT
    observed_closure: dict[str, str] = {}
    for relative, expected in closure.items():
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise QualificationError(f"V7 source closure file unavailable: {relative}")
        actual = sha256_file(path)
        observed_closure[relative] = actual
        if actual != expected:
            raise QualificationError(f"V7 source closure bytes changed: {relative}")
    offline_relative = "experiments/cmr_ros2_backend/offline_chain.py"
    if observed_closure.get(offline_relative) != sha256_file(root / offline_relative):
        raise QualificationError("V7 offline_chain source SHA is not closure-bound")
    if set(plan.get("backends", ())) != set(V7_BACKENDS):
        raise QualificationError("V7 plan backend set mismatch")
    if set(binding.get("backends", {})) != set(V7_BACKENDS):
        raise QualificationError("V7 binding backend set mismatch")
    exact = {
        "semantic_contract_id": "INITIAL_LABEL_V1",
        "objective": "prefix_cost + 10*suffix_cost",
        "nonempty_accepting_suffix": True,
        "full_ts_rebuild_every_round": True,
        "planner_budget_seconds": 180,
        "outer_watchdog_seconds": 195,
        "formal_campaign": False,
    }
    for key, expected in exact.items():
        if binding.get(key) != expected or type(binding.get(key)) is not type(expected):
            raise QualificationError(f"V7 binding semantic mismatch: {key}")
    for key in ("receipt_sha256", "original_execution_binding_sha256", "manifest_sha256"):
        if not isinstance(binding.get(key), str) or binding.get(key) != plan.get(key):
            raise QualificationError(f"V7 binding/plan authority mismatch: {key}")
    descriptor = _V7Backends(binding_path).describe(binding_path, "ros2-v7")
    execution = plan.get("execution_identity")
    content_without_execution = dict(plan)
    content_without_execution.pop("execution_identity", None)
    expected_execution = str(plan.get("source_head")) + "+cmr-search-entry-" + sha256_bytes(
        canonical(content_without_execution).encode("utf-8")
    )[:16]
    if execution != expected_execution:
        raise QualificationError("V7 plan execution identity canonical mismatch")
    return plan, binding, {"root": str(root), "binding_sha256": binding_sha,
                           "descriptor": descriptor, "closure_files": len(closure),
                           "closure_hashes": observed_closure,
                           "offline_chain_path": str(root / offline_relative)}


def _validate_v7_binding(binding: dict[str, Any]) -> None:
    exact = {
        "schema": "cmr-search-entry-binding-v1",
        "semantic_contract_id": "INITIAL_LABEL_V1",
        "objective": "prefix_cost + 10*suffix_cost",
        "nonempty_accepting_suffix": True,
        "full_ts_rebuild_every_round": True,
        "planner_budget_seconds": 180,
        "outer_watchdog_seconds": 195,
        "formal_campaign": False,
    }
    for key, expected in exact.items():
        if binding.get(key) != expected:
            raise QualificationError(f"V7 binding semantic mismatch: {key}")
    if set(binding.get("backends", {})) != set(V7_BACKENDS):
        raise QualificationError("V7 binding backend set mismatch")


def _guard_rejections(module: ModuleType, version_path: Path, binding: dict[str, Any],
                      schedule: dict[str, Any], campaign_id: str,
                      backends: _V7Backends) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    stale = copy.deepcopy(binding)
    stale["formal_campaign"] = True
    try:
        module.validate_version_binding_contract(stale)
    except QualificationError:
        checks["stale_v7_binding_rejected"] = True
    else:
        checks["stale_v7_binding_rejected"] = False
    stale_schedule = copy.deepcopy(schedule)
    stale_schedule["campaign_id"] = campaign_id + "::STALE"
    try:
        with tempfile.TemporaryDirectory(prefix="cmr-v7-stale-schedule-") as directory:
            stale_path = Path(directory) / "schedule.json"
            module.atomic_write(stale_path, stale_schedule)
            module.frozen_schedule(stale_path, campaign_id)
    except QualificationError:
        checks["stale_v7_schedule_rejected"] = True
    else:
        checks["stale_v7_schedule_rejected"] = False
    try:
        backends.describe(version_path, "unknown-backend")
    except QualificationError:
        checks["unknown_v7_backend_rejected"] = True
    else:
        checks["unknown_v7_backend_rejected"] = False
    if not all(checks.values()):
        raise QualificationError("V7 offline rejection guard failed")
    return checks


def _check_frozen_schedule_exception(module: ModuleType, schedule: dict[str, Any],
                                     campaign_id: str) -> bool:
    """Exercise the exec-module frozen_schedule and its unified exception type."""
    stale_schedule = copy.deepcopy(schedule)
    stale_schedule["campaign_id"] = campaign_id + "::TYPE-CHECK"
    try:
        with tempfile.TemporaryDirectory(prefix="cmr-v7-schedule-type-") as directory:
            stale_path = Path(directory) / "schedule.json"
            module.atomic_write(stale_path, stale_schedule)
            module.frozen_schedule(stale_path, campaign_id)
    except QualificationError:
        return True
    raise QualificationError("exec-module frozen_schedule did not raise wrapper QualificationError")


def qualify(args: argparse.Namespace) -> dict[str, Any]:
    plan, binding, identity = _check_plan_and_binding(args)
    _validate_v7_binding(binding)
    offline_path = Path(identity["offline_chain_path"])
    offline_expected = identity["closure_hashes"]["experiments/cmr_ros2_backend/offline_chain.py"]
    if sha256_file(offline_path) != offline_expected:
        raise QualificationError("offline_chain.py changed before AST specialization")
    module, rebinding = _specialize_base()
    module.SCOPE = V7_SCOPE
    module.SYNTHETIC_LABEL = V7_LABEL
    module.SYNTHETIC_PROVENANCE = V7_PROVENANCE
    backends = _V7Backends(Path(args.version_binding).resolve())
    module.load_backends = lambda: backends
    module.validate_version_binding_contract = _validate_v7_binding
    original_formal_driver_sources = module.formal_driver_sources

    def formal_driver_sources_metadata(execution_path: Path) -> dict[str, Any]:
        # The frozen helper only reads source bytes and does not import the
        # formal driver.  Preserve that metadata while making the execution
        # boundary explicit in the V7 report.
        metadata = dict(original_formal_driver_sources(execution_path))
        metadata.update({"status": "UNVERIFIED", "formal_execution": "UNRUN",
                         "scope": "source hashes/metadata only"})
        return metadata

    def publication_probe_unrun(execution_path: Path) -> dict[str, Any]:
        # Do not call the frozen publication probe: it imports the formal
        # driver and would turn this synthetic chain into an execution path.
        driver_path = execution_path.parent / "driver_core_r2.py"
        source_hashes = ({"driver_core_r2.py": sha256_file(driver_path)}
                         if driver_path.is_file() else {})
        return {"status": "UNRUN", "source_hashes": source_hashes,
                "reason": "publication probe deliberately not run",
                "full_campaign_chain": "UNVERIFIED"}

    module.formal_driver_sources = formal_driver_sources_metadata
    module.actual_driver_publication_checks = publication_probe_unrun
    module.guard_rejections = lambda version_path, value, schedule, campaign_id, loaded: _guard_rejections(
        module, version_path, value, schedule, campaign_id, loaded)
    output = Path(args.output).resolve()
    frozen_schedule_type_check = _check_frozen_schedule_exception(
        module, {"schema_version": "cmr-three-method-analysis-schedule-v1",
                 "campaign_id": "TYPE-CHECK", "methods": ["FULL", "AP-D", "DEP-D"],
                 "denominators": {"Core": 170}, "cells": []}, "EXPECTED")
    module.qualify(args)
    observed_after: dict[str, str] = {}
    root = Path(identity["root"])
    for relative, expected in identity["closure_hashes"].items():
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise QualificationError(f"V7 runtime source closure file unavailable: {relative}")
        actual = sha256_file(path)
        observed_after[relative] = actual
        if actual != expected:
            raise QualificationError(f"V7 runtime source bytes changed: {relative}")
    runtime_closure = {
        "files": len(observed_after),
        "before_after_equal": observed_after == identity["closure_hashes"],
        "sha256": sha256_bytes(canonical(observed_after).encode("utf-8")),
    }
    if not runtime_closure["before_after_equal"]:
        raise QualificationError("V7 runtime source closure differs before/after execution")
    report_path = output / "offline_chain_evidence.json"
    report = read_json(report_path)
    report.update({
        "harness_sha256": sha256_file(Path(__file__)),
        "schema": "cmr-search-entry-v7-offline-chain-qualification-v1",
        "v7_synthetic": True,
        "real_results": 0,
        "certificate_worker_calls": 0,
        "formal_campaign": False,
        "planner_calls": 0,
        "provider_calls": 0,
        "dds_calls": 0,
        "version_binding": {
            "path": str(Path(args.version_binding).resolve()),
            "sha256": identity["binding_sha256"],
            "binding_id": binding["binding_id"],
            "descriptor": identity["descriptor"],
        },
        "plan": {
            "path": str(Path(args.plan).resolve()),
            "source_head": plan.get("source_head"),
            "execution_identity": plan.get("execution_identity"),
            "source_closure_files": identity["closure_files"],
            "source_root": identity["root"],
        },
        "source_rebinding": rebinding,
        "runtime_source_closure": runtime_closure,
        "offline_rejection_checks": {
            "frozen_schedule_exception_unified": frozen_schedule_type_check,
        },
        "qualification_boundary": "synthetic validation only; no formal V7 campaign or certificate qualification",
    })
    module.atomic_write(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True,
                        help="frozen Core authority receipt")
    parser.add_argument("--version-binding", type=Path, required=True,
                        help="V7 backend_binding.json")
    parser.add_argument("--plan", type=Path, required=True,
                        help="V7 plan.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args(argv)
    try:
        report = qualify(args)
    except Exception as exc:
        output = Path(args.output).resolve()
        output.mkdir(parents=True, exist_ok=True)
        (output / "offline_chain_v7_error.json").write_text(
            json.dumps({"schema": "cmr-search-entry-v7-offline-chain-error-v1",
                        "status": "FAILED", "error": repr(exc)},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    print(json.dumps({"status": report.get("status"), "synthetic": True,
                      "real_results": 0, "cells": report.get("schedule", {}).get("cells", 510),
                      "certificate_worker_calls": 0}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
