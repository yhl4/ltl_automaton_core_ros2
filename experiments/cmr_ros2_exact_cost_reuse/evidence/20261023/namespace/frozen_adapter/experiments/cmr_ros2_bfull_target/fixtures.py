"""Deterministic V5 target-settled suffix checks over the V4 adapter."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import networkx as nx
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[2]
_KERNEL_ROOT = Path(
    "/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/"
    "Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel"
)
for _path in (_REPO_ROOT, _KERNEL_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from experiments.cmr_ros2_bfull_compact import backend as v3_backend
from experiments.cmr_ros2_bfull_reuse import backend as v4_backend
from experiments.cmr_ros2_bfull_reuse import fixtures as v4_fixtures
from experiments.cmr_ros2_bfull_target import backend
from experiments.cmr_ros2_bfull_perf import backend as v2_backend


def _summary(result):
    return v4_fixtures._summary(result)


def _hand_checks(result, abstract):
    v4_fixtures._hand_checks(result, abstract)


def _compact_graph(abstract):
    ordered = v2_backend._base._canonical_nodes(abstract)
    node_id = {state: index for index, state in enumerate(ordered)}
    rows = v2_backend._base._edge_rows(abstract, node_id)
    graph, _ = v3_backend._compact_graph(ordered, rows)
    return graph


def _structure_checks(cases):
    baseline = v4_fixtures._direct_layer_checks(cases)
    zero_graph = _compact_graph(cases["zero_self_loop"])
    accepting = {0}
    target_zero, dummy_zero, finish_zero = v4_backend._suffix_graph(
        zero_graph, {0}, 0, accepting, {})
    if target_zero.number_of_nodes() != 2 or target_zero.number_of_edges() != 2:
        raise AssertionError("target accepting layer shape changed")
    if any(node[1] is False for node in target_zero if node != dummy_zero):
        raise AssertionError("target accepting entry retained false layer")
    if finish_zero not in target_zero or list(target_zero.predecessors(dummy_zero)):
        raise AssertionError("target accepting dummy/finish is invalid")
    nonaccept_graph = _compact_graph(cases["nonaccepting_entry"])
    nonaccepting = {1}
    target_nonaccept, dummy_nonaccept, _ = v4_backend._suffix_graph(
        nonaccept_graph, {0, 1}, 0, nonaccepting, {})
    v4_nonaccept, _, _ = v4_backend._suffix_graph(
        nonaccept_graph, {0, 1}, 0, nonaccepting, {})
    if {node[1] for node in target_nonaccept if node != dummy_nonaccept} != {
            False, True}:
        raise AssertionError("target non-accepting entry lost a layer")
    if list(target_nonaccept.predecessors(dummy_nonaccept)):
        raise AssertionError("target non-accepting dummy has incoming edges")
    if (target_nonaccept.number_of_nodes(), target_nonaccept.number_of_edges()) != (
            v4_nonaccept.number_of_nodes(), v4_nonaccept.number_of_edges()):
        raise AssertionError("target/V4 non-accepting layer shape differs")
    return {"status": "PASSED", "v4_baseline": baseline,
            "target_accepting": {
                "nodes": target_zero.number_of_nodes(),
                "edges": target_zero.number_of_edges(),
                "layers": 1,
            },
            "target_nonaccepting": {
                "nodes": target_nonaccept.number_of_nodes(),
                "edges": target_nonaccept.number_of_edges(),
                "layers": 2,
            }}


def _path_cost(graph, path):
    return sum((Fraction(graph[source][target].get("weight", 1))
                for source, target in zip(path, path[1:])), Fraction(0))


def _target_directional_checks():
    from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp

    cases = {}
    first = nx.DiGraph()
    first.add_edge("s", "t", weight=10)
    first.add_edge("s", "a", weight=1)
    first.add_edge("a", "b", weight=1)
    first.add_edge("b", "t", weight=0)
    cases["discovered_then_improved"] = (first, "s", "t")

    equal = nx.DiGraph()
    equal.add_edge("s", "z", weight=0)
    equal.add_edge("z", "t", weight=0)
    equal.add_edge("z", "u", weight=0)
    equal.add_edge("u", "z", weight=0)
    cases["equal_cost_zero_cycle"] = (equal, "s", "t")

    unreachable = nx.DiGraph()
    unreachable.add_edge("s", "a", weight=2)
    unreachable.add_node("t")
    cases["unreachable_target"] = (unreachable, "s", "t")

    report = {}
    for name, (graph, source, target) in cases.items():
        full = dp._component_distances(graph, source, set(graph))
        work = {}
        distances = backend._target_component_distances(
            graph, source, set(graph), target, work)
        record = work["target_searches"][-1]
        if name == "discovered_then_improved":
            if record["target_settled"] is not True or record["target_distance"] != "2":
                raise AssertionError("target helper stopped at first discovery")
            if record["fringe_remaining"] <= 0 or record["settled_nodes"] != 4:
                raise AssertionError("target helper did not preserve stale fringe")
        elif name == "equal_cost_zero_cycle":
            if record["target_settled"] is not True or distances.get(target) != full[target]:
                raise AssertionError("equal-cost target settlement changed")
            if distances[target] != 0 or "u" in distances or record["fringe_remaining"] <= 0:
                raise AssertionError("zero-cost path did not stop before a tied frontier state")
            path = dp._restore_tight_path(graph, distances, {source}, target)
            if path[0] != source or path[-1] != target:
                raise AssertionError("finite target tight path is malformed")
            if _path_cost(graph, path) != Fraction(distances[target]):
                raise AssertionError("finite target tight path cost differs")
        else:
            if record["target_settled"] or record["stop_reason"] != "fringe_exhausted":
                raise AssertionError("unreachable target did not exhaust fringe")
            if distances != full or record["fringe_remaining"] != 0:
                raise AssertionError("unreachable target distance map differs")
        if name != "equal_cost_zero_cycle" and target in distances:
            path = dp._restore_tight_path(graph, distances, {source}, target)
            if _path_cost(graph, path) != Fraction(distances[target]):
                raise AssertionError("target tight path cost differs")
        report[name] = {"status": "PASSED", "record": record,
                        "target_distance": (str(distances[target])
                                             if target in distances else None),
                        "full_target_distance": (str(full[target])
                                                  if target in full else None)}
        if target in distances and distances[target] != full[target]:
            raise AssertionError("finalized target differs from full-distance reference")
    return report


def run_fixtures():
    cases = dict(v4_fixtures.v3_fixtures.v2_fixtures._cases())
    cases.update(v4_fixtures.v3_fixtures._extra_cases())
    invalid = {"none_cost": TypeError, "float_cost": TypeError,
               "negative_cost": ValueError}
    hand_expected = {
        "nonaccepting_entry": "10", "zero_self_loop": "0", "zero_cycle": "0",
        "parallel_witness": "10/3", "multiple_scc": "1",
        "first_bound_is_loose": "21", "no_accepting_cycle": None,
        "equal_parallel_tie": "10", "multiple_initial": "1",
        "accepting_entry_no_selfloop": "10",
    }
    report = {"schema": "cmr-ros2-bfull-target-fixtures-v1", "cases": {}}
    for name, abstract in cases.items():
        if name in invalid:
            try:
                backend.solve_cmr_lasso(abstract)
            except invalid[name]:
                report["cases"][name] = {"status": "REJECTED",
                                          "error_type": invalid[name].__name__}
                continue
            raise AssertionError(f"invalid cost case was accepted: {name}")
        reference = v4_backend.solve_cmr_lasso(abstract)
        phases = []
        work = {}
        before = v4_fixtures._input_fingerprint(abstract)

        def phase_call(phase, function, *args):
            phases.append(phase)
            return function(*args)

        target = backend.solve_cmr_lasso(abstract, work=work,
                                         phase_call=phase_call)
        if v4_fixtures._input_fingerprint(abstract) != before:
            raise AssertionError(f"target adapter mutated input: {name}")
        values = (_summary(reference), _summary(target))
        if any(value is None for value in values):
            if not all(value is None for value in values):
                raise AssertionError(f"V4/target feasibility disagreement: {name}")
            if hand_expected[name] is not None:
                raise AssertionError(f"unexpected infeasibility in {name}")
        else:
            if values[0]["objective"] != values[1]["objective"]:
                raise AssertionError(f"V4/target objective mismatch: {name}")
            if values[0]["objective"] != hand_expected[name]:
                raise AssertionError(f"hand objective mismatch: {name}")
            _hand_checks(target, abstract)
        if name == "first_bound_is_loose" and work["exact_entry_searches"] != 2:
            raise AssertionError("loose bound pruned a better entry")
        if name == "nonaccepting_entry" and target.suffix[0][1] != "q_wait":
            raise AssertionError("non-accepting optimal entry was lost")
        report["cases"][name] = {
            "status": "PASSED", "reference": _summary(reference),
            "target": _summary(target), "work": work, "phases": phases,
            "input_unchanged": True,
        }
    structures = _structure_checks(cases)
    target_checks = _target_directional_checks()
    multiple_work = report["cases"]["multiple_scc"]["work"]
    if multiple_work["subgraph_copies"] < 2:
        raise AssertionError("subset reach/SCC did not exercise graph copies")
    report["directional"] = {
        "subset_copies": {"status": "PASSED",
                          "count": multiple_work["subgraph_copies"]},
        "layers_view_immutability": structures,
    }
    report["target_checks"] = target_checks
    report["total_checks"] = len(cases) + 2 + len(target_checks)
    if report["total_checks"] != 18:
        raise AssertionError("fixture check count is not 13+2+3")
    report["status"] = "PASSED"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = run_fixtures()
        code = 0
    except Exception as error:
        report = {"schema": "cmr-ros2-bfull-target-fixtures-v1", "status": "FAILED",
                  "error": repr(error)}
        code = 1
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
