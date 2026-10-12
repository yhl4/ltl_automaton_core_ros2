"""Replay corrected DDS assertions and pending certificates; never run workers."""

import argparse
import ast
import copy
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from experiments.cmr_ros2_backend import runner, backends, dds, qualification


def without_validator(path):
    tree = ast.parse(path.read_bytes())
    tree.body = [node for node in tree.body if not
                 (isinstance(node, ast.FunctionDef) and node.name == '_validate_case')]
    return ast.dump(tree, include_attributes=False)


def run(output, receipt, kernel_root):
    original_path = output / 'qualification.json'
    original = json.loads(original_path.read_bytes())
    plan = original['plan']
    if original['status'] != 'FAILED' or not all(c['status'] == 'PASSED' for c in original['cells']):
        raise ValueError('validation-only replay requires all 12 paired methods already passed')
    if [c.get('error') for c in original['dds']['cases']] != [
            "AssertionError('observation generation mismatch')", None]:
        raise ValueError('original DDS failure is outside this narrow correction')
    name = 'experiments/cmr_ros2_backend/dds.py'
    frozen = output / 'frozen_adapter' / name
    corrected = HERE / 'dds.py'
    if backends.digest(frozen) != plan['source_closure'][name]:
        raise ValueError('executed DDS source snapshot mismatch')
    if without_validator(frozen) != without_validator(corrected):
        raise ValueError('DDS changed beyond the acceptance assertion function')
    for path, expected in plan['source_closure'].items():
        if path != name and backends.digest(backends.ROOT / path) != expected:
            raise ValueError('nonvalidator execution source changed')
    backends.load_binding(plan['version_binding_path'], plan['version_binding_sha256'])
    report = copy.deepcopy(original)
    descriptor = backends.describe(plan['version_binding_path'], 'ros2-v6')
    for case, selected in zip(report['dds']['cases'], plan['dds_cases']):
        dds._validate_case(dict(selected, **case['request']), case, descriptor)
        case['original_validation_status'] = case['status']
        case['status'] = 'PASSED'
        case.pop('error', None)
        case.pop('traceback', None)
        directory = output / 'dds' / selected['request_id'] / 'cmr_attempt'
        value = json.loads((directory / 'result.json').read_bytes())
        case['certificate_replay'] = runner.replay(plan, receipt, kernel_root, value, directory)
        paired = next(item for item in report['cells'] if item['instance_id'] == selected['instance_id']
                      and item['method'] == selected['method'])
        qualification.check_pair(paired['backends']['reference'], value, selected['method'])
    correction = dict(schema='cmr-dds-validator-correction-v1', status='PASSED',
        original_qualification_sha256=backends.digest(original_path),
        original_dds_report_sha256=backends.digest(output / 'dds/dds_report.json'),
        original_status='FAILED', reason='existing driver deliberately emits stale generation 0 after accepted dispatch',
        acceptance='original rule: stale observation received but ignored; complete unique dispatch and independent TS feedback retained',
        execution_identity=plan['execution_identity'], version_binding_id=plan['version_binding_id'],
        original_dds_sha256=backends.digest(frozen), corrected_dds_sha256=backends.digest(corrected),
        outside_validator_ast_unchanged=True, additional_solver_workers=0, additional_dds_runs=0,
        validation_replay_only=True)
    report.update(status='PASSED', validation_correction=correction)
    report['dds']['status'] = 'PASSED'
    runner.write(output / 'validation_correction.json', correction)
    runner.write(output / 'qualified_replay.json', report)
    runner.write(output / 'frozen_inputs_after.json', qualification.frozen_inputs(plan))
    print(json.dumps(dict(status='PASSED', validation_replay_only=True,
        additional_solver_workers=0, additional_dds_runs=0, independent_pending_feasible_certificate_replays=1)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    args = parser.parse_args()
    run(args.output, args.binding, args.kernel_root)
