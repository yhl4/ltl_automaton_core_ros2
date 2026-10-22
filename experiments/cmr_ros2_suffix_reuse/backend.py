"""V10 suffix-graph reuse over the unchanged V9 reduction and search rules."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

from experiments.cmr_ros2_reduction_reuse import backend as v9
from experiments.cmr_ros2_search_entry import runner as v7

HERE = Path(__file__).resolve().parent
ID = 'ROS2-DISCRETE-PLAN-CMR-SUFFIX-GRAPH-REUSE-V10'


def identity():
    paths = [HERE/name for name in ('backend.py','search.py','runner.py')]
    return hashlib.sha256('|'.join([ID,v9.identity()]+[v7.digest(p) for p in paths]).encode()).hexdigest()


def configure(formal, *, optimized=True):
    from experiments.cmr_ros2_reduction_reuse.builder import FullTSContext
    from experiments.cmr_ros2_suffix_reuse import search
    from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp
    backend_id, backend_sha = (ID,identity()) if optimized else (v9.ID,v9.identity())
    capture = dict(backend_id=backend_id,backend_sha256=backend_sha,
        search_work=[],build_work=[],lasso=None,instance=None,
        counter_basis='V9 rules with actual suffix graph construction/reuse counters')
    original = formal.run_method_local
    context = None

    def build(model, precision, *, timing=None):
        work = {}
        try:
            return context.build(model,precision,timing=timing,work=work)
        finally:
            capture['build_work'].append(work)

    def solve(abstract, stats=None):
        if stats is None:
            raise TypeError('qualified SearchStats required')
        def measured_search(abstract,work=None,phase_call=None):
            return search.solve_cmr_lasso(abstract,work=work,phase_call=phase_call,reuse_suffix=optimized)
        return v7.v6.foundation.measure(SimpleNamespace(solve_cmr_lasso=measured_search),dp,capture,abstract,stats)

    formal.BACKEND_ID,formal.BACKEND_SHA256 = backend_id,backend_sha
    loop = v7.adapter._clone_function(formal._run_kernel_loop,
        {'solve_exact_abstract_lasso':solve,'build_optimistic_abstraction':build})
    local = v7.adapter._clone_function(original,{'_run_kernel_loop':loop})

    def captured_local(*args,**kwargs):
        nonlocal context
        instance = args[0] if args else kwargs['instance']
        method = args[1] if len(args)>1 else kwargs['method']
        if method!='AP-D':
            raise ValueError('bounded V10 qualification is AP-D only')
        capture['instance']=instance
        capture['deadline_ns']=kwargs.get('deadline_ns')
        context=FullTSContext(instance.model,reuse_projection=True)
        try:
            result=local(*args,**kwargs)
            capture['lasso']=result[2]
            return result
        finally:
            context.close()
            context=None

    formal.run_method_local=captured_local
    capture.update(original_loop_code_preserved=loop.__code__ is formal._run_kernel_loop.__code__,
        original_local_code_preserved=local.__code__ is original.__code__,
        original_builder_global_preserved=formal.build_optimistic_abstraction is formal._p2f_grouped.build_optimistic_abstraction)
    return capture
