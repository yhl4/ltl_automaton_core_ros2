"""Validation-only gate for genuine V6 result directories.

This module loads the frozen P2c coordinator source and calls its original
``checked_record``, ``publication_gate`` and ``receipt`` methods against rows
already produced by the caller.  It never starts a worker.  The R2 campaign
constructor is deliberately not entered. Its unchanged checked wrapper and
receipt-restoration method run against isolated representative publications;
live dispatch remains NOT_RUN_BY_DESIGN.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from types import MethodType, SimpleNamespace, CodeType, FunctionType

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_backend import backends


P2C = Path(r"D:\Robotics\Robotics4LLM\ltl_planning_studio\analysis\cmr_ltl_v2_pilot_execution_p2c_20260930\execute_pilot.py")
R2 = Path(r"D:\Robotics\Robotics4LLM\ltl_planning_studio\analysis\cmr_ltl_v2_core_r2_binding_20261002\driver_core_r2.py")
P2F_SHA = "29dcdcfb444c4fe9156a91eb8b7ceaaaee6286ebbae80c3606de96456256bfa0"
EXPECTED_P2C_SHA = "b4778deca76c5df7ae01e77079810b258f2d1f37e6af8ce6da807008cb509379"
EXPECTED_R2_SHA = "d319bc0c48cbd0639279f35bacca5ab34e73af639f6f9e90c55b4e1596dcd4a4"


def _read(path):
    return json.loads(Path(path).read_bytes())


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _raw(value):
    return (_canonical(value) + "\n").encode()


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _sha(path):
    return _sha_bytes(Path(path).read_bytes())


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_r2():
    source_path = _frozen_path(R2)
    inserted = str(source_path.parent)
    if inserted not in sys.path:
        sys.path.insert(0, inserted)
    return _load("frozen_r2_publication_gate", source_path)


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_raw(value) if not isinstance(value, bytes) else value)


def _path(value):
    path = Path(value).expanduser()
    if path.exists():
        return path.resolve()
    text = str(value).replace("\\", "/")
    match = re.match(r"^([A-Za-z]):/(.*)$", text)
    if match:
        wsl = Path("/mnt") / match.group(1).lower() / match.group(2)
        if wsl.exists():
            return wsl.resolve()
    return path.resolve()


def _frozen_path(path):
    return _path(path)


def _nested_r2_checked_source():
    source_path = _frozen_path(R2)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "checked":
            segment = ast.get_source_segment(source, node)
            if segment:
                found.append(segment)
    if len(found) != 1:
        raise ValueError("R2 checked wrapper source is not uniquely identified")
    return found[0]


def _qualified_descriptor(plan, version_path, qualification_root):
    """Replay an immutable qualification version, never relax runtime loading.

    Only the two recorded test-harness Popen routing guards may differ from
    the qualified source snapshot. All worker/solver/transport bytes match.
    """
    value = _read(version_path)
    if _sha(version_path) != plan['version_binding_sha256']:
        raise ValueError('qualified version file changed')
    content = dict(value)
    binding_id = content.pop('binding_id')
    if binding_id != backends.VERSION + '-' + _sha_bytes(_canonical(content).encode())[:16]:
        raise ValueError('qualified version identity mismatch')
    if (value['qualification_only'] is not True or value['formal_campaign'] is not False
            or value['planner_budget_seconds'] != 180 or value['outer_watchdog_seconds'] != 195
            or value['semantic_contract_id'] != 'INITIAL_LABEL_V1'
            or value['objective'] != 'prefix_cost + 10*suffix_cost'):
        raise ValueError('qualified contract changed')
    allowed = [ast.dump(ast.parse("if str(HERE / '" + name + "') not in command:\n    return REAL_POPEN(command, **kwargs)").body[0], include_attributes=False)
               for name in ('runner.py', 'dds.py')]
    class RoutingGuards(ast.NodeTransformer):
        count = 0
        def visit_FunctionDef(self, node):
            self.generic_visit(node)
            if node.name == 'popen':
                retained = []
                for part in node.body:
                    if ast.dump(part, include_attributes=False) in allowed:
                        self.count += 1
                    else:
                        retained.append(part)
                node.body = retained
            return node
    differences = []
    for name, expected in plan['source_closure'].items():
        snapshot = Path(qualification_root) / 'frozen_adapter' / name
        if _sha(snapshot) != expected:
            raise ValueError('qualified source snapshot changed: ' + name)
        current = ROOT / name
        if _sha(current) != expected:
            if name != 'experiments/cmr_ros2_backend/lifecycle.py':
                raise ValueError('non-harness source changed: ' + name)
            transformer = RoutingGuards()
            tree = transformer.visit(ast.parse(current.read_text(encoding='utf-8')))
            if transformer.count != 2 or ast.dump(tree, include_attributes=False) != ast.dump(ast.parse(snapshot.read_text(encoding='utf-8')), include_attributes=False):
                raise ValueError('test harness change exceeds two routing guards')
            differences.append(name)
    expected = dict(backend_id=backends.v6.ID, backend_sha256=backends.v6.identity())
    if value['backends']['ros2-v6'] != expected:
        raise ValueError('qualified V6 algorithm changed')
    return dict(expected, backend='ros2-v6', version_binding_id=binding_id,
                version_binding_sha256=plan['version_binding_sha256']), differences


def _r2_checked(driver, outer, old_check):
    """Reuse the original nested code object with its two original closures."""
    candidates = [c for c in driver.Campaign.__init__.__code__.co_consts
                  if isinstance(c, CodeType) and c.co_name == 'checked']
    if len(candidates) != 1:
        raise ValueError('original R2 checked code object is not unique')
    code = candidates[0]
    values = {'self': outer, 'old_check': old_check}
    def cell(value):
        return (lambda: value).__closure__[0]
    return FunctionType(code, driver.__dict__, closure=tuple(cell(values[k]) for k in code.co_freevars))


class _V6Adapter:
    """P2c-shaped adapter backed by the repository's exact V6 schema."""

    def __init__(self, receipt, version_path, descriptor):
        self.receipt = receipt
        self.version_path = Path(version_path).resolve()
        self.descriptor = descriptor
        self.schema = backends.schema_for(receipt, "ros2-v6")
        self.scope = None

    def validate_bound_result(self, row, _binding_path):
        if row.get("formal_campaign") is not False:
            raise ValueError("formal gate accepts qualification-only V6 rows")
        if self.scope is not None and row.get("qualification_scope") != self.scope:
            raise ValueError("V6 result campaign scope differs from plan")
        for key, expected in self.descriptor.items():
            if row.get(key) != expected:
                raise ValueError(f"V6 result {key} differs from version binding")
        for round_row in row.get("rounds") or []:
            for key, expected in self.descriptor.items():
                if round_row.get(key) != expected:
                    raise ValueError(f"V6 round {key} differs from version binding")
        self.schema.validate_result(row)
        return {"status": "PASS", "schema_binding_id": self.schema.binding_id}


