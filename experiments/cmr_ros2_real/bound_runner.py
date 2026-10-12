"""Bound P2F runner adapter for the isolated ROS2 real-instance prototype.

The module deliberately does not copy the P2F algorithm.  It binds the frozen
runner to the execution binding and, for the ROS2 arm, replaces only the
solver function in cloned function globals so that the runner's own loop,
refinement, certification, and certificate fields remain authoritative.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import importlib.util
import os
import sys
import time
import types
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any, Mapping


_FORMAL_ROOT = r"C:\Users\Yuhling\.codex\worktrees\cmr-p1b-initial-label\Robotics4LLM\ltl_planning_studio\analysis\cmr_p2b_exact_empty_repair_20260929_01"
_FORMAL_P2D = r"D:\Robotics\Robotics4LLM\ltl_planning_studio\analysis\cmr_p2d_control_cohort_interface_20261001\control_cohort_loader_p2d.py"
_ROS2_BACKEND_ID = "ROS2-DISCRETE-PLAN-CMR-LASSO-V1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _native_path(value: str | Path) -> Path:
    """Accept binding paths from either the native or WSL process."""
    raw = str(value)
    path = Path(raw)
    if path.exists() or os.name == "nt":
        return path
    windows = PureWindowsPath(raw)
    if windows.drive:
        return Path("/mnt") / windows.drive.rstrip(":").lower() / Path(*windows.parts[1:])
    return path


def _source_row(bound: Mapping[str, Any], *names: str, suffix: str | None = None):
    """Resolve one binding source, refusing ambiguous role matches."""
    sources = bound.get("scientific_sources")
    if not isinstance(sources, Mapping):
        raise TypeError("binding scientific_sources is missing")
    rows = []
    wanted = {name.lower() for name in names}
    for name, row in sources.items():
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            raise ValueError(f"malformed binding source row: {name}")
        path = _native_path(row["path"]).resolve()
        lower_name = str(name).lower()
        lower_path = path.name.lower()
        if lower_name in wanted or (suffix is not None and lower_path == suffix.lower()):
            rows.append((str(name), path, str(row.get("sha256"))))
    if len(rows) != 1:
        raise KeyError(f"binding source role is not unique: {names!r}, {suffix!r}")
    name, path, expected = rows[0]
    if not path.is_file() or _sha256(path) != expected:
        raise RuntimeError(f"binding source hash mismatch: {name}")
    return name, path, expected


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _ConstantRebase(ast.NodeTransformer):
    """Change exactly the two frozen Path constants in the formal runner."""

    def __init__(self, root: Path, p2d: Path):
        self.root = root
        self.p2d = p2d
        self.seen_root = 0
        self.seen_p2d = 0
        self.records: list[dict[str, str]] = []

    def visit_Assign(self, node: ast.Assign):  # noqa: N802
        self.generic_visit(node)
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if names == ["ROOT"] or "ROOT" in names:
            value = node.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == "Path" and len(value.args) == 1
                    and isinstance(value.args[0], ast.Constant)
                    and isinstance(value.args[0].value, str)):
                raise RuntimeError("formal runner ROOT is not the frozen Path constant")
            original = value.args[0].value
            if original != _FORMAL_ROOT:
                raise RuntimeError("formal runner ROOT constant changed")
            value.args[0] = ast.Constant(value=str(self.root))
            self.seen_root += 1
            self.records.append({"name": "ROOT", "original": original,
                                 "rebased": str(self.root)})
        if names == ["_P2D_LOADER_PATH"] or "_P2D_LOADER_PATH" in names:
            value = node.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == "Path" and len(value.args) == 1
                    and isinstance(value.args[0], ast.Constant)
                    and isinstance(value.args[0].value, str)):
                raise RuntimeError("formal runner P2D path is not the frozen Path constant")
            original = value.args[0].value
            if original != _FORMAL_P2D:
                raise RuntimeError("formal runner P2D constant changed")
            value.args[0] = ast.Constant(value=str(self.p2d))
            self.seen_p2d += 1
            self.records.append({"name": "_P2D_LOADER_PATH", "original": original,
                                 "rebased": str(self.p2d)})
        return node


def _load_rebased_runner(path: Path, root: Path, p2d: Path):
    source = path.read_bytes()
    source_sha = hashlib.sha256(source).hexdigest()
    tree = ast.parse(source, filename=str(path), mode="exec")
    original_dump = ast.dump(tree, include_attributes=False)
    transformer = _ConstantRebase(root, p2d)
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)
    if transformer.seen_root != 1 or transformer.seen_p2d != 1:
        raise RuntimeError("formal runner did not expose exactly two rebase constants")
    restored = copy.deepcopy(tree)
    originals = {record['name']: record['original'] for record in transformer.records}
    for node in restored.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in originals:
                node.value.args[0].value = originals[target.id]
    if ast.dump(restored, include_attributes=False) != original_dump:
        raise RuntimeError('AST changed beyond the two top-level Path constants')
    module_name = "_cmr_ros2_real_bound_formal_runner"
    code = compile(tree, str(path), "exec")
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__spec__ = importlib.util.spec_from_file_location(module_name, path)
    sys.modules[module_name] = module
    exec(code, module.__dict__, module.__dict__)
    return module, {"source": str(path), "source_sha256": source_sha,
                    "ast_transform": "only ROOT and _P2D_LOADER_PATH Path constants",
                    "rebases": transformer.records, "other_ast_unchanged": True}


def load_bound_runner(binding: str | Path, kernel_root: str | Path):
    """Load the frozen runner after binding and path/SHA preflight."""
    integration = importlib.import_module("runtime")
    expected_runtime = Path(__file__).resolve().parents[1] / 'cmr_ros2_integration/runtime.py'
    if Path(integration.__file__).resolve() != expected_runtime:
        raise RuntimeError('integration runtime import mismatch')
    context = integration.prepare_context(str(binding), str(kernel_root))
    _, _, bound, _ = integration.core_smoke._load_binding(str(binding))
    if not isinstance(bound, Mapping):
        raise TypeError("prepare_context did not return bound binding")
    _, runner_path, runner_sha = _source_row(
        bound, "formal_runner_p2f", "formal_runner", suffix="formal_runner_p2f.py")
    _, verifier_path, verifier_sha = _source_row(
        bound, "verifier", "certificate_verifier", suffix="certificate_verifier_initial_label_v1.py")
    _, p2d_path, p2d_sha = _source_row(
        bound, "P2d_loader", "p2d_loader", suffix="control_cohort_loader_p2d.py")
    _, legacy_path, legacy_sha = _source_row(
        bound, "legacy_loader", "e2_2_runner", suffix="e2_2_runner.py")
    _, reference_path, reference_sha = _source_row(
        bound, "direct_reference", "reference", suffix="reference_initial_label_v1.py")
    _, schema_path, schema_sha = _source_row(
        bound, "validation_contract", "schema_contract", suffix="p2c_schema_contract.py")

    if verifier_path.parent != _native_path(_FORMAL_ROOT).resolve():
        raise RuntimeError('bound verifier differs from the qualified P2b root')
    if p2d_path != _native_path(_FORMAL_P2D).resolve():
        raise RuntimeError('bound P2d loader differs from the qualified path')

    runner, transform = _load_rebased_runner(runner_path, verifier_path.parent, p2d_path)
    schema_contract = _load_module("_cmr_ros2_real_bound_schema_contract", schema_path)
    preflight = runner.preflight()
    imports = {}
    for name, module, expected, expected_sha in (
            ('runner', runner, runner_path, runner_sha),
            ('verifier', runner._verifier_module, verifier_path, verifier_sha),
            ('p2d_loader', runner._p2d_loader_module, p2d_path, p2d_sha),
            ('legacy_loader', runner._legacy, legacy_path, legacy_sha),
            ('direct_reference', runner._verifier_module._reference_module,
             reference_path, reference_sha),
            ('validation_contract', schema_contract, schema_path, schema_sha)):
        actual = Path(module.__file__).resolve()
        if actual != expected or _sha256(actual) != expected_sha:
            raise RuntimeError(f'actual runner dependency import mismatch: {name}')
        imports[name] = dict(__file__=str(actual), sha256=expected_sha,
                             expected_path=str(expected), expected_sha256=expected_sha,
                             size=actual.stat().st_size)
    manifest = dict(context.get("manifest", {}))
    manifest['source_preflight_restrictions'] = manifest.pop('forbidden', {})
    manifest.update({"bound_runner": transform, "runner_imports": imports,
                     "runner_preflight": preflight,
                     "schema_contract_module": str(schema_contract.__file__),
                     "formal_runner_imported": True,
                     "benchmark_from_binding": True})
    return runner, bound, manifest


def _clone_function(function, replacements: Mapping[str, Any]):
    globals_copy = dict(function.__globals__)
    globals_copy.update(replacements)
    cloned = types.FunctionType(function.__code__, globals_copy, function.__name__,
                                function.__defaults__, function.__closure__)
    cloned.__kwdefaults__ = copy.copy(function.__kwdefaults__)
    return cloned


def _set_stats(stats: Any, work: Mapping[str, Any], product_count: int):
    prefix = int(work.get("prefix_settled", 0))
    suffix = int(work.get("suffix_settled", 0))
    component_calls = int(work.get("component_calls", 0))
    values = {
        "prefix_settled": prefix, "suffix_settled": suffix,
        "expanded_states": prefix + suffix,
        "prefix_expansions": prefix, "suffix_expansions": suffix,
        "reachable_nodes": int(work.get("reachable_nodes", 0)),
        "candidate_entries": component_calls,
        "exact_entry_searches": component_calls,
        "shortest_path_calls": int(work.get("helper_calls", 0)),
        "queue_pushes": int(work.get("queue_pushes", 0)),
        "queue_pops": int(work.get("queue_pops", 0)),
        "product_states_unique": product_count,
        "qualifying_sccs": 0, "lower_bound_settled": 0,
        "bound_pruned_entries": 0,
    }
    for name, value in values.items():
        if not hasattr(stats, name):
            raise TypeError(f"SearchStats missing required field {name}")
        setattr(stats, name, int(value))


def _measure_ros2_solver(backend, discrete_plan, capture, abstract, stats):
    work = {"precision": sorted(getattr(abstract, "precision", ())),
            "helper_calls": 0, "component_calls": 0, "prefix_settled": 0,
            "suffix_settled": 0, "reachable_nodes": 0, "queue_pushes": 0,
            "queue_pops": 0, "helpers": [],
            "deadline_ns": capture.get("deadline_ns"),
            "deadline_observed_exceeded": False}
    originals = {name: getattr(discrete_plan, name) for name in
                 ("_prefix_distances", "_component_distances", "_restore_tight_path",
                  "heappush", "heappop")}
    product_count = len(getattr(abstract, "states", ()))

    def push(heap, item):
        work["queue_pushes"] += 1
        return originals["heappush"](heap, item)

    def pop(heap):
        work["queue_pops"] += 1
        return originals["heappop"](heap)

    def distance_wrapper(name, original, *args, **kwargs):
        graph = args[0] if args else None
        from networkx import DiGraph
        if type(graph) is not DiGraph:
            raise TypeError('heap instrumentation requires the native auxiliary DiGraph')
        record = {"helper": name, "nodes": len(graph) if graph is not None else None,
                  "edges": graph.number_of_edges() if graph is not None else None}
        work["helper_calls"] += 1
        if name == "_component_distances":
            work["component_calls"] += 1
        try:
            deadline = capture.get('deadline_ns')
            if deadline is not None and time.perf_counter_ns() >= deadline:
                raise TimeoutError('method deadline reached before helper')
            result = original(*args, **kwargs)
            record.update({"returned_len": len(result), "completed": True})
            if name == "_prefix_distances":
                work["prefix_settled"] += len(result)
                work["reachable_nodes"] = sum(
                    1 for key in result if isinstance(key, int) and key < product_count)
            elif name == "_component_distances":
                work["suffix_settled"] += len(result)
            elif name == "_restore_tight_path":
                record["returned_len"] = len(result)
            if deadline is not None and time.perf_counter_ns() >= deadline:
                raise TimeoutError('method deadline reached after helper')
            return result
        except BaseException as exc:
            record.update({"completed": False, "error": repr(exc)})
            raise
        finally:
            work["helpers"].append(record)

    discrete_plan.heappush = push
    discrete_plan.heappop = pop
    discrete_plan._prefix_distances = lambda *a, **k: distance_wrapper(
        "_prefix_distances", originals["_prefix_distances"], *a, **k)
    discrete_plan._component_distances = lambda *a, **k: distance_wrapper(
        "_component_distances", originals["_component_distances"], *a, **k)
    discrete_plan._restore_tight_path = lambda *a, **k: distance_wrapper(
        "_restore_tight_path", originals["_restore_tight_path"], *a, **k)
    try:
        result = backend.solve_cmr_lasso(abstract)
        work["completed"] = True
        return result, work, product_count
    except BaseException:
        work["completed"] = False
        raise
    finally:
        work["queue_pushes"] = int(work["queue_pushes"])
        work["queue_pops"] = int(work["queue_pops"])
        deadline = work.get("deadline_ns")
        if deadline is not None:
            work["deadline_observed_exceeded"] = time.perf_counter_ns() >= deadline
        for name, original in originals.items():
            setattr(discrete_plan, name, original)
        capture.setdefault("search_work", []).append(work)


def configure_backend(runner: Any, backend: str) -> dict[str, Any]:
    """Configure one runner and return its transport/search capture object."""
    if backend not in {"reference", "ros2"}:
        raise ValueError("backend must be reference or ros2")
    capture: dict[str, Any] = {"backend": backend, "search_work": [],
                               "lasso": None, "instance": None,
                               "counter_basis": (
                                   "qualified reference SearchStats" if backend == "reference"
                                   else "ROS2 adapter does not run SCC lower-bound or pruning phases")}
    original_local = runner.run_method_local
    capture["original_run_method_local"] = original_local

    if backend == "reference":
        def reference_local(*args, **kwargs):
            capture["instance"] = args[0] if args else kwargs.get("instance")
            capture["deadline_ns"] = kwargs.get("deadline_ns")
            returned = original_local(*args, **kwargs)
            if isinstance(returned, tuple) and len(returned) == 3:
                capture["lasso"] = returned[2]
            return returned

        runner.run_method_local = reference_local
        capture["backend_id"] = getattr(runner, "BACKEND_ID", None)
        capture["backend_sha256"] = getattr(runner, "BACKEND_SHA256", None)
        capture["run_method_local"] = reference_local
        return capture

    smoke_backend = importlib.import_module('runtime').core_backend
    discrete_plan = importlib.import_module(
        "ltl_automaton_planner_core.ltl_tools.discrete_plan")

    def solve_wrapper(abstract, stats=None):
        result, work, product_count = _measure_ros2_solver(
            smoke_backend, discrete_plan, capture, abstract, stats)
        if stats is not None:
            _set_stats(stats, work, product_count)
        capture["lasso"] = result
        return result

    dp_path = Path(discrete_plan.__file__).resolve()
    old_sha = _sha256(Path(smoke_backend.__file__).resolve())
    canonical = f"{_ROS2_BACKEND_ID}|{_sha256(dp_path)}|{old_sha}"
    runner.BACKEND_ID = _ROS2_BACKEND_ID
    runner.BACKEND_SHA256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    cloned_loop = _clone_function(runner._run_kernel_loop,
                                  {"solve_exact_abstract_lasso": solve_wrapper})
    cloned_local = _clone_function(runner.run_method_local,
                                   {"_run_kernel_loop": cloned_loop})
    capture['original_loop_code_preserved'] = cloned_loop.__code__ is runner._run_kernel_loop.__code__
    capture['original_local_code_preserved'] = cloned_local.__code__ is original_local.__code__

    def local_capture(*args, **kwargs):
        capture["instance"] = args[0] if args else kwargs.get("instance")
        capture["deadline_ns"] = kwargs.get("deadline_ns")
        result = cloned_local(*args, **kwargs)
        if isinstance(result, tuple) and len(result) == 3:
            capture["lasso"] = result[2]
        return result

    runner.run_method_local = local_capture
    capture.update({"backend_id": runner.BACKEND_ID,
                    "backend_sha256": runner.BACKEND_SHA256,
                    "run_method_local": local_capture,
                    "solve_wrapper": solve_wrapper})
    return capture

