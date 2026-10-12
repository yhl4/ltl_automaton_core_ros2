"""Run one selected real CMR instance in a fresh, isolated process."""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'cmr_ros2_integration'))
import runtime  # noqa: E402

SCOPE = 'CORE_SUBSET_QUALIFICATION'
SOURCE_FILES = ('bound_runner.py', 'runner.py', 'verify_small.py', 'dds_real.py',
                'verifier_checks.py')
PROOF_FIELDS = ('infeasibility_certificate_type', 'infeasibility_proof_basis',
                'infeasibility_precision', 'lower_precision_infeasibility')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_selection():
    value = json.loads((HERE / 'selection.json').read_text())
    if (value['scope'] != SCOPE or value['methods'] != ['FULL', 'AP-D', 'DEP-D']
            or value['planner_budget_seconds'] != 180
            or value['outer_watchdog_seconds'] != 195):
        raise ValueError('qualification selection contract mismatch')
    return value


def request_for(instance_id, method, backend):
    selection = load_selection()
    if backend not in ('reference', 'ros2'):
        raise ValueError('unknown backend')
    found = [c for c in selection['cells']
             if c['instance_id'] == instance_id and c['method'] == method]
    if len(found) != 1:
        raise ValueError('cell is outside the fixed qualification subset')
    cell = dict(found[0])
    cell['source_cell_id'] = cell.pop('cell_id')
    return dict(cell, backend=backend, qualification_id=selection['qualification_id'],
                population=SCOPE, planner_budget_seconds=180, outer_watchdog_seconds=195)


def load_schema(receipt, backend='reference'):
    source = receipt['scientific_source_refs']['validation_contract']
    path = runtime.core_smoke._native_path(source['path'])
    if digest(path) != source['sha256']:
        raise ValueError('P2c validator source mismatch')
    spec = importlib.util.spec_from_file_location('cmr_real_p2c_schema', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    schemas = {}
    source_hashes = {}
    for kind in ('result', 'round'):
        ref = receipt['scientific_source_refs'][kind + '_schema']
        schema_path = runtime.core_smoke._native_path(ref['path'])
        if digest(schema_path) != ref['sha256']:
            raise ValueError(f'{kind} schema source mismatch')
        schema = json.loads(schema_path.read_text())
        source_hashes[kind] = ref['sha256']
        if backend == 'ros2':
            expected_original = receipt['scientific_source_refs']['SCC_solver']['sha256']
            if schema['properties']['backend_sha256'].get('const') != expected_original:
                raise ValueError('frozen P2c backend binding changed')
            canonical = ('ROS2-DISCRETE-PLAN-CMR-LASSO-V1|'
                         + runtime.core_smoke.EXPECTED_DISCRETE_PLAN_SHA256 + '|'
                         + digest(runtime.core_backend.__file__))
            schema = copy.deepcopy(schema)
            schema['properties']['backend_sha256']['const'] = hashlib.sha256(
                canonical.encode()).hexdigest()
            schema['$id'] += ':ros2-backend-binding-v1'
        elif backend != 'reference':
            raise ValueError('unknown schema backend')
        schemas[kind] = schema

    def validate_result(row):
        expected_id = ('ROS2-DISCRETE-PLAN-CMR-LASSO-V1' if backend == 'ros2'
                       else 'ECC-P1-SCC-INITIAL_LABEL_V1')
        if row['backend_id'] != expected_id:
            raise ValueError('result backend identity differs from the requested arm')
        module.validate(row, schemas['result'])
        for index, round_row in enumerate(row.get('rounds') or []):
            if round_row['backend_id'] != expected_id:
                raise ValueError('round backend identity differs from the requested arm')
            module.validate(round_row, schemas['round'], f'$/rounds/{index}')

    return SimpleNamespace(validate_result=validate_result, schemas=schemas,
                           source_hashes=source_hashes,
                           binding_id=('P2C_FROZEN_ECC' if backend == 'reference'
                                       else 'CMR_ROS2_REAL_P2C_BACKEND_BINDING_V1'))


def terminal_delivery(row, completion, *, outer_start, forced_timeout=False):
    """Authorize claims only after observed delivery and logging completion."""
    start = row.get('method_start_ns')
    if forced_timeout or not isinstance(start, int):
        start = outer_start
        row['timing_basis'] = 'outer worker elapsed; method start unavailable'
    else:
        row['timing_basis'] = 'qualified runner method start; worker startup excluded'
    row['method_start_ns'] = start
    runner_completion = row.setdefault('qualified_runner_completion_ns',
                                       row.get('terminal_completion_ns'))
    row['terminal_completion_ns'] = completion
    row['T_total'] = row['T_plan_wall'] = (completion - start) / 1e9
    if isinstance(runner_completion, int) and not forced_timeout:
        row.setdefault('phase_intervals_ns', {})['ROS_result_delivery'] = [
            runner_completion, completion]
        row['post_runner_delivery_seconds'] = (completion - runner_completion) / 1e9
    components = ('T_input_preprocess', 'T_initialization', 'T_full_ts', 'T_reduction',
                  'T_product', 'T_search', 'T_concretization', 'T_certification',
                  'T_refinement', 'T_logging')
    if all(isinstance(row.get(name), (int, float)) for name in components):
        row['T_other'] = row['T_total'] - sum(row[name] for name in components)
    expired = forced_timeout or completion >= start + 180_000_000_000
    if expired or row['terminal_status'] == 'TIMEOUT':
        row.update(terminal_status='TIMEOUT', canonical_status='TIMEOUT', exact_status='TIMEOUT',
                   objective=None, right_censored=True, timing_status='RIGHT_CENSORED',
                   timeout_stage='outer_watchdog' if forced_timeout else 'planner',
                   certificate_verifier_status='NOT_AVAILABLE',
                   certificate_path='NOT_AVAILABLE', certificate_hash='NOT_AVAILABLE',
                   certificate_schema='NOT_AVAILABLE', certificate_objective=None)
        for name in PROOF_FIELDS:
            row[name] = None
        for round_row in row.get('rounds') or []:
            for name in PROOF_FIELDS:
                round_row[name] = None
            round_row['terminal_claim_valid'] = False
    else:
        for round_row in row.get('rounds') or []:
            round_row['terminal_claim_valid'] = row['terminal_status'] in (
                'OPTIMALITY_CERTIFIED', 'INFEASIBLE_CERTIFIED')
    row['certificate_valid_for_terminal'] = (
        row['terminal_status'] == 'OPTIMALITY_CERTIFIED'
        and row.get('certificate_verifier_status') == 'PASS')
    row.pop('result_hash', None)
    row['result_hash'] = hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True,
                   separators=(',', ':')).encode()).hexdigest()
    return row