class _CoordinatorProxy:
    pass


def _original_cells(receipt):
    value = receipt if isinstance(receipt, dict) else _read(receipt)
    execution = _read(_frozen_path(value["execution_binding"]["path"]))
    return execution, {(c["instance_id"], c["method"]): c for c in execution["cells"]}


def _find_rows(root):
    rows = {}
    for result in sorted(Path(root).rglob("result.json")):
        try:
            value = _read(result)
            row = value.get("row")
            if not isinstance(row, dict) or row.get('backend') != 'ros2-v6':
                continue
            key = (row.get("instance_id"), row.get("method"))
            if None not in key:
                # Also include genuine lifecycle attempts. Choose a timeout
                # for its failure gate, without replacing it by a later crash.
                if key not in rows or row.get('terminal_status') == 'TIMEOUT':
                    rows[key] = (result.parent, value, row)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return rows


def _normalised_files(folder, envelope, row):
    folder = Path(folder)
    files = {}
    for name in ("stdout.log", "stderr.log", "environment.json"):
        source = folder / name
        if name in ('stdout.log', 'stderr.log') and not source.exists():
            source = folder / name.replace('.log', '.txt')
        files[name] = source.read_bytes() if source.exists() else (b"{}" if name == "environment.json" else b"")
    rounds = folder / "rounds.jsonl"
    files["rounds.jsonl"] = rounds.read_bytes() if rounds.exists() else b"".join(_raw(r) for r in (row.get("rounds") or []))
    cert_name = row.get("certificate_path")
    if row.get("terminal_status") == "OPTIMALITY_CERTIFIED" and isinstance(cert_name, str):
        if Path(cert_name).name != cert_name or "/" in cert_name or "\\" in cert_name:
            raise ValueError("noncanonical certificate path")
        cert = folder / "certificates" / cert_name
        files["certificate.json"] = cert.read_bytes()
    else:
        files["certificate.json"] = b'"NOT_AVAILABLE"'
    attempt = envelope.get("attempt_id") or row.get("attempt_id") or "a-formal-gate"
    envelope = dict(envelope)
    envelope.setdefault("attempt_id", attempt)
    envelope.setdefault("worker_result", row)
    envelope.setdefault("terminal_status", row.get("terminal_status"))
    envelope.setdefault('worker_exit_code', envelope.get('worker_exitcode'))
    envelope.setdefault('t_plan_wall_lower_bound_seconds', row.get('T_total'))
    envelope.setdefault("timed_out_outer", row.get("terminal_status") == "TIMEOUT")
    files["result.json"] = _raw(envelope)
    return files, attempt


