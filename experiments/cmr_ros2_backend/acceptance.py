"""Bounded V6 default qualification; never executes the formal campaign."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from experiments.cmr_ros2_backend import backends, runner, qualification

SCOPE = 'CMR_V6_DEFAULT_ACCEPTANCE'
METHODS = ('FULL', 'AP-D', 'DEP-D')
RULE = ('Metadata only: minimum (Cartesian size, ID) A and EXT; '
        'B-D-BRANCH at the next static scale S2; C2/T3 and C3/T4 expand '
        'worlds and temporal families. Each FULL/AP-D/DEP-D, one attempt per backend.')


def selection(receipt_path):
    old = qualification.selection(receipt_path)
    receipt = json.loads(runner.adapter._native_path(receipt_path).read_bytes())
    bound = json.loads(runner.adapter._native_path(receipt['execution_binding']['path']).read_bytes())
    rows = json.loads(runner.adapter._native_path(bound['manifest_path']).read_bytes())
    choose = lambda cohort: min((r for r in rows if r['cohort'] == cohort),
                               key=lambda r: (r['nominal_cartesian_state_count'], r['instance_id']))
    records = {r['instance_id']: r for r in rows}
    chosen = [choose('A'), choose('EXT'), records['B-D-BRANCH-S2'],
              records['C2-T3'], records['C3-T4']]
    if [r['instance_id'] for r in chosen] != ['A-T1-M0-A-S-BRANCH', 'EXT-L2L-G01',
            'B-D-BRANCH-S2', 'C2-T3', 'C3-T4']:
        raise ValueError('metadata-only selection changed')
    if chosen[2]['nominal_cartesian_state_count'] != 4 * records['B-D-BRANCH-S1']['nominal_cartesian_state_count']:
        raise ValueError('B scale extension changed')
    source_cells = {(c['instance_id'], c['method']): c for c in bound['cells']}
    cells = []
    for record in chosen:
        for method in METHODS:
            name = record['instance_id']
            source = source_cells[(name, method)]
            cells.append(dict(instance_id=name, method=method, source_cell_id=source['cell_id'],
                canonical_instance_index=source['canonical_instance_index'], execution_index=source['execution_index'],
                method_order_position=source['method_order_position'],
                expected_initial_S0=bound['expected_initialization'][name][method]))
    return dict(selection_rule=RULE, records=chosen, cells=cells,
        dds_cases=[dict(instance_id='C2-T3', method='FULL', backend='ros2-v6',
                       fault=fault, expected_terminal=status)
                   for fault, status in (('none', 'OPTIMALITY_CERTIFIED'),
                                         ('late_delivery', 'TIMEOUT'),
                                         ('crash', 'INFRASTRUCTURE_FAILURE'), ('server_error', 'ERROR'))])


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    selected = selection(args.binding)
    version = backends.create_binding(args.binding)
    binding_path = args.output / 'backend_binding.json'
    runner.write(binding_path, version)
    old = backends.v6.real.load_selection()
    closure = runner.execution_sources()
    head = subprocess.check_output(['git', '-C', str(backends.ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    plan = dict(selected, schema='cmr-unified-backend-acceptance-plan-v2', scope=SCOPE,
        qualification_id='CMR_V6_DEFAULT_ACCEPTANCE_20261012', source_head=head, source_closure=closure,
        authority_receipt=str(runner.adapter._native_path(args.binding)), receipt_sha256=old['receipt_sha256'],
        original_execution_binding_sha256=old['binding_sha256'], manifest_sha256=old['manifest_sha256'],
        version_binding_path=str(binding_path), version_binding_sha256=backends.digest(binding_path),
        version_binding_id=version['binding_id'], backends=list(backends.NAMES),
        planner_budget_seconds=180, outer_watchdog_seconds=195, attempts_per_cell_backend=1,
        expected_method_workers=30, expected_dds_workers=4, formal_campaign=False,
        acceptance='original certified verdict/initial precision/exact objective and persisted certificate verifier')
    plan['execution_identity'] = head + '+cmr-unified-' + hashlib.sha256(backends.canonical(dict(
        source_closure=closure, version_binding_sha256=plan['version_binding_sha256'], cells=plan['cells'])).encode()).hexdigest()[:16]
    runner.write(args.output / 'plan.json', plan)
    runner.write(args.output / 'selection.json', selected)
    runner.write(args.output / 'frozen_inputs_before.json', qualification.frozen_inputs(plan))
    for name in closure:
        destination = args.output / 'frozen_adapter' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(backends.ROOT / name, destination)
    print(json.dumps(dict(prepared=True, workers=30, binding=version['binding_id'],
                         execution_identity=plan['execution_identity'])), flush=True)


def run(args):
    plan_path = args.output / 'plan.json'
    plan = runner.load_plan(plan_path)
    version_path = Path(plan['version_binding_path'])
    from experiments.cmr_ros2_backend import fixtures, offline_chain, lifecycle
    fixtures.run(plan_path, args.binding, args.kernel_root, args.output / 'fixtures.json')
    offline_chain.qualify(argparse.Namespace(binding=Path(args.binding), version_binding=version_path,
                                             output=args.output / 'offline_chain'))
    lifecycle.boundary_checks(plan, args.binding, args.kernel_root, args.output / 'boundaries.json')
    report = dict(schema='cmr-v6-default-acceptance-v2', status='RUNNING', plan=plan, cells=[])
    failures = []
    for cell in plan['cells']:
        directory = args.output / (cell['instance_id'] + '_' + cell['method'])
        directory.mkdir()
        item = dict(instance_id=cell['instance_id'], method=cell['method'], backends={}, status='RUNNING')
        report['cells'].append(item)
        try:
            for backend in backends.NAMES:
                request = runner.make_request(plan, cell['instance_id'], cell['method'], backend)
                value = runner.run_isolated(request, args.binding, args.kernel_root, version_path,
                                            plan_path, directory / backend)
                item['backends'][backend] = value
                print(json.dumps(dict(instance=cell['instance_id'], method=cell['method'], backend=backend,
                    status=value['row']['terminal_status'], objective=value['row']['objective'],
                    seconds=value['row']['T_total'])), flush=True)
                runner.write(args.output / 'acceptance.json', report)
            qualification.check_pair(item['backends']['reference'], item['backends']['ros2-v6'], cell['method'])
            item['certificate_replays'] = {backend: runner.replay(plan, args.binding, args.kernel_root,
                item['backends'][backend], directory / backend) for backend in backends.NAMES}
            item['status'] = 'PASSED'
        except Exception:
            item.update(status='FAILED', traceback=traceback.format_exc())
            failures.append(item['instance_id'] + '/' + item['method'])
        runner.write(args.output / 'acceptance.json', report)
    report['lifecycle'] = lifecycle.run(args, plan, args.output / 'lifecycle')
    runner.write(args.output / 'frozen_inputs_after.json', qualification.frozen_inputs(plan))
    if (runner.execution_sources() != plan['source_closure'] or
            json.loads((args.output / 'frozen_inputs_before.json').read_bytes()) !=
            json.loads((args.output / 'frozen_inputs_after.json').read_bytes())):
        failures.append('source/input changed')
    if report['lifecycle']['status'] != 'PASSED':
        failures.append('lifecycle')
    report.update(status='FAILED' if failures else 'PASSED', failures=failures,
                  formal_campaign_workers=0, provider_calls=0)
    runner.write(args.output / 'acceptance.json', report)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
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
            return 0
        return run(args)
    except Exception:
        args.output.mkdir(parents=True, exist_ok=True)
        runner.write(args.output / 'fatal_error.json', dict(status='FAILED', traceback=traceback.format_exc()))
        raise


if __name__ == '__main__':
    raise SystemExit(main())
