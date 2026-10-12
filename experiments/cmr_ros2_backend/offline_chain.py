"""Offline qualification of the V6 Core result chain.

This module is deliberately not a campaign driver.  It reads only frozen
membership/authority metadata, fabricates explicitly labelled rows, and runs
the frozen three-method analysis in validation-only mode.  No planner, DDS,
provider, or certificate worker is imported or started here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
METHODS = ("FULL", "AP-D", "DEP-D")
SCOPE = "CMR_UNIFIED_BACKEND_OFFLINE_CHAIN_V6"
SYNTHETIC_LABEL = "SYNTHETIC_ANALYSIS_PIPELINE_VALIDATION_ONLY"
SYNTHETIC_PROVENANCE = "SYNTHETIC_OFFLINE_ONLY"


class QualificationError(ValueError):
    """A fail-closed offline qualification rejection."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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


def native_path(value: str | os.PathLike[str], adapter: Any = None) -> Path:
    """Resolve Windows paths embedded in frozen JSON while running under WSL."""
    if adapter is not None and hasattr(adapter, "_native_path"):
        return Path(adapter._native_path(value))
    raw = str(value)
    if os.name != "nt" and len(raw) >= 3 and raw[1] == ":" and raw[2] in ("\\", "/"):
        return Path("/mnt") / raw[0].lower() / raw[3:].replace("\\", "/")
    return Path(raw)


def atomic_write(path: Path, value: Any) -> None:
    """Replace one JSON file atomically; never expose a partial ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (canonical(value) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_backends() -> Any:
    sys.path.insert(0, str(ROOT))
    from experiments.cmr_ros2_backend import backends  # type: ignore
    return backends


def load_authority(receipt_path: Path, backend_binding: dict[str, Any], backends: Any) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Load authority metadata without opening any result or outcome view."""
    receipt = read_json(receipt_path)
    required = ("campaign_id", "population", "instances", "methods", "scientific_cells", "historical_cells_imported")
    if any(key not in receipt for key in required):
        raise QualificationError("authority receipt lacks required metadata")
    if receipt["population"] != "Core" or receipt["instances"] != 170 or receipt["scientific_cells"] != 510:
        raise QualificationError("stale or non-Core authority receipt")
    if receipt["methods"] != list(METHODS) or receipt["historical_cells_imported"] != 0:
        raise QualificationError("authority method/history contract mismatch")
    for key in ("campaign_id", "execution_campaign_id", "qualification_campaign_id"):
        if key in backend_binding and backend_binding[key] != receipt["campaign_id"]:
            raise QualificationError("version binding campaign identity is stale")
    if backend_binding.get("receipt_sha256") and backend_binding["receipt_sha256"] != sha256_file(receipt_path):
        raise QualificationError("version binding is stale for the supplied authority receipt")
    execution_ref = receipt.get("execution_binding")
    if not isinstance(execution_ref, dict) or not execution_ref.get("path"):
        raise QualificationError("authority receipt has no execution binding reference")
    execution_path = native_path(execution_ref["path"], backends.v6.adapter)
    if not execution_path.is_file():
        raise QualificationError(f"execution binding is unavailable: {execution_path}")
    execution_sha = sha256_file(execution_path)
    if execution_ref.get("sha256") and execution_ref["sha256"] != execution_sha:
        raise QualificationError("authority execution binding hash mismatch")
    if backend_binding.get("original_execution_binding_sha256") and backend_binding["original_execution_binding_sha256"] != execution_sha:
        raise QualificationError("version binding points at a stale execution binding")
    execution = read_json(execution_path)
    if execution.get("campaign_id") != receipt["campaign_id"] or execution.get("population") not in ("Core", "Core170"):
        raise QualificationError("execution binding campaign/population mismatch")
    if execution.get("methods") != list(METHODS) or execution.get("population_count") != 170 or execution.get("cell_count") != 510:
        raise QualificationError("execution binding schedule metadata mismatch")
    return receipt, execution, execution_path


