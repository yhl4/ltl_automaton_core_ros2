"""V5 target-settled suffix adapter layered over the V4 implementation."""

from __future__ import annotations

from types import FunctionType
from typing import Any

from experiments.cmr_ros2_bfull_reuse import backend as _v4


# The prefix, component-distance, and reachable-component helpers adapt
# NetworkX 2.4.
# Copyright (c) 2004-2019, NetworkX Developers.
# Copyright (c) Aric Hagberg, Dan Schult, and Pieter Swart.
# SCC authors: Eben Kenah, Aric Hagberg, Christopher Ellison, and Ben Edwards.
# The following BSD-3-Clause notice applies to these helpers:
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
#  * Neither the name of the NetworkX Developers nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


def _target_component_distances(product, source, component, target, work):
    """Run the production distance loop, stopping only when target settles."""
    from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp

    record = {
        "target_settled": False,
        "settled_nodes": 0,
        "discovered_nodes": 0,
        "fringe_remaining": 0,
        "stop_reason": "running",
        "target_distance": None,
    }
    distances = {}
    seen = {}
    sequence = dp.count()
    fringe = []
    push = dp.heappush
    pop = dp.heappop
    successors = product._succ if product.is_directed() else product._adj
    try:
        sources = {source}
        for start in sources:
            if start not in product:
                raise dp.NodeNotFound("Source {} not in G".format(start))
            seen[start] = 0
            push(fringe, (0, next(sequence), start))
        while fringe:
            distance, _, current = pop(fringe)
            if current in distances:
                continue
            distances[current] = distance
            if current == target:
                record["target_settled"] = True
                record["stop_reason"] = "target_finalized"
                break
            for successor, data in successors[current].items():
                if successor not in component:
                    continue
                cost = data.get("weight", 1)
                if cost is None:
                    continue
                candidate = distance + cost
                if successor in distances:
                    if candidate < distances[successor]:
                        raise ValueError("Contradictory paths found:",
                                         "negative weights?")
                elif successor not in seen or candidate < seen[successor]:
                    seen[successor] = candidate
                    push(fringe, (candidate, next(sequence), successor))
                elif candidate == seen[successor]:
                    # NetworkX evaluates equality even when pred=None.
                    pass
        else:
            record["stop_reason"] = "fringe_exhausted"
        return distances
    except BaseException as error:
        record["stop_reason"] = "exception"
        record["error"] = repr(error)
        raise
    finally:
        record["settled_nodes"] = len(distances)
        record["discovered_nodes"] = len(seen)
        record["fringe_remaining"] = len(fringe)
        if target in distances:
            record["target_distance"] = str(distances[target])
        work.setdefault("target_searches", []).append(record)


def solve_cmr_lasso(abstract: Any, work: dict[str, Any] | None = None,
                    phase_call=None):
    """Run one V4 solve with a local target registration and target helper."""
    if work is None:
        work = {}
    targets = {}

    def target_suffix_graph(graph, component, entry, accepting_ids, local_work):
        lift, dummy, finish = _v4._suffix_graph(
            graph, component, entry, accepting_ids, local_work)
        targets[id(lift)] = finish
        local_work.setdefault("target_searches", [])
        return lift, dummy, finish

    def target_call(local_phase_call, phase, function, *args):
        if phase != "suffix":
            return local_phase_call(phase, function, *args)
        target = targets.pop(id(args[0]), None)
        if target is None:
            raise RuntimeError("suffix target registration is missing")
        return local_phase_call(
            phase, _target_component_distances, *args, target, work)

    clone_globals = dict(_v4.solve_cmr_lasso.__globals__)
    clone_globals["_suffix_graph"] = target_suffix_graph
    clone_globals["_call"] = target_call
    clone = FunctionType(
        _v4.solve_cmr_lasso.__code__, clone_globals,
        name="solve_cmr_lasso", argdefs=_v4.solve_cmr_lasso.__defaults__,
        closure=_v4.solve_cmr_lasso.__closure__,
    )
    clone.__kwdefaults__ = _v4.solve_cmr_lasso.__kwdefaults__
    clone.__annotations__ = dict(_v4.solve_cmr_lasso.__annotations__)
    clone.__doc__ = "V4 solver with target-settled suffix distances."
    return clone(abstract, work=work, phase_call=phase_call)


__all__ = ["solve_cmr_lasso", "_target_component_distances"]
