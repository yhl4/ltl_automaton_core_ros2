"""Outcome-blind negative checks for persisted CMR certificates."""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any


_INVALID_ACTION = "__cmr_smoke_invalid_action__"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _selected_row(report: dict[str, Any]) -> dict[str, Any]:
    """Return the fixed C1-T1/AP-D/ROS2 row, refusing any other selection."""
    matches = []
    for pair in report.get("pairs", []):
        if pair.get("instance_id") == "C1-T1" and pair.get("method") == "AP-D":
            value = pair.get("ros2")
            if isinstance(value, dict) and isinstance(value.get("row"), dict):
                matches.append(value["row"])
    if len(matches) != 1:
        raise AssertionError("fixed C1-T1/AP-D/ros2 qualification row is unavailable")
    row = matches[0]
    if row.get("certificate_verifier_status") != "PASS":
        raise AssertionError("selected row lacks an independent verifier PASS")
    certificate_path = row.get("certificate_path")
    certificate_hash = row.get("certificate_hash")
    if not isinstance(certificate_path, str) or not certificate_path:
        raise AssertionError("selected row has no certificate path")
    if not isinstance(certificate_hash, str) or not certificate_hash:
        raise AssertionError("selected row has no certificate hash")
    return row


def _verify(formal: Any, path: Path, digest: str, bound: dict[str, Any], selection: dict[str, Any]):
    """Call the actual bound P2E verifier with its authority paths."""
    import runtime

    benchmark_root = runtime.core_smoke._native_path(bound["benchmark_root"])
    manifest_path = runtime.core_smoke._native_path(bound["manifest_path"])
    return formal.verify_certificate_file(
        path, digest, benchmark_root, manifest_path, selection["execution_identity"],
        formal.EXECUTION_CONTRACT_COMMIT, formal.BENCHMARK_COMMIT,
    )


def _expected_rejection(formal: Any, path: Path, digest: str, bound: dict[str, Any],
                        selection: dict[str, Any]) -> str:
    try:
        result = _verify(formal, path, digest, bound, selection)
    except ValueError as error:
        return str(error)
    if isinstance(result, dict) and result.get("status") == "REJECTED":
        return str(result.get("reason", "REJECTED"))
    raise AssertionError(f"negative certificate was accepted: {path.name}")


def check_negative_certificates(args, report):
    """Reject two content mutations while preserving the original certificate."""
    from bound_runner import load_bound_runner
    import runner as real_runner

    row = _selected_row(report)
    formal, bound, manifest = load_bound_runner(args.binding, args.kernel_root)
    selection = real_runner.load_selection()
    case_dir = Path(args.output) / "C1-T1_AP-D_ros2"
    source_path = case_dir / "certificates" / row["certificate_path"]
    if not source_path.is_file():
        raise AssertionError(f"selected certificate is missing: {source_path}")
    source_sha = _sha256(source_path)
    if source_sha != row["certificate_hash"]:
        raise AssertionError("selected certificate bytes differ from the qualification row")
    positive = _verify(formal, source_path, source_sha, bound, selection)
    if not isinstance(positive, dict) or positive.get("status") != "PASS":
        raise AssertionError("selected certificate did not independently verify")

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("full_model_lasso"), dict):
        raise TypeError("certificate full_model_lasso payload is missing")
    destination = Path(args.output) / "verifier_negatives"
    destination.mkdir(parents=True, exist_ok=True)
    cases = []

    objective_copy = json.loads(json.dumps(payload))
    objective_copy["objective"] = str(Fraction(payload["objective"]) + 1)
    objective_path = destination / "objective_plus_one.json"
    _write_json(objective_path, objective_copy)
    objective_sha = _sha256(objective_path)
    objective_reason = _expected_rejection(
        formal, objective_path, objective_sha, bound, selection)
    cases.append({"case": "objective_plus_one", "mutation": "objective + exact Fraction(1)",
                  "source_sha256": source_sha, "mutated_sha256": objective_sha,
                  "status": "REJECTED", "reason": objective_reason})

    action_copy = json.loads(json.dumps(payload))
    lasso = action_copy["full_model_lasso"]
    edge_group = "prefix_edges" if lasso.get("prefix_edges") else "suffix_edges"
    edges = lasso.get(edge_group)
    if not isinstance(edges, list) or not edges or not isinstance(edges[0], dict):
        raise AssertionError("certificate has no mutable lasso edge")
    if "action" not in edges[0]:
        raise AssertionError("certificate lasso edge has no action field")
    edges[0]["action"] = _INVALID_ACTION
    action_path = destination / "invalid_action.json"
    _write_json(action_path, action_copy)
    action_sha = _sha256(action_path)
    action_reason = _expected_rejection(formal, action_path, action_sha, bound, selection)
    cases.append({"case": "invalid_action", "mutation": f"{edge_group}[0].action replaced",
                  "source_sha256": source_sha, "mutated_sha256": action_sha,
                  "status": "REJECTED", "reason": action_reason})

    result = {"status": "PASSED", "rejected": len(cases), "source_sha256": source_sha,
              "source_path": str(source_path), "positive_verifier": positive,
              "manifest_runner_preflight": manifest.get("runner_preflight"),
              "cases": cases}
    _write_json(destination / "report.json", result)
    return result