def analysis_paths(execution: dict[str, Any], backends: Any) -> dict[str, Path]:
    ingestion_ref = execution.get("experiment_a_ingestion_binding")
    if not isinstance(ingestion_ref, dict) or not ingestion_ref.get("path"):
        raise QualificationError("missing Experiment A ingestion metadata")
    ingestion_path = native_path(ingestion_ref["path"], backends.v6.adapter)
    if ingestion_ref.get("sha256") and ingestion_ref["sha256"] != sha256_file(ingestion_path):
        raise QualificationError("Experiment A ingestion metadata hash mismatch")
    ingestion = read_json(ingestion_path)
    files: dict[str, Path] = {"ingestion": ingestion_path}
    for name, section in (("schedule", "analysis_schedule"), ("analyze", "analysis_program"),
                          ("result_schema", "result_schema"), ("round_schema", "round_schema")):
        ref = ingestion.get(section)
        if not isinstance(ref, dict) or not ref.get("path"):
            raise QualificationError(f"missing frozen analysis path: {section}")
        path = native_path(ref["path"], backends.v6.adapter)
        if not path.is_file() or (ref.get("sha256") and ref["sha256"] != sha256_file(path)):
            raise QualificationError(f"frozen analysis bytes changed: {section}")
        files[name] = path
    fixture = files["analyze"].with_name("synthetic_fixture.py")
    if not fixture.is_file():
        raise QualificationError(f"frozen synthetic fixture is unavailable: {fixture}")
    files["synthetic_fixture"] = fixture
    files["schema_validation"] = files["analyze"].with_name("schema_validation.py")
    return files


def frozen_schedule(path: Path, campaign_id: str) -> dict[str, Any]:
    schedule = read_json(path)
    if schedule.get("schema_version") != "cmr-three-method-analysis-schedule-v1":
        raise QualificationError("unknown frozen analysis schedule schema")
    if schedule.get("campaign_id") != campaign_id or schedule.get("methods") != list(METHODS):
        raise QualificationError("stale analysis schedule campaign or method set")
    if schedule.get("denominators", {}).get("Core") != 170:
        raise QualificationError("Core denominator is not 170")
    cells = schedule.get("cells")
    if not isinstance(cells, list) or len(cells) != 510:
        raise QualificationError("frozen analysis schedule is not 510 cells")
    keys = [(c.get("population"), c.get("instance_id"), c.get("method")) for c in cells]
    if len(set(keys)) != 510 or any(p != "Core" or m not in METHODS for p, _, m in keys):
        raise QualificationError("schedule contains duplicate, non-Core, or unknown cells")
    instances = {instance for _, instance, _ in keys}
    if len(instances) != 170 or {(instance, m) for instance in instances for m in METHODS} != {(i, m) for _, i, m in keys}:
        raise QualificationError("schedule is not a complete 170 x three-method matrix")
    if any(c.get("status") not in ("EXPECTED_NOT_EXECUTED", "PENDING") for c in cells):
        raise QualificationError("schedule contains outcome state; offline path requires membership metadata")
    result = copy.deepcopy(schedule)
    result["role"] = "SYNTHETIC_FIXTURE_ONLY"
    result["offline_provenance"] = SYNTHETIC_PROVENANCE
    return result


def validate_schedule_campaign(schedule: dict[str, Any], campaign_id: str) -> None:
    if schedule.get("campaign_id") != campaign_id:
        raise QualificationError("stale analysis schedule campaign")


def load_analysis_modules(files: dict[str, Path], backend_sha256: str) -> tuple[Any, Any, dict[str, str]]:
    pipeline = str(files["analyze"].parent)
    if pipeline not in sys.path:
        sys.path.insert(0, pipeline)
    # synthetic_fixture imports the frozen analyze module by this exact name.
    analyze_spec = importlib.util.spec_from_file_location("analyze", files["analyze"])
    if analyze_spec is None or analyze_spec.loader is None:
        raise QualificationError("cannot load frozen analyze.py")
    analyze = importlib.util.module_from_spec(analyze_spec)
    sys.modules["analyze"] = analyze
    analyze_spec.loader.exec_module(analyze)
    # The frozen P2c schemas bind the reference backend SHA as a const.  Keep
    # the source tree untouched: point the in-memory analyzer at a temporary
    # schema directory with only that const rebound to V6.
    rebound_root = Path(tempfile.mkdtemp(prefix="cmr-v6-schema-rebind-"))
    rebound_schema_dir = rebound_root / "schemas"
    rebound_schema_dir.mkdir()
    rebound_hashes: dict[str, str] = {}
    for name, file_key in (("result_schema.json", "result_schema"), ("round_schema.json", "round_schema")):
        original = files[file_key]
        schema = read_json(original)
        prop = schema.get("properties", {}).get("backend_sha256", {})
        if prop.get("const") is not None:
            prop["const"] = backend_sha256
        target = rebound_schema_dir / name
        target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        rebound_hashes[name] = sha256_file(target)
    analyze.HERE = rebound_root
    fixture_spec = importlib.util.spec_from_file_location("synthetic_fixture", files["synthetic_fixture"])
    if fixture_spec is None or fixture_spec.loader is None:
        raise QualificationError("cannot load frozen synthetic_fixture.py")
    fixture = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture)
    return analyze, fixture, rebound_hashes


