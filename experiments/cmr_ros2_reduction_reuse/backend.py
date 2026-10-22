"""V9 projection/witness reuse and counter-only observation of pinned V8."""
import hashlib
from pathlib import Path

from experiments.cmr_ros2_ap_ts_reuse import backend as v8
from experiments.cmr_ros2_search_entry import runner as v7

HERE = Path(__file__).resolve().parent
ID = 'ROS2-DISCRETE-PLAN-CMR-PROJECTION-WITNESS-REUSE-V9'


def identity():
    paths = [HERE/name for name in ('builder.py', 'search.py', 'backend.py', 'runner.py')]
    return hashlib.sha256('|'.join([ID, v8.identity()] + [v7.digest(p) for p in paths]).encode()).hexdigest()


def configure(formal, *, optimized=True):
    from experiments.cmr_ros2_reduction_reuse import builder, search
    from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp
    backend_id, backend_sha = (ID, identity()) if optimized else (v8.ID, v8.identity())
    capture = dict(backend_id=backend_id, backend_sha256=backend_sha,
        search_work=[], build_work=[], lasso=None, instance=None,
        counter_basis='actual projection and witness canonicalization calls; V8 has counters only')
    original = formal.run_method_local
    context = None

    def build(model, precision, *, timing=None):
        work = {}
        try:
            return context.build(model, precision, timing=timing, work=work)
        finally:
            capture['build_work'].append(work)

    def solve(abstract, stats=None):
        if stats is None:
            raise TypeError('qualified SearchStats required')
        from types import SimpleNamespace
        def measured_search(abstract, work=None, phase_call=None):
            return search.solve_cmr_lasso(abstract, work=work, phase_call=phase_call,
                                         reuse_witness=optimized)
        return v7.v6.foundation.measure(SimpleNamespace(solve_cmr_lasso=measured_search),
                                        dp, capture, abstract, stats)

    formal.BACKEND_ID, formal.BACKEND_SHA256 = backend_id, backend_sha
    loop = v7.adapter._clone_function(formal._run_kernel_loop,
        {'solve_exact_abstract_lasso': solve, 'build_optimistic_abstraction': build})
    local = v7.adapter._clone_function(original, {'_run_kernel_loop': loop})

    def captured_local(*args, **kwargs):
        nonlocal context
        instance = args[0] if args else kwargs['instance']
        method = args[1] if len(args) > 1 else kwargs['method']
        if method != 'AP-D':
            raise ValueError('bounded V9 qualification is AP-D only')
        capture['instance'] = instance
        capture['deadline_ns'] = kwargs.get('deadline_ns')
        context = builder.FullTSContext(instance.model, reuse_projection=optimized)
        try:
            result = local(*args, **kwargs)
            capture['lasso'] = result[2]
            return result
        finally:
            context.close()
            context = None

    formal.run_method_local = captured_local
    capture.update(original_loop_code_preserved=loop.__code__ is formal._run_kernel_loop.__code__,
        original_local_code_preserved=local.__code__ is original.__code__,
        original_builder_global_preserved=(formal.build_optimistic_abstraction is
            formal._p2f_grouped.build_optimistic_abstraction))
    return capture
