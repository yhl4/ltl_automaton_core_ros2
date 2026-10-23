"""Fixed reference / current V4 / settled-target V5 isolated comparison."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_bfull_reuse import compare as previous
from experiments.cmr_ros2_bfull_perf import compare as foundation

ID = 'ROS2-DISCRETE-PLAN-CMR-SETTLED-TARGET-V5'
spec = importlib.util.spec_from_file_location('_cmr_settled_target_driver', Path(foundation.__file__))
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
_configure, _schema_for, _prepare = driver.configure, driver.schema_for, driver.prepare


def source_closure():
    closure = previous.source_closure()
    archive = previous.HERE / 'evidence/20261012/raw_attempts.zip'
    if foundation.real.digest(archive) != 'd62faef8c5e9a77f1c02e5fbf47037b1d35eb04688148b88757952e8a569bcef':
        raise ValueError('qualified current V4 archive changed')
    with zipfile.ZipFile(archive) as zipped:
        expected = json.loads(zipped.read('plan.json'))['source_closure']
    if closure != expected:
        raise ValueError('qualified current V4 source bytes changed')
    closure.update({str((HERE / name).relative_to(ROOT)): foundation.real.digest(HERE / name)
                    for name in ('backend.py', 'fixtures.py', 'compare.py')})
    return closure


def identity():
    from ltl_automaton_planner_core.ltl_tools import discrete_plan
    dependencies = [Path(discrete_plan.__file__), Path(foundation.real.runtime.core_backend.__file__)]
    for name in ('cmr_ros2_bfull_perf', 'cmr_ros2_bfull_compact', 'cmr_ros2_bfull_reuse'):
        dependencies += [HERE.parent / name / 'compare.py', HERE.parent / name / 'backend.py']
    dependencies += [HERE / 'backend.py', HERE / 'compare.py']
    return hashlib.sha256('|'.join([ID] + [foundation.real.digest(p) for p in dependencies]).encode()).hexdigest()


def configure(formal, arm):
    if arm == 'baseline':
        return previous.configure(formal, 'optimized')
    capture = _configure(formal, arm)
    if arm == 'optimized':
        capture['counter_basis'] = 'V4 original/layer graphs; target-finalized suffix Dijkstra settled work and actual heap operations'
    return capture


def schema_for(receipt, arm):
    if arm == 'baseline':
        return previous.schema_for(receipt, 'optimized')
    result = _schema_for(receipt, arm)
    if arm == 'optimized':
        result.binding_id = 'CMR_ROS2_SETTLED_TARGET_P2C_BACKEND_BINDING_V5'
        for schema in result.schemas.values():
            schema['$id'] = schema['$id'].replace(':ros2-scc-bound-v2', ':ros2-settled-target-v5')
    return result


def prepare(args):
    _prepare(args)
    path = args.output / 'plan.json'
    plan = json.loads(path.read_text())
    plan.update(schema='cmr-bfull-settled-target-plan-v1', qualification_id='CMR_BFULL_SETTLED_TARGET_20261012',
                baseline_backend='ROS2-DISCRETE-PLAN-CMR-GRAPH-REUSE-V4', candidate_backend=ID,
                authorized_changes=['suffix Dijkstra stops only when closed-walk target is finalized'])
    foundation.write(path, plan)


# Reuse original experimental worker, measurement, budgets, delivery and replay
# in a separate module. Previous modules and the scientific runner are untouched.
driver.HERE, driver.ID = HERE, ID
driver.source_closure, driver.identity = source_closure, identity
driver.configure, driver.schema_for, driver.prepare = configure, schema_for, prepare


if __name__ == '__main__':
    raise SystemExit(driver.main())
