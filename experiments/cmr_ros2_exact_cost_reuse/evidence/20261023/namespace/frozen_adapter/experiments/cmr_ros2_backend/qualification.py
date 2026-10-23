"""Freeze a small static selection, qualify both backends, then actual DDS."""

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
from experiments.cmr_ros2_backend import backends, runner

write, adapter = runner.write, runner.adapter
OLD = ('B-D-BRANCH-S1', 'C1-T1', 'D3-1')
RULE = ('Keep B/FULL, C/AP-D, D/FULL anchors; add minimum (nominal_cartesian_state_count, '
        'instance_id) B excluding old B, C with different temporal_family, and statically '
        'INFEASIBLE D. New instances each FULL/AP-D/DEP-D. No outcome-based selection.')


def selection(receipt_path):
    receipt_path = adapter._native_path(receipt_path)
    original = backends.v6.real.load_selection()
    if backends.digest(receipt_path) != original['receipt_sha256']:
        raise ValueError('receipt authority mismatch')
    receipt = json.loads(receipt_path.read_bytes())
    bound_path = adapter._native_path(receipt['execution_binding']['path'])
    if backends.digest(bound_path) != original['binding_sha256']:
        raise ValueError('original execution binding mismatch')
    bound = json.loads(bound_path.read_bytes())
    manifest = adapter._native_path(bound['manifest_path'])
    if backends.digest(manifest) != original['manifest_sha256']:
        raise ValueError('manifest authority mismatch')
    rows = json.loads(manifest.read_bytes())
    if len(rows) != 170:
        raise ValueError('original Core170 manifest changed')
    records = {r['instance_id']: r for r in rows}
    for old in original['records']:
        if records[old['instance_id']] != old:
            raise ValueError('prior selected metadata changed')
    choose = lambda candidates: min(candidates, key=lambda r: (r['nominal_cartesian_state_count'], r['instance_id']))
    new = [choose([r for r in rows if r['cohort'] == 'B' and r['instance_id'] != OLD[0]]),
           choose([r for r in rows if r['cohort'] == 'C' and
                   r['temporal_family'] != records[OLD[1]]['temporal_family']]),
           choose([r for r in rows if r['cohort'] == 'D' and r['feasibility_class'] == 'INFEASIBLE'])]
    if [r['instance_id'] for r in new] != ['B-D-CHAIN-S1', 'C1-T2', 'D1-1']:
        raise ValueError('expected metadata-only extension changed')
    source_cells = {(c['instance_id'], c['method']): c for c in bound['cells']}
    pairs = [(OLD[0], 'FULL'), (OLD[1], 'AP-D'), (OLD[2], 'FULL')]
    pairs += [(r['instance_id'], method) for r in new for method in ('FULL', 'AP-D', 'DEP-D')]
    cells = []
    for instance_id, method in pairs:
        source = source_cells[(instance_id, method)]
        cells.append(dict(instance_id=instance_id, method=method,
            source_cell_id=source['cell_id'], canonical_instance_index=source['canonical_instance_index'],
            execution_index=source['execution_index'], method_order_position=source['method_order_position'],
            expected_initial_S0=bound['expected_initialization'][instance_id][method]))
    return dict(selection_rule=RULE, records=[records[name] for name in OLD] + new, cells=cells,
        dds_cases=[dict(request_id='cmr-unified-v6-C1-T1-AP-D', instance_id='C1-T1', method='AP-D',
                        backend='ros2-v6', expected_terminal='OPTIMALITY_CERTIFIED'),
                   dict(request_id='cmr-unified-v6-D1-1-FULL', instance_id='D1-1', method='FULL',
                        backend='ros2-v6', expected_terminal='INFEASIBLE_CERTIFIED')])


