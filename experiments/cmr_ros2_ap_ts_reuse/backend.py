"""AP-only full reachable TS reuse; unchanged V7 search and P2f loop."""

import hashlib
from pathlib import Path

from experiments.cmr_ros2_search_entry import runner as v7

HERE = Path(__file__).resolve().parent
ID = 'ROS2-DISCRETE-PLAN-CMR-AP-FULL-TS-REUSE-V8'


def identity():
    sources = [HERE / name for name in ('builder.py', 'backend.py', 'runner.py')]
    return hashlib.sha256('|'.join([ID, v7.identity()] +
        [v7.digest(p) for p in sources]).encode()).hexdigest()


def configure(formal):
    from experiments.cmr_ros2_ap_ts_reuse.builder import FullTSContext
    from experiments.cmr_ros2_product_perf import builder as v6_builder
    from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp

    capture = dict(backend_id=ID, backend_sha256=identity(), search_work=[],
        build_work=[], lasso=None, instance=None,
        counter_basis='unchanged V7 search; actual per-method full TS builds and cache hits')
    original = formal.run_method_local
    full_ts = None

    def build(model, precision, *, timing=None):
        work = {}
        try:
            if full_ts is None:
                return v6_builder.build_optimistic_abstraction(model, precision, timing=timing, work=work)
            return full_ts.build(model, precision, timing=timing, work=work)
        finally:
            capture['build_work'].append(work)

    def solve(abstract, stats=None):
        if stats is None:
            raise TypeError('qualified SearchStats required')
        return v7.v6.foundation.measure(v7.backend, dp, capture, abstract, stats)

    formal.BACKEND_ID, formal.BACKEND_SHA256 = ID, capture['backend_sha256']
    loop = v7.adapter._clone_function(formal._run_kernel_loop,
        {'solve_exact_abstract_lasso': solve, 'build_optimistic_abstraction': build})
    local = v7.adapter._clone_function(original, {'_run_kernel_loop': loop})

    def captured_local(*args, **kwargs):
        nonlocal full_ts
        instance = args[0] if args else kwargs['instance']
        method = args[1] if len(args) > 1 else kwargs['method']
        capture['instance'] = instance
        capture['deadline_ns'] = kwargs.get('deadline_ns')
        # The cache is born and disposed within this invocation. A second
        # method/attempt, even for the same model object, starts cold.
        full_ts = FullTSContext(instance.model) if method == 'AP-D' else None
        try:
            result = local(*args, **kwargs)
            capture['lasso'] = result[2]
            return result
        finally:
            if full_ts is not None:
                full_ts.close()
            full_ts = None

    formal.run_method_local = captured_local
    capture.update(original_loop_code_preserved=loop.__code__ is formal._run_kernel_loop.__code__,
        original_local_code_preserved=local.__code__ is original.__code__,
        original_builder_global_preserved=(formal.build_optimistic_abstraction is
            formal._p2f_grouped.build_optimistic_abstraction))
    return capture