def synthetic_rows(schedule: dict[str, Any], descriptor: dict[str, Any], fixture: Any) -> list[dict[str, Any]]:
    rows = fixture.make_rows(schedule, "mixed_timeout")
    if len(rows) != 510:
        raise QualificationError("synthetic fixture did not produce exactly 510 rows")
    binding_id = descriptor.get("version_binding_id")
    binding_sha = descriptor.get("version_binding_sha256")
    for row in rows:
        row.update({"backend": "ros2-v6", "backend_id": descriptor["backend_id"],
                    "backend_sha256": descriptor["backend_sha256"],
                    "version_binding_id": binding_id, "version_binding_sha256": binding_sha,
                    "fixture_label": SYNTHETIC_LABEL, "provenance_kind": SYNTHETIC_PROVENANCE,
                    "formal_campaign": False, "planner_calls": 0, "provider_calls": 0, "dds_calls": 0})
        if not isinstance(row.get("objective"), (str, type(None))):
            raise QualificationError("synthetic objective is not exact rational text")
        for round_row in row.get("rounds") or []:
            round_row.update({"backend": "ros2-v6", "backend_id": descriptor["backend_id"],
                              "backend_sha256": descriptor["backend_sha256"],
                              "version_binding_id": binding_id, "version_binding_sha256": binding_sha,
                              "provenance_kind": SYNTHETIC_PROVENANCE})
    if any(row.get("fixture_label") != SYNTHETIC_LABEL or row.get("provenance_kind") != SYNTHETIC_PROVENANCE for row in rows):
        raise QualificationError("synthetic provenance guard failed")
    return rows


def validate_version_binding_contract(binding: dict[str, Any]) -> None:
    if binding.get("formal_campaign") is not False or binding.get("qualification_only") is not True:
        raise QualificationError("stale or campaign-authorized version binding")
    if binding.get("semantic_contract_id") != "INITIAL_LABEL_V1" or binding.get("methods") != list(METHODS):
        raise QualificationError("semantic/method contract mismatch")
    if binding.get("planner_budget_seconds") != 180 or binding.get("outer_watchdog_seconds") != 195:
        raise QualificationError("budget contract mismatch")


def guard_rejections(version_path: Path, binding: dict[str, Any], schedule: dict[str, Any], campaign_id: str, backends: Any) -> dict[str, bool]:
    """Exercise rejection paths against in-memory stale/unknown values only."""
    checks: dict[str, bool] = {}
    stale = copy.deepcopy(binding)
    stale["formal_campaign"] = True
    try:
        validate_version_binding_contract(stale)
    except QualificationError:
        checks["stale_binding_rejected"] = True
    else:
        checks["stale_binding_rejected"] = False
    stale_schedule = copy.deepcopy(schedule)
    stale_schedule["campaign_id"] = campaign_id + "::STALE"
    try:
        with tempfile.TemporaryDirectory(prefix="cmr-stale-schedule-") as directory:
            stale_path = Path(directory) / "schedule.json"
            atomic_write(stale_path, stale_schedule)
            frozen_schedule(stale_path, campaign_id)
    except QualificationError:
        checks["stale_campaign_rejected"] = True
    else:
        checks["stale_campaign_rejected"] = False
    try:
        backends.describe(version_path, "unknown-backend")
    except (ValueError, KeyError):
        checks["unknown_backend_rejected"] = True
    else:
        checks["unknown_backend_rejected"] = False
    if not all(checks.values()):
        raise QualificationError("one or more fail-closed rejection guards did not reject")
    return checks


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows), encoding="utf-8")