def worker(request, binding, kernel_root, output):
    """Use the bound original runner and its persisted certificate verifier."""
    from bound_runner import load_bound_runner, configure_backend

    selected = request_for(request['instance_id'], request['method'], request['backend'])
    if request != selected:
        raise ValueError('worker request differs from the frozen subset contract')
    selection = load_selection()
    sources = {name: digest(HERE / name) for name in SOURCE_FILES}
    if sources != selection['adapter_source_sha256']:
        raise ValueError('adapter source closure differs from frozen execution identity')
    runner, bound, manifest = load_bound_runner(binding, kernel_root)
    receipt_path = runtime.core_smoke._native_path(binding)
    if digest(receipt_path) != selection['receipt_sha256']:
        raise ValueError('receipt differs from selection authority')
    if manifest['binding_sha256'] != selection['binding_sha256']:
        raise ValueError('binding differs from selection authority')
    benchmark_root = runtime.core_smoke._native_path(bound['benchmark_root'])
    manifest_path = runtime.core_smoke._native_path(bound['manifest_path'])
    if digest(manifest_path) != selection['manifest_sha256']:
        raise ValueError('benchmark manifest differs from selection authority')
    rows = json.loads(manifest_path.read_text())
    records = {r['instance_id']: r for r in rows}
    record = records[request['instance_id']]
    frozen_record = next(r for r in selection['records']
                         if r['instance_id'] == request['instance_id'])
    if record != frozen_record:
        raise ValueError('selected instance metadata changed')
    capture = configure_backend(runner, request['backend'])
    certificate_root = output / 'certificates'
    certificate_root.mkdir()
    runtime.write_json(output / 'preflight.json', manifest)
    row = runner.run_one(dict(request), records, certificate_root,
                         benchmark_root=benchmark_root,
                         execution_commit=selection['execution_identity'], planner_budget_seconds=180)
    runtime.write_json(output / 'runner_raw_result.json', row)
    row.update(qualification_scope=SCOPE, qualification_id=selection['qualification_id'],
               source_campaign_id=bound['campaign_id'], formal_campaign=False,
               search_counter_basis=capture.get('counter_basis', 'qualified SCC SearchStats'))
    row.pop('result_hash', None)
    row['result_hash'] = runner.sha256_bytes(runner.canonical_json(row).encode())
    if row.get('initial_S0') != bound['expected_initialization'][request['instance_id']][request['method']]:
        raise ValueError('initial precision differs from frozen Experiment A binding')
    schema = load_schema(json.loads(receipt_path.read_text()), request['backend'])
    runtime.write_json(output / 'schema_binding.json', dict(
        binding_id=schema.binding_id, source_hashes=schema.source_hashes, schemas=schema.schemas))
    schema.validate_result(row)
    transport = None
    if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
        lasso = capture.get('lasso')
        if lasso is None:
            raise ValueError('certified result lacks captured full-model lasso')
        transport = dict(concrete_lasso=runtime.lasso_payload(lasso),
                         accepting_buchi_states=sorted(capture['instance'].model.buchi.accepting))
    runtime.write_json(output / 'worker_result.json', dict(
        row=row, transport=transport, manifest=manifest,
        search_work=capture.get('search_work', []), worker_pid=__import__('os').getpid(),
        backend_configuration=dict(backend_id=capture['backend_id'],
                                   backend_sha256=capture['backend_sha256'],
                                   loop_code_preserved=capture.get('original_loop_code_preserved', True),
                                   local_code_preserved=capture.get('original_local_code_preserved', True))))


