"""Small deterministic comparisons for the bounded ROS2 lasso adapter."""

from __future__ import annotations

import json
import argparse
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_KERNEL_ROOT = Path("/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel")
if str(_KERNEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_KERNEL_ROOT))

from experiments.cmr_ros2_smoke import backend as old_backend
from experiments.cmr_ros2_bfull_perf import backend


@dataclass(frozen=True)
class _EdgeSpec:
    source: tuple[Any, str]
    action: str
    target: tuple[Any, str]
    cost: Any


def _abstract(states, initial, accepting, specs):
    from ecc_p1.abstraction import AbstractTransition
    from ecc_p1.model import StateTransition

    transitions = []
    for spec in specs:
        witness = StateTransition(spec.source[0], spec.action, spec.target[0], spec.cost)
        transitions.append(AbstractTransition(
            spec.source, spec.action, spec.target, spec.cost, (witness,)))
    return SimpleNamespace(
        precision=frozenset({0}), states=tuple(states), initial_states=tuple(initial),
        transitions=tuple(transitions), accepting_buchi_states=frozenset(accepting),
    )


def _edge(source, action, target, cost):
    return _EdgeSpec((source[0], source[1]), action, (target[0], target[1]), cost)


def _cases():
    a = ((0,), "q_wait")
    b = ((1,), "q_accept")
    c = ((2,), "q_accept")
    return {
        "nonaccepting_entry": _abstract(
            (a, b), (a,), ("q_accept",),
            (_edge(a, "go", b, 1), _edge(b, "back", a, 0))),
        "zero_self_loop": _abstract(
            (a,), (a,), ("q_wait",), (_edge(a, "wait", a, 0),)),
        "zero_cycle": _abstract(
            (a, b), (a,), ("q_accept",),
            (_edge(a, "go", b, 0), _edge(b, "back", a, 0))),
        "parallel_witness": _abstract(
            (a, b), (a,), ("q_accept",),
            (_edge(a, "a_fast", b, Fraction(1, 3)),
             _edge(a, "b_slow", b, Fraction(2, 3)), _edge(b, "back", a, 0))),
        "multiple_scc": _abstract(
            (a, b, c), (a,), ("q_accept",),
            (_edge(a, "stay", a, 0), _edge(a, "enter", b, 1),
             _edge(b, "accept_wait", b, 0), _edge(c, "unreachable", c, 0))),
        "first_bound_is_loose": _abstract(
            (a, b), (a,), ("q_wait", "q_accept"),
            (_edge(a, "to_b", b, 1), _edge(b, "back", a, 100),
             _edge(b, "b_wait", b, 2))),
        "no_accepting_cycle": _abstract(
            (a, b), (a,), ("q_accept",), (_edge(a, "go", b, 1),)),
        "none_cost": _abstract(
            (a,), (a,), ("q_wait",), (_edge(a, "none", a, None),)),
        "float_cost": _abstract(
            (a,), (a,), ("q_wait",), (_edge(a, "float", a, 0.5),)),
        "negative_cost": _abstract(
            (a,), (a,), ("q_wait",), (_edge(a, "negative", a, -1),)),
    }


def _signature(result):
    if result is None:
        return None
    return {
        "objective": str(result.lower_bound),
        "prefix_cost": str(result.prefix_cost),
        "suffix_cost": str(result.suffix_cost),
        "prefix_actions": [edge.action for edge in result.prefix_edges],
        "suffix_actions": [edge.action for edge in result.suffix_edges],
        "suffix_closed": result.suffix[0] == result.suffix[-1],
        "accepting": bool(result.accepting_product_states),
    }


def run_fixtures() -> dict[str, Any]:
    """Compare bounded, legacy ROS2, and qualified non-pruning answers."""
    from ecc_p1.solver import SearchStats, solve_exact_abstract_lasso
    report = {"schema": "cmr-ros2-bfull-perf-fixtures-v1", "cases": {}}
    hand_expected = {
        "nonaccepting_entry": "10", "zero_self_loop": "0", "zero_cycle": "0",
        "parallel_witness": "10/3", "multiple_scc": "1",
        "first_bound_is_loose": "21", "no_accepting_cycle": None,
    }
    invalid = {"none_cost": TypeError, "float_cost": TypeError, "negative_cost": ValueError}
    for name, abstract in _cases().items():
        if name in invalid:
            try:
                backend.solve_cmr_lasso(abstract)
            except invalid[name]:
                report["cases"][name] = {"status": "REJECTED", "error_type": invalid[name].__name__}
            else:
                raise AssertionError(f"{name} was accepted")
            continue
        qualified = solve_exact_abstract_lasso(abstract, SearchStats(), prune=False)
        legacy = old_backend.solve_cmr_lasso(abstract)
        work = {}
        phases = []

        def phase_call(phase, function, *args):
            phases.append(phase)
            return function(*args)

        bounded = backend.solve_cmr_lasso(abstract, work=work, phase_call=phase_call)
        if _signature(qualified) != _signature(legacy):
            raise AssertionError(f"legacy/reference mismatch in {name}")
        if _signature(bounded) != _signature(qualified):
            raise AssertionError(f"bounded/reference mismatch in {name}")
        if _signature(bounded) is None:
            actual_objective = None
        else:
            actual_objective = _signature(bounded)["objective"]
        if actual_objective != hand_expected[name]:
            raise AssertionError(
                f"hand expected objective mismatch in {name}: {actual_objective}")
        if name == "nonaccepting_entry" and bounded.suffix[0][1] != "q_wait":
            raise AssertionError("non-accepting optimal entry was not retained")
        if name == "parallel_witness" and bounded.suffix_edges[0].action != "a_fast":
            raise AssertionError("parallel witness/action was not preserved")
        if name == "first_bound_is_loose" and work["exact_entry_searches"] != 2:
            raise AssertionError("loose lower bound incorrectly pruned a better entry")
        report["cases"][name] = {"status": "PASSED", "result": _signature(bounded),
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
        report = {"schema": "cmr-ros2-bfull-perf-fixtures-v1", "status": "FAILED",
                  "error": repr(error)}
        code = 1
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
