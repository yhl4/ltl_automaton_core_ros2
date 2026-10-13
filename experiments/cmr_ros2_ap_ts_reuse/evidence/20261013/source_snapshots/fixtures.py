"""Small offline checks for the per-attempt AP full-TS cache."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from fractions import Fraction
from pathlib import Path


def _path(value: str | Path) -> Path:
    path = Path(value)
    if path.exists():
        return path
    text = str(value)
    if len(text) > 2 and text[1] == ":":
        if os.name == "nt":
            return Path(text)
        return Path("/mnt", text[0].lower(), *text[3:].replace("\\", "/").split("/"))
    return path


def _load_kernel(root: str | Path):
    root = _path(root).resolve()
    if not (root / "ecc_p1" / "model.py").exists():
        raise ValueError(f"kernel root does not contain ecc_p1/model.py: {root}")
    sys.path.insert(0, str(root))
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from experiments.cmr_ros2_product_perf import builder as authority
    from experiments.cmr_ros2_product_perf.fixtures import _make_model, _model_signature
    from experiments.cmr_ros2_ap_ts_reuse import builder as candidate
    return authority, candidate, _make_model, _model_signature


def _assert_model_equal(authority, candidate, make_model, signature):
    from ecc_p1.model import FormalAction
    actions = (
        FormalAction("a_go", frozenset({0}), frozenset({0}), frozenset({0}),
                      lambda state: state[0] == 0,
                      lambda state: (1, state[1]),
                      lambda source, target: Fraction(5, 7)),
        FormalAction("b_stay", frozenset({0}), frozenset(), frozenset(),
                      lambda state: state[0] == 1,
                      lambda state: state,
                      lambda source, target: Fraction(2, 3)),
        FormalAction("c_hidden", frozenset({1}), frozenset({1}), frozenset({1}),
                      lambda state: state == (0, 0),
                      lambda state: (0, 1),
                      lambda source, target: Fraction(1, 1)),
    )
    model = make_model(initial=((0, 0),), dimensions=(0, 1),
                       local_states=((0, 1), (0, 1)), actions=actions)
    ctx = candidate.FullTSContext(model)
    first_work, second_work = {}, {}
    first_timing, second_timing = {}, {}
    old1 = authority.build_optimistic_abstraction(model, (0,))
    new1 = ctx.build(model, (0,), timing=first_timing, work=first_work)
    old2 = authority.build_optimistic_abstraction(model, (0, 1))
    new2 = ctx.build(model, (0, 1), timing=second_timing, work=second_work)
    if signature(old1) != signature(new1) or signature(old2) != signature(new2):
        raise AssertionError("V8 Product dataclass differs from V6")
    if first_work["full_ts_rebuild_calls"] != 1 or first_work["full_ts_cache_hits"] != 0:
        raise AssertionError("first build did not construct exactly once")
    if second_work["full_ts_rebuild_calls"] != 0 or second_work["full_ts_cache_hits"] != 1:
        raise AssertionError("second build did not hit the context cache")
    for result in (new1, new2):
        for transition in result.transitions:
            for witness in transition.witnesses:
                if not any(witness is edge for edge in ctx._edges):
                    raise AssertionError("reduction lost full-TS witness identity")
    if new1 is new2 or new1.transitions is new2.transitions:
        raise AssertionError("Product result was reused across precision rounds")
    if new1.labels is new2.labels or new1.transitions[0].witnesses is new2.transitions[0].witnesses:
        raise AssertionError("reduction/Product mutable containers were shared")
    new2_labels = dict(new2.labels)
    new1.labels.clear()
    if dict(new2.labels) != new2_labels:
        raise AssertionError("mutating first reduction changed second labels")
    fresh_ctx = candidate.FullTSContext(model)
    fresh_work = {}
    fresh_ctx.build(model, (0,), work=fresh_work)
    if fresh_work["full_ts_rebuild_calls"] != 1 or fresh_work["full_ts_cache_hits"] != 0:
        raise AssertionError("new context reused another context's cache")
    fresh_ctx.close()
    ctx.close()
    try:
        ctx.build(model, (0,))
    except RuntimeError:
        pass
    else:
        raise AssertionError("closed context accepted a build")
    return first_work, second_work


def run_fixtures(authority, candidate, make_model, signature):
    from ecc_p1.model import FormalAction
    rows = []
    first, second = _assert_model_equal(authority, candidate, make_model, signature)
    rows.append({"name": "same_model_two_builds", "status": "PASSED",
                 "first_work": first, "second_work": second})

    model_a = make_model()
    model_b = make_model(transition=lambda q, labels: ("q1",))
    ctx = candidate.FullTSContext(model_a)
    ctx.build(model_a, (0,), work={})
    try:
        ctx.build(model_b, (0,), work={})
    except ValueError:
        rows.append({"name": "different_model_rejected", "status": "PASSED"})
    else:
        raise AssertionError("different model was accepted by old context")
    new_ctx = candidate.FullTSContext(model_b)
    new_work = {}
    new_ctx.build(model_b, (0,), work=new_work)
    if new_work["full_ts_rebuild_calls"] != 1 or new_work["full_ts_cache_hits"] != 0:
        raise AssertionError("new context did not miss for a new model")
    new_ctx.close()
    ctx.close()

    initial_model = make_model(initial=((1,),))
    initial_ctx = candidate.FullTSContext(model_a)
    try:
        initial_ctx.build(initial_model, (0,), work={})
    except ValueError:
        pass
    else:
        raise AssertionError("old context accepted a model with a different initial state")
    initial_ctx.close()
    fresh_initial = candidate.FullTSContext(initial_model)
    old_initial = authority.build_optimistic_abstraction(initial_model, (0,))
    new_initial = fresh_initial.build(initial_model, (0,), work={})
    if signature(old_initial) != signature(new_initial):
        raise AssertionError("new initial-state context differs from V6")
    fresh_initial.close()
    bad = make_model(
        initial=((0, 0),), dimensions=(0, 1), local_states=((0,), (0, 1)),
        label=lambda state: frozenset({"goal"}) if state[1] else frozenset(),
        actions=(FormalAction(
            "a_hidden", frozenset({1}), frozenset({1}), frozenset({1}),
            lambda state: state == (0, 0), lambda state: (0, 1),
            lambda source, target: Fraction(1, 1),
        ),),
    )
    bad_ctx = candidate.FullTSContext(bad)
    bad_work = []
    for _ in range(2):
        work = {}
        try:
            bad_ctx.build(bad, (0,), work=work)
        except ValueError as exc:
            if "task label disagreement" not in str(exc):
                raise
        else:
            raise AssertionError("invalid projected label was accepted")
        bad_work.append(work)
    if (bad_work[0]["full_ts_rebuild_calls"], bad_work[0]["full_ts_cache_hits"]) != (1, 0):
        raise AssertionError("failed reduction first-build metrics are wrong")
    if (bad_work[1]["full_ts_rebuild_calls"], bad_work[1]["full_ts_cache_hits"]) != (0, 1):
        raise AssertionError("failed reduction cache-hit metrics are wrong")
    bad_ctx.close()

    failed = make_model(actions=(FormalAction(
        "bad_domain", frozenset({0}), frozenset({0}), frozenset({0}),
        lambda state: state[0] == 0, lambda state: (2,),
        lambda source, target: Fraction(1, 1),
    ),))
    failed_ctx = candidate.FullTSContext(failed)
    for _ in range(2):
        failed_work = {}
        try:
            failed_ctx.build(failed, (0,), work=failed_work)
        except ValueError:
            if failed_ctx.cached or failed_work["full_ts_rebuild_calls"] != 1:
                raise AssertionError("failed full-TS construction left bad cache metrics")
        else:
            raise AssertionError("invalid full-TS construction unexpectedly succeeded")
    failed_ctx.close()

    exact = make_model(action_cost=Fraction(0, 1))
    exact_ctx = candidate.FullTSContext(exact)
    exact_result = exact_ctx.build(exact, (0,), work={})
    if not exact_result.transitions or exact_result.transitions[0].cost != Fraction(0, 1):
        raise AssertionError("zero Fraction action cost changed")
    exact_ctx.close()
    rows.extend([
        {"name": "fraction_and_zero_cost_exact", "status": "PASSED"},
        {"name": "invalid_projected_label_rejected", "status": "PASSED"},
        {"name": "failed_full_ts_has_no_partial_cache", "status": "PASSED"},
    ])
    return {"status": "PASSED", "schema": "cmr-v8-ap-ts-reuse-fixtures-v1",
            "cases": rows, "case_count": len(rows)}


def run(kernel_root=None):
    """Run only the deterministic fixture suite; no formal authority load."""
    if kernel_root is None:
        kernel_root = os.environ.get("ECC_P1_KERNEL_ROOT")
    if not kernel_root:
        raise ValueError("kernel_root is required for the offline fixture suite")
    authority, candidate, make_model, signature = _load_kernel(kernel_root)
    return run_fixtures(authority, candidate, make_model, signature)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = _path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING"}
    try:
        report.update(run(args.kernel_root))
    except Exception as exc:
        report.update({"status": "FAILED", "error": repr(exc),
                       "traceback": traceback.format_exc()})
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
