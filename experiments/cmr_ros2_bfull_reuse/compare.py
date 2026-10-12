"""Fixed reference / current V3 / graph-reuse V4 isolated comparison."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_bfull_compact import compare as previous
from experiments.cmr_ros2_bfull_perf import compare as foundation

ID = 'ROS2-DISCRETE-PLAN-CMR-GRAPH-REUSE-V4'
spec = importlib.util.spec_from_file_location('_cmr_graph_reuse_driver', Path(foundation.__file__))
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
_configure, _schema_for, _prepare = driver.configure, driver.schema_for, driver.prepare


def source_closure():
    closure = previous.source_closure()
    archive = previous.HERE / 'evidence/20261012/raw_attempts.zip'
    if foundation.real.digest(archive) != 'cd8d4e037199a743a0aad6451bb5adec636c56e6fe78c5185fadcb6203ac3a48':
        raise ValueError('qualified current V3 archive changed')
    with zipfile.ZipFile(archive) as zipped:
        expected = json.loads(zipped.read('plan.json'))['source_closure']
    if closure != expected:
        raise ValueError('qualified current V3 source bytes changed')
    closure.update({str((HERE / name).relative_to(ROOT)): foundation.real.digest(HERE / name)
                    for name in ('backend.py', 'fixtures.py', 'compare.py')})
    return closure


def identity():
    from ltl_automaton_planner_core.ltl_tools import discrete_plan
    paths = [Path(discrete_plan.__file__), Path(foundation.real.runtime.core_backend.__file__),
             Path(foundation.__file__), Path(foundation.__file__).with_name('backend.py'),
             Path(previous.__file__), Path(previous.__file__).with_name('backend.py'),
             HERE / 'backend.py', HERE / 'compare.py']
    return hashlib.sha256('|'.join([ID] + [foundation.real.digest(p) for p in paths]).encode()).hexdigest()


def configure(formal, arm):
    if arm == 'baseline':
        return previous.configure(formal, 'optimized')
    capture = _configure(formal, arm)
    if arm == 'optimized':
        capture['counter_basis'] = 'original min-parallel node graph; one/two accepting layers plus dummy source; measured ROS2 heap work'
    return capture


def schema_for(receipt, arm):
    if arm == 'baseline':
        return previous.schema_for(receipt, 'optimized')
    result = _schema_for(receipt, arm)
    if arm == 'optimized':
        result.binding_id = 'CMR_ROS2_GRAPH_REUSE_P2C_BACKEND_BINDING_V4'
        for schema in result.schemas.values():
            schema['$id'] = schema['$id'].replace(':ros2-scc-bound-v2', ':ros2-graph-reuse-v4')
    return result


def prepare(args):
    _prepare(args)
    path = args.output / 'plan.json'
    plan = json.loads(path.read_text())
    plan.update(schema='cmr-bfull-graph-reuse-plan-v1', qualification_id='CMR_BFULL_GRAPH_REUSE_20261012',
                baseline_backend='ROS2-DISCRETE-PLAN-CMR-COMPACT-V3', candidate_backend=ID,
                authorized_changes=['within-solve graph reuse and reverse view',
                                    'one acceptance layer for already accepting entries'])
    foundation.write(path, plan)


# Pin and reuse the existing experimental worker/measurement/delivery/replay.
# Substitutions affect only this independent module, never the previous modules
# or the frozen scientific runner. All implementation dependencies are hashed.
driver.HERE, driver.ID = HERE, ID
driver.source_closure, driver.identity = source_closure, identity
driver.configure, driver.schema_for, driver.prepare = configure, schema_for, prepare


if __name__ == '__main__':
    raise SystemExit(driver.main())
