"""Fixed nine-cell reference / V5 / Product V6 isolated qualification."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
from types import SimpleNamespace
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_bfull_target import compare as previous
from experiments.cmr_ros2_bfull_target import backend as search_backend
from experiments.cmr_ros2_bfull_perf import compare as foundation

ID = 'ROS2-DISCRETE-PLAN-CMR-PRODUCT-V6'
SCOPE = 'FIXED_SUBSET_PRODUCT_REFINEMENT_QUALIFICATION'
ARMS = foundation.ARMS
real, adapter, write = foundation.real, foundation.binding_adapter, foundation.write
spec = importlib.util.spec_from_file_location('_cmr_product_driver', Path(foundation.__file__))
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
_schema_for = driver.schema_for


def source_closure():
    closure = previous.source_closure()
    archive = previous.HERE / 'evidence/20261012/raw_attempts.zip'
    if real.digest(archive) != '815e1dabe2087d7bc1ee75b8079f3e2310643eb1547ede1cfec054be9a6e56f2':
        raise ValueError('qualified V5 archive changed')
    with zipfile.ZipFile(archive) as zipped:
        expected = json.loads(zipped.read('plan.json'))['source_closure']
    if closure != expected:
        raise ValueError('qualified V5 source bytes changed')
    closure.update({str((HERE / name).relative_to(ROOT)): real.digest(HERE / name)
                    for name in ('builder.py', 'fixtures.py', 'compare.py')})
    return closure


def identity():
    # V5 binds its complete search lineage and the unchanged production helper.
    original_sha = 'c964ad7c6cf8f80d9d0831f6955ebe651efa7701a3ccf1304d332b421efa8dfc'
    values = [ID, previous.identity(), original_sha, real.digest(HERE / 'builder.py'),
              real.digest(HERE / 'compare.py')]
    return hashlib.sha256('|'.join(values).encode()).hexdigest()


def configure(formal, arm):
    if arm in ('baseline', 'reference'):
        original_before = formal.run_method_local
        capture = (previous.configure(formal, 'optimized') if arm == 'baseline'
                   else adapter.configure_backend(formal, 'reference'))
        capture['original_builder_global_preserved'] = (formal.build_optimistic_abstraction is
            formal._p2f_grouped.build_optimistic_abstraction)
        if arm == 'reference':
            original = capture['original_run_method_local']
            capture['original_loop_code_preserved'] = (
                original.__globals__['_run_kernel_loop'].__code__ is formal._run_kernel_loop.__code__)
            capture['original_local_code_preserved'] = (
                original.__code__ is original_before.__code__)
        return capture
    if arm != 'optimized':
        raise ValueError('unknown arm')
    from experiments.cmr_ros2_product_perf import builder
    from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp
    capture = dict(backend_id=ID, backend_sha256=identity(), search_work=[],
                   build_work=[], lasso=None, instance=None,
                   counter_basis='unchanged V5 search; within-build Buchi cache queries/hits/misses')
    original = formal.run_method_local

    def build(model, precision, *, timing=None):
        work = {}
        try:
            return builder.build_optimistic_abstraction(model, precision, timing=timing, work=work)
        finally:
            capture['build_work'].append(work)

    def solve(abstract, stats=None):
        if stats is None:
            raise TypeError('qualified SearchStats required')
        return foundation.measure(search_backend, dp, capture, abstract, stats)

    formal.BACKEND_ID, formal.BACKEND_SHA256 = ID, capture['backend_sha256']
    loop = adapter._clone_function(formal._run_kernel_loop,
        {'solve_exact_abstract_lasso': solve, 'build_optimistic_abstraction': build})
    local = adapter._clone_function(original, {'_run_kernel_loop': loop})

    def captured_local(*args, **kwargs):
        capture['instance'] = args[0] if args else kwargs['instance']
        capture['deadline_ns'] = kwargs.get('deadline_ns')
        returned = local(*args, **kwargs)
        capture['lasso'] = returned[2]
        return returned

    formal.run_method_local = captured_local
    capture.update(original_loop_code_preserved=loop.__code__ is formal._run_kernel_loop.__code__,
                   original_local_code_preserved=local.__code__ is original.__code__,
                   original_builder_global_preserved=(formal.build_optimistic_abstraction is
                       formal._p2f_grouped.build_optimistic_abstraction))
    return capture


def schema_for(receipt, arm):
    if arm == 'baseline':
        return previous.schema_for(receipt, 'optimized')
    result = _schema_for(receipt, arm)
    if arm == 'optimized':
        result.binding_id = 'CMR_ROS2_PRODUCT_P2C_BACKEND_BINDING_V6'
        for schema in result.schemas.values():
            schema['$id'] = schema['$id'].replace(':ros2-scc-bound-v2', ':ros2-product-v6')
    return result


def load_plan(path):
    plan = json.loads(path.read_text())
    selection = real.load_selection()
    if (plan['cells'] != selection['cells'] or plan['arms'] != list(ARMS)
            or plan['attempts_per_arm'] != 1 or plan['formal_campaign'] is not False
            or plan['planner_budget_seconds'] != 180 or plan['outer_watchdog_seconds'] != 195
            or plan['source_closure'] != source_closure()
            or plan['baseline_backend'] != previous.ID or plan['candidate_backend'] != ID):
        raise ValueError('fixed nine-cell plan or source bytes changed')
    if 'instance_id' in plan:
        found = [c for c in plan['cells'] if c['instance_id'] == plan['instance_id']
                 and c['method'] == plan['method']]
        if len(found) != 1:
            raise ValueError('cell outside frozen selection')
    return plan


def authority(plan, binding, kernel):
    formal, bound, manifest = adapter.load_bound_runner(binding, kernel)
    selection = real.load_selection()
    if real.digest(adapter._native_path(binding)) != selection['receipt_sha256']:
        raise ValueError('receipt authority mismatch')
    if manifest['binding_sha256'] != selection['binding_sha256']:
        raise ValueError('binding authority mismatch')
    manifest_path = adapter._native_path(bound['manifest_path'])
    if real.digest(manifest_path) != selection['manifest_sha256']:
        raise ValueError('manifest authority mismatch')
    records = {r['instance_id']: r for r in json.loads(manifest_path.read_text())}
    for record in selection['records']:
        if records[record['instance_id']] != record:
            raise ValueError('selected instance metadata mismatch')
    return formal, bound, manifest, records


def request_for(plan, arm):
    request = real.request_for(plan['instance_id'], plan['method'],
                               'reference' if arm == 'reference' else 'ros2')
    request.update(arm=arm, qualification_id=plan['qualification_id'])
    return request


def worker(args):
    plan = load_plan(args.output.parent / 'plan.json')
    request = json.loads(args.request.read_text())
    arm = request['arm']
    if arm not in ARMS or request != request_for(plan, arm):
        raise ValueError('worker request outside frozen cells')
    formal, bound, manifest, records = authority(plan, args.binding, args.kernel_root)
    capture = configure(formal, arm)
    certs = args.output / 'certificates'
    certs.mkdir()
    write(args.output / 'preflight.json', manifest)
    row = formal.run_one(request, records, certs,
                         benchmark_root=adapter._native_path(bound['benchmark_root']),
                         execution_commit=plan['execution_identity'], planner_budget_seconds=180)
    write(args.output / 'runner_raw_result.json', row)
    if row.get('initial_S0') != bound['expected_initialization'][plan['instance_id']][plan['method']]:
        raise ValueError('initial precision mismatch')
    row.update(qualification_scope=real.SCOPE, experiment_scope=SCOPE, formal_campaign=False,
               search_counter_basis=capture['counter_basis'])
    row.pop('result_hash', None)
    row['result_hash'] = formal.sha256_bytes(formal.canonical_json(row).encode())
    schema = schema_for(json.loads(adapter._native_path(args.binding).read_text()), arm)
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
          search_work=capture['search_work'], build_work=capture.get('build_work', []),
          worker_pid=os.getpid(), backend_configuration={k: capture.get(k, True) for k in
          ('backend_id', 'backend_sha256', 'original_loop_code_preserved',
           'original_local_code_preserved', 'original_builder_global_preserved')}))


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output / 'frozen_inputs_before.json', foundation.frozen_inputs())
    closure = source_closure()
    head = foundation.subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    plan = dict(schema='cmr-product-perf-plan-v1', scope=SCOPE,
                qualification_id='CMR_PRODUCT_REFINEMENT_20261012', cells=real.load_selection()['cells'],
                arms=list(ARMS), attempts_per_arm=1, expected_workers=27, formal_campaign=False,
                planner_budget_seconds=180, outer_watchdog_seconds=195,
                baseline_backend=previous.ID, candidate_backend=ID,
                authorized_changes=['deque FIFO', 'pure Buchi successors cached inside each Product build'],
                full_ts_rebuild_every_round=True, source_head=head, source_closure=closure,
                acceptance='same certified verdict and exact Fraction objective; original persisted-certificate replay',
                execution_identity=head + '+cmr-product-' + hashlib.sha256(
                    json.dumps(closure, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16])
    write(args.output / 'plan.json', plan)
    for name in closure:
        dest = args.output / 'frozen_adapter' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    _, _, manifest, _ = authority(plan, args.binding, args.kernel_root)
    write(args.output / 'preflight.json', manifest)
    # Freeze every cell before the fixtures or any method outcome is observed.
    for cell in plan['cells']:
        directory = args.output / (cell['instance_id'] + '_' + cell['method'])
        directory.mkdir()
        write(directory / 'plan.json', dict(plan, instance_id=cell['instance_id'], method=cell['method']))
    print(json.dumps(dict(prepared=True, workers=27, execution_identity=plan['execution_identity'])), flush=True)


def run(args):
    plan = load_plan(args.output / 'plan.json')
    if json.loads((args.output / 'fixtures.json').read_text())['status'] != 'PASSED':
        raise ValueError('deterministic Product checks must pass before real execution')
    report = dict(schema='cmr-product-perf-comparison-v1', status='RUNNING', plan=plan, cells=[])
    try:
        for cell in plan['cells']:
            directory = args.output / (cell['instance_id'] + '_' + cell['method'])
            cell_plan = load_plan(directory / 'plan.json')
            if cell_plan != dict(plan, instance_id=cell['instance_id'], method=cell['method']):
                raise ValueError('cell plan differs from frozen master')
            item = dict(instance_id=cell['instance_id'], method=cell['method'], arms={}, status='RUNNING')
            report['cells'].append(item)
            local_args = SimpleNamespace(**dict(vars(args), output=directory))
            for arm in ARMS:
                item['arms'][arm] = driver.isolated(local_args, cell_plan, arm)
                write(args.output / 'comparison.json', report)
                row = item['arms'][arm]['row']
                print(json.dumps(dict(instance_id=cell['instance_id'], method=cell['method'], arm=arm,
                      status=row['terminal_status'], T_total=row['T_total'], T_product=row['T_product'],
                      rounds=len(row.get('rounds') or []))), flush=True)
            for arm in ('baseline', 'optimized'):
                foundation.check_pair(item['arms']['reference'], item['arms'][arm], cell['method'])
            # Product-only changes must preserve the entire deterministic V5
            # refinement/search trace, apart from backend metadata and time.
            normalized = []
            for arm in ('baseline', 'optimized'):
                normalized.append([{k: v for k, v in row.items() if k not in
                    ('backend_id', 'backend_sha256', 'timings', 'phase_intervals_ns')}
                    for row in item['arms'][arm]['row']['rounds']])
            if normalized[0] != normalized[1]:
                raise ValueError('Product optimization changed the V5 scientific round trace')
            item['certificate_replays'] = {arm: driver.replay(local_args, cell_plan,
                item['arms'][arm], directory / arm) for arm in ARMS}
            item['status'] = 'PASSED'
            write(args.output / 'comparison.json', report)
        if source_closure() != plan['source_closure']:
            raise ValueError('source bytes changed during execution')
        write(args.output / 'frozen_inputs_after.json', foundation.frozen_inputs())
        report['status'] = 'PASSED'
        write(args.output / 'comparison.json', report)
        return 0
    except Exception:
        report.update(status='FAILED', traceback=traceback.format_exc())
        write(args.output / 'comparison.json', report)
        raise


# Only this independent module is substituted. Its isolation/delivery/replay
# functions and the qualified scientific runner code remain unchanged.
driver.HERE, driver.ID = HERE, ID
driver.source_closure, driver.identity = source_closure, identity
driver.configure, driver.schema_for = configure, schema_for
driver.load_plan, driver.authority, driver.request_for = load_plan, authority, request_for
driver.worker, driver.prepare, driver.run = worker, prepare, run

if __name__ == '__main__':
    raise SystemExit(driver.main())
