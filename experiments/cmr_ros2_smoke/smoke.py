"""Prepare and run the isolated ROS2/CMR lasso smoke (explicitly opt-in)."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import traceback
from dataclasses import asdict
from dataclasses import replace
from fractions import Fraction
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DISCRETE_PLAN_SHA256 = "556b6925a61ce408a0b42d56da45138fcdf3c7c7655e7850eb17b551996df31b"
EXPECTED_SCHEMA = "cmr-ros2-integration-smoke-v1"
EXPECTED_SEMANTIC_CONTRACT_SHA256 = (
    "ceafe2799bf469f24bb53d2fdb5070f2e11d581445d4ae47adf921c4590d4308"
)
EXPECTED_METHODS = ("FULL", "AP-D", "DEP-D")
EXPECTED_BINDING_SCHEMA = "CMR_CORE_R2_EXECUTION_BINDING_V1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _native_path(value: str | Path) -> Path:
    raw = str(value)
    candidate = Path(raw)
    if candidate.exists() or os.name == "nt":
        return candidate
    windows = PureWindowsPath(raw)
    if windows.drive:
        drive = windows.drive.rstrip(":").lower()
        return Path("/mnt") / drive / Path(*windows.parts[1:])
    return candidate


def _json(path: Path) -> Any:
    """Read one JSON control document."""
    return json.loads(path.read_text(encoding="utf-8"))


def _source_map_checks(mapping: Mapping[str, Any], label: str) -> list[dict[str, Any]]:
    """Hash every explicitly named source row and reject malformed rows."""
    if not isinstance(mapping, Mapping):
        raise TypeError(f"{label} must be an object")
    checks = []
    for name, value in mapping.items():
        if (not isinstance(value, Mapping) or not isinstance(value.get("path"), str)
                or not isinstance(value.get("sha256"), str)):
            raise ValueError(f"malformed source row: {label}.{name}")
        path = _native_path(value["path"])
        expected = value.get("sha256")
        exists = path.is_file()
        actual = sha256_file(path) if exists else None
        row = {"label": label, "name": name, "path": str(path),
               "size": path.stat().st_size if exists else None,
               "expected_sha256": expected, "actual_sha256": actual,
               "match": bool(exists and actual == expected)}
        checks.append(row)
        if not row["match"]:
            raise ValueError(f"source hash mismatch: {label}.{name}")
    return checks


def _load_binding(path_arg: str) -> tuple[Path | None, Path, dict[str, Any], list[dict[str, Any]]]:
    """Load the receipt/binding pair and verify the 20 code-source rows."""
    supplied = _native_path(path_arg).resolve()
    document = _json(supplied)
    receipt_path = (
        supplied
        if isinstance(document, Mapping) and "scientific_source_refs" in document
        else None
    )
    checks = []
    if receipt_path is not None:
        checks.extend(_source_map_checks(
            document.get("scientific_source_refs", {}), "receipt.scientific_source_refs"
        ))
        execution = document.get("execution_binding") or {}
        binding_raw = execution.get("path") if isinstance(execution, Mapping) else None
        binding_expected_sha = execution.get("sha256") if isinstance(execution, Mapping) else None
        if not isinstance(binding_raw, str):
            raise ValueError("receipt has no execution_binding path")
        if not isinstance(binding_expected_sha, str):
            raise ValueError("receipt execution_binding has no SHA256")
        binding_path = _native_path(binding_raw).resolve()
        if not binding_path.is_file() or sha256_file(binding_path) != binding_expected_sha:
            raise ValueError("receipt execution_binding hash mismatch")
        binding = _json(binding_path)
    else:
        binding_path = supplied
        binding = document
    receipt_sources = document.get("scientific_source_refs") if receipt_path else None
    if receipt_path and len(receipt_sources) != 20:
        raise ValueError("receipt scientific_source_refs must contain exactly 20 rows")
    binding_sources = binding.get("scientific_sources")
    if not isinstance(binding_sources, Mapping) or len(binding_sources) != 20:
        raise ValueError("binding scientific_sources must contain exactly 20 rows")
    if receipt_path:
        for name, receipt_row in receipt_sources.items():
            binding_row = binding_sources.get(name)
            if (not isinstance(binding_row, Mapping)
                    or binding_row.get("path") != receipt_row.get("path")
                    or binding_row.get("sha256") != receipt_row.get("sha256")):
                raise ValueError(f"receipt/binding source mismatch: {name}")
    if receipt_path and document.get("population") != "Core":
        raise ValueError("receipt population must be Core")
    if receipt_path and document.get("instances") != 170:
        raise ValueError("receipt instances must be 170")
    if binding.get("methods") != list(EXPECTED_METHODS):
        raise ValueError("binding methods must be FULL/AP-D/DEP-D")
    if binding.get("population") != "Core170" or binding.get("population_count") != 170:
        raise ValueError("binding population must be Core170 with population_count 170")
    if binding.get("schema") != EXPECTED_BINDING_SCHEMA:
        raise ValueError("binding schema mismatch")
    semantic = binding_sources.get("semantic_contract")
    if (not isinstance(semantic, Mapping)
            or semantic.get("sha256") != EXPECTED_SEMANTIC_CONTRACT_SHA256):
        raise ValueError("semantic contract SHA mismatch")
    checks.extend(_source_map_checks(binding_sources, "binding.scientific_sources"))
    return receipt_path, binding_path, binding, checks


def _load_file_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _binding_source(binding: Mapping[str, Any], *names: str) -> tuple[Path, str]:
    """Resolve one path/SHA role from the binding's scientific sources."""
    sources = binding.get("scientific_sources", {})
    for name in names:
        value = sources.get(name)
        if isinstance(value, Mapping) and isinstance(value.get("path"), str):
            return _native_path(value["path"]).resolve(), str(value.get("sha256"))
    raise KeyError(f"binding source not found: {names}")