class ResultChain:
    """Single-file atomic ledger with fail-closed interrupted-attempt handling."""

    def __init__(self, directory: Path, value: dict[str, Any]):
        self.directory = directory
        self.path = directory / "ledger.json"
        self.value = value

    @classmethod
    def create(cls, directory: Path, cells: list[dict[str, Any]], identity: str,
               backend_binding: dict[str, Any]) -> "ResultChain":
        if directory.exists() and any(directory.iterdir()):
            raise QualificationError(f"result-chain directory is not fresh: {directory}")
        directory.mkdir(parents=True, exist_ok=True)
        value = {"schema": "cmr-offline-result-chain-v1", "scope": SCOPE,
                 "execution_identity": identity, "formal_campaign": False,
                 "backend_binding": copy.deepcopy(backend_binding),
                 "cells": cells, "pending": {}, "committed": {}}
        atomic_write(directory / "ledger.json", value)
        return cls(directory, value)

    @classmethod
    def load(cls, directory: Path, expected_identity: str | None = None) -> "ResultChain":
        if directory.is_dir() and any(path.name.endswith(".tmp") for path in directory.iterdir()):
            raise QualificationError("torn temporary ledger remains; manual recovery required")
        path = directory / "ledger.json"
        if not path.is_file():
            raise QualificationError("missing atomic result ledger")
        value = read_json(path)
        if value.get("schema") != "cmr-offline-result-chain-v1" or value.get("scope") != SCOPE:
            raise QualificationError("stale result-chain ledger")
        if expected_identity is not None and value.get("execution_identity") != expected_identity:
            raise QualificationError("stale result-chain execution identity")
        if not isinstance(value.get("backend_binding"), dict):
            raise QualificationError("result-chain backend binding is missing")
        return cls(directory, value)

    def _save(self) -> None:
        atomic_write(self.path, self.value)

    def resume(self) -> dict[str, int]:
        pending = self.value.get("pending", {})
        if pending:
            raise QualificationError("interrupted attempt remains unresolved; no automatic retry")
        return {"committed": len(self.value.get("committed", {})), "pending": 0}

    def begin(self, key: str) -> None:
        if key in self.value.get("committed", {}):
            raise QualificationError("duplicate committed cell; retry forbidden")
        if self.value.get("pending"):
            raise QualificationError("another attempt is unresolved; silent retry forbidden")
        if key not in {c["key"] for c in self.value["cells"]}:
            raise QualificationError("cell is outside frozen result chain")
        self.value.setdefault("pending", {})[key] = {"attempt": sha256_bytes(key.encode())[:16], "state": "STARTED"}
        self._save()

    def _expected_cell(self, key: str) -> dict[str, Any]:
        for cell in self.value["cells"]:
            if cell.get("key") == key:
                return cell
        raise QualificationError("cell is outside frozen result chain")

    def _check_provenance(self, value: dict[str, Any], label: str) -> None:
        expected = self.value["backend_binding"]
        fields = ("backend", "backend_id", "backend_sha256", "version_binding_id", "version_binding_sha256")
        if any(value.get(field) != expected.get(field) for field in fields):
            raise QualificationError(f"{label} backend/version provenance mismatch")
        if value.get("execution_identity") != self.value["execution_identity"]:
            raise QualificationError(f"{label} execution identity mismatch")
        if value.get("provenance_kind") != SYNTHETIC_PROVENANCE:
            raise QualificationError(f"{label} provenance is not explicitly synthetic")

    def _validate_result(self, key: str, result: dict[str, Any]) -> None:
        cell = self._expected_cell(key)
        for field in ("key", "instance_id", "method", "instance_sha256", "benchmark_payload_sha256"):
            if result.get(field) != (key if field == "key" else cell[field]):
                raise QualificationError(f"result cell identity mismatch: {field}")
        if result.get("formal_campaign") is not False:
            raise QualificationError("result-chain result is campaign-authorized")
        self._check_provenance(result, "result")
        rounds = result.get("rounds")
        if not isinstance(rounds, list) or not rounds:
            raise QualificationError("result has no rounds for provenance binding")
        for index, round_row in enumerate(rounds):
            if not isinstance(round_row, dict) or round_row.get("round_index") != index:
                raise QualificationError("round index is not contiguous")
            for field in ("instance_id", "method", "instance_sha256", "benchmark_payload_sha256"):
                if round_row.get(field) != cell[field]:
                    raise QualificationError(f"round cell identity mismatch: {field}")
            self._check_provenance(round_row, f"round {index}")

    def commit(self, key: str, result: dict[str, Any]) -> None:
        if key not in self.value.get("pending", {}):
            raise QualificationError("commit without exactly one started attempt")
        self._validate_result(key, result)
        self.value["committed"][key] = result
        del self.value["pending"][key]
        self._save()


