"""Verified, single-attempt entry context for the CMR search adapters.

This module only removes repeated control-plane parsing and descriptor/schema
construction.  It deliberately does not replace the frozen formal runner,
its preflight, instance loading, or any search code.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping


VERSION = "CMR_SEARCH_ENTRY_V1"
SCHEMA = "cmr-search-entry-binding-v1"
BACKENDS = ("reference", "ros2-v6", "ros2-v7")
_SEMANTIC_CONTRACT = "INITIAL_LABEL_V1"
_OBJECTIVE = "prefix_cost + 10*suffix_cost"


def canonical(value: Any) -> str:
    """Return the binding/receipt canonical JSON representation."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_canonical(value: Any) -> str:
    return sha256_bytes(canonical(value).encode("utf-8"))


def _path(value: str | Path) -> Path:
    return Path(value).resolve()


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


class VerifiedEntry:
    """One fully verified plan/binding context for one process/attempt.

    The context owns no global or cross-attempt cache.  A schema cache is tied
    to one canonical receipt identity; a second receipt in this context is
    rejected instead of being silently associated with the first schema.
    """

    def __init__(self, plan: Mapping[str, Any],
                 source_closure_fn: Callable[[], Mapping[str, str]],
                 schema_factory: Callable[[Mapping[str, Any], str], Any]):
        self._plan = copy.deepcopy(dict(_require_mapping(plan, "plan")))
        self._source_closure_fn = source_closure_fn
        self._schema_factory = schema_factory
        self._invalidated = False
        self._receipt_identity: str | None = None
        self._schemas: dict[str, Any] = {}
        self._metrics = {
            "binding_reads": 0,
            "source_closure_checks": 0,
            "descriptor_requests": 0,
            "schema_builds": 0,
        }

        self._binding_path = _path(self._plan.get("version_binding_path", ""))
        self._binding_raw, self._binding = self._read_and_validate_binding()
        self._binding_sha256 = sha256_bytes(self._binding_raw)
        self._check_source_closure()

    def _read_and_validate_binding(self) -> tuple[bytes, dict[str, Any]]:
        expected_sha = _require_text(
            self._plan.get("version_binding_sha256"),
            "plan.version_binding_sha256",
        )
        try:
            raw = self._binding_path.read_bytes()
        except OSError as exc:
            raise ValueError("version binding cannot be read") from exc
        self._metrics["binding_reads"] += 1
        actual_sha = sha256_bytes(raw)
        if actual_sha != expected_sha:
            raise ValueError("version binding SHA256 differs from plan")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("version binding is not UTF-8 JSON") from exc
        content = dict(_require_mapping(value, "version binding"))
        try:
            binding_id = content.pop("binding_id")
        except KeyError as exc:
            raise ValueError("version binding has no binding_id") from exc
        expected_id = f"{VERSION}-{sha256_canonical(content)[:16]}"
        if binding_id != expected_id:
            raise ValueError("version binding canonical identity mismatch")
        self._validate_binding_content(value)
        return raw, value

    def _validate_binding_content(self, value: Mapping[str, Any]) -> None:
        if value.get("schema") != SCHEMA:
            raise ValueError("unsupported search-entry binding schema")
        plan_binding_id = _require_text(
            self._plan.get("version_binding_id"),
            "plan.version_binding_id",
        )
        if value.get("binding_id") != plan_binding_id:
            raise ValueError("binding/plan version binding identity mismatch")
        # The schema and binding-id prefix are the version contract.  If a
        # producer also writes a version field, it must agree exactly.
        if "version" in value and value["version"] != VERSION:
            raise ValueError("search-entry binding version mismatch")

        exact = {
            "semantic_contract_id": _SEMANTIC_CONTRACT,
            "objective": _OBJECTIVE,
            "nonempty_accepting_suffix": True,
            "full_ts_rebuild_every_round": True,
            "planner_budget_seconds": 180,
            "outer_watchdog_seconds": 195,
            "formal_campaign": False,
        }
        for key, expected in exact.items():
            if value.get(key) != expected or type(value.get(key)) is not type(expected):
                raise ValueError(f"binding semantic contract mismatch: {key}")

        plan = self._plan
        for key in ("receipt_sha256", "original_execution_binding_sha256",
                    "manifest_sha256"):
            binding_value = _require_text(value.get(key), f"binding.{key}")
            plan_value = _require_text(plan.get(key), f"plan.{key}")
            if binding_value != plan_value:
                raise ValueError(f"binding/plan identity mismatch: {key}")

        plan_backends = plan.get("backends")
        if (not isinstance(plan_backends, (list, tuple))
                or len(plan_backends) != len(BACKENDS)
                or set(plan_backends) != set(BACKENDS)):
            raise ValueError("plan backend set must be reference/ros2-v6/ros2-v7")
        binding_backends = _require_mapping(value.get("backends"), "binding.backends")
        if set(binding_backends) != set(BACKENDS):
            raise ValueError("binding backend set mismatch")
        for backend in BACKENDS:
            row = _require_mapping(binding_backends.get(backend),
                                   f"binding.backends.{backend}")
            _require_text(row.get("backend_id"),
                          f"binding.backends.{backend}.backend_id")
            _require_text(row.get("backend_sha256"),
                          f"binding.backends.{backend}.backend_sha256")

    def _check_source_closure(self) -> None:
        self._metrics["source_closure_checks"] += 1
        try:
            observed = dict(self._source_closure_fn())
        except Exception as exc:
            raise ValueError("source closure could not be computed") from exc
        expected = self._plan.get("source_closure")
        bound = self._binding.get("source_closure")
        if not isinstance(expected, Mapping) or not isinstance(bound, Mapping):
            raise ValueError("source closure is missing")
        if dict(expected) != dict(bound) or observed != dict(expected):
            raise ValueError("source closure differs from plan/binding")

    def _guard(self) -> None:
        if self._invalidated:
            raise RuntimeError("VerifiedEntry was invalidated by release_check")

    @property
    def binding_id(self) -> str:
        self._guard()
        return str(self._binding["binding_id"])

    @property
    def binding_sha256(self) -> str:
        self._guard()
        return self._binding_sha256

    @property
    def binding(self) -> dict[str, Any]:
        self._guard()
        return copy.deepcopy(self._binding)

    @property
    def metrics(self) -> dict[str, int]:
        return copy.deepcopy(self._metrics)

    def describe(self, backend: str) -> dict[str, Any]:
        self._guard()
        self._metrics["descriptor_requests"] += 1
        if backend not in BACKENDS:
            raise ValueError("unknown backend")
        descriptor = dict(self._binding["backends"][backend])
        descriptor.update(
            backend=backend,
            version_binding_id=self._binding["binding_id"],
            version_binding_sha256=self._binding_sha256,
        )
        return copy.deepcopy(descriptor)

    def _expected_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        instance_id = request.get("instance_id")
        method = request.get("method")
        cells = self._plan.get("cells")
        if not isinstance(cells, list):
            raise ValueError("plan.cells must be a list")
        matches = [cell for cell in cells
                   if isinstance(cell, Mapping)
                   and cell.get("instance_id") == instance_id
                   and cell.get("method") == method]
        if len(matches) != 1:
            raise ValueError("request cell is not uniquely in the frozen plan")
        records = self._plan.get("records")
        if not isinstance(records, list):
            raise ValueError("plan.records must be a list")
        record_matches = [record for record in records
                          if isinstance(record, Mapping)
                          and record.get("instance_id") == instance_id]
        if len(record_matches) != 1:
            raise ValueError("request input is not uniquely in the frozen plan")
        expected = dict(matches[0])
        expected["instance_sha256"] = _require_text(
            record_matches[0].get("instance_sha256"), "record.instance_sha256")
        expected.update(self.describe(request.get("backend")),
                        qualification_id=_require_text(
                            self._plan.get("qualification_id"),
                            "plan.qualification_id"),
                        population=_require_text(self._plan.get("scope"),
                                                 "plan.scope"),
                        formal_campaign=False,
                        execution_identity=_require_text(
                            self._plan.get("execution_identity"),
                            "plan.execution_identity"),
                        planner_budget_seconds=180,
                        outer_watchdog_seconds=195)
        return expected

    def validate_request(self, request: Mapping[str, Any]) -> None:
        self._guard()
        if not isinstance(request, Mapping):
            raise ValueError("request must be an object")
        expected = self._expected_request(request)
        if dict(request) != expected:
            raise ValueError("request differs from the verified frozen entry")

    def schema(self, backend: str, receipt: Mapping[str, Any]) -> Any:
        self._guard()
        if backend not in BACKENDS:
            raise ValueError("unknown backend")
        receipt_copy = copy.deepcopy(_require_mapping(receipt, "receipt"))
        try:
            receipt_identity = sha256_canonical(receipt_copy)
        except (TypeError, ValueError) as exc:
            raise ValueError("receipt is not canonical JSON") from exc
        if self._receipt_identity is None:
            self._receipt_identity = receipt_identity
        elif self._receipt_identity != receipt_identity:
            raise ValueError("schema receipt identity differs within VerifiedEntry")
        if backend not in self._schemas:
            self._metrics["schema_builds"] += 1
            self._schemas[backend] = self._schema_factory(receipt_copy, backend)
        return copy.deepcopy(self._schemas[backend])

    def release_check(self) -> bool:
        """Revalidate bytes and source closure before accepting a result."""
        self._guard()
        try:
            raw = self._binding_path.read_bytes()
            self._metrics["binding_reads"] += 1
            actual_sha = sha256_bytes(raw)
            if actual_sha != self._plan["version_binding_sha256"]:
                raise ValueError("version binding changed before release")
            value = json.loads(raw.decode("utf-8"))
            content = dict(_require_mapping(value, "version binding"))
            binding_id = content.pop("binding_id", None)
            if binding_id != f"{VERSION}-{sha256_canonical(content)[:16]}":
                raise ValueError("release binding canonical identity mismatch")
            self._validate_binding_content(value)
            if value != self._binding:
                raise ValueError("version binding content changed before release")
            self._check_source_closure()
        except Exception:
            self._invalidated = True
            raise
        return True


__all__ = ["BACKENDS", "SCHEMA", "VERSION", "VerifiedEntry",
           "canonical", "sha256_bytes", "sha256_canonical"]
