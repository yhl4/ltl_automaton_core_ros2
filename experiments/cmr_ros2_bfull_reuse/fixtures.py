"""V4 reuse comparisons and focused layer/reuse checks."""

from __future__ import annotations

import argparse
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

from experiments.cmr_ros2_bfull_compact import fixtures as v3_fixtures
from experiments.cmr_ros2_bfull_compact import backend as v3_backend
from experiments.cmr_ros2_bfull_perf import backend as v2_backend
from experiments.cmr_ros2_bfull_reuse import backend


def _summary(result):
    return v3_fixtures._summary(result)


def _hand_checks(result, abstract):
    v3_fixtures._independent_checks(result, abstract)


def _input_fingerprint(abstract):
    """Capture object identity and the visible abstract model before solving."""
    return (repr(vars(abstract)), tuple(
        (id(edge), tuple(id(witness) for witness in edge.witnesses))
        for edge in abstract.transitions
    ))


def _graph_fingerprint(graph):
    return (tuple(graph.nodes()), tuple(
        (source, target, data["weight"])
        for source, target, data in graph.edges(data=True)
    ))


def _reverse_view_checks(graph, source_nodes):
    """Check NetworkX's native reverse view and equivalent copied distances."""
    from ltl_automaton_planner_core.ltl_tools import discrete_plan

    before = _graph_fingerprint(graph)
    view = graph.reverse(copy=False)
    copied = graph.reverse(copy=True)
    if type(view) is not nx.DiGraph:
        raise AssertionError("reverse(copy=False) did not return native DiGraph")
    if view._succ is not graph._pred or view._pred is not graph._succ:
        raise AssertionError("reverse view did not exchange native adjacency maps")
    if "is_multigraph" in view.__dict__:
        raise AssertionError("reverse view carries an is_multigraph override")
    view_dist = discrete_plan._prefix_distances(view, source_nodes)
    copy_dist = discrete_plan._prefix_distances(copied, source_nodes)
    if view_dist != copy_dist:
        raise AssertionError("reverse view and copied graph distances differ")
    if _graph_fingerprint(graph) != before:
        raise AssertionError("reverse distance checks mutated the source graph")
    return {"type": type(view).__name__, "distance_equal": True,
            "source_unchanged": True}


def _direct_layer_checks(cases):
    zero = cases["zero_self_loop"]
    ordered = v2_backend._base._canonical_nodes(zero)
    node_id = {state: index for index, state in enumerate(ordered)}
    rows = v2_backend._base._edge_rows(zero, node_id)
    graph, _ = v3_backend._compact_graph(ordered, rows)
    accepting = {0}
    v3_lift, _, _ = v3_backend._suffix_graph(graph, {0}, 0, accepting)
    v4_work = {}
    zero_graph_before = _graph_fingerprint(graph)
    v4_lift, dummy, finish = backend._suffix_graph(graph, {0}, 0, accepting, v4_work)
    if any(node[1] is False for node in v4_lift if node != dummy):
        raise AssertionError("accepting entry retained an unnecessary false layer")
    if not any(node[1] is False for node in v3_lift if node[0] != -1):
        raise AssertionError("V3 accepting comparison graph lacks its false layer")
    if finish not in v4_lift or dummy not in v4_lift:
        raise AssertionError("compact V4 accepting layer is incomplete")
    if list(v4_lift.predecessors(dummy)):
        raise AssertionError("accepting suffix dummy unexpectedly has incoming edges")
    if v4_lift.number_of_nodes() != 2 or v4_lift.number_of_edges() != 2:
        raise AssertionError("zero self-loop accepting layer shape changed")
    if _graph_fingerprint(graph) != zero_graph_before:
        raise AssertionError("accepting suffix layer mutated the source graph")
    nonaccept = cases["nonaccepting_entry"]
    ordered = v2_backend._base._canonical_nodes(nonaccept)
    node_id = {state: index for index, state in enumerate(ordered)}
    rows = v2_backend._base._edge_rows(nonaccept, node_id)
    graph, _ = v3_backend._compact_graph(ordered, rows)
    nonaccept_graph_before = _graph_fingerprint(graph)
    lift, dummy, _ = backend._suffix_graph(graph, {0, 1}, 0, {1}, {})
    v3_nonaccept, _, _ = v3_backend._suffix_graph(graph, {0, 1}, 0, {1})
    if {node[1] for node in lift if node != dummy} != {False, True}:
        raise AssertionError("non-accepting entry did not retain both layers")
    if list(lift.predecessors(dummy)):
        raise AssertionError("suffix dummy unexpectedly has incoming edges")
    if (lift.number_of_nodes(), lift.number_of_edges()) != (
            v3_nonaccept.number_of_nodes(), v3_nonaccept.number_of_edges()):
        raise AssertionError("V3/V4 non-accepting suffix graph shape differs")
    if _graph_fingerprint(graph) != nonaccept_graph_before:
        raise AssertionError("suffix layer construction mutated the source graph")
    reverse_check = _reverse_view_checks(graph, {0})
    return {"accepting_v3_nodes": v3_lift.number_of_nodes(),
            "accepting_v4_nodes": v4_lift.number_of_nodes(),
            "accepting_v4_edges": v4_lift.number_of_edges(),
            "nonaccepting_v4_nodes": lift.number_of_nodes(),
            "nonaccepting_v4_dummy": dummy,
            "reverse_view": reverse_check,
            "status": "PASSED"}