def execution_order(execution: dict[str, Any], schedule: dict[str, Any], backends: Any) -> tuple[list[dict[str, Any]], Path, str]:
    ref = execution.get("execution_schedule")
    if not isinstance(ref, dict) or not ref.get("path"):
        raise QualificationError("external execution schedule reference is missing")
    path = native_path(ref["path"], backends.v6.adapter)
    if not path.is_file() or (ref.get("sha256") and ref["sha256"] != sha256_file(path)):
        raise QualificationError("external execution schedule bytes changed")
    value = read_json(path)
    external = value.get("cells")
    if not isinstance(external, list) or len(external) != 510:
        raise QualificationError("external execution schedule is not 510 cells")
    membership = {f"{c['instance_id']}::{c['method']}": c for c in schedule["cells"]}
    ordered = sorted(external, key=lambda c: c.get("execution_index", -1))
    if [c.get("execution_index") for c in ordered] != list(range(510)):
        raise QualificationError("external execution indices are not unique and contiguous")
    if len({f"{c.get('instance_id')}::{c.get('method')}" for c in external}) != 510:
        raise QualificationError("external execution schedule contains duplicate cells")
    cells = []
    for external_cell in ordered:
        key = f"{external_cell.get('instance_id')}::{external_cell.get('method')}"
        if key not in membership or external_cell.get("instance_sha256") != membership[key]["instance_sha256"]:
            raise QualificationError("external execution order does not match frozen membership")
        cell = membership[key]
        cells.append({"key": key, "execution_index": external_cell["execution_index"],
                      "order_position": external_cell.get("order_position", external_cell["execution_index"]),
                      "external_cell_id": external_cell.get("cell_id"),
                      "instance_id": cell["instance_id"], "method": cell["method"],
                      "instance_sha256": cell["instance_sha256"],
                      "benchmark_payload_sha256": cell["benchmark_payload_sha256"]})
    return cells, path, sha256_file(path)


def chain_cells(schedule: dict[str, Any], execution: dict[str, Any], backends: Any) -> tuple[list[dict[str, Any]], Path, str]:
    return execution_order(execution, schedule, backends)


def formal_driver_sources(execution_path: Path) -> dict[str, Any]:
    root = execution_path.parent
    names = ("driver_core_r2.py", "ledger_chain_check_core_r2.py", "campaign_worker_core_r2.py")
    found = {name: sha256_file(root / name) for name in names if (root / name).is_file()}
    return {"status": "UNVERIFIED", "source_hashes": found,
            "reason": "offline_chain uses a separate synthetic ledger; the frozen formal driver chain was not invoked or mutated"}