def _git_info() -> dict[str, Any]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=REPO_ROOT, text=True)
    return {
        "root": str(REPO_ROOT), "head": head, "clean": status == "",
        "status_lines": status.splitlines(),
    }


def preflight(
    kernel_root_arg: str, binding_arg: str,
) -> tuple[dict[str, Any], dict[str, Any], Any, Any, Any, Any, Any]:
    receipt_path, binding_path, binding, source_checks = _load_binding(binding_arg)
    kernel_root = _native_path(kernel_root_arg).resolve()
    if str(kernel_root) not in sys.path:
        sys.path.insert(0, str(kernel_root))

    model = importlib.import_module("ecc_p1.model")
    solver = importlib.import_module("ecc_p1.solver")
    abstraction = importlib.import_module("ecc_p1.abstraction")
    concretization = importlib.import_module("ecc_p1.concretization")
    certificate = importlib.import_module("ecc_p1.certificate")
    grouped_path, grouped_expected = _binding_source(binding, "grouped_abstraction")
    grouped = _load_file_module("cmr_ros2_smoke_grouped", grouped_path)
    discrete_plan = importlib.import_module("ltl_automaton_planner_core.ltl_tools.discrete_plan")

    expected_modules = {
        "model": (model, _binding_source(binding, "model")),
        "solver": (solver, _binding_source(binding, "SCC_solver", "solver")),
        "abstraction": (abstraction, _binding_source(binding, "projection", "abstraction")),
        "concretization": (
            concretization, _binding_source(binding, "concretizer", "concretization")
        ),
        "certificate": (certificate, _binding_source(binding, "certificate")),
        "grouped_abstraction": (grouped, (grouped_path, grouped_expected)),
    }
    imports = {}
    for name, (module, (expected_path, expected_sha)) in expected_modules.items():
        actual_path = Path(module.__file__).resolve()
        actual_sha = sha256_file(actual_path)
        if actual_path != expected_path or actual_sha != expected_sha:
            raise RuntimeError(f"qualified import mismatch: {name}")
        imports[name] = {"__file__": str(actual_path), "size": actual_path.stat().st_size,
                         "sha256": actual_sha, "expected_path": str(expected_path),
                         "expected_sha256": expected_sha}

    dp_path = Path(discrete_plan.__file__).resolve()
    expected_dp_path = (REPO_ROOT / "ltl_automaton_planner_core" / "ltl_automaton_planner_core" /
                        "ltl_tools" / "discrete_plan.py").resolve()
    dp_sha = sha256_file(dp_path)
    if dp_path != expected_dp_path or dp_sha != EXPECTED_DISCRETE_PLAN_SHA256:
        raise RuntimeError("ROS2 discrete_plan import/hash mismatch")
    imports["ros2_discrete_plan"] = {"__file__": str(dp_path), "size": dp_path.stat().st_size,
                                     "sha256": dp_sha, "expected_path": str(expected_dp_path),
                                     "expected_sha256": EXPECTED_DISCRETE_PLAN_SHA256}

    manifest = {
        "schema": "cmr-ros2-integration-smoke-preflight-v1",
        "receipt_path": str(receipt_path) if receipt_path else None,
        "binding_path": str(binding_path),
        "binding_sha256": sha256_file(binding_path),
        "kernel_root": str(kernel_root),
        "imports": imports,
        "source_checks": source_checks,
        "git": _git_info(),
        "forbidden": {"formal_runner_imported": False, "planner_pickle_loaded": False,
                       "benchmark_or_results_read": False},
    }
    return manifest, binding, model, solver, grouped, concretization, certificate


