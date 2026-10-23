"""Deterministic compact-adapter comparisons against V2 and qualified search."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import sys
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[2]
_KERNEL_ROOT = Path(
    "/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/"
    "Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel"
)
for _path in (_REPO_ROOT, _KERNEL_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from experiments.cmr_ros2_bfull_perf import fixtures as v2_fixtures
from experiments.cmr_ros2_bfull_compact import backend
from experiments.cmr_ros2_bfull_perf import backend as v2_backend


def _extra_cases():
    from ecc_p1.abstraction import AbstractTransition
    from ecc_p1.model import StateTransition

    a = ((0,), "q_accept")
    b = ((1,), "q_other")
    c = ((2,), "q_accept")

    def make(states, initial, accepting, specs):
        transitions = []
        for source, action, target, cost in specs:
            witness = StateTransition(source[0], action, target[0], cost)
            transitions.append(AbstractTransition(source, action, target, cost, (witness,)))
        return SimpleNamespace(
            precision=frozenset({0}), states=tuple(states), initial_states=tuple(initial),
            transitions=tuple(transitions), accepting_buchi_states=frozenset(accepting),
        )

    tie1 = AbstractTransition(a, "same", b, 1,
                              (StateTransition(a[0], "same", b[0], 1),))
    tie2 = AbstractTransition(a, "same", b, 1,
                              (StateTransition(a[0], "same", b[0], 1),))
    tie = SimpleNamespace(
        precision=frozenset({0}), states=(a, b), initial_states=(a,),
        transitions=(tie2, tie1, AbstractTransition(
            b, "back", a, 0, (StateTransition(b[0], "back", a[0], 0),))),
        accepting_buchi_states=frozenset({"q_other"}),
    )
    return {
        "equal_parallel_tie": tie,
        "multiple_initial": make(
            (a, b, c), (a, b), ("q_accept",),
            ((a, "a_to_c", c, 2), (b, "b_to_c", c, 1),
             (c, "c_wait", c, 0))),
        "accepting_entry_no_selfloop": make(
            (a, b), (a,), ("q_accept",),
            ((a, "to_other", b, 1), (b, "back_accept", a, 0))),
    }


def _summary(result):
    if result is None:
        return None
    return {"objective": str(result.lower_bound), "prefix_cost": str(result.prefix_cost),
            "suffix_cost": str(result.suffix_cost),
            "prefix_actions": [edge.action for edge in result.prefix_edges],
            "suffix_actions": [edge.action for edge in result.suffix_edges]}


def _independent_checks(result, abstract):
    allowed = {id(edge) for edge in abstract.transitions}
    prefix = tuple(result.prefix)
    suffix = tuple(result.suffix)
    prefix_edges = tuple(result.prefix_edges)
    suffix_edges = tuple(result.suffix_edges)
    if len(prefix) != len(prefix_edges) + 1 or len(suffix) != len(suffix_edges) + 1:
        raise AssertionError("state/edge lengths are inconsistent")
    if not prefix or not suffix or not suffix_edges or prefix[-1] != suffix[0]:
        raise AssertionError("lasso junction or nonempty suffix is invalid")
    for states, edges in ((prefix, prefix_edges), (suffix, suffix_edges)):
        for source, edge, target in zip(states, edges, states[1:]):
            if edge.source != source or edge.target != target:
                raise AssertionError("decoded edge adjacency is invalid")
            if id(edge) not in allowed:
                raise AssertionError("decoded edge is not an original object")
    prefix_cost = sum((Fraction(edge.cost) for edge in prefix_edges), Fraction(0))
    suffix_cost = sum((Fraction(edge.cost) for edge in suffix_edges), Fraction(0))
    if prefix_cost != result.prefix_cost or suffix_cost != result.suffix_cost:
        raise AssertionError("independent edge sums differ from reported costs")
    if suffix[0] != suffix[-1] or not any(
            state[1] in abstract.accepting_buchi_states for state in suffix):
        raise AssertionError("suffix is not an accepting closed walk")


def run_fixtures():
    from ecc_p1.solver import SearchStats, solve_exact_abstract_lasso

    cases = dict(v2_fixtures._cases())
    cases.update(_extra_cases())
    report = {"schema": "cmr-ros2-bfull-compact-fixtures-v1", "cases": {}}
    invalid = {"none_cost": TypeError, "float_cost": TypeError, "negative_cost": ValueError}
    hand_expected = {
        "nonaccepting_entry": "10", "zero_self_loop": "0", "zero_cycle": "0",
        "parallel_witness": "10/3", "multiple_scc": "1",
        "first_bound_is_loose": "21", "no_accepting_cycle": None,
        "equal_parallel_tie": "10", "multiple_initial": "1",
        "accepting_entry_no_selfloop": "10",
    }
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
        v2 = v2_backend.solve_cmr_lasso(abstract)
        phases = []
        work = {}

        def phase_call(phase, function, *args):
            phases.append(phase)
            return function(*args)

        compact = backend.solve_cmr_lasso(abstract, work=work, phase_call=phase_call)
        if _summary(compact) is None or _summary(v2) is None or _summary(reference) is None:
            if not (_summary(compact) is None and _summary(v2) is None
                    and _summary(reference) is None):
                raise AssertionError(f"feasibility disagreement in {name}")
            if hand_expected[name] is not None:
                raise AssertionError(f"unexpected infeasibility in {name}")
        else:
            if _summary(compact)["objective"] != _summary(reference)["objective"]:
                raise AssertionError(f"compact/reference objective mismatch in {name}")
            if _summary(v2)["objective"] != _summary(reference)["objective"]:
                raise AssertionError(f"V2/reference objective mismatch in {name}")
            if _summary(compact)["objective"] != hand_expected[name]:
                raise AssertionError(f"hand objective mismatch in {name}")
            _independent_checks(compact, abstract)
        if name == "first_bound_is_loose" and work["exact_entry_searches"] != 2:
            raise AssertionError("loose bound must search both entries")
        if name == "nonaccepting_entry" and compact.suffix[0][1] != "q_wait":
            raise AssertionError("non-accepting optimal entry was lost")
        if name == "equal_parallel_tie":
            rows = v2_backend._base._edge_rows(
                abstract, {state: index for index, state in enumerate(
                    v2_backend._base._canonical_nodes(abstract))})
            expected = next(row[4] for row in rows if row[1] == 0 and row[2] == 1)
            if not any(edge is expected for edge in compact.suffix_edges):
                raise AssertionError("equal-cost parallel tie did not retain canonical first edge")
        if name == "multiple_initial" and compact.prefix_edges[0].action != "b_to_c":
            raise AssertionError("multiple initial states did not choose the shorter prefix")
        if name == "accepting_entry_no_selfloop" and len(compact.suffix_edges) < 2:
            raise AssertionError("accepting entry without self-loop did not form a real cycle")
        report["cases"][name] = {"status": "PASSED", "reference": _summary(reference),
                                  "v2": _summary(v2), "compact": _summary(compact),
                                  "work": work, "phases": phases}
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
        report = {"schema": "cmr-ros2-bfull-compact-fixtures-v1", "status": "FAILED",
                  "error": repr(error)}
        code = 1
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
