"""Directed equivalence checks for V12 compact-cost scalarization."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import sys


def _path(value: str | Path) -> Path:
    path = Path(value)
    if path.exists():
        return path
    text = str(value)
    if len(text) > 2 and text[1] == ":" and os.name != "nt":
        return Path("/mnt", text[0].lower(), *text[3:].replace("\\", "/").split("/"))
    return path


def _load(kernel_root):
    root = _path(kernel_root).resolve()
    if not (root / "ecc_p1" / "model.py").exists():
        raise ValueError(f"kernel root does not contain ecc_p1/model.py: {root}")
    repo = Path(__file__).resolve().parents[2]
    for path in (root, repo, repo / "ltl_automaton_planner_core"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from experiments.cmr_ros2_bfull_compact import fixtures as v3_fixtures
    from experiments.cmr_ros2_compact_cost import search
    from experiments.cmr_ros2_exact_cost_reuse import search as v11
    return v3_fixtures, search, v11


def _graph_snapshot(graph):
    return {
        "nodes": tuple((node, dict(data)) for node, data in graph.nodes(data=True)),
        "edges": tuple((source, target, dict(data))
                       for source, target, data in graph.edges(data=True)),
        "successors": tuple((node, tuple(graph.successors(node))) for node in graph.nodes),
        "predecessors": tuple((node, tuple(graph.predecessors(node)))
                               for node in graph.nodes),
    }


def _direct_graph_check(search):
    edges = [object() for _ in range(7)]
    rows = (
        (0, 0, 1, Fraction(1, 1), edges[0]),
        (1, 0, 1, Fraction(1, 1), edges[1]),
        (2, 0, 1, Fraction(2, 1), edges[2]),
        (3, 1, 2, Fraction(0, 1), edges[3]),
        (4, 2, 3, Fraction(2**80 + 1, 1), edges[4]),
        (5, 3, 4, Fraction(1, 3), edges[5]),
        (6, 3, 4, Fraction(1, 5), edges[6]),
    )
    old_work = {key: 0 for key in (
        "compact_cost_requests", "compact_cost_scalarized_before_insert",
        "compact_cost_comparisons", "integer_weight_edges", "fractional_weight_edges")}
    new_work = dict(old_work)
    old_graph, old_objects = search._compact_graph((0, 1, 2, 3, 4), rows,
                                                    old_work, False)
    new_graph, new_objects = search._compact_graph((0, 1, 2, 3, 4), rows,
                                                    new_work, True)
    if _graph_snapshot(old_graph) != _graph_snapshot(new_graph):
        raise AssertionError("early scalarization changed graph nodes, edges, order, or weights")
    if {key: id(value) for key, value in old_objects.items()} != {
            key: id(value) for key, value in new_objects.items()}:
        raise AssertionError("early scalarization changed selected arc object identity")
    if old_objects[(0, 1)] is not edges[0] or new_objects[(0, 1)] is not edges[0]:
        raise AssertionError("equal-cost tie did not retain the first original edge")
    if old_objects[(3, 4)] is not edges[6] or new_objects[(3, 4)] is not edges[6]:
        raise AssertionError("strict lower-cost replacement did not retain the minimum edge")
    if old_graph[2][3]["weight"] != 2**80 + 1 or type(old_graph[2][3]["weight"]) is not int:
        raise AssertionError("arbitrary precision integer weight was not preserved")
    if old_graph[3][4]["weight"] != Fraction(1, 5):
        raise AssertionError("nonintegral Fraction weight was changed")
    if old_work["compact_cost_scalarized_before_insert"] != 0:
        raise AssertionError("baseline unexpectedly scalarized before insertion")
    if new_work["compact_cost_scalarized_before_insert"] != 5:
        raise AssertionError("optimized path did not scalarize every denominator-one row")
    if old_work["compact_cost_requests"] != 7 or new_work["compact_cost_requests"] != 7:
        raise AssertionError("compact row request counter is wrong")
    if old_work["compact_cost_comparisons"] != 3 or new_work["compact_cost_comparisons"] != 3:
        raise AssertionError("duplicate arc comparison counter is wrong")
    for key in ("integer_weight_edges", "fractional_weight_edges"):
        if old_work[key] != new_work[key]:
            raise AssertionError(f"selected edge classification changed: {key}")
    return {"status": "PASSED", "baseline_work": old_work,
            "optimized_work": new_work}


def _result_signature(result):
    if result is None:
        return None
    return (
        result.lower_bound, result.prefix_cost, result.suffix_cost,
        tuple(result.prefix), tuple(result.suffix),
        tuple(id(edge) for edge in result.prefix_edges),
        tuple(id(edge) for edge in result.suffix_edges),
    )


def _without_compact_cost(work):
    return {key: value for key, value in work.items()
            if not key.startswith("compact_cost_")}


def _search_checks(compact_fixtures, search, v11):
    cases = dict(compact_fixtures.v2_fixtures._cases())
    cases.update(compact_fixtures._extra_cases())
    selected = (
        "nonaccepting_entry", "zero_self_loop", "zero_cycle", "parallel_witness",
        "multiple_scc", "first_bound_is_loose", "equal_parallel_tie",
        "multiple_initial", "accepting_entry_no_selfloop",
    )
    rows = []
    scalarized_any = False
    for name in selected:
        abstract = cases[name]
        reference_work, optimized_work, control_work = {}, {}, {}
        reference = v11.solve_cmr_lasso(abstract, work=reference_work)
        optimized = search.solve_cmr_lasso(abstract, work=optimized_work, scalarize=True)
        control = search.solve_cmr_lasso(abstract, work=control_work, scalarize=False)
        if _result_signature(reference) != _result_signature(optimized):
            raise AssertionError(f"optimized result or original witness identity differs: {name}")
        if _result_signature(reference) != _result_signature(control):
            raise AssertionError(f"scalarization control result differs: {name}")
        if _without_compact_cost(reference_work) != _without_compact_cost(optimized_work):
            raise AssertionError(f"optimized non-cost counters differ from V11: {name}")
        if _without_compact_cost(reference_work) != _without_compact_cost(control_work):
            raise AssertionError(f"control non-cost counters differ from V11: {name}")
        scalarized_any = scalarized_any or (
            optimized_work["compact_cost_scalarized_before_insert"] > 0)
        if control_work["compact_cost_scalarized_before_insert"] != 0:
            raise AssertionError(f"scalarization control converted a row early: {name}")
        if optimized_work["compact_cost_requests"] != control_work["compact_cost_requests"]:
            raise AssertionError(f"optimized/control row request counts differ: {name}")
        if optimized_work["compact_cost_comparisons"] != control_work["compact_cost_comparisons"]:
            raise AssertionError(f"optimized/control comparison counts differ: {name}")
        rows.append({"name": name, "status": "PASSED",
                     "result": _result_signature(reference),
                     "optimized_work": optimized_work,
                     "control_work": control_work})
    if not scalarized_any:
        raise AssertionError("selected search cases did not exercise early scalarization")
    return rows


def run(kernel_root=None):
    if not kernel_root:
        raise ValueError("kernel_root is required")
    compact_fixtures, search, v11 = _load(kernel_root)
    return {"schema": "cmr-v12-compact-cost-fixtures-v1",
            "status": "PASSED",
            "direct_graph": _direct_graph_check(search),
            "search_cases": _search_checks(compact_fixtures, search, v11),
            "real_cmr_workers": 0, "dds_requests": 0, "provider_calls": 0}


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
        report = {"schema": "cmr-v12-compact-cost-fixtures-v1",
                  "status": "FAILED", "error": repr(error)}
        code = 1
    else:
        code = 0
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
                      encoding="utf-8", newline="\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
