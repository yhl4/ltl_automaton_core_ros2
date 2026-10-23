"""Offline V11 exact-cost reuse and V10 equivalence checks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import networkx as nx


def _path(value: str | Path) -> Path:
    path = Path(value)
    if path.exists():
        return path
    text = str(value)
    if len(text) > 2 and text[1] == ":" and os.name != "nt":
        return Path("/mnt", text[0].lower(), *text[3:].replace("\\", "/").split("/"))
    return path


def _load_kernel(kernel_root):
    root = _path(kernel_root).resolve()
    if not (root / "ecc_p1" / "model.py").exists():
        raise ValueError(f"kernel root does not contain ecc_p1/model.py: {root}")
    repo = Path(__file__).resolve().parents[2]
    for path in (root, repo, repo / "ltl_automaton_planner_core"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from experiments.cmr_ros2_bfull_compact import fixtures as compact_fixtures
    from experiments.cmr_ros2_bfull_reuse import backend as v4
    from experiments.cmr_ros2_reduction_reuse import search as v9
    from experiments.cmr_ros2_suffix_reuse import search as v10
    from experiments.cmr_ros2_exact_cost_reuse import search as v11
    return compact_fixtures, v4, v9, v10, v11


def _graph_snapshot(graph):
    return {
        "nodes": tuple((node, dict(data)) for node, data in graph.nodes(data=True)),
        "edges": tuple((source, target, dict(data))
                       for source, target, data in graph.edges(data=True)),
        "successors": tuple((node, tuple(graph.successors(node))) for node in graph.nodes),
        "predecessors": tuple((node, tuple(graph.predecessors(node))) for node in graph.nodes),
    }


def _lift_snapshot(value):
    lift, dummy, finish = value
    return {"graph": _graph_snapshot(lift), "dummy": dummy, "finish": finish}


def _make_graph():
    graph = nx.DiGraph()
    edges = (
        (0, 1, Fraction(1, 3)), (1, 2, Fraction(0, 1)),
        (2, 0, Fraction(2**80 + 1, 1)), (1, 1, Fraction(1, 1)),
        (2, 1, Fraction(2, 1)), (3, 4, Fraction(0, 1)),
        (4, 3, Fraction(5, 7)),
    )
    for source, target, weight in edges:
        graph.add_edge(source, target, weight=weight)
    return graph


def _suffix_context_checks(v4, v10):
    graph = _make_graph()
    original = _graph_snapshot(graph)
    accepting = frozenset({2, 4})
    context_work = {
        "suffix_lifts": [],
        "suffix_graph_requests": 0,
        "suffix_graph_materializations": 0,
        "suffix_graph_reuses": 0,
        "suffix_graph_source_edge_scans": 0,
        "suffix_graph_source_edges_examined": 0,
        "suffix_graph_component_indexes": 0,
        "suffix_graph_dummy_rebinds": 0,
    }
    context = v10.SuffixGraphContext(context_work)
    checks = []
    for component, entry in ((frozenset({0, 1, 2}), 0),
                             (frozenset({0, 1, 2}), 1),
                             (frozenset({0, 1, 2}), 2),
                             (frozenset({3, 4}), 3),
                             (frozenset({3, 4}), 4)):
        fresh_work = {"suffix_lifts": []}
        fresh = v4._suffix_graph(graph, component, entry, accepting, fresh_work)
        cached = context.get(graph, component, entry, accepting, context_work)
        if _lift_snapshot(fresh) != _lift_snapshot(cached):
            raise AssertionError(f"fresh/cached suffix graph differs for entry {entry}")
        if list(cached[0].predecessors(cached[1])):
            raise AssertionError("dummy source acquired an incoming edge")
        checks.append({"entry": entry, "snapshot": _lift_snapshot(cached)})
    if _graph_snapshot(graph) != original:
        raise AssertionError("suffix context mutated the borrowed graph")
    expected = {
        "suffix_graph_requests": 5,
        "suffix_graph_materializations": 4,
        "suffix_graph_reuses": 1,
        "suffix_graph_source_edge_scans": 2,
        "suffix_graph_source_edges_examined": 14,
        "suffix_graph_component_indexes": 2,
        "suffix_graph_dummy_rebinds": 1,
    }
    if {key: context_work[key] for key in expected} != expected:
        raise AssertionError(f"unexpected suffix counters: {context_work}")

    try:
        context.get(graph, frozenset({0, 1, 2}), 0, frozenset({0, 3}))
    except ValueError:
        pass
    else:
        raise AssertionError("changed accepting set was accepted")
    other_graph = _make_graph()
    try:
        context.get(other_graph, frozenset({0, 1, 2}), 0, accepting)
    except ValueError:
        pass
    else:
        raise AssertionError("different graph object was accepted")
    return {"status": "PASSED", "checks": checks, "work": context_work}


def _result_summary(compact_fixtures, result):
    return compact_fixtures._summary(result)


def _result_identity(result, abstract):
    if result is None:
        return None
    allowed = {id(edge) for edge in abstract.transitions}
    return {
        "prefix_edges_original": all(id(edge) in allowed for edge in result.prefix_edges),
        "suffix_edges_original": all(id(edge) in allowed for edge in result.suffix_edges),
        "prefix_actions": tuple(edge.action for edge in result.prefix_edges),
        "suffix_actions": tuple(edge.action for edge in result.suffix_edges),
    }


def _without_reuse_counters(work):
    return {key: value for key, value in work.items()
            if not key.startswith(("suffix_graph_", "witness_", "exact_cost_"))}


def _without_exact_counters(work):
    return {key: value for key, value in work.items()
            if not key.startswith("exact_cost_")}


def _search_checks(compact_fixtures, v4, v9, v10, v11):
    cases = dict(compact_fixtures.v2_fixtures._cases())
    cases.update(compact_fixtures._extra_cases())
    selected = (
        "nonaccepting_entry", "zero_self_loop", "zero_cycle", "parallel_witness",
        "multiple_scc", "first_bound_is_loose", "equal_parallel_tie",
        "multiple_initial", "accepting_entry_no_selfloop",
    )
    rows = []
    for name in selected:
        abstract = cases[name]
        v9_work, v10_work, new_work = {}, {}, {}
        v9_result = v9.solve_cmr_lasso(abstract, work=v9_work)
        old = v10.solve_cmr_lasso(abstract, work=v10_work)
        new = v11.solve_cmr_lasso(abstract, work=new_work)
        if _result_summary(compact_fixtures, v9_result) != _result_summary(compact_fixtures, old):
            raise AssertionError(f"V10 result differs from V9: {name}")
        if _result_summary(compact_fixtures, old) != _result_summary(compact_fixtures, new):
            raise AssertionError(f"V11 result differs from V10: {name}")
        if _without_reuse_counters(v9_work) != _without_reuse_counters(v10_work):
            raise AssertionError(f"V10 search trace differs from V9: {name}")
        if _without_exact_counters(v10_work) != _without_exact_counters(new_work):
            raise AssertionError(f"V11 search trace differs from V10: {name}")
        if _result_identity(old, abstract) != _result_identity(new, abstract):
            raise AssertionError(f"V11 witness/edge identity differs: {name}")
        if name == "first_bound_is_loose" and new_work["suffix_graph_reuses"] < 1:
            raise AssertionError("repeated accepting mode did not reuse a suffix graph")
        rows.append({"name": name, "status": "PASSED",
                     "result": _result_summary(compact_fixtures, new),
                     "v9_work": v9_work, "v10_work": v10_work,
                     "v11_work": new_work})

    control_work = {}
    control = v11.solve_cmr_lasso(cases["first_bound_is_loose"], work=control_work,
                                  reuse_suffix=False, reuse_exact=False)
    if _result_summary(compact_fixtures, control) != rows[5]["result"]:
        raise AssertionError("cache-disabled suffix control changed result")
    if (control_work["suffix_graph_component_indexes"] != 0
            or control_work["suffix_graph_source_edge_scans"]
            != control_work["suffix_graph_materializations"]
            or control_work["suffix_graph_source_edges_examined"] <= 0
            or control_work["suffix_graph_reuses"] != 0
            or control_work["exact_cost_requests"] != rows[5]["v11_work"]["exact_cost_requests"]
            or control_work["exact_cost_reuses"] != 0
            or control_work["exact_cost_fallbacks"] != control_work["exact_cost_requests"]):
        raise AssertionError("cache-disabled suffix control scan counters are invalid")
    if not any(row["v11_work"]["exact_cost_reuses"] > 0 for row in rows):
        raise AssertionError("optimized exact-cost path did not reuse a Fraction")
    parallel_row = next(row for row in rows if row["name"] == "parallel_witness")
    exact_control = {}
    v11.solve_cmr_lasso(cases["parallel_witness"], work=exact_control,
                        reuse_exact=False)
    if exact_control["exact_cost_requests"] != parallel_row["v11_work"]["exact_cost_requests"]:
        raise AssertionError("exact-cost control and optimized requests differ")

    cold1, cold2 = {}, {}
    v11.solve_cmr_lasso(cases["first_bound_is_loose"], work=cold1)
    v11.solve_cmr_lasso(cases["first_bound_is_loose"], work=cold2)
    keys = ("suffix_graph_materializations", "suffix_graph_reuses",
            "suffix_graph_source_edge_scans", "suffix_graph_component_indexes")
    if any(cold1[key] != cold2[key] for key in keys):
        raise AssertionError("suffix graph cache crossed solve boundaries")

    incoming_work = {
        "suffix_lifts": [],
        "suffix_graph_requests": 0,
        "suffix_graph_materializations": 0,
        "suffix_graph_reuses": 0,
        "suffix_graph_source_edge_scans": 0,
        "suffix_graph_source_edges_examined": 0,
        "suffix_graph_component_indexes": 0,
        "suffix_graph_dummy_rebinds": 0,
    }
    incoming_context = v10.SuffixGraphContext(incoming_work)
    incoming_context.get(graph := _make_graph(), frozenset({0, 1, 2}), 0,
                         frozenset({2}), incoming_work)
    cached_lift, cached_dummy, _ = incoming_context._cache[(frozenset({0, 1, 2}), False)]
    cached_lift.add_edge((999, False), cached_dummy)
    try:
        incoming_context.get(graph, frozenset({0, 1, 2}), 1,
                             frozenset({2}), incoming_work)
    except ValueError:
        incoming_dummy_rejected = True
    else:
        incoming_dummy_rejected = False
    if not incoming_dummy_rejected:
        raise AssertionError("cached dummy incoming edge was silently accepted")

    from experiments.cmr_ros2_bfull_perf.fixtures import _abstract, _edge
    a = ((0,), "q_wait")
    b = ((1,), "q_accept")
    c = ((2,), "q_accept")
    three = _abstract(
        (a, b, c), (a,), ("q_wait", "q_accept"),
        (_edge(a, "to_b", b, 1), _edge(b, "back_a", a, 100),
         _edge(b, "to_c", c, 1), _edge(c, "back_b", b, 100),
         _edge(c, "c_wait", c, 3)),
    )
    three_work = {}
    three_result = v10.solve_cmr_lasso(three, work=three_work)
    if three_result is None or three_work["exact_entry_searches"] < 3:
        raise AssertionError("synthetic fixture did not exercise three exact searches")
    return {"status": "PASSED", "cases": rows,
            "cache_disabled": control_work, "cold_cache_1": cold1,
            "cold_cache_2": cold2, "three_exact_searches": three_work,
            "exact_control": exact_control,
            "incoming_dummy_rejected": incoming_dummy_rejected}


def _exact_checks(v11, compact_fixtures):
    """Exercise the type boundary without changing the frozen solver."""
    from decimal import Decimal

    class FractionSubclass(Fraction):
        pass

    class IntSubclass(int):
        pass

    work = {"exact_cost_requests": 0, "exact_cost_reuses": 0,
            "exact_cost_fallbacks": 0}
    convert = v11._exact_converter(work, True)
    values = (Fraction(0), Fraction(1, 3), Fraction(2**80 + 1, 7))
    exact = []
    for value in values:
        result = convert(value)
        if result is not value:
            raise AssertionError("exact Fraction was reconstructed")
        exact.append(str(result))
    from experiments.cmr_ros2_smoke import backend as base
    for value in (0, 1, 2**80 + 1, IntSubclass(4), FractionSubclass(3, 7)):
        actual = convert(value)
        expected = base._exact(value)
        if actual != expected or type(actual) is not type(expected):
            raise AssertionError(f"fallback exact conversion changed for {value!r}")
    if work["exact_cost_reuses"] != 3 or work["exact_cost_fallbacks"] != 5:
        raise AssertionError(f"unexpected exact converter counters: {work}")

    def error_signature(function, value):
        try:
            function(value)
        except Exception as error:
            return type(error).__name__, str(error)
        raise AssertionError(f"invalid cost was accepted: {value!r}")

    invalid = (True, 0.5, None, Decimal("1.25"))
    for value in invalid:
        expected = error_signature(lambda item: v11._exact_converter(
            {"exact_cost_requests": 0, "exact_cost_reuses": 0,
             "exact_cost_fallbacks": 0}, True)(item), value)
        actual = error_signature(lambda item: v11._exact_converter(
            {"exact_cost_requests": 0, "exact_cost_reuses": 0,
             "exact_cost_fallbacks": 0}, False)(item), value)
        if actual != expected:
            raise AssertionError(f"invalid cost rejection changed for {value!r}")

    cases = compact_fixtures.v2_fixtures._cases()
    try:
        v11.solve_cmr_lasso(cases["negative_cost"])
    except ValueError:
        negative_rejected = True
    else:
        negative_rejected = False
    if not negative_rejected:
        raise AssertionError("negative edge cost was accepted")

    from ecc_p1.abstraction import AbstractTransition
    from ecc_p1.model import StateTransition
    a = ((0,), "q_wait")
    b = ((1,), "q_accept")
    malformed = SimpleNamespace(
        precision=frozenset({0}), states=(a, b), initial_states=(a,),
        transitions=(AbstractTransition(
            a, "bad_witness", b, Fraction(1, 3),
            (StateTransition(a[0], "bad_witness", b[0], 0.5),)),),
        accepting_buchi_states=frozenset({"q_accept"}),
    )
    try:
        v11.solve_cmr_lasso(malformed)
    except TypeError:
        malformed_rejected = True
    else:
        malformed_rejected = False
    if not malformed_rejected:
        raise AssertionError("float witness cost was accepted")
    return {"status": "PASSED", "exact_values": exact, "work": work,
            "negative_edge_rejected": negative_rejected,
            "float_witness_rejected": malformed_rejected}


def _safe(value):
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_safe(item) for item in value), key=repr)
    return value


def run(kernel_root=None):
    if not kernel_root:
        raise ValueError("kernel_root is required")
    compact_fixtures, v4, v9, v10, v11 = _load_kernel(kernel_root)
    return _safe({
        "status": "PASSED",
        "schema": "cmr-v11-exact-cost-reuse-fixtures-v1",
        "suffix_context": _suffix_context_checks(v4, v10),
        "exact_cost": _exact_checks(v11, compact_fixtures),
        "search": _search_checks(compact_fixtures, v4, v9, v10, v11),
        "real_cmr_workers": 0,
        "dds_requests": 0,
        "provider_calls": 0,
        "development_fixture_solver_calls": "unknown",
    })


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = _path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = run(args.kernel_root)
    except Exception as error:
        report = {"status": "FAILED", "error": repr(error)}
        code = 1
    else:
        code = 0
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
