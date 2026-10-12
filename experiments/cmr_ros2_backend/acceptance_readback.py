"""Standard-library readback of bounded V2 qualification evidence."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_backend.readback import check_attempt, canonical
from experiments.cmr_ros2_product_perf.native_readback import read, digest, native, checked

PROOFS = ('infeasibility_certificate_type', 'infeasibility_proof_basis',
          'infeasibility_precision', 'lower_precision_infeasibility')


def failure_row(row, transport, expected):
    checked(row['terminal_status'] == expected and row['objective'] is None and transport is None,
            'failure verdict/no executable witness')
    checked(row['certificate_valid_for_terminal'] is False and row['certificate_verifier_status'] == 'NOT_AVAILABLE', 'failure certificate authority')
    checked(all(row.get(k) is None for k in PROOFS), 'failure has no exact-empty claim')
    checked(all(r['terminal_claim_valid'] is False and all(r.get(k) is None for k in PROOFS)
                for r in row.get('rounds') or []), 'failure round claims invalidated')
    checked(row['right_censored'] is (expected == 'TIMEOUT'), 'failure censoring')


def main(output, recovery):
    plan, version, report = (read(output / name) for name in ('plan.json', 'backend_binding.json', 'acceptance.json'))
    aggregate = read(recovery / 'qualified_recovery.json')
    recovered = read(recovery / 'recovery.json')
    new_plan, new_version = (read(recovery / name) for name in ('plan.json', 'backend_binding.json'))
    checked(report['status'] == 'FAILED' and report['failures'] == ['lifecycle'], 'original harness failure preserved')
    checked(aggregate['status'] == recovered['status'] == 'PASSED' and not aggregate['successful_modes_rerun'], 'only failed modes recovered')
    checked(report['formal_campaign_workers'] == report['provider_calls'] == aggregate['formal_campaign_workers'] == aggregate['provider_calls'] == 0, 'no campaign/provider')
    checked(plan['formal_campaign'] is False and len(plan['cells']) == 15 and len(plan['records']) == 5, 'fixed small selection')
    checked(version['qualification_only'] is True and version['formal_campaign'] is False, 'campaign disabled')
    checked(digest(output / 'backend_binding.json') == plan['version_binding_sha256'], 'version-file hash')
    content = dict(version)
    binding_id = content.pop('binding_id')
    checked(binding_id == 'CMR_UNIFIED_BACKENDS_V2-' + hashlib.sha256(canonical(content).encode()).hexdigest()[:16], 'canonical V2 identity')
    checked(version['source_closure'].items() <= plan['source_closure'].items(), 'complete bound source closure')
    for name, expected in plan['source_closure'].items():
        checked(digest(output / 'frozen_adapter' / name) == expected, 'original executed source snapshot')
        checked(digest(recovery / 'frozen_adapter' / name) == digest(ROOT / name) == new_plan['source_closure'][name], 'current source snapshot')
    changed = [name for name in plan['source_closure'] if plan['source_closure'][name] != new_plan['source_closure'][name]]
    checked(changed == ['experiments/cmr_ros2_backend/lifecycle.py'], 'only fault harness changed')
    relative = changed[0]
    expected_guards = [ast.dump(ast.parse("if str(HERE / '" + name + "') not in command:\n    return REAL_POPEN(command, **kwargs)").body[0], include_attributes=False) for name in ('runner.py', 'dds.py')]
    class Guards(ast.NodeTransformer):
        count = 0
        def visit_FunctionDef(self, node):
            self.generic_visit(node)
            if node.name == 'popen':
                retained = []
                for part in node.body:
                    if ast.dump(part, include_attributes=False) in expected_guards:
                        self.count += 1
                    else:
                        retained.append(part)
                node.body = retained
            return node
    guards = Guards()
    corrected = guards.visit(ast.parse((ROOT / relative).read_text(encoding='utf-8')))
    checked(guards.count == 2 and ast.dump(corrected, include_attributes=False) == ast.dump(ast.parse((output / 'frozen_adapter' / relative).read_text(encoding='utf-8')), include_attributes=False), 'exact two routing guards and otherwise identical AST')
    checked(version['backends'] == new_version['backends'], 'same exact algorithms under independent versions')
    checked(digest(recovery / 'backend_binding.json') == new_plan['version_binding_sha256'], 'new version hash')
    current_content = dict(new_version)
    current_id = current_content.pop('binding_id')
    checked(current_id == 'CMR_UNIFIED_BACKENDS_V2-' + hashlib.sha256(canonical(current_content).encode()).hexdigest()[:16], 'new canonical version ID')
    checked(read(output / 'frozen_inputs_before.json') == read(output / 'frozen_inputs_after.json'), 'frozen inputs unchanged')
    for path, expected in read(output / 'frozen_inputs_after.json').items():
        checked(digest(native(path)) == expected['sha256'], 'original frozen authority/model bytes')
    receipt = read(native(plan['authority_receipt']))
    schemas = None
    rounds = feasible = empty = 0
    timings = []
    checked(len(report['cells']) == 15, 'all selected cells recorded')
    for item, cell in zip(report['cells'], plan['cells']):
        checked(item['status'] == 'PASSED' and item['instance_id'] == cell['instance_id'] and item['method'] == cell['method'], 'fixed selected order')
        rows = []
        for backend in ('reference', 'ros2-v6'):
            directory = output / (cell['instance_id'] + '_' + cell['method']) / backend
            row, schemas = check_attempt(directory, item['backends'][backend], plan, version, receipt, schemas)
            rows.append(row)
            rounds += len(row['rounds'])
            if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
                checked(item['certificate_replays'][backend]['status'] == 'PASS', 'independent feasible certificate replay')
                feasible += 1
            else:
                checked(item['certificate_replays'][backend]['status'] == 'NOT_APPLICABLE', 'original exact-empty rule')
                empty += 1
        checked(rows[0]['terminal_status'] == rows[1]['terminal_status'] and rows[0]['objective'] == rows[1]['objective'] and rows[0]['initial_S0'] == rows[1]['initial_S0'], 'paired verdict/objective/initial precision')
        timings.append(dict(instance=cell['instance_id'], method=cell['method'], objective=rows[0]['objective'],
                            reference=rows[0]['T_total'], v6=rows[1]['T_total'], rounds=[len(r['rounds']) for r in rows]))
    offline = read(output / 'offline_chain/offline_chain_evidence.json')
    checked(offline['status'] == 'PASSED' and offline['schedule']['cells'] == offline['schedule']['unique_keys'] == 510, 'offline 510 schedule')
    checked(offline['planner_calls'] == offline['provider_calls'] == offline['dds_calls'] == 0, 'offline zero calls')
    checked(offline['analysis']['validation_only'] and offline['analysis']['rows'] == 510, 'synthetic analysis only')
    checked(all(offline['guards'].values()), 'offline rejection checks')
    checked(all(offline['result_chain']['negative_checks'].values()), 'offline ledger corruption checks')
    gate = read(output / 'formal_gate_r3/formal_gate_evidence.json')
    checked(gate['status'] == 'PASSED' and gate['selected_rows_checked'] == 3
            and gate['r2_checked_wrapper'] == gate['r2_restore_receipts'] == 'PASSED', 'original formal gate replay')
    checked(gate['formal_gate_source']['unchanged'] and gate['r2_checked_original_code_object'], 'unchanged original gate code')
    for tree in (output / 'formal_gate_r3/replay').iterdir():
        metadata = read(tree / 'gate_metadata.json')
        final = tree / 'completed' / metadata['cell_id']
        for name, expected in read(final / 'commit_manifest.json').items():
            checked(digest(final / name) == expected, 'real atomic publication bytes')
        body, record = read(final / 'ledger_entry.json'), read(final / 'pilot_record.json')
        raw = lambda value: (canonical(value) + '\n').encode()
        checked(hashlib.sha256(raw(body)).hexdigest() == record['ledger_commit_sha256'], 'real ledger receipt hash')
        checked(hashlib.sha256(raw({k:v for k,v in record.items() if k != 'ledger_commit_sha256'})).hexdigest() == body['record_payload_sha256'], 'real ledger payload hash')
    boundaries = read(output / 'boundaries.json')
    checked(boundaries['status'] == 'PASSED' and boundaries['simulated_clock'] and boundaries['solver_calls'] == 0, 'deadline boundary predicates')
    life = read(output / 'lifecycle/lifecycle.json')
    checked(life['status'] == 'FAILED' and len(life['cases']) == 9 and len(life['dds_cases']) == 4, 'original full matrix/failure retained')
    direct = {c['mode']: (c, output) for c in life['cases'] if c['status'] == 'PASSED'}
    dds_cases = {c['mode']: (c, output) for c in life['dds_cases'] if c['status'] == 'PASSED'}
    for c in recovered['cases']:
        (direct if c['kind'] == 'direct' else dds_cases)[c['mode']] = (c, recovery)
    checked(len(direct) == 9 and len(dds_cases) == 4, 'all original paths qualified after narrow recovery')
    for item, base in direct.values():
        checked(item['status'] == 'PASSED', 'fault path passed')
        value = item['result']
        row = value['row']
        directory = base / 'lifecycle' / item['mode']
        checked(read(directory / 'result.json')['row'] == row, 'persisted failure row')
        expected = 'TIMEOUT' if item['mode'].startswith('late_') or item['mode'] == 'watchdog' else 'INFRASTRUCTURE_FAILURE'
        failure_row(row, value['transport'], expected)
        checked(not value['worker_alive_after_cleanup'], 'fault worker reaped')
        checked(row['T_total'] == (row['terminal_completion_ns'] - row['method_start_ns']) / 1e9, 'observed or simulated elapsed')
        checked(row['planner_budget_seconds'] == 180 and row['outer_watchdog_seconds'] == 195, 'failure budgets unchanged')
        if item['mode'] == 'watchdog':
            checked(value['fault_qualification']['actual_wall_seconds'] >= 195 and value['worker_exitcode'] == -9 and row['T_total'] >= 195, 'actual 195-second kill and measured censoring')
        elif item['mode'].startswith('late_'):
            checked(value['fault_qualification']['simulated_clock'] and value['fault_qualification']['injected_offset_ns'] == 180_000_000_000, 'deadline injection explicitly labelled')
    for item, base in dds_cases.values():
        checked(item['status'] == 'PASSED', 'actual DDS case passed')
        artifact = item['artifact']
        result = artifact['driver']['result']
        checked(artifact['server_rc'] == artifact['driver_rc'] == 0 and artifact['domain_id'] == 219, 'DDS nodes exited')
        if item['mode'] == 'none':
            directory = output / 'lifecycle/dds_none/cmr_attempt'
            value = read(directory / 'result.json')
            _, schemas = check_attempt(directory, value, plan, version, receipt, schemas)
            checked(artifact['certificate_replay']['status'] == 'PASS', 'DDS independent certificate replay')
            feasible += 1
            rounds += len(value['row']['rounds'])
            checked(artifact['driver']['execution_counts_match'], 'actual DDS complete feedback')
        else:
            failure_row(result, result.get('concrete_lasso'), {'late_delivery': 'TIMEOUT', 'crash': 'INFRASTRUCTURE_FAILURE', 'server_error': 'ERROR'}[item['mode']])
            driver = artifact['driver']
            checked(not driver['commands'] and driver['completion_count'] == driver['observer_feedback_count'] == driver['abstraction_feedback_count'] == 0, 'no dispatch or completion after failure')
            checked(not any(e['event'] == 'snapshot_served' for e in artifact['server']['events']), 'failure has no execution snapshot')
    result = dict(status='PASSED', paired_cells=15, method_workers=30, build_rounds=rounds,
                  feasible_certificates_replayed=feasible, exact_empty_outcomes=empty,
                  lifecycle_paths=9, dds_cases=4, boundary_checks=boundaries['count'],
                  offline_cells=510, formal_campaign_workers=0, provider_calls=0,
                  frozen_inputs=len(read(output / 'frozen_inputs_after.json')), timings=timings)
    result.update(original_status=report['status'], narrow_recovery_status=recovered['status'],
                  successful_method_workers_repeated=0, recovery_cases=len(recovered['cases']),
                  formal_gate_rows=3)
    (recovery / 'acceptance_native_readback.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'timings'}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recovery', type=Path, required=True)
    args = parser.parse_args()
    main(args.output, args.recovery)