def _fixture_model(model_module: Any, variant: str):
    """Build one deterministic two-factor synthetic CMR fixture."""
    FormalAction = model_module.FormalAction
    FormalFactorizedModel = model_module.FormalFactorizedModel
    BuchiAutomaton = model_module.BuchiAutomaton
    initial = (1, 0) if variant == "initial_goal" else (0, 0)
    zero = variant == "zero_cost"

    def buchi_transition(state, labels):
        return {"q_accept"} if "goal" in labels else {"q_wait"}

    def label(state):
        return frozenset({"goal"}) if state[0] == 1 else frozenset()

    def go_guard(state):
        return state[0] == 0

    def go_effect(state):
        return (1, state[1])

    def return_guard(state):
        return state[0] == 1

    def return_effect(state):
        return (0, state[1])

    def noise_effect(state):
        return (state[0], 1 - state[1])

    def go_cost(_source, _target):
        return Fraction(0) if zero else Fraction(1 + _source[1], 3)

    def b_cost(_source, _target):
        return Fraction(0) if zero else Fraction(2 + _source[1], 3)

    def return_cost(_source, _target):
        return Fraction(0 if zero else 2, 3)

    def noise_cost(_source, _target):
        return Fraction(5)

    actions = (
        FormalAction(
            "a_go", frozenset({0}), frozenset({0}), frozenset({1}),
            go_guard, go_effect, go_cost,
        ),
        FormalAction(
            "b_go", frozenset({0}), frozenset({0}), frozenset({1}),
            go_guard, go_effect, b_cost,
        ),
        FormalAction(
            "c_return", frozenset({0}), frozenset({0}), frozenset({0}),
            return_guard, return_effect, return_cost,
        ),
        FormalAction(
            "d_noise", frozenset({1}), frozenset({1}), frozenset({1}),
            lambda state: True, noise_effect, noise_cost,
        ),
    )
    accepting = frozenset() if variant == "no_accept" else frozenset({"q_accept"})
    buchi = BuchiAutomaton("q_wait", accepting, buchi_transition)
    return FormalFactorizedModel(
        dimensions=(0, 1), local_states=((0, 1), (0, 1)),
        initial_states=frozenset({initial}), actions=actions, label=label,
        buchi=buchi, task_ap=frozenset({"goal"}), task_support={"goal": frozenset({0})},
    )


def _edge_payload(edge: Any) -> dict[str, Any]:
    """Serialize one abstract transition and its concrete witnesses."""
    return {"source": edge.source, "action": edge.action, "target": edge.target,
            "cost": str(edge.cost), "witnesses": [
                {"source": w.source, "action": w.action, "target": w.target, "cost": str(w.cost)}
                for w in edge.witnesses
            ]}


def _result_payload(result: Any) -> dict[str, Any] | None:
    """Serialize a qualified lasso without changing the returned objects."""
    if result is None:
        return None
    return {"status": result.status, "precision": sorted(result.precision),
            "prefix": result.prefix, "suffix": result.suffix,
            "prefix_cost": str(result.prefix_cost), "suffix_cost": str(result.suffix_cost),
            "lower_bound": str(result.lower_bound),
            "prefix_edges": [_edge_payload(e) for e in result.prefix_edges],
            "suffix_edges": [_edge_payload(e) for e in result.suffix_edges],
            "accepting_product_states": result.accepting_product_states,
            "identity": result.identity}


def _require(condition: bool, message: str) -> None:
    """Raise a visible assertion error for a failed smoke invariant."""
    if not condition:
        raise AssertionError(message)


