"""Small deterministic qualification fixtures for the Product V6 builder.

This module is deliberately fixture-only.  It binds the frozen grouped-builder
source by receipt/binding bytes, then compares that builder with the V6 copy on
small formal models.  It never loads the formal runner or invokes a planner.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import traceback
from fractions import Fraction
from typing import Iterable


GROUPED_SHA = "c964ad7c6cf8f80d9d0831f6955ebe651efa7701a3ccf1304d332b421efa8dfc"
RECEIPT_DEFAULT = Path(
    r"D:\Robotics\Robotics4LLM\ltl_planning_studio\analysis"
    r"\cmr_experiment_a_missing_data_repair_20261004\final_campaign_receipt.json"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(value: str | Path) -> Path:
    path = Path(value)
    if path.exists():
        return path
    text = str(value)
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if match:
        return Path("/mnt", match.group(1).lower(), *re.split(r"[\\/]", match.group(2)))
    return path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _authority(binding_arg: str, kernel_arg: str) -> dict:
    # The CLI binding is the frozen receipt.  The bound adapter performs the
    # complete source/import preflight and returns the runner's actual module.
    receipt_path = _path(binding_arg).resolve()
    if receipt_path.name != "final_campaign_receipt.json":
        raise ValueError("--binding must be final_campaign_receipt.json")
    kernel_root = _path(kernel_arg).resolve()
    if not (kernel_root / "ecc_p1" / "model.py").exists():
        raise ValueError("kernel root does not contain ecc_p1/model.py")
    if str(kernel_root) not in sys.path:
        sys.path.insert(0, str(kernel_root))
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from experiments.cmr_ros2_bfull_perf import compare as foundation
    formal, bound, manifest = foundation.binding_adapter.load_bound_runner(
        receipt_path, kernel_root)
    authority = formal._p2f_grouped
    grouped_path = Path(authority.__file__).resolve()
    grouped_sha = _sha(grouped_path)
    if grouped_sha != GROUPED_SHA:
        raise ValueError("runner imported grouped abstraction hash mismatch")
    return {
        "binding_path": str(receipt_path),
        "binding_sha256": _sha(receipt_path),
        "grouped_path": str(grouped_path),
        "grouped_sha256": grouped_sha,
        "receipt_path": str(receipt_path),
        "receipt_sha256": _sha(receipt_path),
        "kernel_root": str(kernel_root),
        "module": authority,
        "formal": formal,
        "bound": bound,
        "manifest": manifest,
    }


def _fn_body(module, name: str):
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name)


def _prefix_ast(module) -> list[str]:
    fn = _fn_body(module, "build_optimistic_abstraction")
    result = []
    for statement in fn.body:
        dump = ast.dump(statement, include_attributes=False)
        if "product_started" in dump:
            break
        if (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)):
            continue
        if "work" not in dump:
            result.append(dump)
    return result


def _static_checks(authority, candidate) -> dict:
    original = Path(authority.__file__).read_text(encoding="utf-8")
    source = Path(candidate.__file__).read_text(encoding="utf-8")
    original_tree = ast.parse(original)
    candidate_tree = ast.parse(source)
    reachable_calls = [node for node in ast.walk(_fn_body(candidate, "build_optimistic_abstraction"))
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id == "_reachable_full_ts"]
    candidate_timing = set(re.findall(r'timing\["(T_[A-Za-z_]+_ns)"\]', source))
    def result_constructor(module):
        fn = _fn_body(module, "build_optimistic_abstraction")
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "OptimisticAbstractModel"):
                return ast.dump(node, include_attributes=False)
        return None
    def timing_dumps(module):
        fn = _fn_body(module, "build_optimistic_abstraction")
        return tuple(ast.dump(node, include_attributes=False)
                     for node in fn.body if isinstance(node, ast.If)
                     and isinstance(node.test, ast.Compare)
                     and isinstance(node.test.left, ast.Name)
                     and node.test.left.id == "timing")
    return {
        "authority_source_sha256": _sha(Path(authority.__file__)),
        "candidate_source_sha256": _sha(Path(candidate.__file__)),
        "authority_ast_parse": True,
        "candidate_ast_parse": True,
        "product_prefix_ast_match": _prefix_ast(authority) == _prefix_ast(candidate),
        "reachable_full_ts_calls": len(reachable_calls),
        "candidate_uses_deque": "from collections import deque" in source and ".popleft()" in source,
        "timing_keys_unchanged": candidate_timing == {"T_full_ts_ns", "T_reduction_ns", "T_product_ns"},
        "result_constructor_ast_match": result_constructor(authority) == result_constructor(candidate),
        "timing_write_ast_match": timing_dumps(authority) == timing_dumps(candidate),
        "candidate_has_work_metrics": all(key in source for key in (
            "full_ts_rebuild_calls", "buchi_queries", "cache_hits", "cache_misses",
            "cache_entries", "product_states", "product_edges")),
        "source_function_count": sum(isinstance(node, ast.FunctionDef)
                                      and node.name == "build_optimistic_abstraction"
                                      for node in candidate_tree.body),
        "authority_function_count": sum(isinstance(node, ast.FunctionDef)
                                        and node.name == "build_optimistic_abstraction"
                                        for node in original_tree.body),
    }


def _make_model(*, initial=((0,),), dimensions=(0,), local_states=((0, 1),),
                label=None, transition=None, accepting=("q1",), task_ap=("goal",),
                action_cost=Fraction(1, 3), action_name="a_go", actions=None):
    from ecc_p1.model import BuchiAutomaton, FormalAction, FormalFactorizedModel

    dimensions = tuple(dimensions)
    initial_states = frozenset(tuple(state) for state in initial)
    if label is None:
        label = lambda state: frozenset({"goal"}) if state[0] == 1 else frozenset()
    if transition is None:
        transition = lambda q, labels: ("q1",) if "goal" in labels else ("q0",)
    if actions is None:
        actions = (
            FormalAction(
                action_name,
                frozenset({0}),
                frozenset({0}),
                frozenset({0}),
                lambda state: state[0] == 0,
                lambda state: (1,) + tuple(state[1:]),
                lambda source, target: action_cost,
            ),
            FormalAction(
                "b_stay",
                frozenset({0}),
                frozenset(),
                frozenset(),
                lambda state: state[0] == 1,
                lambda state: state,
                lambda source, target: Fraction(2, 3),
            ),
        )
    return FormalFactorizedModel(
        dimensions=dimensions,
        local_states=tuple(tuple(domain) for domain in local_states),
        initial_states=initial_states,
        actions=actions,
        label=label,
        buchi=BuchiAutomaton("q0", frozenset(accepting), transition),
        task_ap=frozenset(task_ap),
        task_support={"goal": frozenset({0})} if task_ap else {},
    )


def _edge_signature(edge):
    return (edge.source, edge.action, edge.target, edge.cost,
            tuple((w.source, w.action, w.target, w.cost) for w in edge.witnesses))


def _model_signature(model):
    return {
        "precision": model.precision,
        "states": model.states,
        "initial_states": model.initial_states,
        "transitions": tuple(_edge_signature(edge) for edge in model.transitions),
        "labels": dict(model.labels),
        "supports": model.supports,
        "accepting_buchi_states": model.accepting_buchi_states,
        "reachable_ts_states": model.reachable_ts_states,
        "provenance": model.provenance,
        "reduced_ts_edge_count": model.reduced_ts_edge_count,
    }


def _run_pair(original, candidate, model, precision, *, require_hit=False):
    original_edges = []
    candidate_edges = []
    original_reach = original._reachable_full_ts
    candidate_reach = candidate._reachable_full_ts

    def record_original(value):
        states, edges = original_reach(model)
        original_edges.append(edges)
        return states, edges

    def record_candidate(value):
        states, edges = candidate_reach(model)
        candidate_edges.append(edges)
        return states, edges

    transition = model.buchi.transition
    calls = {"count": 0}

    def counted_transition(state, label):
        calls["count"] += 1
        return transition(state, label)

    old = new = None
    old_error = new_error = None
    original._reachable_full_ts = record_original
    candidate._reachable_full_ts = record_candidate
    object.__setattr__(model.buchi, "transition", counted_transition)
    try:
        old_timing, new_timing, work = {}, {}, {}
        try:
            old = original.build_optimistic_abstraction(model, precision, timing=old_timing)
        except Exception as exc:  # compare the two arms on rejected inputs
            old_error = exc
        old_calls = calls["count"]
        calls["count"] = 0
        try:
            new = candidate.build_optimistic_abstraction(model, precision, timing=new_timing, work=work)
        except Exception as exc:
            new_error = exc
        new_calls = calls["count"]
    finally:
        object.__setattr__(model.buchi, "transition", transition)
        original._reachable_full_ts = original_reach
        candidate._reachable_full_ts = candidate_reach
    if (old_error is None) != (new_error is None):
        raise AssertionError(f"original/candidate error mismatch: {old_error!r} / {new_error!r}")
    if old_error is not None:
        if type(old_error) is not type(new_error) or str(old_error) != str(new_error):
            raise AssertionError(f"original/candidate errors differ: {old_error!r} / {new_error!r}")
        raise type(old_error)(str(old_error))
    if (old_calls != work["buchi_queries"]
            or new_calls != work["cache_misses"]
            or work["buchi_queries"] != work["cache_hits"] + work["cache_misses"]
            or (require_hit and work["cache_hits"] <= 0)):
        raise AssertionError("Buchi cache query/call accounting is invalid")
    if _model_signature(old) != _model_signature(new):
        raise AssertionError("original and candidate Product dataclasses differ")
    if old_calls <= 0 or len(original_edges) != 1 or len(candidate_edges) != 1:
        raise AssertionError("full TS was not rebuilt exactly once per build")
    for result, captured, label in ((old, original_edges, "original"),
                                    (new, candidate_edges, "candidate")):
        for edge in result.transitions:
            for witness in edge.witnesses:
                if not any(witness is item for item in captured[0]):
                    raise AssertionError(f"{label} witness is not from its full TS build")
    if not work["completed"] or work["full_ts_rebuild_calls"] != 1:
        raise AssertionError("candidate work completion metrics are invalid")
    return old, new, work


@dataclass(frozen=True)
class Fixture:
    name: str
    model: object
    precision: tuple[int, ...]
    expect_error: str | None = None


def _fixtures() -> tuple[Fixture, ...]:
    from ecc_p1.model import FormalAction

    duplicate = _make_model(
        initial=((1,),),
        transition=lambda q, labels: ("q1", "q1", "q0") if "goal" in labels else ("q0",),
    )
    empty = _make_model(transition=lambda q, labels: ())
    fraction = _make_model(action_cost=Fraction(5, 7))
    multi = _make_model(
        initial=((0,), (1,)),
        transition=lambda q, labels: ("q1",) if "goal" in labels else ("q0",),
    )
    unreachable = _make_model(
        accepting=("q1", "q_dead"),
        transition=lambda q, labels: ("q1",) if "goal" in labels else ("q0",),
    )
    disagree = _make_model(
        initial=((0, 0),), dimensions=(0, 1), local_states=((0,), (0, 1)),
        label=lambda state: frozenset({"goal"}) if state[1] else frozenset(),
        actions=(
            FormalAction(
                "a_hidden",
                frozenset({1}), frozenset({1}), frozenset({1}),
                lambda state: state == (0, 0),
                lambda state: (0, 1),
                lambda source, target: Fraction(1, 1),
            ),
        ),
    )
    same_s_a = _make_model(transition=lambda q, labels: ("q1",))
    same_s_b = _make_model(transition=lambda q, labels: ("q0",))
    return (
        Fixture("duplicate_successors", duplicate, (0,)),
        Fixture("empty_successors", empty, (0,)),
        Fixture("fraction_and_initial_consumption", fraction, (0,)),
        Fixture("multiple_initial", multi, (0,)),
        Fixture("unreachable_buchi", unreachable, (0,)),
        Fixture("label_disagreement", disagree, (0,), "task label disagreement"),
        Fixture("same_shape_model_a", same_s_a, (0,)),
        Fixture("same_shape_model_b", same_s_b, (0,)),
    )


def run_fixtures(authority, candidate) -> dict:
    static = _static_checks(authority, candidate)
    if not static["product_prefix_ast_match"]:
        raise AssertionError("authority Product pre-region changed")
    if (static["reachable_full_ts_calls"] != 1 or not static["candidate_uses_deque"]
            or not static["result_constructor_ast_match"]
            or not static["timing_write_ast_match"] or not static["timing_keys_unchanged"]):
        raise AssertionError("candidate Product traversal shape is not the approved one")
    rows = []
    built = {}
    for fixture in _fixtures():
        try:
            old, new, work = _run_pair(
                authority, candidate, fixture.model, fixture.precision,
                require_hit=fixture.name in {"duplicate_successors", "multiple_initial"})
            if fixture.expect_error:
                raise AssertionError("expected fixture error was not raised")
            if fixture.name == "fraction_and_initial_consumption":
                if new.initial_states != (((0,), "q0"),):
                    raise AssertionError("initial Buchi consumption changed")
                if not new.transitions or new.transitions[0].action != "a_go":
                    raise AssertionError("initial action fixture is not represented")
                if new.transitions[0].cost != Fraction(5, 7):
                    raise AssertionError("Fraction action cost changed")
            built[fixture.name] = _model_signature(new)
            rows.append({"name": fixture.name, "status": "PASSED", "work": work,
                         "states": len(new.states), "transitions": len(new.transitions)})
        except Exception as exc:
            if (fixture.expect_error and type(exc) is ValueError
                    and str(exc).startswith(fixture.expect_error)):
                rows.append({"name": fixture.name, "status": "PASSED", "expected_error": str(exc)})
            else:
                raise

    # A second build of the same model must start with a fresh local cache.
    repeat = _fixtures()[2].model
    _, _, first_work = _run_pair(authority, candidate, repeat, (0,))
    _, _, second_work = _run_pair(authority, candidate, repeat, (0,))
    if first_work["cache_misses"] != second_work["cache_misses"]:
        raise AssertionError("Buchi cache leaked across builds")
    rows.append({"name": "repeat_build_no_cache_leak", "status": "PASSED",
                 "first_work": first_work, "second_work": second_work})

    if built["same_shape_model_a"] == built["same_shape_model_b"]:
        raise AssertionError("same-shape models did not remain semantically distinct")
    rows.append({"name": "same_shape_model_isolation", "status": "PASSED"})
    return {"status": "PASSED", "schema": "cmr-ros2-product-fixtures-v1",
            "static": static, "cases": rows, "case_count": len(rows)}


def _real_product_checks(authority, candidate) -> list[dict]:
    """Build at most S_phi/full precision for each frozen selected model."""
    selection_path = Path(__file__).resolve().parents[1] / "cmr_ros2_real" / "selection.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    bound = authority["bound"]
    manifest_path = _path(bound["manifest_path"]).resolve()
    benchmark_root = _path(bound["benchmark_root"]).resolve()
    rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {row["instance_id"]: row for row in rows}
    result = []
    for selected in selection["records"]:
        instance_id = selected["instance_id"]
        instance = authority["formal"].load_instance(records[instance_id], benchmark_root)
        accepting_before = frozenset(instance.model.buchi.accepting)
        precisions = [frozenset(instance.s_phi), frozenset(instance.model.dimensions)]
        if precisions[0] == precisions[1]:
            precisions.pop()
        for precision in precisions:
            old, new, work = _run_pair(authority["module"], candidate,
                                        instance.model, tuple(sorted(precision)))
            accepting_after = frozenset(instance.model.buchi.accepting)
            if accepting_after != accepting_before:
                raise AssertionError(f"Buchi accepting set changed for {instance_id}")
            result.append({"instance_id": instance_id,
                           "precision": sorted(precision),
                           "full_precision": precision == frozenset(instance.model.dimensions),
                           "accepting_before": sorted(accepting_before),
                           "accepting_after": sorted(accepting_after),
                           "states": len(new.states), "transitions": len(new.transitions),
                           "work": work})
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", required=True)
    parser.add_argument("--kernel-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = _path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "schema": "cmr-ros2-product-fixtures-v1"}
    try:
        authority = _authority(args.binding, args.kernel_root)
        candidate = _load_module(Path(__file__).with_name("builder.py").resolve(),
                                 "_cmr_product_v6_builder")
        report.update({"authority": {key: authority[key] for key in (
                           "binding_path", "binding_sha256", "grouped_path",
                           "grouped_sha256", "receipt_path", "receipt_sha256",
                           "kernel_root")},
                       "builder_path": str(Path(candidate.__file__).resolve())})
        report.update(run_fixtures(authority["module"], candidate))
        report["real_product_checks"] = _real_product_checks(authority, candidate)
    except Exception as exc:
        report.update({"status": "FAILED", "error": repr(exc),
                       "traceback": traceback.format_exc()})
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
