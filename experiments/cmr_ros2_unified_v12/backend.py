"""V12 search behind explicit FULL/AP-D/DEP-D construction policies."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

from experiments.cmr_ros2_compact_cost import backend as component
from experiments.cmr_ros2_search_entry import runner as v7

HERE = Path(__file__).resolve().parent
ID = 'ROS2-DISCRETE-PLAN-CMR-UNIFIED-V12'
METHODS = ('FULL', 'AP-D', 'DEP-D')
BUILD_POLICY = {'FULL': 'original_every_round', 'AP-D': 'one_full_TS_per_method',
                'DEP-D': 'original_every_round'}


def identity():
    return hashlib.sha256('|'.join([ID, component.identity(),
        v7.digest(HERE/'backend.py'), v7.digest(HERE/'runner.py')]).encode()).hexdigest()


def configure(formal):
    from experiments.cmr_ros2_reduction_reuse.builder import FullTSContext
    from experiments.cmr_ros2_product_perf import builder
    from experiments.cmr_ros2_compact_cost import search
    from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp
    capture = dict(backend_id=ID, backend_sha256=identity(), search_work=[],
        build_work=[], lasso=None, instance=None, build_policy=BUILD_POLICY,
        counter_basis='V12 exact search; AP-D TS/projection reuse; original FULL/DEP-D builder')
    context = None
    original = formal.run_method_local

    def build(model, precision, *, timing=None):
        work = {}
        try:
            if context is not None:
                return context.build(model, precision, timing=timing, work=work)
            result = builder.build_optimistic_abstraction(model, precision, timing=timing, work=work)
            work.update(full_ts_rebuild_calls=1, full_ts_cache_hits=0)
            return result
        finally:
            capture['build_work'].append(work)

    def solve(abstract, stats=None):
        if stats is None:
            raise TypeError('qualified SearchStats required')
        return v7.v6.foundation.measure(SimpleNamespace(solve_cmr_lasso=search.solve_cmr_lasso),
                                       dp, capture, abstract, stats)

    formal.BACKEND_ID, formal.BACKEND_SHA256 = ID, identity()
    loop = v7.adapter._clone_function(formal._run_kernel_loop,
        {'solve_exact_abstract_lasso': solve, 'build_optimistic_abstraction': build})
    local = v7.adapter._clone_function(original, {'_run_kernel_loop': loop})

    def captured_local(*args, **kwargs):
        nonlocal context
        instance = args[0] if args else kwargs['instance']
        method = args[1] if len(args)>1 else kwargs['method']
        if method not in METHODS:
            raise ValueError('unsupported unified V12 method')
        capture['instance'] = instance
        capture['deadline_ns'] = kwargs.get('deadline_ns')
        context = FullTSContext(instance.model, reuse_projection=True) if method == 'AP-D' else None
        try:
            result = local(*args, **kwargs)
            capture['lasso'] = result[2]
            return result
        finally:
            if context is not None:
                context.close()
            context = None

    formal.run_method_local = captured_local
    capture.update(original_loop_code_preserved=loop.__code__ is formal._run_kernel_loop.__code__,
        original_local_code_preserved=local.__code__ is original.__code__,
        original_builder_global_preserved=formal.build_optimistic_abstraction is formal._p2f_grouped.build_optimistic_abstraction)
    return capture