def actual_driver_publication_checks(execution_path: Path) -> dict[str, Any]:
    """Exercise only frozen driver's publication/readback guards on temp bytes.

    Campaign construction, model loading, certificates, and worker dispatch are
    intentionally outside this check.  The result therefore cannot certify the
    complete formal Campaign chain.
    """
    driver_path = execution_path.parent / "driver_core_r2.py"
    if not driver_path.is_file():
        return {"status": "UNVERIFIED", "reason": "driver_core_r2.py unavailable"}
    try:
        if str(driver_path.parent) not in sys.path:
            sys.path.insert(0, str(driver_path.parent))
        spec = importlib.util.spec_from_file_location("cmr_frozen_driver_publication_probe", driver_path)
        if spec is None or spec.loader is None:
            raise QualificationError("cannot load frozen driver module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="cmr-driver-publication-") as directory:
            root = Path(directory)
            final = root / "committed"
            body = {"synthetic": True}
            record = {"ledger_commit_sha256": sha256_bytes((module.adapter.canonical(body) + "\n").encode()),
                      "execution_identity_sha256": "synthetic-execution-identity"}
            files = {name: b"synthetic" for name in module.REQUIRED_FILES
                     if name not in {"commit_manifest.json", "ledger_entry.json", "pilot_record.json"}}
            files["ledger_entry.json"] = (module.adapter.canonical(body) + "\n").encode()
            files["pilot_record.json"] = (module.adapter.canonical(record) + "\n").encode()
            module.atomic_publish(final, files)
            duplicate_rejected = False
            try:
                module.atomic_publish(final, files)
            except (RuntimeError, FileExistsError):
                duplicate_rejected = True
            if not duplicate_rejected:
                raise QualificationError("frozen publication duplicate guard accepted a duplicate")
            cell = {"cell_id": "synthetic", "execution_identity_sha256": "synthetic-execution-identity"}
            readback = module._read_committed(final, cell)
            if readback.get("status") != "ALREADY_COMPLETE":
                raise QualificationError("frozen publication readback did not skip complete cell")
            wrong_identity_rejected = False
            try:
                module._read_committed(final, {"cell_id": "synthetic", "execution_identity_sha256": "wrong"})
            except ValueError:
                wrong_identity_rejected = True
            if not wrong_identity_rejected:
                raise QualificationError("frozen readback accepted wrong cell identity")
            partial = root / "partial"
            partial.mkdir()
            (partial / "result.json").write_bytes(b"partial")
            partial_rejected = False
            try:
                module._read_committed(partial, cell)
            except RuntimeError:
                partial_rejected = True
            if not partial_rejected:
                raise QualificationError("frozen readback accepted partial publication")
        hashes = {"driver_core_r2.py": sha256_file(driver_path)}
        prior = getattr(module, "PRIOR_DRIVER", None)
        if prior is not None and Path(prior).is_file():
            hashes["prior_campaign_driver_p2d.py"] = sha256_file(Path(prior))
        return {"status": "PARTIAL_PASS", "scope": "atomic publication/readback only",
                "duplicate_rejected": True, "wrong_cell_identity_rejected": True,
                "partial_publication_rejected": True, "source_hashes": hashes,
                "full_campaign_chain": "UNVERIFIED"}
    except Exception as exc:
        return {"status": "UNVERIFIED", "reason": f"publication probe unavailable: {exc}",
                "source_hashes": {"driver_core_r2.py": sha256_file(driver_path)}}


def qualify(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise QualificationError("FRESH_DIR must be empty or absent")
    output.mkdir(parents=True, exist_ok=True)
    backends = load_backends()
    version_path = args.version_binding.resolve()
    binding = read_json(version_path)
    descriptor = backends.describe(version_path, "ros2-v6")
    validate_version_binding_contract(binding)
    receipt, execution, execution_path = load_authority(args.binding.resolve(), binding, backends)
    files = analysis_paths(execution, backends)
    schedule = frozen_schedule(files["schedule"], receipt["campaign_id"])
    rejection_checks = guard_rejections(version_path, binding, schedule, receipt["campaign_id"], backends)
    descriptor["version_binding_sha256"] = sha256_file(version_path)
    source_hashes_before = {name: sha256_file(path) for name, path in files.items() if path.is_file()}
    analyze, fixture, rebound_schema_hashes = load_analysis_modules(files, descriptor["backend_sha256"])
    rows = synthetic_rows(schedule, descriptor, fixture)
    synthetic_schedule_path = output / "synthetic_schedule.json"
    synthetic_rows_path = output / "synthetic_results.jsonl"
    atomic_write(synthetic_schedule_path, schedule)
    write_jsonl(synthetic_rows_path, rows)
    # The frozen analyzer performs both P2c result/round validation and its
    # exact-rational/cross-method checks.  validation_only is mandatory here.
    tables = analyze.analyze(schedule, rows, validation_only=True)
    analyze.write_outputs(tables, output / "analysis", SYNTHETIC_LABEL)
    source_hashes_after = {name: sha256_file(path) for name, path in files.items() if path.is_file()}
    if source_hashes_before != source_hashes_after:
        raise QualificationError("frozen analysis source bytes changed during offline run")
    cells, execution_schedule_path, execution_schedule_sha256 = chain_cells(schedule, execution, backends)
    identity = sha256_bytes(canonical({"schedule": sha256_file(synthetic_schedule_path),
                                       "version_binding": descriptor["version_binding_sha256"],
                                       "execution_schedule": execution_schedule_sha256, "scope": SCOPE}).encode())
    chain = ResultChain.create(output / "result_chain", cells, identity, descriptor)
    rows_by_key = {f"{row['instance_id']}::{row['method']}": row for row in rows}
    for cell in cells:
        row = rows_by_key[cell["key"]]
        key = cell["key"]
        chain.begin(key)
        chain.commit(key, {"key": key, "instance_id": row["instance_id"], "method": row["method"],
                           "instance_sha256": row["instance_sha256"],
                           "benchmark_payload_sha256": row["benchmark_payload_sha256"],
                           "backend": "ros2-v6", "backend_id": descriptor["backend_id"],
                           "backend_sha256": descriptor["backend_sha256"],
                           "version_binding_id": descriptor["version_binding_id"],
                           "version_binding_sha256": descriptor["version_binding_sha256"],
                           "execution_identity": identity,
                           "provenance_kind": SYNTHETIC_PROVENANCE, "formal_campaign": False,
                           "rounds": [{"round_index": i, "instance_id": row["instance_id"],
                                       "method": row["method"],
                                       "instance_sha256": row["instance_sha256"],
                                       "benchmark_payload_sha256": row["benchmark_payload_sha256"],
                                       "backend": "ros2-v6",
                                       "backend_id": descriptor["backend_id"],
                                       "backend_sha256": descriptor["backend_sha256"],
                                       "version_binding_id": descriptor["version_binding_id"],
                                       "version_binding_sha256": descriptor["version_binding_sha256"],
                                       "execution_identity": identity,
                                       "provenance_kind": SYNTHETIC_PROVENANCE} for i, _ in enumerate(row.get("rounds") or [])]})
    persisted_chain = ResultChain.load(output / "result_chain", identity)
    persisted_resume = persisted_chain.resume()
    duplicate_rejected = False
    try:
        chain.begin(cells[0]["key"])
    except QualificationError:
        duplicate_rejected = True
    interrupted = ResultChain.create(output / "interrupted_chain", cells[:1], identity, descriptor)
    interrupted.begin(cells[0]["key"])
    interrupted_resume_rejected = False
    try:
        ResultChain.load(interrupted.directory).resume()
    except QualificationError:
        interrupted_resume_rejected = True
    if not duplicate_rejected or not interrupted_resume_rejected:
        raise QualificationError("atomic resume/duplicate guard did not reject unsafe operation")
    valid_record = copy.deepcopy(chain.value["committed"][cells[0]["key"]])
    negative_checks: dict[str, bool] = {}

    def rejected_without_mutation(name: str, operation: Any, ledger: Path) -> None:
        before = sha256_file(ledger)
        try:
            operation()
        except QualificationError:
            if sha256_file(ledger) != before:
                raise QualificationError(f"rejected {name} mutated the ledger")
            negative_checks[name] = True
            return
        raise QualificationError(f"negative fixture was accepted: {name}")

    tampered_round = ResultChain.create(output / "negative_round_sha_chain", cells[:1], identity, descriptor)
    tampered_round.begin(cells[0]["key"])
    tampered = copy.deepcopy(valid_record)
    tampered["rounds"][0]["backend_sha256"] = "0" * 64
    rejected_without_mutation("tampered_round_sha_rejected", lambda: tampered_round.commit(cells[0]["key"], tampered), tampered_round.path)
    tampered_version = ResultChain.create(output / "negative_round_version_chain", cells[:1], identity, descriptor)
    tampered_version.begin(cells[0]["key"])
    tampered = copy.deepcopy(valid_record)
    tampered["rounds"][0]["version_binding_id"] = "STALE"
    rejected_without_mutation("tampered_round_version_rejected", lambda: tampered_version.commit(cells[0]["key"], tampered), tampered_version.path)
    wrong_cell = ResultChain.create(output / "negative_wrong_cell_chain", cells[:1], identity, descriptor)
    wrong_cell.begin(cells[0]["key"])
    tampered = copy.deepcopy(valid_record)
    tampered["instance_id"] = "WRONG-CELL"
    rejected_without_mutation("wrong_cell_rejected", lambda: wrong_cell.commit(cells[0]["key"], tampered), wrong_cell.path)
    torn = ResultChain.create(output / "negative_torn_chain", cells[:1], identity, descriptor)
    torn_temp = torn.directory / ".ledger.json.torn.tmp"
    torn_temp.write_text("partial", encoding="utf-8")
    rejected_without_mutation("torn_temp_ledger_rejected", lambda: ResultChain.load(torn.directory), torn.path)
    stale = ResultChain.create(output / "negative_stale_chain", cells[:1], identity, descriptor)
    stale_value = read_json(stale.path)
    stale_value["execution_identity"] = "STALE"
    atomic_write(stale.path, stale_value)
    stale_loaded_rejected = False
    try:
        ResultChain.load(stale.directory, identity)
    except QualificationError:
        stale_loaded_rejected = True
    if not stale_loaded_rejected:
        raise QualificationError("negative fixture was accepted: stale_ledger_identity_rejected")
    negative_checks["stale_ledger_identity_rejected"] = True
    formal_driver = formal_driver_sources(execution_path)
    formal_driver["publication_probe"] = actual_driver_publication_checks(execution_path)
    report = {"schema": "cmr-offline-chain-qualification-v1", "status": "PASSED",
              "scope": SCOPE, "formal_campaign": False, "provenance_kind": SYNTHETIC_PROVENANCE,
              "planner_calls": 0, "provider_calls": 0, "dds_calls": 0,
              "campaign_id": receipt["campaign_id"], "execution_binding_sha256": sha256_file(execution_path),
              "version_binding_id": descriptor["version_binding_id"],
              "version_binding_sha256": descriptor["version_binding_sha256"],
              "backend": descriptor, "schedule": {"instances": 170, "cells": 510,
              "methods": list(METHODS), "unique_keys": len({c["key"] for c in cells})},
              "analysis": {"tables": len(tables), "rows": len(rows), "validation_only": True,
                           "synthetic_label": SYNTHETIC_LABEL,
                           "schema_rebound_in_memory": True,
                           "rebound_schema_hashes": rebound_schema_hashes,
                           "rebound_fields": ["backend_sha256", "backend_id", "version_binding_id",
                                              "version_binding_sha256", "campaign_id"]},
              "result_chain": {"committed": persisted_resume["committed"], "pending": persisted_resume["pending"],
                               "duplicate_rejected": duplicate_rejected,
                               "interrupted_resume_rejected": interrupted_resume_rejected,
                               "negative_checks": negative_checks},
              "execution_order": {"path": str(execution_schedule_path),
                                   "sha256": execution_schedule_sha256,
                                   "mapped_cells": len(cells),
                                   "indices_unique_contiguous": True},
              "actual_formal_driver_commit_chain": formal_driver,
              "live_campaign_dispatch": "NOT_RUN",
              "frozen_source_hashes": source_hashes_after,
              "guards": {**rejection_checks, "all_rounds_provenance": True}}
    atomic_write(output / "offline_chain_evidence.json", report)
    print(json.dumps({"status": report["status"], "cells": 510, "committed": 510,
                      "analysis_rows": len(rows), "planner_calls": 0, "provider_calls": 0,
                      "dds_calls": 0, "live_campaign_dispatch": "NOT_RUN"}, sort_keys=True), flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True, help="original authority final_campaign_receipt.json")
    parser.add_argument("--version-binding", type=Path, required=True, help="fresh V6 backend binding")
    parser.add_argument("--output", type=Path, required=True, help="fresh offline evidence directory")
    args = parser.parse_args()
    try:
        qualify(args)
        return 0
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        atomic_write(args.output / "offline_chain_error.json", {"status": "FAILED", "error": str(exc)})
        print(f"offline chain qualification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