def run_isolated(request, binding, kernel_root, output):
    """Run one immutable attempt without a campaign ledger or automatic retry."""
    output = Path(output).resolve()
    if not str(output).startswith('/tmp/'):
        raise ValueError('output must be a fresh /tmp directory')
    output.mkdir(parents=True, exist_ok=False)
    runtime.write_json(output / 'request.json', request)
    outer_start = time.perf_counter_ns()
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker',
               '--request', str(output / 'request.json'), '--binding', binding,
               '--kernel-root', kernel_root, '--output', str(output)]
    with (output / 'stdout.txt').open('w') as out, (output / 'stderr.txt').open('w') as err:
        process = subprocess.Popen(command, stdout=out, stderr=err)
        killed = False
        try:
            process.wait(timeout=max(0, 195 - (time.perf_counter_ns() - outer_start) / 1e9))
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
        raise RuntimeError(f'worker failed, rc={process.returncode}; see {output}/stderr.txt')
    worker_path = output / 'worker_result.json'
    if not worker_path.exists():
        if not killed:
            raise RuntimeError(f'worker failed, rc={process.returncode}; see {output}/stderr.txt')
        receipt = json.loads(runtime.core_smoke._native_path(binding).read_text())
        # Preserve the qualified timeout vocabulary; unobserved rounds stay null.
        from bound_runner import load_bound_runner
        original, _, manifest = load_bound_runner(binding, kernel_root)
        row = original.timeout_serialization(request, 'outer_watchdog',
                                              method_start_ns=outer_start,
                                              terminal_completion_ns=time.perf_counter_ns())
        row.update(qualification_scope=SCOPE, formal_campaign=False)
        value = dict(row=row, transport=None, manifest=manifest, search_work=[])
    else:
        value = json.loads(worker_path.read_text())
    row = value['row']
    value.update(outer_start_ns=outer_start, worker_pid=process.pid,
                 worker_exitcode=process.returncode, worker_alive_after_cleanup=False)
    runtime.write_json(output / 'delivered_attempt.json', value)
    terminal_delivery(row, time.perf_counter_ns(), outer_start=outer_start, forced_timeout=killed)
    if not row['certificate_valid_for_terminal']:
        value['transport'] = None
    runtime.write_json(output / 'result.json', value)
    post_write = time.perf_counter_ns()
    if post_write >= row['method_start_ns'] + 180_000_000_000 and row['terminal_status'] != 'TIMEOUT':
        terminal_delivery(row, post_write, outer_start=outer_start)
        value['transport'] = None
        runtime.write_json(output / 'result.json', value)
    receipt = json.loads(runtime.core_smoke._native_path(binding).read_text())
    load_schema(receipt, request['backend']).validate_result(row)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not args.worker:
        raise SystemExit('use the isolated qualification driver')
    try:
        worker(json.loads(args.request.read_text()), args.binding, args.kernel_root, args.output)
        return 0
    except Exception:
        (args.output / 'error.txt').write_text(traceback.format_exc())
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
