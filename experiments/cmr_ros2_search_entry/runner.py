"""Three fixed cells: original solver, unchanged V6 entry, and candidate V7.

Reuse the qualified unified runner's worker lifecycle and delivery code. Each
process validates its own source boundary. Never dispatch the formal campaign.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_backend import backends as old_backends
from experiments.cmr_ros2_backend import runner as old_runner, acceptance, qualification
from experiments.cmr_ros2_search_entry import backend
from experiments.cmr_ros2_search_entry.entry import VerifiedEntry

v6 = old_backends.v6
adapter, write = old_runner.adapter, old_runner.write
ID = 'ROS2-DISCRETE-PLAN-CMR-EXACT-INTEGER-V7'
NAMES = ('reference', 'ros2-v6', 'ros2-v7')
TARGETS = (('A-T1-M0-A-S-BRANCH', 'FULL'),
           ('B-D-BRANCH-S2', 'FULL'), ('C3-T4', 'AP-D'))
SCOPE = 'CMR_SEARCH_ENTRY_ISOLATED_QUALIFICATION'
canonical = old_backends.canonical
digest = old_backends.digest


def identity():
    return hashlib.sha256('|'.join((ID, v6.identity(),
        digest(HERE / 'backend.py'), digest(HERE / 'entry.py'),
        digest(HERE / 'runner.py'))).encode()).hexdigest()


def source_closure():
    # Bind search and its DDS/execution boundary under one fresh version.
    closure = old_runner.execution_sources()
    for name in ('backend.py', 'entry.py', 'entry_fixtures.py', 'fixtures.py', 'runner.py', 'dds.py'):
        closure[str((HERE / name).relative_to(ROOT))] = digest(HERE / name)
    paths = (
        'ltl_automaton_execution/ltl_automaton_execution/accepted_run_resolver.py',
        'ltl_automaton_execution/ltl_automaton_execution/execution.py',
        'ltl_automaton_execution/ltl_automaton_execution/execution_node.py',
        'ltl_automaton_execution/ltl_automaton_execution/fake_runtime.py',
        'ltl_automaton_execution/ltl_automaton_execution/models.py',
        'ltl_automaton_execution/ltl_automaton_execution/observation.py',
        'ltl_automaton_planner/ltl_automaton_planner/planning_graph_snapshot.py',
    )
    messages = ('AcceptedRunSnapshot', 'PlanningExecutionObservation',
                'TransitionSystemStateStamped', 'TransitionSystemState',
                'ProductGraphNode', 'ProductGraphEdge', 'PlanningGraphMetadata',
                'PlanningGraphSnapshot', 'BuchiGraphNode', 'BuchiGraphEdge')
    for path in paths + tuple('ltl_automaton_msgs/msg/' + name + '.msg'
                              for name in messages):
        closure[path] = digest(ROOT / path)
    return closure


def implementations():
    return dict(reference={'backend_id': 'ECC-P1-SCC-INITIAL_LABEL_V1',
        'backend_sha256': '3f0c3775febe070699e9e353a5183aad24b569303547f77e1ea07d0e853ed1a3'},
        **{'ros2-v6': {'backend_id': v6.ID, 'backend_sha256': v6.identity()},
           'ros2-v7': {'backend_id': ID, 'backend_sha256': identity()}})


def load_plan(path):
    plan = json.loads(Path(path).read_bytes())
    current = old_runner.load_plan(plan['current_plan_path'])
    selected = [c for c in current['cells']
                if (c['instance_id'], c['method']) in TARGETS]
    if (plan['schema'] != 'cmr-search-entry-plan-v1' or plan['scope'] != SCOPE
            or plan['cells'] != selected or plan['records'] != current['records']
            or plan['backends'] != list(NAMES) or plan['expected_method_workers'] != 9
            or plan['attempts_per_cell_backend'] != 1 or plan['formal_campaign'] is not False
            or plan['planner_budget_seconds'] != 180 or plan['outer_watchdog_seconds'] != 195
            or plan['source_closure'] != source_closure()):
        raise ValueError('fixed three-cell scope/source/budgets changed')
    content = dict(plan)
    execution = content.pop('execution_identity')
    if execution != plan['source_head'] + '+cmr-search-entry-' + hashlib.sha256(
            canonical(content).encode()).hexdigest()[:16]:
        raise ValueError('execution identity mismatch')
    binding = json.loads(Path(plan['version_binding_path']).read_bytes())
    if binding['backends'] != implementations():
        raise ValueError('advertised backend implementation mismatch')
    return plan


def schema_for(receipt, name):
    if name != 'ros2-v7':
        return old_backends.schema_for(receipt, name)
    # Schema differs only in implementation identity, as in the V2--V6 lineage.
    schema_fn = adapter._clone_function(v6.foundation.schema_for,
        {'ID': ID, 'identity': identity})
    result = schema_fn(receipt, 'optimized')
    result.binding_id = 'CMR_ROS2_SEARCH_ENTRY_P2C_BACKEND_BINDING_V7'
    return result


def configure(formal, name, descriptor):
    if name == 'ros2-v7':
        fn = adapter._clone_function(v6.configure,
            {'ID': ID, 'identity': identity, 'search_backend': backend})
        capture = fn(formal, 'optimized')
    else:
        capture = v6.configure(formal, 'reference' if name == 'reference' else 'optimized')
    if any(capture[key] != descriptor[key] for key in ('backend_id', 'backend_sha256')):
        raise ValueError('configured implementation identity mismatch')
    capture['backend_binding'] = descriptor
    return capture


def request_for(plan, entry, cell, name):
    return dict(cell, **entry.describe(name), qualification_id=plan['qualification_id'],
        population=plan['scope'], formal_campaign=False,
        execution_identity=plan['execution_identity'],
        planner_budget_seconds=180, outer_watchdog_seconds=195)


def worker(args):
    started = time.perf_counter_ns()
    plan = load_plan(args.plan)
    entry = VerifiedEntry(plan, source_closure, schema_for)
    request = json.loads(args.request.read_bytes())
    entry.validate_request(request)
    if request['backend'] != args.backend:
        raise ValueError('worker backend mismatch')
    formal, bound, manifest, records = old_runner.authority(plan, args.binding, args.kernel_root)
    capture = configure(formal, args.backend, entry.describe(args.backend))
    ready = time.perf_counter_ns()
    certs = args.output / 'certificates'
    certs.mkdir()
    write(args.output / 'preflight.json', manifest)
    # Original run_one, input preflight and loader remain within their budget.
    row = formal.run_one(request, records, certs,
        benchmark_root=adapter._native_path(bound['benchmark_root']),
        execution_commit=plan['execution_identity'], planner_budget_seconds=180)
    write(args.output / 'runner_raw_result.json', row)
    if row['initial_S0'] != bound['expected_initialization'][request['instance_id']][request['method']]:
        raise ValueError('initial precision mismatch')
    descriptor = capture['backend_binding']
    row.update(qualification_scope=plan['scope'], formal_campaign=False,
               search_counter_basis=capture['counter_basis'], **descriptor)
    for round_row in row.get('rounds') or []:
        round_row.update(**descriptor)
    row.pop('result_hash', None)
    row['result_hash'] = formal.sha256_bytes(formal.canonical_json(row).encode())
    schema = entry.schema(args.backend, json.loads(adapter._native_path(args.binding).read_bytes()))
    write(args.output / 'schema_binding.json', dict(binding_id=schema.binding_id,
        source_hashes=schema.source_hashes, schemas=schema.schemas))
    schema.validate_result(row)
    transport = None
    if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
        if capture['lasso'] is None:
            raise ValueError('certified result lacks concrete lasso')
        transport = dict(concrete_lasso=v6.real.runtime.lasso_payload(capture['lasso']),
            accepting_buchi_states=sorted(capture['instance'].model.buchi.accepting))
    entry.release_check()
    write(args.output / 'worker_result.json', dict(row=row, transport=transport,
        search_work=capture['search_work'], build_work=capture.get('build_work', []),
        backend_binding=descriptor, worker_pid=os.getpid(),
        entry_metrics=dict(entry.metrics, worker_pre_method_seconds=(ready-started)/1e9),
        backend_configuration={k: capture[k] for k in ('backend_id', 'backend_sha256',
            'original_loop_code_preserved', 'original_local_code_preserved',
            'original_builder_global_preserved')}))


def candidate_isolated(args, plan, cell, output):
    entry = VerifiedEntry(plan, source_closure, schema_for)
    request = request_for(plan, entry, cell, 'ros2-v7')
    def describe(path, name):
        if Path(path).resolve() != Path(plan['version_binding_path']).resolve():
            raise ValueError('binding path mismatch')
        return entry.describe(name)
    proxy = SimpleNamespace(**dict(vars(old_backends), describe=describe,
        schema_for=lambda receipt, name: entry.schema(name, receipt),
        configure=lambda formal, name, path:
            configure(formal, name, describe(path, name))))
    def guarded_write(path, value):
        # Check the source boundary before authorizing the delivered result.
        if Path(path).name == 'result.json':
            entry.release_check()
        write(path, value)
    # Preserve the exact lifecycle, failure serializer, provenance validation,
    # result deadline predicates and process-group cleanup of qualified V6.
    isolated = adapter._clone_function(old_runner.run_isolated, {
        'HERE': HERE, 'load_plan': lambda path: plan,
        'validate_request': lambda p, r, b: entry.validate_request(r),
        'backends': proxy, 'write': guarded_write})
    started = time.perf_counter_ns()
    value = isolated(request, args.binding, args.kernel_root,
        Path(plan['version_binding_path']), args.output / 'plan.json', output)
    value['parent_entry_metrics'] = dict(entry.metrics)
    value['harness_wall_seconds'] = (time.perf_counter_ns()-started)/1e9
    # Final values are already rechecked; this metadata adds no scientific phase.
    write(output / 'entry_metrics.json', dict(worker=value.get('entry_metrics'),
        parent=value['parent_entry_metrics'], harness_wall_seconds=value['harness_wall_seconds']))
    return value


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    acceptance.prepare(SimpleNamespace(**dict(vars(args), output=args.output / 'current')))
    current = old_runner.load_plan(args.output / 'current/plan.json')
    content = dict(schema='cmr-search-entry-binding-v1', source_closure=source_closure(),
        semantic_contract_id='INITIAL_LABEL_V1', objective='prefix_cost + 10*suffix_cost',
        nonempty_accepting_suffix=True, full_ts_rebuild_every_round=True,
        planner_budget_seconds=180, outer_watchdog_seconds=195, formal_campaign=False,
        backends=implementations(), **{k: current[k] for k in
            ('receipt_sha256', 'original_execution_binding_sha256', 'manifest_sha256')})
    content['binding_id'] = 'CMR_SEARCH_ENTRY_V1-' + hashlib.sha256(canonical(content).encode()).hexdigest()[:16]
    version_path = args.output / 'backend_binding.json'
    write(version_path, content)
    plan = dict(schema='cmr-search-entry-plan-v1', scope=SCOPE,
        qualification_id='CMR_SEARCH_ENTRY_AUDIT_REPAIR_20261013', source_head=current['source_head'],
        current_plan_path=str(args.output / 'current/plan.json'),
        source_closure=source_closure(), records=current['records'],
        cells=[c for c in current['cells'] if (c['instance_id'], c['method']) in TARGETS],
        selection_rule='Fixed A minimum/FULL, B branch scale S2/FULL, C3-T4/AP-D; no candidate outcomes used.',
        backends=list(NAMES), expected_method_workers=9, attempts_per_cell_backend=1,
        planner_budget_seconds=180, outer_watchdog_seconds=195, formal_campaign=False,
        version_binding_path=str(version_path), version_binding_sha256=digest(version_path),
        version_binding_id=content['binding_id'],
        **{k: current[k] for k in ('authority_receipt', 'receipt_sha256',
            'original_execution_binding_sha256', 'manifest_sha256')})
    plan['continued_controls'] = []
    if args.continue_from is not None:
        previous = args.continue_from.resolve()
        old_report = json.loads((previous / 'comparison.json').read_bytes())
        # Narrow continuation of the two completed controls from the failed
        # first harness; never carry or relabel the rejected candidate result.
        if (len(old_report['cells']) != 1 or
                old_report['cells'][0]['instance_id'] != TARGETS[0][0] or
                set(old_report['cells'][0]['arms']) != {'reference', 'ros2-v6'} or
                not (previous / 'fatal_error.json').exists()):
            raise ValueError('continuation is not the recorded two-control failure')
        pair = old_report['cells'][0]['arms']
        qualification.check_pair(pair['reference'], pair['ros2-v6'], 'FULL')
        for name in ('reference', 'ros2-v6'):
            directory = previous / (TARGETS[0][0]+'_FULL') / name
            result = json.loads((directory / 'result.json').read_bytes())
            if (result['row'] != pair[name]['row'] or
                    result['row']['execution_commit'] != current['execution_identity'] or
                    result['backend_binding'] != old_backends.describe(current['version_binding_path'], name)):
                raise ValueError('original completed control provenance changed')
            files = {str(p.relative_to(directory)): digest(p)
                     for p in directory.rglob('*') if p.is_file()}
            plan['continued_controls'].append(dict(instance_id=TARGETS[0][0], method='FULL',
                backend=name, directory=str(directory), files=files,
                harness_wall_seconds=pair[name]['harness_wall_seconds'],
                original_plan_sha256=digest(previous / 'plan.json')))
    plan['execution_identity'] = plan['source_head'] + '+cmr-search-entry-' + hashlib.sha256(canonical(plan).encode()).hexdigest()[:16]
    write(args.output / 'plan.json', plan)
    write(args.output / 'frozen_inputs_before.json', qualification.frozen_inputs(plan))
    for name in plan['source_closure']:
        destination = args.output / 'frozen_adapter' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    print(json.dumps(dict(prepared=True, workers=9, version_binding=content['binding_id'])), flush=True)


def normalized(value):
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items() if not
            (k.startswith('T_') or k.endswith('_ns') or k.endswith('_sha256') or
             'backend' in k or k in ('result_hash', 'row_hash', 'execution_commit',
             'certificate_path', 'certificate_hash', 'certificate_objective',
             'search_counter_basis', 'qualification_scope', 'population',
             'version_binding_id', 'version_binding_sha256'))}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def run(args):
    plan = load_plan(args.output / 'plan.json')
    from experiments.cmr_ros2_search_entry import fixtures, entry_fixtures
    write(args.output / 'search_fixtures.json', fixtures.run())
    write(args.output / 'entry_fixtures.json', entry_fixtures.run_fixtures())
    write(args.output / 'fixtures.json', dict(status='PASSED', execution_identity=plan['execution_identity'],
        version_binding_id=plan['version_binding_id'], version_binding_sha256=plan['version_binding_sha256']))
    # The exact unchanged unified entry handles both controls, with its own
    # original plan/version metadata. Only these three cells are dispatched.
    from experiments.cmr_ros2_backend import fixtures as old_fixtures
    old_plan_path = Path(plan['current_plan_path'])
    old_fixtures.run(old_plan_path, args.binding, args.kernel_root, old_plan_path.parent / 'fixtures.json')
    current = old_runner.load_plan(old_plan_path)
    report = dict(status='RUNNING', plan=plan, cells=[], formal_campaign_workers=0, provider_calls=0)
    write(args.output / 'comparison.json', report)
    for cell in plan['cells']:
        item = dict(instance_id=cell['instance_id'], method=cell['method'], arms={})
        report['cells'].append(item)
        directory = args.output / (cell['instance_id']+'_'+cell['method'])
        directory.mkdir()
        for name in NAMES:
            output = directory / name
            continued = [c for c in plan['continued_controls'] if
                (c['instance_id'], c['method'], c['backend']) ==
                (cell['instance_id'], cell['method'], name)]
            if continued:
                saved = continued[0]
                prior = Path(saved['directory'])
                observed = {str(p.relative_to(prior)): digest(p)
                            for p in prior.rglob('*') if p.is_file()}
                if observed != saved['files']:
                    raise ValueError('original control bytes changed')
                shutil.copytree(prior, output)
                value = json.loads((output / 'result.json').read_bytes())
                value['harness_wall_seconds'] = saved['harness_wall_seconds']
                value['continuation'] = dict(original_directory=str(prior),
                    original_plan_sha256=saved['original_plan_sha256'], new_worker_dispatched=False)
            elif name == 'ros2-v7':
                value = candidate_isolated(args, plan, cell, output)
            else:
                request = old_runner.make_request(current, cell['instance_id'], cell['method'], name)
                started = time.perf_counter_ns()
                value = old_runner.run_isolated(request, args.binding, args.kernel_root,
                    Path(current['version_binding_path']), old_plan_path, output)
                value['harness_wall_seconds'] = (time.perf_counter_ns()-started)/1e9
            item['arms'][name] = value
            write(args.output / 'comparison.json', report)
            row = value['row']
            print(json.dumps(dict(instance=cell['instance_id'], method=cell['method'], backend=name,
                status=row['terminal_status'], total=row['T_total'], search=row['T_search'],
                other=row['T_other'], harness_wall=value['harness_wall_seconds'])), flush=True)
        for name in NAMES[1:]:
            qualification.check_pair(item['arms']['reference'], item['arms'][name], cell['method'])
        left, right = item['arms']['ros2-v6'], item['arms']['ros2-v7']
        if normalized(left['row']['rounds']) != normalized(right['row']['rounds']):
            raise AssertionError('V6/V7 scientific refinement trace changed')
        if left['transport'] != right['transport']:
            raise AssertionError('V6/V7 concrete lasso/witness changed')
        item['certificate_replays'] = {name: old_runner.replay(
            plan if name == 'ros2-v7' else current, args.binding, args.kernel_root,
            item['arms'][name], directory / name) for name in NAMES}
        item['status'] = 'PASSED'
        write(args.output / 'comparison.json', report)
    after = qualification.frozen_inputs(plan)
    write(args.output / 'frozen_inputs_after.json', after)
    if source_closure() != plan['source_closure'] or after != json.loads((args.output / 'frozen_inputs_before.json').read_bytes()):
        raise ValueError('source or frozen input changed')
    report['status'] = 'PASSED'
    write(args.output / 'comparison.json', report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--backend', choices=NAMES)
    parser.add_argument('--request', type=Path)
    parser.add_argument('--version-binding', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--continue-from', type=Path)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not str(args.output).startswith('/tmp/'):
        raise ValueError('fresh output must be under /tmp/')
    try:
        if args.prepare:
            prepare(args)
        elif args.worker:
            worker(args)
        else:
            run(args)
    except Exception:
        args.output.mkdir(parents=True, exist_ok=True)
        write(args.output / 'fatal_error.json', dict(status='FAILED', traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    main()
