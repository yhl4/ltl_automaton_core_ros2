"""Small offline checks for V9 projection and witness reuse."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import replace
from fractions import Fraction
from pathlib import Path


def _path(value: str | Path) -> Path:
    path = Path(value)
    if path.exists():
        return path
    text = str(value)
    if len(text) > 2 and text[1] == ":" and os.name != "nt":
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
    planner_root = repo_root / "ltl_automaton_planner_core"
    if str(planner_root) not in sys.path:
        sys.path.insert(0, str(planner_root))
    from experiments.cmr_ros2_product_perf import builder as authority_builder
    from experiments.cmr_ros2_product_perf import fixtures as authority_fixtures
    from experiments.cmr_ros2_ap_ts_reuse import builder as v8_builder
    from experiments.cmr_ros2_ap_ts_reuse import fixtures as v8_fixtures
    from experiments.cmr_ros2_product_perf.fixtures import _make_model, _model_signature
    from experiments.cmr_ros2_search_entry import backend as v7_search
    from experiments.cmr_ros2_reduction_reuse import builder, search
    return (
        authority_builder,
        authority_fixtures,
        v8_builder,
        v8_fixtures,
        _make_model,
        _model_signature,
        v7_search,
        builder,
        search,
    )


def _inherited_v8_checks(authority, v8_fixtures, candidate, make_model, signature):
    """Run the V8 behavioral fixtures without its module-level AST gate."""
    # The V8 fixture's AST gate expects a module-level cloned builder.  V9
    # deliberately binds projection to an attempt context, so reproduce its
    # behavioral cases against that explicit context instead.
    v8_fixtures._assert_model_equal(authority, candidate, make_model, signature)
    rows = [{"name": "same_model_two_builds", "status": "PASSED"}]

    from ecc_p1.model import FormalAction
    bad = make_model(
        initial=((0, 0),), dimensions=(0, 1), local_states=((0,), (0, 1)),
        label=lambda state: frozenset({"goal"}) if state[1] else frozenset(),
        actions=(FormalAction(
            "a_hidden", frozenset({1}), frozenset({1}), frozenset({1}),
            lambda state: state == (0, 0), lambda state: (0, 1),
            lambda source, target: Fraction(1, 1),
        ),),
    )
    bad_context = candidate.FullTSContext(bad)
    bad_works = []
    for _ in range(2):
        work = {}
        try:
            bad_context.build(bad, (0,), work=work)
        except ValueError as exc:
            if "task label disagreement" not in str(exc):
                raise
        else:
            raise AssertionError("invalid projected label was accepted")
        bad_works.append(work)
    if (bad_works[0]["full_ts_rebuild_calls"], bad_works[0]["full_ts_cache_hits"]) != (1, 0):
        raise AssertionError("failed reduction first-build metrics are wrong")
    if (bad_works[1]["full_ts_rebuild_calls"], bad_works[1]["full_ts_cache_hits"]) != (0, 1):
        raise AssertionError("failed reduction cache-hit metrics are wrong")
    bad_context.close()
    rows.append({"name": "invalid_projected_label_rejected", "status": "PASSED",
                 "first_work": bad_works[0], "second_work": bad_works[1]})

    failed = make_model(actions=(FormalAction(
        "bad_domain", frozenset({0}), frozenset({0}), frozenset({0}),
        lambda state: state[0] == 0, lambda state: (2,),
        lambda source, target: Fraction(1, 1),
    ),))
    failed_context = candidate.FullTSContext(failed)
    failed_works = []
    for _ in range(2):
        work = {}
        try:
            failed_context.build(failed, (0,), work=work)
        except ValueError:
            if failed_context.cached or work["full_ts_rebuild_calls"] != 1:
                raise AssertionError("failed full-TS construction left partial cache")
        else:
            raise AssertionError("invalid full-TS construction unexpectedly succeeded")
        failed_works.append(work)
    failed_context.close()
    rows.append({"name": "failed_full_ts_has_no_partial_cache", "status": "PASSED",
                 "attempts": failed_works})

    same_a = make_model(transition=lambda q, labels: ("q1",))
    same_b = make_model(transition=lambda q, labels: ("q0",))
    if signature(authority.build_optimistic_abstraction(same_a, (0,))) == signature(
        authority.build_optimistic_abstraction(same_b, (0,))
    ):
        raise AssertionError("same-shape models lost semantic isolation")
    rows.append({"name": "same_shape_model_isolation", "status": "PASSED"})
    return {"status": "PASSED", "schema": "cmr-v8-behavioral-fixtures-v1",
            "cases": rows, "case_count": len(rows)}


def _result_signature(result):
    if result is None:
        return None
    return {
        name: getattr(result, name)
        for name in (
            "status", "precision", "prefix", "suffix", "prefix_edges",
            "suffix_edges", "prefix_cost", "suffix_cost", "lower_bound",
            "accepting_product_states", "provenance",
        )
    }


def _without_witness_metrics(work):
    return {
        key: value
        for key, value in work.items()
        if not key.startswith("witness_")
    }


def _projection_checks(authority, v8_builder, candidate, make_model, signature):
    model = make_model(
        initial=((0, 0),),
        dimensions=(0, 1),
        local_states=((0, 1), (0, 1)),
    )
    v8_context = v8_builder.FullTSContext(model)
    v9_context = candidate.FullTSContext(model)
    v8_first = v8_context.build(model, (0,), work={})
    v8_second = v8_context.build(model, (0, 1), work={})
    first_work, second_work = {}, {}
    v9_first = v9_context.build(model, (0,), work=first_work)
    v9_second = v9_context.build(model, (0, 1), work=second_work)
    if signature(v8_first) != signature(v9_first) or signature(v8_second) != signature(v9_second):
        raise AssertionError("V9 projection changed the V8 abstraction")
    if first_work["full_ts_rebuild_calls"] != 1 or second_work["full_ts_rebuild_calls"] != 0:
        raise AssertionError("V9 full-TS reuse counts are wrong")
    if first_work["position_map_builds"] != 1 or second_work["position_map_builds"] != 1:
        raise AssertionError("projection position maps were not build-local")
    if first_work["projection_cache_hits"] <= 0:
        raise AssertionError("projection cache did not observe repeated states")
    if not (
        first_work["projection_computations"] < first_work["projection_requests"]
        and second_work["projection_computations"] <= second_work["projection_requests"]
    ):
        raise AssertionError("projection work was not reduced")

    control = candidate.FullTSContext(model, reuse_projection=False)
    control_work = {}
    control_result = control.build(model, (0,), work=control_work)
    if signature(control_result) != signature(v8_first):
        raise AssertionError("V9 control projection changed the abstraction")
    if control_work["projection_cache_hits"] != 0 or control_work["projection_computations"] != control_work["projection_requests"]:
        raise AssertionError("V9 control projection counters are wrong")

    invalid = candidate.FullTSContext(model)
    invalid_work = {}
    try:
        invalid.build(model, (99,), work=invalid_work)
    except ValueError:
        if invalid_work["position_map_builds"] != 0 or invalid_work["projection_requests"] != 0:
            raise AssertionError("invalid precision initialized projection state")
    else:
        raise AssertionError("invalid precision was accepted")
    for context in (v8_context, v9_context, control, invalid):
        context.close()
    return {
        "status": "PASSED",
        "first_work": first_work,
        "second_work": second_work,
        "control_work": control_work,
    }


def _search_checks(make_model, v7_search, candidate_search):
    model = make_model()
    from experiments.cmr_ros2_reduction_reuse.builder import FullTSContext

    context = FullTSContext(model)
    abstract = context.build(model, (0,), work={})
    v7_work, v9_work = {}, {}
    old = v7_search.solve_cmr_lasso(abstract, work=v7_work)
    new = candidate_search.solve_cmr_lasso(abstract, work=v9_work)
    if _result_signature(old) != _result_signature(new):
        raise AssertionError("V9 search result differs from V7")
    if _without_witness_metrics(v7_work) != _without_witness_metrics(v9_work):
        raise AssertionError("V9 search trace differs from V7")
    control_work = {}
    control_result = candidate_search.solve_cmr_lasso(abstract, work=control_work, reuse_witness=False)
    if _result_signature(control_result) != _result_signature(old) or _without_witness_metrics(control_work) != v7_work:
        raise AssertionError("counter-only V8 search differs from V7")
    if control_work['witness_key_cache_hits'] != 0 or control_work['witness_key_computations'] != control_work['witness_key_requests']:
        raise AssertionError("counter-only V8 witness accounting differs")
    if v9_work["witness_key_requests"] <= 0:
        raise AssertionError("V9 witness cache was not exercised")

    edge = abstract.transitions[0]
    if not edge.witnesses:
        raise AssertionError("fixture transition has no witness tuple")
    shared = edge.witnesses
    shared_abstract = replace(
        abstract,
        transitions=abstract.transitions + (replace(edge, witnesses=shared),),
    )
    shared_work = {}
    shared_result = candidate_search.solve_cmr_lasso(shared_abstract, work=shared_work)
    if _result_signature(shared_result) != _result_signature(old):
        raise AssertionError("shared-witness tie changed the selected lasso")
    if shared_work["witness_key_cache_hits"] < 1:
        raise AssertionError("shared witness tuple did not hit")

    different = tuple(list(shared))
    if different is shared:
        raise AssertionError("fixture failed to create a distinct witness tuple")
    different_abstract = replace(
        abstract,
        transitions=(replace(edge, witnesses=shared), replace(edge, witnesses=different)),
    )
    different_work = {}
    candidate_search.solve_cmr_lasso(different_abstract, work=different_work)
    if different_work["witness_key_cache_hits"] != 0:
        raise AssertionError("different witness tuples were incorrectly shared")

    list_abstract = replace(
        abstract,
        transitions=(replace(edge, witnesses=list(shared)), replace(edge, witnesses=list(shared))),
    )
    list_work = {}
    candidate_search.solve_cmr_lasso(list_abstract, work=list_work)
    if list_work["witness_key_cache_hits"] != 0:
        raise AssertionError("non-tuple witnesses entered the cache")

    generator_abstract = replace(
        abstract,
        transitions=(
            replace(edge, witnesses=(item for item in shared)),
            replace(edge, witnesses=(item for item in shared)),
        ),
    )
    generator_work = {}
    candidate_search.solve_cmr_lasso(generator_abstract, work=generator_work)
    if generator_work["witness_key_cache_hits"] != 0:
        raise AssertionError("generator witnesses entered the identity cache")

    exact_model = make_model(action_cost=Fraction(0, 1))
    exact_context = FullTSContext(exact_model)
    exact_abstract = exact_context.build(exact_model, (0,), work={})
    exact_result = candidate_search.solve_cmr_lasso(exact_abstract, work={})
    if exact_result != v7_search.solve_cmr_lasso(exact_abstract, work={}):
        raise AssertionError("zero cost differs from V7")
    if exact_result is None or not isinstance(exact_result.prefix_cost, Fraction):
        raise AssertionError("zero/Fraction search result lost exact arithmetic")
    huge_abstract = replace(
        abstract,
        transitions=tuple(
            replace(item, cost=Fraction(2**80 + 1, 1))
            for item in abstract.transitions
        ),
    )
    huge_result = candidate_search.solve_cmr_lasso(huge_abstract, work={})
    if huge_result != v7_search.solve_cmr_lasso(huge_abstract, work={}):
        raise AssertionError("large integer cost differs from V7")
    if huge_result is None or not isinstance(huge_result.lower_bound, Fraction):
        raise AssertionError("large exact cost was not preserved")

    rejected = replace(abstract, transitions=(replace(edge, cost=Fraction(-1, 1)),))
    try:
        candidate_search.solve_cmr_lasso(rejected, work={})
    except ValueError as error:
        if "negative costs" not in str(error):
            raise
    else:
        raise AssertionError("negative edge cost was accepted")

    cold1, cold2 = {}, {}
    candidate_search.solve_cmr_lasso(shared_abstract, work=cold1)
    candidate_search.solve_cmr_lasso(shared_abstract, work=cold2)
    if (cold1["witness_key_computations"], cold1["witness_key_cache_hits"]) != (
        cold2["witness_key_computations"], cold2["witness_key_cache_hits"]
    ):
        raise AssertionError("witness cache crossed solve boundaries")
    context.close()
    exact_context.close()
    return {
        "status": "PASSED",
        "v7_result": None if old is None else {
            "status": old.status,
            "prefix": old.prefix,
            "suffix": old.suffix,
            "prefix_cost": str(old.prefix_cost),
            "suffix_cost": str(old.suffix_cost),
            "lower_bound": str(old.lower_bound),
        },
        "v9_work": v9_work,
        "control_work": control_work,
        "shared_work": shared_work,
        "different_tuple_work": different_work,
        "non_tuple_work": list_work,
        "generator_work": generator_work,
    }


def run(kernel_root):
    """Run deterministic V8 inheritance and V9-specific offline checks."""
    (
        authority_builder,
        authority_fixtures,
        v8_builder,
        v8_fixtures,
        make_model,
        signature,
        v7_search,
        candidate_builder,
        candidate_search,
    ) = _load_kernel(kernel_root)
    inherited = _inherited_v8_checks(
        authority_builder, v8_fixtures, candidate_builder,
        make_model, signature,
    )
    projection = _projection_checks(
        None, v8_builder, candidate_builder, make_model, signature
    )
    search = _search_checks(make_model, v7_search, candidate_search)
    return {
        "status": "PASSED",
        "schema": "cmr-v9-projection-witness-fixtures-v1",
        "inherited_v8": inherited,
        "projection": projection,
        "search": search,
        "real_cmr_workers": 0,
        "dds_requests": 0,
        "provider_calls": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = {"status": "RUNNING"}
    try:
        report.update(run(args.kernel_root))
    except Exception as exc:
        report.update({"status": "FAILED", "error": repr(exc),
                       "traceback": traceback.format_exc()})
    output = _path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
