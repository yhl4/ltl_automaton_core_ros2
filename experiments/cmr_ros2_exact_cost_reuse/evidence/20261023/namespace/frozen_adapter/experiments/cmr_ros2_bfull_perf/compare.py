"""One fixed B/FULL triple; reuse the qualified runner and terminal contract."""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import tracemalloc
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REAL = HERE.parent / 'cmr_ros2_real'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REAL))
import runner as real
import bound_runner as binding_adapter
from verify_small import check_pair

ARMS = ('reference', 'baseline', 'optimized')
SOURCES = ('backend.py', 'fixtures.py', 'compare.py')
ID = 'ROS2-DISCRETE-PLAN-CMR-SCC-BOUND-V2'
PRIOR_ARCHIVE_SHA = '3a5788a3abaaceddf547c9cb09f375e58fe30cf7f45148cbd2ec790ccd86ca9d'


def write(path, value):
    real.runtime.write_json(path, value)


def candidate_module():
    spec = importlib.util.spec_from_file_location('cmr_bfull_optimized_backend', HERE / 'backend.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_closure():
    paths = [HERE / name for name in SOURCES]
    paths += [REAL / name for name in real.SOURCE_FILES] + [REAL / 'selection.json']
    paths += [Path(real.runtime.__file__), Path(real.runtime.core_backend.__file__),
              Path(real.runtime.core_smoke.__file__)]
    return {str(p.relative_to(ROOT)): real.digest(p) for p in paths}


def frozen_inputs():
    archive = REAL / 'evidence/20261012/raw_attempts.zip'
    if real.digest(archive) != PRIOR_ARCHIVE_SHA:
        raise ValueError('prior qualified archive changed')
    with zipfile.ZipFile(archive) as zipped:
        expected = json.loads(zipped.read('fix1/runner.json'))['before']
    observed = {name: dict(size=Path(name).stat().st_size, sha256=real.digest(name))
                for name in expected}
    if observed != expected:
        raise ValueError('qualified frozen inputs changed')
    return observed


def identity():
    from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp
    value = '|'.join((ID, real.digest(dp.__file__),
                      real.digest(real.runtime.core_backend.__file__),
                      real.digest(HERE / 'backend.py'), real.digest(HERE / 'compare.py')))
    return hashlib.sha256(value.encode()).hexdigest()


def measure(module, dp, capture, abstract, stats):
    work = dict(precision=sorted(abstract.precision), helpers=[], queue_pushes=0,
                queue_pops=0, prefix_settled=0, lower_bound_settled=0,
                suffix_settled=0, tracemalloc_enabled=tracemalloc.is_tracing(),
                deadline_ns=capture.get('deadline_ns'))
    if not work['tracemalloc_enabled']:
        raise RuntimeError('qualified runner tracemalloc must remain enabled')
    push, pop = dp.heappush, dp.heappop

    def counted_push(heap, item):
        work['queue_pushes'] += 1
        return push(heap, item)

    def counted_pop(heap):
        work['queue_pops'] += 1
        return pop(heap)

    def phase_call(phase, function, *args):
        graph = args[0]
        record = dict(phase=phase, helper=function.__name__, nodes=len(graph),
                      edges=graph.number_of_edges(), completed=False)
        started = time.perf_counter_ns()
        deadline = capture.get('deadline_ns')
        try:
            if deadline is not None and started >= deadline:
                raise TimeoutError('method deadline reached before helper')
            returned = function(*args)
            record.update(returned_len=len(returned), completed=True)
            if phase in ('prefix', 'lower_bound', 'suffix'):
                work[phase + '_settled'] += len(returned)
            if deadline is not None and time.perf_counter_ns() >= deadline:
                raise TimeoutError('method deadline reached after helper')
            return returned
        except BaseException as exc:
            record.update(completed=False, error=repr(exc))
            raise
        finally:
            record['elapsed_ns'] = time.perf_counter_ns() - started
            work['helpers'].append(record)

    dp.heappush, dp.heappop = counted_push, counted_pop
    try:
        returned = module.solve_cmr_lasso(abstract, work=work, phase_call=phase_call)
        work['completed'] = True
        for name in ('prefix_settled', 'lower_bound_settled', 'suffix_settled',
                     'queue_pushes', 'queue_pops', 'reachable_nodes',
                     'product_states_unique', 'qualifying_sccs', 'candidate_entries',
                     'exact_entry_searches', 'bound_pruned_entries'):
            setattr(stats, name, work[name])
        stats.expanded_states = sum(work[n] for n in
                                    ('prefix_settled', 'lower_bound_settled', 'suffix_settled'))
        stats.prefix_expansions = work['prefix_settled']
        stats.suffix_expansions = work['suffix_settled']
        stats.shortest_path_calls = sum(h['phase'] != 'restore' for h in work['helpers'])
        return returned
    except BaseException:
        work['completed'] = False
        raise
    finally:
        dp.heappush, dp.heappop = push, pop
        deadline = work['deadline_ns']
        work['deadline_observed_exceeded'] = deadline is not None and time.perf_counter_ns() >= deadline
        capture['search_work'].append(work)


def configure(formal, arm):
    if arm != 'optimized':
        return binding_adapter.configure_backend(formal, 'reference' if arm == 'reference' else 'ros2')
    module = candidate_module()
    from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp
    capture = dict(backend=arm, search_work=[], lasso=None, instance=None,
                   backend_id=ID, backend_sha256=identity(),
                   counter_basis='ROS2 auxiliary distance/heap work; original SCC and entry counts')
    original = formal.run_method_local

    def solve(abstract, stats=None):
        if stats is None:
            raise TypeError('qualified SearchStats required')
        return measure(module, dp, capture, abstract, stats)

    formal.BACKEND_ID, formal.BACKEND_SHA256 = ID, capture['backend_sha256']
    loop = binding_adapter._clone_function(formal._run_kernel_loop, {'solve_exact_abstract_lasso': solve})
    local = binding_adapter._clone_function(original, {'_run_kernel_loop': loop})

    def captured_local(*args, **kwargs):
        capture['instance'] = args[0] if args else kwargs['instance']
        capture['deadline_ns'] = kwargs.get('deadline_ns')
        returned = local(*args, **kwargs)
        capture['lasso'] = returned[2]
        return returned

    formal.run_method_local = captured_local
    capture.update(original_loop_code_preserved=loop.__code__ is formal._run_kernel_loop.__code__,
                   original_local_code_preserved=local.__code__ is original.__code__)
    return capture


def schema_for(receipt, arm):
    if arm != 'optimized':
        return real.load_schema(receipt, 'reference' if arm == 'reference' else 'ros2')
    frozen = real.load_schema(receipt)
    schemas = copy.deepcopy(frozen.schemas)
    for schema in schemas.values():
        schema['properties']['backend_sha256']['const'] = identity()
        schema['$id'] += ':ros2-scc-bound-v2'
    path = binding_adapter._native_path(receipt['scientific_source_refs']['validation_contract']['path'])
    validator = binding_adapter._load_module('_cmr_bfull_schema', path)

    def validate(row):
        if row['backend_id'] != ID:
            raise ValueError('optimized result backend identity mismatch')
        validator.validate(row, schemas['result'])
        for index, round_row in enumerate(row.get('rounds') or []):
            if round_row['backend_id'] != ID:
                raise ValueError('optimized round backend identity mismatch')
            validator.validate(round_row, schemas['round'], f'$/rounds/{index}')

    frozen.schemas, frozen.validate_result = schemas, validate
    frozen.binding_id = 'CMR_ROS2_SCC_BOUND_P2C_BACKEND_BINDING_V2'
    return frozen


def load_plan(path):
    plan = json.loads(path.read_text())
    if (plan['instance_id'] != 'B-D-BRANCH-S1' or plan['method'] != 'FULL'
            or plan['arms'] != list(ARMS) or plan['attempts_per_arm'] != 1
            or plan['planner_budget_seconds'] != 180 or plan['outer_watchdog_seconds'] != 195
            or plan['source_closure'] != source_closure()):
        raise ValueError('fixed B/FULL execution plan or source closure changed')
    return plan


def authority(plan, binding, kernel):
    formal, bound, manifest = binding_adapter.load_bound_runner(binding, kernel)
    selection = real.load_selection()
    if real.digest(binding_adapter._native_path(binding)) != selection['receipt_sha256']:
        raise ValueError('receipt authority mismatch')
    if manifest['binding_sha256'] != selection['binding_sha256']:
        raise ValueError('binding authority mismatch')
    manifest_path = binding_adapter._native_path(bound['manifest_path'])
    if real.digest(manifest_path) != selection['manifest_sha256']:
        raise ValueError('manifest authority mismatch')
    records = {r['instance_id']: r for r in json.loads(manifest_path.read_text())}
    if records[plan['instance_id']] != selection['records'][0]:
        raise ValueError('B instance metadata mismatch')
    return formal, bound, manifest, records


def worker(args):
    plan = load_plan(args.output.parent / 'plan.json')
    request = json.loads(args.request.read_text())
    arm = request['arm']
    if arm not in ARMS or request != request_for(plan, arm):
        raise ValueError('worker request outside fixed triple')
    formal, bound, manifest, records = authority(plan, args.binding, args.kernel_root)
    capture = configure(formal, arm)
    certs = args.output / 'certificates'
    certs.mkdir()
    write(args.output / 'preflight.json', manifest)
    row = formal.run_one(request, records, certs,
                         benchmark_root=binding_adapter._native_path(bound['benchmark_root']),
                         execution_commit=plan['execution_identity'], planner_budget_seconds=180)
    write(args.output / 'runner_raw_result.json', row)
    if row.get('initial_S0') != bound['expected_initialization'][plan['instance_id']]['FULL']:
        raise ValueError('initial precision mismatch')
    row.update(qualification_scope=real.SCOPE, experiment_scope=plan['scope'], formal_campaign=False,
               search_counter_basis=capture['counter_basis'])
    row.pop('result_hash', None)
    row['result_hash'] = formal.sha256_bytes(formal.canonical_json(row).encode())
    receipt = json.loads(binding_adapter._native_path(args.binding).read_text())
    schema = schema_for(receipt, arm)
    write(args.output / 'schema_binding.json', dict(binding_id=schema.binding_id,
          source_hashes=schema.source_hashes, schemas=schema.schemas))
    schema.validate_result(row)
    transport = None
    if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
        if capture['lasso'] is None:
            raise ValueError('certified row lacks full-model lasso')
        transport = dict(concrete_lasso=real.runtime.lasso_payload(capture['lasso']),
                         accepting_buchi_states=sorted(capture['instance'].model.buchi.accepting))
    write(args.output / 'worker_result.json', dict(row=row, transport=transport,
          search_work=capture['search_work'], worker_pid=os.getpid(),
          backend_configuration={k: capture.get(k, True) for k in
          ('backend_id', 'backend_sha256', 'original_loop_code_preserved', 'original_local_code_preserved')}))


def request_for(plan, arm):
    request = real.request_for(plan['instance_id'], 'FULL', 'reference' if arm == 'reference' else 'ros2')
    request.update(arm=arm, qualification_id=plan['qualification_id'])
    return request


def isolated(args, plan, arm):
    output = args.output / arm
    output.mkdir(exist_ok=False)
    request = request_for(plan, arm)
    write(output / 'request.json', request)
    start = time.perf_counter_ns()
    command = [sys.executable, '-B', str(HERE / 'compare.py'), '--worker', '--request',
               str(output / 'request.json'), '--binding', args.binding, '--kernel-root',
               args.kernel_root, '--output', str(output)]
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
        raise RuntimeError(f'{arm} worker failed: {output}/stderr.txt')
    delivered = output / 'worker_result.json'
    if delivered.exists():
        value = json.loads(delivered.read_text())
    elif killed:
        formal, _, _, _ = authority(plan, args.binding, args.kernel_root)
        configure(formal, arm)
        value = dict(row=formal.timeout_serialization(request, 'outer_watchdog',
                     method_start_ns=start, terminal_completion_ns=time.perf_counter_ns()),
                     transport=None, search_work=[])
    else:
        raise RuntimeError('worker exited without a result')
    value.update(worker_pid=process.pid, worker_exitcode=process.returncode,
                 worker_alive_after_cleanup=process.poll() is None, outer_start_ns=start)
    write(output / 'delivered_attempt.json', value)
    real.terminal_delivery(value['row'], time.perf_counter_ns(), outer_start=start, forced_timeout=killed)
    if not value['row']['certificate_valid_for_terminal']:
        value['transport'] = None
    write(output / 'result.json', value)
    end = time.perf_counter_ns()
    if end >= value['row']['method_start_ns'] + 180_000_000_000 and value['row']['terminal_status'] != 'TIMEOUT':
        real.terminal_delivery(value['row'], end, outer_start=start)
        value['transport'] = None
        write(output / 'result.json', value)
    receipt = json.loads(binding_adapter._native_path(args.binding).read_text())
    schema_for(receipt, arm).validate_result(value['row'])
    return value


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / 'frozen_inputs_before.json', frozen_inputs())
    closure = source_closure()
    head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    plan = dict(schema='cmr-bfull-perf-plan-v1', scope='SINGLE_INSTANCE_PERFORMANCE_REGRESSION',
                qualification_id='CMR_BFULL_SCC_BOUND_20261012', instance_id='B-D-BRANCH-S1',
                method='FULL', arms=list(ARMS), attempts_per_arm=1, formal_campaign=False,
                planner_budget_seconds=180, outer_watchdog_seconds=195, source_head=head,
                source_closure=closure, acceptance='same certified verdict and exact Fraction objective; original persisted-certificate replay',
                execution_identity=head + '+cmr-bfull-' + hashlib.sha256(
                    json.dumps(closure, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16])
    write(args.output / 'plan.json', plan)
    for name in closure:
        dest = args.output / 'frozen_adapter' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    _, _, manifest, _ = authority(plan, args.binding, args.kernel_root)
    write(args.output / 'preflight.json', manifest)
    print(json.dumps(dict(prepared=True, execution_identity=plan['execution_identity'])), flush=True)


def replay(args, plan, value, directory):
    formal, bound, _, _ = authority(plan, args.binding, args.kernel_root)
    row = value['row']
    cert = directory / 'certificates' / row['certificate_path']
    if real.digest(cert) != row['certificate_hash']:
        raise ValueError('persisted certificate bytes mismatch')
    result = formal.verify_certificate_file(cert, row['certificate_hash'],
        binding_adapter._native_path(bound['benchmark_root']),
        binding_adapter._native_path(bound['manifest_path']), plan['execution_identity'],
        formal.EXECUTION_CONTRACT_COMMIT, formal.BENCHMARK_COMMIT)
    if result['status'] != 'PASS':
        raise ValueError('independent persisted certificate replay failed')
    return result


def run(args):
    plan = load_plan(args.output / 'plan.json')
    fixture = args.output / 'fixtures.json'
    if not fixture.exists() or json.loads(fixture.read_text())['status'] != 'PASSED':
        raise ValueError('deterministic fixtures must pass before real-instance execution')
    report = dict(schema='cmr-bfull-perf-comparison-v1', status='RUNNING', plan=plan, arms={})
    try:
        for arm in ARMS:
            value = isolated(args, plan, arm)
            report['arms'][arm] = value
            write(args.output / 'comparison.json', report)
            print(json.dumps(dict(arm=arm, status=value['row']['terminal_status'],
                                  T_total=value['row']['T_total'], T_search=value['row']['T_search'])), flush=True)
        check_pair(report['arms']['reference'], report['arms']['baseline'], 'FULL')
        check_pair(report['arms']['reference'], report['arms']['optimized'], 'FULL')
        report['certificate_replays'] = {arm: replay(args, plan, report['arms'][arm], args.output / arm)
                                         for arm in ARMS}
        if source_closure() != plan['source_closure']:
            raise ValueError('source bytes changed during execution')
        write(args.output / 'frozen_inputs_after.json', frozen_inputs())
        report['status'] = 'PASSED'
        write(args.output / 'comparison.json', report)
        return 0
    except Exception:
        report.update(status='FAILED', traceback=traceback.format_exc())
        write(args.output / 'comparison.json', report)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not str(args.output).startswith('/tmp/'):
        raise ValueError('fresh isolated output must be under /tmp/')
    try:
        if args.prepare:
            prepare(args)
        elif args.worker:
            worker(args)
        else:
            return run(args)
        return 0
    except Exception:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'error.txt').write_text(traceback.format_exc())
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
