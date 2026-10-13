import json
from types import SimpleNamespace

from experiments.cmr_ros2_product_perf.fixtures import _make_model
from experiments.cmr_ros2_ap_ts_reuse import backend


def loop(instance, method, deadline_ns=None):
    abstract = None
    for precision in instance.precisions:
        abstract = build_optimistic_abstraction(instance.model, precision,
                                                 timing={})
    return abstract, None, None


def local(instance, method, deadline_ns=None):
    return _run_kernel_loop(instance, method, deadline_ns)


model = _make_model()
formal = SimpleNamespace(
    run_method_local=local,
    _run_kernel_loop=loop,
    build_optimistic_abstraction=object(),
    _p2f_grouped=SimpleNamespace(build_optimistic_abstraction=object()),
)
capture = backend.configure(formal)
instance = SimpleNamespace(model=model, precisions=[(0,), (0,)])
formal.run_method_local(instance, 'AP-D', deadline_ns=1)
ap_rounds = capture['build_work'][:]
instance.precisions[:] = [(0,), (0,)]
formal.run_method_local(instance, 'AP-D', deadline_ns=1)
ap_second_invocation = capture['build_work'][len(ap_rounds):]
instance.precisions[:] = [(0,), (0,)]
formal.run_method_local(instance, 'FULL', deadline_ns=1)
full = capture['build_work'][len(ap_rounds) + len(ap_second_invocation):]
instance.precisions[:] = [(0,), (0,)]
formal.run_method_local(instance, 'DEP-D', deadline_ns=1)
dep = capture['build_work'][len(ap_rounds) + len(ap_second_invocation) + len(full):]
def pairs(rows):
    return [[w.get('full_ts_rebuild_calls', 0), w.get('full_ts_cache_hits', 0)] for w in rows]
print(json.dumps({
    'ap_rounds_one_invocation': pairs(ap_rounds),
    'ap_second_invocation_cold': pairs(ap_second_invocation),
    'full_cold_rounds': pairs(full),
    'dep_d_cold_rounds': pairs(dep),
    'backend_id': capture['backend_id'],
}, sort_keys=True))