def frozen_inputs(plan):
    values = backends.v6.foundation.frozen_inputs()
    receipt = json.loads(adapter._native_path(plan['authority_receipt']).read_bytes())
    bound = json.loads(adapter._native_path(receipt['execution_binding']['path']).read_bytes())
    for record in plan['records']:
        path = adapter._native_path(bound['benchmark_root']) / record['path']
        if backends.digest(path) != record['instance_sha256']:
            raise ValueError('selected instance hash changed')
        values[str(path)] = dict(size=path.stat().st_size, sha256=backends.digest(path))
    return values


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    selected = selection(args.binding)
    version = backends.create_binding(args.binding)
    args.version_binding = args.output / 'backend_binding.json'
    write(args.version_binding, version)
    head = subprocess.check_output(['git', '-C', str(backends.ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    closure = runner.execution_sources()
    authority = backends.v6.real.load_selection()
    plan = dict(selected, schema='cmr-unified-backend-plan-v1', scope=runner.SCOPE,
        qualification_id='CMR_UNIFIED_V6_20261012', source_head=head, source_closure=closure,
        authority_receipt=str(adapter._native_path(args.binding)), receipt_sha256=authority['receipt_sha256'],
        original_execution_binding_sha256=authority['binding_sha256'], manifest_sha256=authority['manifest_sha256'],
        version_binding_path=str(args.version_binding), version_binding_sha256=backends.digest(args.version_binding),
        version_binding_id=version['binding_id'], backends=list(backends.NAMES),
        planner_budget_seconds=180, outer_watchdog_seconds=195, attempts_per_cell_backend=1,
        expected_method_workers=24, expected_dds_workers=2, formal_campaign=False,
        acceptance='original certified verdict/initial precision/exact objective, original exact-empty fields, original persisted certificate verifier')
    plan['execution_identity'] = head + '+cmr-unified-' + hashlib.sha256(backends.canonical(
        dict(source_closure=closure, version_binding_sha256=plan['version_binding_sha256'], cells=plan['cells'])).encode()).hexdigest()[:16]
    write(args.output / 'plan.json', plan)
    write(args.output / 'selection.json', selected)
    write(args.output / 'frozen_inputs_before.json', frozen_inputs(plan))
    for name in closure:
        destination = args.output / 'frozen_adapter' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(backends.ROOT / name, destination)
    _, _, manifest, _ = runner.authority(plan, args.binding, args.kernel_root)
    write(args.output / 'preflight.json', manifest)
    print(json.dumps(dict(prepared=True, cells=len(plan['cells']), workers=24, dds_workers=2,
                        version_binding_id=version['binding_id'], execution_identity=plan['execution_identity'])), flush=True)


def check_pair(left, right, method):
    backends.v6.foundation.check_pair(left, right, method)
    if left['row']['terminal_status'] == 'INFEASIBLE_CERTIFIED':
        fields = ('infeasibility_certificate_type', 'infeasibility_proof_basis',
                  'infeasibility_precision', 'lower_precision_infeasibility')
        if any(left['row'][key] != right['row'][key] for key in fields):
            raise ValueError('original/V6 exact-empty proof metadata differs')
        for value in (left, right):
            if value['row']['objective'] is not None or value['transport'] is not None:
                raise ValueError('infeasible row has objective or executable lasso')


def run(args):
    args.plan = args.output / 'plan.json'
    plan = runner.load_plan(args.plan)
    args.version_binding = Path(plan['version_binding_path'])
    report = dict(schema='cmr-unified-backend-qualification-v1', status='RUNNING', plan=plan, cells=[])
    try:
        for cell in plan['cells']:
            item = dict(instance_id=cell['instance_id'], method=cell['method'], backends={}, status='RUNNING')
            report['cells'].append(item)
            directory = args.output / (cell['instance_id'] + '_' + cell['method'])
            directory.mkdir()
            for backend in backends.NAMES:
                request = runner.make_request(plan, cell['instance_id'], cell['method'], backend)
                value = runner.run_isolated(request, args.binding, args.kernel_root,
                    args.version_binding, args.plan, directory / backend)
                item['backends'][backend] = value
                write(args.output / 'qualification.json', report)
                row = value['row']
                print(json.dumps(dict(instance_id=cell['instance_id'], method=cell['method'], backend=backend,
                    status=row['terminal_status'], objective=row['objective'], T_total=row['T_total'],
                    rounds=len(row.get('rounds') or []))), flush=True)
            check_pair(item['backends']['reference'], item['backends']['ros2-v6'], cell['method'])
            item['certificate_replays'] = {backend: runner.replay(plan, args.binding, args.kernel_root,
                item['backends'][backend], directory / backend) for backend in backends.NAMES}
            item['status'] = 'PASSED'
            write(args.output / 'qualification.json', report)
        from experiments.cmr_ros2_backend.dds import run_dds
        report['dds'] = run_dds(args, plan, args.output / 'dds')
        write(args.output / 'qualification.json', report)
        if report['dds']['status'] != 'PASSED':
            raise ValueError('V6 DDS qualification failed; preserve both attempts')
        for case in report['dds']['cases']:
            directory = args.output / 'dds' / case['request']['request_id'] / 'cmr_attempt'
            value = json.loads((directory / 'result.json').read_bytes())
            case['certificate_replay'] = runner.replay(plan, args.binding, args.kernel_root, value, directory)
            paired = next(item for item in report['cells'] if item['instance_id'] == case['request']['instance_id']
                          and item['method'] == case['request']['method'])
            check_pair(paired['backends']['reference'], value, case['request']['method'])
        if runner.execution_sources() != plan['source_closure']:
            raise ValueError('execution source bytes changed')
        write(args.output / 'frozen_inputs_after.json', frozen_inputs(plan))
        report['status'] = 'PASSED'
        write(args.output / 'qualification.json', report)
        return 0
    except Exception:
        report.update(status='FAILED', traceback=traceback.format_exc())
        write(args.output / 'qualification.json', report)
        raise


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
        (args.output / 'error.txt').write_text(traceback.format_exc())
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