def run_fixtures():
    from ecc_p1.solver import SearchStats, solve_exact_abstract_lasso

    cases = dict(v3_fixtures.v2_fixtures._cases())
    cases.update(v3_fixtures._extra_cases())
    invalid = {"none_cost": TypeError, "float_cost": TypeError, "negative_cost": ValueError}
    hand_expected = {
        "nonaccepting_entry": "10", "zero_self_loop": "0", "zero_cycle": "0",
        "parallel_witness": "10/3", "multiple_scc": "1",
        "first_bound_is_loose": "21", "no_accepting_cycle": None,
        "equal_parallel_tie": "10", "multiple_initial": "1",
        "accepting_entry_no_selfloop": "10",
    }
    report = {"schema": "cmr-ros2-bfull-reuse-fixtures-v1", "cases": {}}
    for name, abstract in cases.items():
        if name in invalid:
            try:
                backend.solve_cmr_lasso(abstract)
            except invalid[name]:
                report["cases"][name] = {"status": "REJECTED",
                                          "error_type": invalid[name].__name__}
                continue
            raise AssertionError(f"invalid cost case was accepted: {name}")
        reference = solve_exact_abstract_lasso(abstract, SearchStats(), prune=False)
        v3 = v3_backend.solve_cmr_lasso(abstract)
        phases = []
        work = {}
        before_input = _input_fingerprint(abstract)

        def phase_call(phase, function, *args):
            phases.append(phase)
            return function(*args)

        reuse = backend.solve_cmr_lasso(abstract, work=work, phase_call=phase_call)
        if _input_fingerprint(abstract) != before_input:
            raise AssertionError(f"V4 mutated abstract input or witness identity: {name}")
        values = (_summary(reference), _summary(v3), _summary(reuse))
        if any(value is None for value in values):
            if not all(value is None for value in values):
                raise AssertionError(f"feasibility disagreement in {name}")
            if hand_expected[name] is not None:
                raise AssertionError(f"unexpected infeasibility in {name}")
        else:
            if not (values[0]["objective"] == values[1]["objective"]
                    == values[2]["objective"] == hand_expected[name]):
                raise AssertionError(f"objective mismatch in {name}")
            _hand_checks(reuse, abstract)
        if name == "first_bound_is_loose" and work["exact_entry_searches"] != 2:
            raise AssertionError("loose bound pruned a better entry")
        if name == "nonaccepting_entry" and reuse.suffix[0][1] != "q_wait":
            raise AssertionError("non-accepting entry was lost")
        report["cases"][name] = {"status": "PASSED", "reference": _summary(reference),
                                  "v3": _summary(v3), "reuse": _summary(reuse),
                                  "work": work, "phases": phases,
                                  "input_unchanged": True}
    multiple = cases["multiple_scc"]
    work = {}
    backend.solve_cmr_lasso(multiple, work=work)
    if work["subgraph_copies"] < 2:
        raise AssertionError("subset reach/SCC did not exercise graph copies")
    layer_checks = _direct_layer_checks(cases)
    report["directional"] = {
        "subset_copies": {"status": "PASSED",
                          "count": work["subgraph_copies"]},
        "layer_view_immutability": {"status": "PASSED",
                                     "checks": layer_checks},
    }
    report["total_checks"] = len(cases) + 2
    if report["total_checks"] != 15:
        raise AssertionError("fixture check count is not 13 cases plus 2 directionals")
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
        report = {"schema": "cmr-ros2-bfull-reuse-fixtures-v1", "status": "FAILED",
                  "error": repr(error)}
        code = 1
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
