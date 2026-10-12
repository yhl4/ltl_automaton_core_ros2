"""V7 exact integer weights on V6's private search graphs.

Only denominator-one Fractions become integers. Original abstract edges and
witnesses stay untouched; nonintegral weights retain Fraction arithmetic.
"""

from fractions import Fraction
from types import SimpleNamespace

from experiments.cmr_ros2_bfull_target import backend as v5
from experiments.cmr_ros2_bfull_reuse import backend as v4
from experiments.cmr_ros2_bfull_compact import backend as v3
from experiments.cmr_ros2_real.bound_runner import _clone_function


def solve_cmr_lasso(abstract, work=None, phase_call=None):
    if work is None:
        work = {}
    work.update(integer_weight_edges=0, fractional_weight_edges=0)

    def compact_graph(ordered_nodes, rows):
        # _edge_rows has already rejected None, floats and negative costs.
        graph, arc_objects = v3._compact_graph(ordered_nodes, rows)
        for _, _, data in graph.edges(data=True):
            cost = data['weight']
            if isinstance(cost, Fraction) and cost.denominator == 1:
                data['weight'] = cost.numerator
                work['integer_weight_edges'] += 1
            else:
                work['fractional_weight_edges'] += 1
        return graph, arc_objects

    compact = SimpleNamespace(**dict(vars(v3), _compact_graph=compact_graph))
    reused = _clone_function(v4.solve_cmr_lasso, {'_v3': compact})
    target_globals = SimpleNamespace(solve_cmr_lasso=reused,
                                    _suffix_graph=v4._suffix_graph)
    target = _clone_function(v5.solve_cmr_lasso, {'_v4': target_globals})
    return target(abstract, work=work, phase_call=phase_call)
