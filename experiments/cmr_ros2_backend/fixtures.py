"""Deterministic selection/binding/request checks, without planner or DDS calls."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from experiments.cmr_ros2_backend import backends, runner


def rejected(name, operation, output):
    try:
        operation()
    except (ValueError, KeyError) as error:
        output.append(dict(name=name, status='PASSED', rejection=str(error)))
        return
    raise AssertionError('invalid request/binding accepted: ' + name)


def run(plan_path, receipt, kernel_root, output):
    plan = runner.load_plan(plan_path)
    binding_path = Path(plan['version_binding_path'])
    value = backends.load_binding(binding_path, plan['version_binding_sha256'])
    checks = []
    for backend in backends.NAMES:
        descriptor = backends.describe(binding_path, backend)
        if descriptor['backend_id'] != value['backends'][backend]['backend_id']:
            raise AssertionError('backend descriptor mismatch')
        for cell in plan['cells']:
            request = runner.make_request(plan, cell['instance_id'], cell['method'], backend)
            runner.validate_request(plan, request, backend)
        checks.append(dict(name=backend + '_twelve_explicit_requests', status='PASSED'))
    rejected('unknown_backend', lambda: backends.describe(binding_path, 'auto'), checks)
    rejected('version_file_hash_mismatch', lambda: backends.load_binding(binding_path, '0' * 64), checks)
    mutated_path = output.parent / 'fixture_mutated_binding.json'
    for field, replacement in (('version', 'CMR_UNIFIED_BACKENDS_V0'), ('planner_budget_seconds', 1)):
        mutated = copy.deepcopy(value)
        mutated[field] = replacement
        content = dict(mutated)
        content.pop('binding_id')
        mutated['binding_id'] = backends.VERSION + '-' + hashlib.sha256(backends.canonical(content).encode()).hexdigest()[:16]
        runner.write(mutated_path, mutated)
        rejected('modified_' + field, lambda: backends.load_binding(mutated_path), checks)
    mutated = copy.deepcopy(value)
    mutated['backends']['ros2-v6']['backend_sha256'] = value['backends']['reference']['backend_sha256']
    content = dict(mutated)
    content.pop('binding_id')
    mutated['binding_id'] = backends.VERSION + '-' + hashlib.sha256(backends.canonical(content).encode()).hexdigest()[:16]
    runner.write(mutated_path, mutated)
    rejected('false_v6_identity', lambda: backends.load_binding(mutated_path), checks)
    first = plan['cells'][0]
    request = runner.make_request(plan, first['instance_id'], first['method'], 'ros2-v6')
    for field, replacement in (('backend_sha256', '0' * 64), ('version_binding_id', 'stale'),
                               ('planner_budget_seconds', 1), ('method', 'AI-D')):
        mutated = dict(request, **{field: replacement})
        rejected('request_modified_' + field, lambda: runner.validate_request(plan, mutated, 'ros2-v6'), checks)
    rejected('request_backend_swapped', lambda: runner.validate_request(plan, request, 'reference'), checks)
    rejected('outside_selected_instances', lambda: runner.make_request(plan, 'unselected', 'FULL', 'ros2-v6'), checks)
    # Test the original schemas against genuine prior rows plus the new binding
    # metadata. This is offline schema replay, not a new scientific execution.
    receipt_data = json.loads(runner.adapter._native_path(receipt).read_bytes())
    archive = backends.v6.HERE / 'evidence/20261012/raw_attempts.zip'
    with zipfile.ZipFile(archive) as zipped:
        for backend, member in (('reference', 'reference'), ('ros2-v6', 'optimized')):
            row = json.loads(zipped.read('B-D-BRANCH-S1_FULL/' + member + '/result.json'))['row']
            descriptor = backends.describe(binding_path, backend)
            row.update(**descriptor)
            for round_row in row['rounds']:
                round_row.update(**descriptor)
            backends.schema_for(receipt_data, backend).validate_result(row)
            checks.append(dict(name=backend + '_unchanged_schema_metadata', status='PASSED'))
    # No solver call: configure one fresh authority runner for each variant and
    # observe the unchanged loop/local/global identities and exact backend SHA.
    configurations = []
    for backend in backends.NAMES:
        formal, _, manifest, _ = runner.authority(plan, receipt, kernel_root)
        capture = backends.configure(formal, backend, binding_path)
        if not all(capture[key] for key in ('original_loop_code_preserved',
                'original_local_code_preserved', 'original_builder_global_preserved')):
            raise AssertionError('runner code/global identity changed')
        if capture['lasso'] is not None or capture['search_work'] or capture.get('build_work'):
            raise AssertionError('configuration invoked a planner')
        configurations.append(dict(backend=backend, descriptor=capture['backend_binding'],
                                    source_rows=len(manifest['source_checks'])))
    checks.append(dict(name='fresh_configuration_without_solver', status='PASSED'))
    result = dict(schema='cmr-unified-backend-fixtures-v1', status='PASSED', checks=checks,
                  check_count=len(checks), configurations=configurations,
                  execution_identity=plan['execution_identity'],
                  version_binding_id=plan['version_binding_id'],
                  version_binding_sha256=plan['version_binding_sha256'], planner_calls=0, dds_calls=0)
    runner.write(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.plan, args.binding, args.kernel_root, args.output)
        print(json.dumps(dict(status=result['status'], checks=result['check_count'], planner_calls=0, dds_calls=0)))
    except Exception:
        import traceback
        runner.write(args.output, dict(status='FAILED', traceback=traceback.format_exc()))
        raise