def _task_precision(model: Any) -> frozenset[int]:
    """Compute S_phi from task propositions and their declared support."""
    task_ap = set(model.task_ap or ())
    if not task_ap:
        return frozenset()
    return frozenset().union(*(model.task_support[prop] for prop in task_ap))


def _dependency_precision(model: Any, initial: frozenset[int]) -> frozenset[int]:
    """Apply write-intersection to support.k until the DEP-D closure settles."""
    precision = set(initial)
    supports = model.supports()
    while True:
        additions = set()
        for action in model.actions:
            support = supports[action.name]
            if support.write & precision:
                additions.update(support.k)
        if additions.issubset(precision):
            return frozenset(sorted(precision))
        precision.update(additions)


def _abstract_snapshot(abstract: Any) -> tuple[Any, ...]:
    """Capture abstract structure and transition/witness identities."""
    transitions = tuple(abstract.transitions)
    witness_ids = tuple(tuple(id(witness) for witness in edge.witnesses) for edge in transitions)
    return (tuple(abstract.states), tuple(abstract.initial_states),
            tuple(id(edge) for edge in transitions), witness_ids)


def _one_case(
    model_module, solver, grouped, concretization, certificate, backend,
    variant: str, method: str,
):
    model = _fixture_model(model_module, variant)
    s_phi = _task_precision(model)
    precision = (frozenset(model.dimensions) if method == "FULL" else
                 s_phi if method == "AP-D" else _dependency_precision(model, s_phi))
    expected_precision = frozenset({0, 1}) if method in {"FULL", "DEP-D"} else frozenset({0})
    _require(
        precision == expected_precision,
        f"{variant}/{method}: unexpected precision {precision}",
    )
    abstract = grouped.build_optimistic_abstraction(model, precision)
    before = _abstract_snapshot(abstract)
    reference = solver.solve_exact_abstract_lasso(abstract, solver.SearchStats())
    adapted = backend.solve_cmr_lasso(abstract)
    after = _abstract_snapshot(abstract)
    _require(before == after, f"{variant}/{method}: abstract input changed")
    expected = (
        None if variant == "no_accept"
        else Fraction(0) if variant == "zero_cost" else Fraction(10)
    )
    _require(
        (reference is None) == (adapted is None),
        f"{variant}/{method}: result presence mismatch",
    )
    if reference is not None:
        _require(reference.lower_bound == expected,
                 f"{variant}/{method}: reference lower bound "
                 f"{reference.lower_bound} != {expected}")
        for field in ("prefix_cost", "suffix_cost", "lower_bound"):
            _require(type(getattr(reference, field)) is Fraction,
                     f"{variant}/{method}: reference {field} is not Fraction")
    _require((adapted is None and expected is None) or adapted.lower_bound == expected,
             f"{variant}/{method}: expected lower bound {expected}, "
             f"got {getattr(adapted, 'lower_bound', None)}")
    if adapted is None:
        return {"variant": variant, "method": method, "expected_cost": None,
                "reference": None, "new": None, "suffix_nonempty": False,
                "accepting_visited": False, "parallel_actions": ["a_go", "b_go"]}

    for field in ("prefix_cost", "suffix_cost", "lower_bound"):
        _require(type(getattr(adapted, field)) is Fraction,
                 f"{variant}/{method}: adapted {field} is not Fraction")
    _require(adapted.suffix[0] == adapted.suffix[-1], f"{variant}/{method}: suffix not closed")
    _require(len(adapted.suffix_edges) >= 1, f"{variant}/{method}: suffix empty")
    _require(any(state[1] in abstract.accepting_buchi_states for state in adapted.suffix[:-1]),
             f"{variant}/{method}: suffix does not visit accepting state")
    if variant == "initial_goal":
        _require(all(state[1] == "q_accept" for state in abstract.initial_states),
                 f"{variant}/{method}: initial label did not enter q_accept")
    if variant == "base":
        _require(adapted.prefix[-1][1] == "q_wait",
                 f"{variant}/{method}: selected entry is not the non-accepting q_wait state")
    abstract_transition_ids = {id(edge) for edge in abstract.transitions}
    _require(
        all(id(edge) in abstract_transition_ids
            for edge in adapted.prefix_edges + adapted.suffix_edges),
        f"{variant}/{method}: transition identity not retained",
    )
    if precision == frozenset(model.dimensions):
        concrete = concretization.validate_identity_lift(model, adapted)
    else:
        concrete = concretization.periodically_concretize(model, abstract, adapted)
    _require(concrete.status == "CONCRETIZABLE", f"{variant}/{method}: not concretizable")
    cert = certificate.evaluate_certificate(adapted.lower_bound, concrete)
    _require(
        cert.status == "OPTIMALITY_CERTIFIED",
        f"{variant}/{method}: certificate {cert.status}",
    )
    parallel = [edge.action for edge in abstract.transitions
                if edge.action in {"a_go", "b_go"}
                and edge.source[0][0] == 0
                and edge.target[0][0] == 1]
    _require(set(parallel) == {"a_go", "b_go"}, f"{variant}/{method}: parallel transitions lost")
    return {"variant": variant, "method": method, "expected_cost": str(expected),
            "reference": _result_payload(reference), "new": _result_payload(adapted),
            "suffix_nonempty": True, "accepting_visited": True,
            "parallel_actions": sorted(set(parallel)), "certificate": asdict(cert)}


