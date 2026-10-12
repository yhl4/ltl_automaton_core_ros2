"""Fixed reference / qualified V2 / compact V3 comparison using the V2 driver."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_bfull_perf import compare as previous

ID = 'ROS2-DISCRETE-PLAN-CMR-COMPACT-V3'
spec = importlib.util.spec_from_file_location('_cmr_compact_comparison_driver',
                                              Path(previous.__file__))
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
_configure = driver.configure
_schema_for = driver.schema_for
_prepare = driver.prepare


def source_closure():
    closure = previous.source_closure()
    archive = previous.HERE / 'evidence/20261012/raw_attempts.zip'
    if previous.real.digest(archive) != '7780fd2bd9d69559ebafffbbf12faf8959228b02ca37580790829a42a7565831':
        raise ValueError('qualified V2 evidence archive changed')
    with zipfile.ZipFile(archive) as zipped:
        expected = json.loads(zipped.read('plan.json'))['source_closure']
    if closure != expected:
        raise ValueError('qualified V2 baseline source bytes changed')
    closure.update({str((HERE / name).relative_to(ROOT)): previous.real.digest(HERE / name)
                    for name in ('backend.py', 'fixtures.py', 'compare.py')})
    return closure


def identity():
    from ltl_automaton_planner_core.ltl_tools import discrete_plan
    paths = [Path(discrete_plan.__file__), Path(previous.real.runtime.core_backend.__file__),
             Path(previous.__file__), Path(previous.__file__).with_name('backend.py'),
             HERE / 'backend.py', HERE / 'compare.py']
    return hashlib.sha256('|'.join([ID] + [previous.real.digest(p) for p in paths]).encode()).hexdigest()


def configure(formal, arm):
    if arm == 'baseline':
        return previous.configure(formal, 'optimized')
    capture = _configure(formal, arm)
    if arm == 'optimized':
        capture['counter_basis'] = 'original min-parallel node graph plus seen_accept/dummy-source suffix graph; measured ROS2 heap work'
    return capture


def schema_for(receipt, arm):
    if arm == 'baseline':
        return previous.schema_for(receipt, 'optimized')
    result = _schema_for(receipt, arm)
    if arm == 'optimized':
        result.binding_id = 'CMR_ROS2_COMPACT_P2C_BACKEND_BINDING_V3'
        for schema in result.schemas.values():
            schema['$id'] = schema['$id'].replace(':ros2-scc-bound-v2', ':ros2-compact-v3')
    return result


def prepare(args):
    _prepare(args)
    path = args.output / 'plan.json'
    plan = json.loads(path.read_text())
    plan.update(schema='cmr-bfull-compact-plan-v1', qualification_id='CMR_BFULL_COMPACT_20261012',
                baseline_backend='ROS2-DISCRETE-PLAN-CMR-SCC-BOUND-V2',
                candidate_backend=ID)
    previous.write(path, plan)


# Reuse the qualified experimental worker, budgets, delivery, counters and replay
# verbatim. These module-local substitutions never modify the original module or
# the frozen scientific runner. Both implementations are pinned in source_closure.
driver.HERE = HERE
driver.ID = ID
driver.source_closure = source_closure
driver.identity = identity
driver.configure = configure
driver.schema_for = schema_for
driver.prepare = prepare


if __name__ == '__main__':
    raise SystemExit(driver.main())
