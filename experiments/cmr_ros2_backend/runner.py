"""Unified, explicitly selected CMR backend worker with original budgets."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from experiments.cmr_ros2_backend import backends

v6 = backends.v6
real, adapter, write = v6.real, v6.adapter, v6.write
SCOPE = 'CMR_UNIFIED_BACKEND_SUBSET_QUALIFICATION'


def load_plan(path):
    plan = json.loads(Path(path).read_bytes())
    from experiments.cmr_ros2_backend.qualification import selection
    if (plan['schema'] != 'cmr-unified-backend-plan-v1' or plan['scope'] != SCOPE
            or plan['formal_campaign'] is not False or plan['planner_budget_seconds'] != 180
            or plan['outer_watchdog_seconds'] != 195 or plan['attempts_per_cell_backend'] != 1
            or plan['backends'] != list(backends.NAMES) or plan['expected_method_workers'] != 24):
        raise ValueError('unsupported execution scope or budget')
    binding = backends.load_binding(plan['version_binding_path'], plan['version_binding_sha256'])
    if binding['binding_id'] != plan['version_binding_id']:
        raise ValueError('plan version binding identity mismatch')
    if plan['source_closure'] != execution_sources():
        raise ValueError('execution source bytes changed')
    # Selection is recomputed from immutable metadata, never from outcomes.
    selected = selection(plan['authority_receipt'])
    if any(plan[key] != selected[key] for key in ('records', 'cells', 'selection_rule', 'dds_cases')):
        raise ValueError('fixed metadata-only selection changed')
    suffix = hashlib.sha256(backends.canonical(dict(source_closure=plan['source_closure'],
        version_binding_sha256=plan['version_binding_sha256'], cells=plan['cells'])).encode()).hexdigest()[:16]
    if plan['execution_identity'] != plan['source_head'] + '+cmr-unified-' + suffix:
        raise ValueError('execution identity does not bind sources/version/selection')
    return plan


def execution_sources():
    closure = backends.source_closure()
    for name in ('qualification.py', 'fixtures.py', 'dds.py'):
        path = HERE / name
        closure[str(path.relative_to(backends.ROOT))] = backends.digest(path)
    # The reused DDS transport is a distinct interface dependency.
    for path in (HERE.parent / 'cmr_ros2_integration/dds_smoke.py',):
        closure[str(path.relative_to(backends.ROOT))] = backends.digest(path)
    return closure


def authority(plan, receipt_path, kernel_root):
    if backends.digest(adapter._native_path(receipt_path)) != plan['receipt_sha256']:
        raise ValueError('receipt differs from frozen plan')
    formal, bound, manifest = adapter.load_bound_runner(receipt_path, kernel_root)
    if manifest['binding_sha256'] != plan['original_execution_binding_sha256']:
        raise ValueError('original science binding mismatch')
    manifest_path = adapter._native_path(bound['manifest_path'])
    if backends.digest(manifest_path) != plan['manifest_sha256']:
        raise ValueError('frozen manifest mismatch')
    records = {r['instance_id']: r for r in json.loads(manifest_path.read_bytes())}
    if any(records[r['instance_id']] != r for r in plan['records']):
        raise ValueError('selected model metadata mismatch')
    for record in plan['records']:
        instance_path = adapter._native_path(bound['benchmark_root']) / record['path']
        if backends.digest(instance_path) != record['instance_sha256']:
            raise ValueError('selected model bytes mismatch')
    return formal, bound, manifest, records


def make_request(plan, instance_id, method, backend):
    found = [c for c in plan['cells'] if c['instance_id'] == instance_id and c['method'] == method]
    if len(found) != 1:
        raise ValueError('cell outside frozen small qualification scope')
    descriptor = backends.describe(plan['version_binding_path'], backend)
    return dict(found[0], **descriptor, qualification_id=plan['qualification_id'],
                population=SCOPE, formal_campaign=False, execution_identity=plan['execution_identity'],
                planner_budget_seconds=180, outer_watchdog_seconds=195)


def validate_request(plan, request, backend):
    if request != make_request(plan, request['instance_id'], request['method'], backend):
        raise ValueError('request/backend differs from the frozen version binding')


def worker(args):
    plan = load_plan(args.plan)
    request = json.loads(args.request.read_bytes())
    validate_request(plan, request, args.backend)
    if str(args.version_binding.resolve()) != str(Path(plan['version_binding_path']).resolve()):
        raise ValueError('unexpected version binding path')
    formal, bound, manifest, records = authority(plan, args.binding, args.kernel_root)
    capture = backends.configure(formal, args.backend, args.version_binding)
    certs = args.output / 'certificates'
    certs.mkdir()
    write(args.output / 'preflight.json', manifest)
    row = formal.run_one(request, records, certs,
        benchmark_root=adapter._native_path(bound['benchmark_root']),
        execution_commit=plan['execution_identity'], planner_budget_seconds=180)
    write(args.output / 'runner_raw_result.json', row)
    if row['initial_S0'] != bound['expected_initialization'][request['instance_id']][request['method']]:
        raise ValueError('initial precision differs from original binding')
    descriptor = capture['backend_binding']
    row.update(qualification_scope=SCOPE, formal_campaign=False,
               search_counter_basis=capture['counter_basis'], **descriptor)
    for round_row in row.get('rounds') or []:
        round_row.update(**descriptor)
    row.pop('result_hash', None)
    row['result_hash'] = formal.sha256_bytes(formal.canonical_json(row).encode())
    schema = backends.schema_for(json.loads(adapter._native_path(args.binding).read_bytes()), args.backend)
    write(args.output / 'schema_binding.json', dict(binding_id=schema.binding_id,
        source_hashes=schema.source_hashes, schemas=schema.schemas))
    schema.validate_result(row)
    transport = None
    if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
        if capture['lasso'] is None:
            raise ValueError('certified result lacks concrete lasso')
        transport = dict(concrete_lasso=real.runtime.lasso_payload(capture['lasso']),
                        accepting_buchi_states=sorted(capture['instance'].model.buchi.accepting))
    write(args.output / 'worker_result.json', dict(row=row, transport=transport,
        search_work=capture['search_work'], build_work=capture.get('build_work', []),
        backend_binding=descriptor, worker_pid=os.getpid(),
        backend_configuration={k: capture[k] for k in ('backend_id', 'backend_sha256',
            'original_loop_code_preserved', 'original_local_code_preserved',
            'original_builder_global_preserved')}))


def run_isolated(request, receipt, kernel_root, version_binding_path, plan_path, output):
    plan = load_plan(plan_path)
    validate_request(plan, request, request['backend'])
    if backends.digest(version_binding_path) != plan['version_binding_sha256']:
        raise ValueError('caller version binding mismatch')
    fixture = Path(plan_path).parent / 'fixtures.json'
    tests = json.loads(fixture.read_bytes()) if fixture.exists() else {}
    if (tests.get('status') != 'PASSED' or tests.get('execution_identity') != plan['execution_identity']
            or tests.get('version_binding_id') != plan['version_binding_id']
            or tests.get('version_binding_sha256') != plan['version_binding_sha256']):
        raise ValueError('binding/interface fixtures must pass first')
    output = Path(output).resolve()
    if not str(output).startswith('/tmp/'):
        raise ValueError('fresh isolated attempt must be under /tmp/')
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'request.json', request)
    start = time.perf_counter_ns()
    command = [sys.executable, '-B', str(HERE / 'runner.py'), '--worker', '--backend', request['backend'],
        '--request', str(output / 'request.json'), '--binding', str(receipt), '--kernel-root', str(kernel_root),
        '--version-binding', str(version_binding_path), '--plan', str(plan_path), '--output', str(output)]
    killed = False
    with (output / 'stdout.txt').open('w') as stdout, (output / 'stderr.txt').open('w') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        try:
            process.wait(timeout=max(0, 195 - (time.perf_counter_ns() - start) / 1e9))
        except subprocess.TimeoutExpired:
            killed = True
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
    (output / 'worker.rc').write_text(str(process.returncode) + '\n')
    if process.returncode != 0 and not killed:
        raise RuntimeError('unified worker failed; retain ' + str(output / 'stderr.txt'))
    delivered = output / 'worker_result.json'
    if delivered.exists():
        value = json.loads(delivered.read_bytes())
    elif killed:
        formal, _, _, _ = authority(plan, receipt, kernel_root)
        backends.configure(formal, request['backend'], version_binding_path)
        value = dict(row=formal.timeout_serialization(request, 'outer_watchdog',
            method_start_ns=start, terminal_completion_ns=time.perf_counter_ns()),
            transport=None, search_work=[], build_work=[],
            backend_binding=backends.describe(version_binding_path, request['backend']))
        value['row'].update(**value['backend_binding'])
    else:
        raise RuntimeError('worker exited without result')
    value.update(worker_pid=process.pid, worker_exitcode=process.returncode,
                 worker_alive_after_cleanup=process.poll() is None, outer_start_ns=start)
    write(output / 'delivered_attempt.json', value)
    real.terminal_delivery(value['row'], time.perf_counter_ns(), outer_start=start, forced_timeout=killed)
    if not value['row']['certificate_valid_for_terminal']:
        value['transport'] = None
    write(output / 'result.json', value)
    completion = time.perf_counter_ns()
    if completion >= value['row']['method_start_ns'] + 180_000_000_000 and value['row']['terminal_status'] != 'TIMEOUT':
        real.terminal_delivery(value['row'], completion, outer_start=start)
        value['transport'] = None
        write(output / 'result.json', value)
    schema = backends.schema_for(json.loads(adapter._native_path(receipt).read_bytes()), request['backend'])
    schema.validate_result(value['row'])
    return value


def replay(plan, receipt, kernel_root, value, output):
    formal, bound, _, _ = authority(plan, receipt, kernel_root)
    row = value['row']
    if row['terminal_status'] == 'INFEASIBLE_CERTIFIED':
        # Original run_one publishes exact-empty metadata, not a feasible
        # lasso certificate. Do not invent an independent replay verdict.
        if (row['objective'] is not None or value['transport'] is not None
                or row['infeasibility_certificate_type'] != 'REDUCED_PRODUCT_EXACT_EMPTY'):
            raise ValueError('original exact-empty contract mismatch')
        return dict(status='NOT_APPLICABLE', basis='original exact-empty proof metadata; paired reference required')
    if row['terminal_status'] != 'OPTIMALITY_CERTIFIED':
        raise ValueError('noncertified outcome retained; qualification cannot pass')
    cert = Path(output) / 'certificates' / row['certificate_path']
    if backends.digest(cert) != row['certificate_hash']:
        raise ValueError('persisted certificate bytes changed')
    result = formal.verify_certificate_file(cert, row['certificate_hash'],
        adapter._native_path(bound['benchmark_root']), adapter._native_path(bound['manifest_path']),
        plan['execution_identity'], formal.EXECUTION_CONTRACT_COMMIT, formal.BENCHMARK_COMMIT)
    if result['status'] != 'PASS':
        raise ValueError('independent certificate replay failed')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=backends.NAMES, required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    parser.add_argument('--version-binding', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--instance-id')
    parser.add_argument('--method', choices=('FULL', 'AP-D', 'DEP-D'))
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not str(args.output).startswith('/tmp/'):
        raise ValueError('fresh isolated output must be under /tmp/')
    try:
        if args.worker:
            worker(args)
        else:
            plan = load_plan(args.plan)
            request = make_request(plan, args.instance_id, args.method, args.backend)
            run_isolated(request, args.binding, args.kernel_root, args.version_binding, args.plan, args.output)
        return 0
    except Exception:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'error.txt').write_text(traceback.format_exc())
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