def _negative_input_checks(model_module, grouped, backend) -> list[dict[str, str]]:
    """Check the exact nonnegative Fraction boundary without reference calls."""
    model = _fixture_model(model_module, "base")
    abstract = grouped.build_optimistic_abstraction(model, frozenset({0, 1}))
    original = abstract.transitions[0]
    checks = []
    for label, bad_cost, expected_error in (
        ("bool", True, "TypeError"),
        ("float", 0.5, "TypeError"),
        ("negative", -1, "ValueError"),
    ):
        transitions = (replace(original, cost=bad_cost),) + tuple(abstract.transitions[1:])
        malformed = replace(abstract, transitions=transitions)
        try:
            backend.solve_cmr_lasso(malformed)
        except Exception as exc:
            actual = type(exc).__name__
            _require(actual == expected_error, f"negative input {label}: got {actual}")
            checks.append({"input": label, "expected": expected_error, "actual": actual})
        else:
            raise AssertionError(f"negative input {label} was accepted")
    return checks


def run_smoke(args: argparse.Namespace, artifact: dict[str, Any]) -> None:
    """Append preflight and completed rows to a caller-owned artifact."""
    manifest, binding, model, solver, grouped, concretization, certificate = preflight(
        args.kernel_root, args.binding)
    artifact["manifest_preflight"] = manifest
    backend = _load_file_module(
        "cmr_ros2_smoke_backend", Path(__file__).with_name("backend.py").resolve()
    )

    artifact["negative_input_checks"] = _negative_input_checks(model, grouped, backend)
    for variant in ("base", "initial_goal", "zero_cost", "no_accept"):
        for method in EXPECTED_METHODS:
            artifact["rows"].append(
                _one_case(
                    model, solver, grouped, concretization, certificate,
                    backend, variant, method,
                )
            )
    artifact["binding_campaign_id"] = binding.get("campaign_id")
    artifact["status"] = "PASSED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True, help="final receipt or execution_binding.json")
    parser.add_argument("--kernel-root", required=True, help="ecc_p1_formal_kernel path")
    parser.add_argument("--output", required=True, help="JSON artifact path, normally under /tmp")
    args = parser.parse_args()
    output = _native_path(args.output).resolve()
    if os.name != "nt" and not str(output).startswith("/tmp/"):
        raise SystemExit("--output must be under /tmp on POSIX/WSL")
    output.parent.mkdir(parents=True, exist_ok=True)
    artifact = {"schema": EXPECTED_SCHEMA, "population": "SYNTHETIC_SMOKE", "status": "RUNNING",
                "manifest_preflight": None, "negative_input_checks": [], "rows": [],
                "methods": list(EXPECTED_METHODS),
                "variants": ["base", "initial_goal", "zero_cost", "no_accept"],
                "discrete_plan_helpers": ["_prefix_distances", "_component_distances",
                                            "_restore_tight_path"]}
    try:
        run_smoke(args, artifact)
        rc = 0
    except Exception as exc:
        artifact["status"] = "FAILED"
        artifact["error"] = repr(exc)
        artifact["traceback"] = traceback.format_exc()
        traceback.print_exc(file=sys.stderr)
        rc = 1
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