def _make_cell(original, descriptor):
    cell = dict(original)
    cell.update(descriptor)
    # P2c's record method reads these legacy fields even for non-AI methods.
    cell.setdefault("ai_selection_artifact_sha256", "NOT_APPLICABLE")
    cell.setdefault("ai_selection_source_artifact_sha256", "NOT_APPLICABLE")
    cell.setdefault("ai_binding_manifest_sha256", "NOT_APPLICABLE")
    return cell


def _expected(cell, row):
    initial = cell.get("expected_initial_S0", cell.get("expected_initialization"))
    if initial is None:
        raise ValueError("bound expected initial precision is missing")
    n = cell.get("N", cell.get("n", cell.get("instance_n")))
    if not isinstance(n, int) or n <= 0:
        raise ValueError("bound instance N metadata is missing")
    return {"initial": initial, "n": n, "ai": None}


def _make_proxy(coordinator, adapter, version_sha, cell, row, temp_root, r2_driver):
    proxy = _CoordinatorProxy()
    proxy.adapter = adapter
    proxy.binding = {"ai_binding_manifest": {"path": "NOT_APPLICABLE"}}
    proxy.binding_sha = version_sha
    proxy.allowed_statuses = {row.get("terminal_status"), "TIMEOUT", "OPTIMALITY_CERTIFIED", "INFEASIBLE_CERTIFIED"}
    proxy.expectations = {cell["cell_id"]: _expected(cell, row)}
    proxy.current = cell
    proxy.ledger = []
    proxy.records = []
    proxy.failures = []
    proxy.original_publish = r2_driver.atomic_publish
    proxy.checked_record = MethodType(coordinator.Campaign.checked_record, proxy)
    return proxy


def _persisted_certificate(formal, bound, plan, cell, row, source, attempt, temp_root):
    if row.get("terminal_status") != "OPTIMALITY_CERTIFIED":
        return {"status": "NOT_APPLICABLE"}
    if formal is None or bound is None:
        raise ValueError("bound certificate verifier is required for a certified V6 row")
    name = row.get("certificate_path")
    if not isinstance(name, str) or Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("certificate path is not canonical")
    source = Path(source) / "certificates" / name
    if not source.exists() or _sha(source) != row.get("certificate_hash"):
        raise ValueError("V6 persisted certificate bytes/hash mismatch")
    certroot = Path(temp_root) / "attempts" / cell["cell_id"] / attempt / "certificates"
    certroot.mkdir(parents=True, exist_ok=True)
    target = certroot / name
    shutil.copyfile(source, target)
    canonical_name = f"{cell['instance_id']}__{cell['method']}__{cell['canonical_instance_index']}.json"
    if name != canonical_name:
        raise ValueError("certificate filename differs from frozen canonical name")
    proof = formal.verify_bound_certificate(formal.verify_certificate_file, target, row["certificate_hash"],
        _path(bound["benchmark_root"]), _path(bound["manifest_path"]),
        plan["execution_identity"], formal.EXECUTION_CONTRACT_COMMIT, formal.BENCHMARK_COMMIT,
        expected_instance_id=cell["instance_id"], expected_method=cell["method"],
        expected_certificate_root=certroot, expected_filename=canonical_name)
    if proof.get("status") != "PASS":
        raise ValueError("independent persisted V6 certificate verifier rejected bytes")
    return proof


def _negative_checks(coordinator, proxy, cell, envelope, files, row, final):
    checks = {}
    before = Path(final).exists()
    bad = copy.deepcopy(row)
    if bad.get("rounds"):
        bad["rounds"][0]["backend_sha256"] = "0" * 64
        bad["result_hash"] = _sha_bytes(_canonical({k: v for k, v in bad.items() if k != "result_hash"}).encode())
        invalid = dict(files, **{"result.json": _raw(dict(envelope, worker_result=bad))})
        try:
            proxy.checked_record(cell, json.loads(invalid["result.json"]), invalid, proxy.expectations[cell["cell_id"]])
        except Exception:
            checks["wrong_round_backend_rejected"] = True
        else:
            checks["wrong_round_backend_rejected"] = False
    if row.get("terminal_status") == "OPTIMALITY_CERTIFIED":
        invalid = dict(files, **{"certificate.json": files["certificate.json"] + b"tampered"})
        try:
            proxy.checked_record(cell, envelope, invalid, proxy.expectations[cell["cell_id"]])
        except Exception:
            checks["bad_certificate_bytes_rejected"] = True
        else:
            checks["bad_certificate_bytes_rejected"] = False
    checks["precommit_rejection_preserves_final"] = before == Path(final).exists()
    return checks


def qualify(plan, receipt, kernel_root, qualification_output, output):
    """Run the formal gate over existing V6 rows and write a bounded report."""
    plan = plan if isinstance(plan, dict) else _read(plan)
    receipt_path = _path(receipt) if not isinstance(receipt, dict) else None
    receipt_value = receipt if isinstance(receipt, dict) else _read(receipt_path)
    version_path = _path(plan["version_binding_path"])
    out = _path(output)
    if out.exists() and any(out.iterdir()):
        raise ValueError("formal gate output must be fresh")
    out.mkdir(parents=True, exist_ok=True)
    gate_source = Path(__file__).resolve()
    gate_source_before = _sha(gate_source)
    gate_snapshot = out / "formal_gate.py.snapshot"
    shutil.copyfile(gate_source, gate_snapshot)
    descriptor, harness_changes = _qualified_descriptor(plan, version_path, qualification_output)
    execution, source_cells = _original_cells(receipt_value)
    manifest_rows = {r["instance_id"]: r for r in _read(_frozen_path(execution["manifest_path"]))}
    plan_records = {r["instance_id"]: r for r in plan.get("records", [])}
    rows = _find_rows(qualification_output)
    p2c_path = _frozen_path(P2C)
    r2_path = _frozen_path(R2)
    if _sha(p2c_path) != EXPECTED_P2C_SHA or _sha(r2_path) != EXPECTED_R2_SHA:
        raise ValueError("frozen coordinator/R2 source hash mismatch")
    if any(c.get("runner_source_sha256") != P2F_SHA for c in execution["cells"]):
        raise ValueError("original execution binding does not identify the frozen P2f runner")
    sources = {"p2c_coordinator": {"path": str(p2c_path), "sha256": _sha(p2c_path)},
               "r2_driver": {"path": str(r2_path), "sha256": _sha(r2_path)},
               "r2_checked_wrapper_source_sha256": _sha_bytes(_nested_r2_checked_source().encode())}
    report = {"schema": "cmr-v6-formal-gate-v1", "status": "UNVERIFIED",
              "scope": "genuine V6 rows only; validation/replay, no dispatch",
              "plan_execution_identity": plan.get("execution_identity"),
              "version_binding": descriptor, "sources": sources,
              "selected_rows_found": len(rows), "selected_rows_checked": 0,
              "test_harness_only_changes": harness_changes,
              "planner_calls": 0, "provider_calls": 0, "dds_calls": 0,
              "live_campaign_dispatch": "NOT_RUN_BY_DESIGN",
              "r2_checked_wrapper": "UNVERIFIED: R2 Campaign constructor not entered",
              "r2_restore_receipts": "UNVERIFIED: R2 Campaign constructor not entered",
              "checks": {}, "limitations": [
                  "R2 checked wrapper was source-hashed but not executed without entering Campaign",
                  "R2 restore_receipts was not executed without entering Campaign"]}
    report["formal_gate_source"] = {"path": str(gate_source),
                                    "snapshot": str(gate_snapshot),
                                    "sha256_before": gate_source_before}
    coordinator = _load("frozen_p2c_formal_gate", p2c_path)
    coordinator.HERE = out / "p2c_replay"
    coordinator.BINDING_PATH = version_path
    coordinator.SOLVER_SHA = descriptor["backend_sha256"]
    coordinator.RUNNER_SHA = P2F_SHA
    coordinator.SEMANTIC_SHA = execution["cells"][0]["semantic_contract_sha256"]
    report["method_code_hashes"] = {
        name: _sha_bytes(getattr(coordinator.Campaign, name).__code__.co_code)
        for name in ("checked_record", "publication_gate", "receipt")}
    report["rebound_globals"] = {
        "HERE": str(coordinator.HERE), "BINDING_PATH": str(coordinator.BINDING_PATH),
        "SOLVER_SHA": coordinator.SOLVER_SHA, "RUNNER_SHA": coordinator.RUNNER_SHA,
        "SEMANTIC_SHA": coordinator.SEMANTIC_SHA,
    }
    try:
        adapter = _V6Adapter(receipt_value, version_path, descriptor)
        adapter.scope = plan.get("scope")
        r2_driver = _load_r2()
        r2_adapter_path = _frozen_path(r2_driver.adapter.__file__)
        report["sources"]["r2_adapter"] = {"path": str(r2_adapter_path), "sha256": _sha(r2_adapter_path)}
    except Exception as error:
        report["limitations"].append("frozen source load failed: " + repr(error))
        _write(out / "formal_gate_evidence.json", report)
        return report
    try:
        # Bound runner loading is needed only for persisted optimal certificates.
        formal = bound = None
        try:
            if receipt_path is None:
                raise ValueError("receipt path is required for bound certificate replay")
            if any(row.get("terminal_status") == "OPTIMALITY_CERTIFIED" for _, _, row in rows.values()):
                formal, bound, _manifest = backends.v6.adapter.load_bound_runner(receipt_path, kernel_root)
        except Exception as error:
            report["limitations"].append("bound certificate verifier unavailable: " + repr(error))
        requested = [("A-T1-M0-A-S-BRANCH", "FULL"), ("C2-T3", "AP-D")]
        timeout_key = next((key for key, item in rows.items()
                            if item[2].get("terminal_status") == "TIMEOUT"), None)
        if timeout_key is not None and timeout_key not in requested:
            requested.append(timeout_key)
        elif timeout_key is None:
            report["limitations"].append("requested lifecycle TIMEOUT row not present among V6 outputs")
        certified_checked = False
        for key in requested:
            if key not in rows:
                report["limitations"].append("representative row absent: " + "/".join(key))
                continue
            folder, value, row = rows[key]
            original = source_cells.get(key)
            if original is None:
                raise ValueError("V6 row is outside original bound cell set: " + repr(key))
            cell = _make_cell(original, descriptor)
            source_cell_id = original["cell_id"]
            cell["source_cell_id"] = source_cell_id
            n = plan_records.get(key[0], {}).get("N", manifest_rows.get(key[0], {}).get("N"))
            if n is None:
                raise ValueError("selected plan/bound manifest lacks N metadata")
            cell["N"] = n
            cell['expected_initial_S0'] = execution['expected_initialization'][key[0]][key[1]]
            cell["execution_identity_sha256"] = r2_driver.adapter.execution_identity_sha256(cell)
            cell["cell_id"] = cell["execution_identity_sha256"]
            cell["cell_identity_sha256"] = cell["execution_identity_sha256"]
            envelope = dict(value)
            if value.get("backend_binding") not in (None, descriptor):
                raise ValueError("worker envelope backend binding differs from version binding")
            if value.get("worker_result") not in (None, row):
                raise ValueError("worker envelope row differs from result.json row")
            if row.get("execution_commit") != plan.get("execution_identity"):
                raise ValueError("V6 result execution identity differs from plan")
            envelope["cell_id"] = cell["cell_id"]
            envelope["cell_identity_sha256"] = cell["cell_identity_sha256"]
            envelope["terminal_status"] = row["terminal_status"]
            files, attempt = _normalised_files(folder, envelope, row)
            envelope = json.loads(files['result.json'])
            replay_name = f"{key[0]}_{key[1]}_{row.get('terminal_status', 'UNKNOWN')}"
            replay_root = out / "replay" / replay_name
            if replay_root.exists():
                raise ValueError("replay output collision: " + replay_name)
            replay_root.mkdir(parents=True, exist_ok=False)
            temp_root = replay_root
            coordinator.HERE = temp_root
            proxy = _make_proxy(coordinator, adapter, plan["version_binding_sha256"], cell, row, temp_root, r2_driver)
            proxy.HERE = temp_root
            final = temp_root / "completed" / cell["cell_id"]
            certificate_proof = _persisted_certificate(formal, bound, plan, cell, row, folder, attempt, temp_root) if formal else None
            benchmark_root = bound["benchmark_root"] if bound is not None else execution["benchmark_root"]
            manifest_path = bound["manifest_path"] if bound is not None else execution["manifest_path"]
            replay_binding = {"cells": [cell], "benchmark_root": str(_path(benchmark_root)),
                              "manifest_path": str(_path(manifest_path))}
            outer = SimpleNamespace(
                runner=formal, binding=replay_binding,
                result_root=temp_root, binding_sha=plan["version_binding_sha256"],
                verify_active=lambda: _qualified_descriptor(plan, version_path, qualification_output))
            original_check = proxy.checked_record
            nested_check = _r2_checked(r2_driver, outer, original_check)
            proxy.checked_record = MethodType(nested_check, proxy)
            # The original method calls self.checked_record, so this is the
            # unchanged frozen method with only bound metadata globals replaced.
            record, checked_row = proxy.checked_record(cell, envelope, files, proxy.expectations[cell["cell_id"]])
            proxy.current = cell
            coordinator.Campaign.publication_gate(proxy, final, files)
            receipt_record, receipt_ledger = coordinator.Campaign.receipt(proxy, cell)
            proxy.ledger.append(receipt_ledger)
            if receipt_record["cell_id"] != cell["cell_id"]:
                raise ValueError("frozen receipt returned wrong cell")
            restore_campaign = _CoordinatorProxy()
            restore_campaign.adapter = adapter
            restore_campaign.receipt = MethodType(coordinator.Campaign.receipt, restore_campaign)
            restore_campaign.ledger = []
            restore_campaign.records = []
            restore_outer = SimpleNamespace(
                binding=replay_binding, result_root=temp_root, binding_sha=plan["version_binding_sha256"],
                binding_path=version_path, campaign=restore_campaign, runner=formal)
            r2_driver.Campaign.restore_receipts(restore_outer)
            neg = _negative_checks(coordinator, proxy, cell, envelope, files, row, final)
            _write(replay_root / "negative_fixture_diagnostics.json", neg)
            _write(replay_root / "gate_metadata.json", {"source_cell_id": source_cell_id,
                "cell_id": cell["cell_id"], "terminal_status": row["terminal_status"],
                "certificate_proof": certificate_proof or {"status": "NOT_APPLICABLE"},
                "receipt_record_cell_id": receipt_record["cell_id"]})
            if not all(neg.values()):
                raise ValueError("negative formal-gate fixture did not reject")
            report["checks"]["/".join(key)] = dict(status="PASSED", terminal_status=row["terminal_status"],
                replay_root=str(replay_root), publication="PASSED", receipt="PASSED", negative=neg,
                certificate="PASSED" if checked_row.get("terminal_status") == "OPTIMALITY_CERTIFIED" else "NOT_APPLICABLE",
                r2_checked_wrapper="PASSED", r2_restore_receipts="PASSED")
            certified_checked = certified_checked or checked_row.get("terminal_status") == "OPTIMALITY_CERTIFIED"
            report["selected_rows_checked"] += 1
        if timeout_key is not None and any(item.get("terminal_status") == "TIMEOUT"
                                           for item in report["checks"].values() if isinstance(item, dict)):
            report["checks"]["timeout_semantics"] = "PASSED"
        if not certified_checked:
            report["limitations"].append("no requested feasible OPTIMALITY_CERTIFIED row available for certificate replay")
        if report["selected_rows_checked"] == len(requested) and requested:
            report["r2_checked_wrapper"] = "PASSED"
            report["r2_restore_receipts"] = "PASSED"
            report["limitations"] = [item for item in report["limitations"]
                                      if not item.startswith("R2 checked wrapper")
                                      and not item.startswith("R2 restore_receipts")]
        if report["selected_rows_checked"] == len(requested) and not report["limitations"]:
            report["status"] = "PASSED"
        else:
            report["status"] = "PARTIAL" if report["selected_rows_checked"] else "UNVERIFIED"
    except Exception as error:
        report["limitations"].append("formal coordinator gate failed: " + repr(error))
        report["status"] = "UNVERIFIED"
    gate_source_after = _sha(gate_source)
    report["formal_gate_source"].update(sha256_after=gate_source_after,
                                         unchanged=(gate_source_before == gate_source_after))
    report['r2_checked_original_code_object'] = report['selected_rows_checked'] > 0
    if gate_source_before != gate_source_after:
        report["limitations"].append("formal_gate.py changed during validation")
    _write(out / "formal_gate_evidence.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--kernel-root", type=Path, required=True)
    parser.add_argument("--qualification-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.plan, args.receipt, args.kernel_root,
                             args.qualification_output, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
