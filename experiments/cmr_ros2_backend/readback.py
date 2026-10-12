"""Native standard-library read-back of unified backend and DDS artifacts."""

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
from fractions import Fraction

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_product_perf.native_readback import read, digest, native, checked, check_lasso


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def check_attempt(directory, value, plan, version, receipt, source_schemas):
    checked(read(directory / 'result.json') == value, 'persisted attempt/report match')
    row = value['row']
    backend = row['backend']
    checked(backend in ('reference', 'ros2-v6'), 'explicit backend')
    checked(row['backend_id'] == version['backends'][backend]['backend_id'] and
            row['backend_sha256'] == version['backends'][backend]['backend_sha256'], 'algorithm identity')
    checked(row['version_binding_id'] == plan['version_binding_id'] and
            row['version_binding_sha256'] == plan['version_binding_sha256'], 'independent version binding')
    descriptor = dict(version['backends'][backend], backend=backend,
        version_binding_id=plan['version_binding_id'], version_binding_sha256=plan['version_binding_sha256'])
    checked(value['backend_binding'] == descriptor, 'configured backend descriptor')
    request = read(directory / 'request.json')
    checked(all(request[key] == val for key, val in descriptor.items()), 'request binding matches result')
    checked(request['execution_identity'] == row['execution_commit'] == plan['execution_identity'], 'execution identity')
    cells = [c for c in plan['cells'] if c['instance_id'] == row['instance_id'] and c['method'] == row['method']]
    checked(len(cells) == 1 and row['initial_S0'] == cells[0]['expected_initial_S0'], 'initial precision/source cell')
    checked(value['worker_exitcode'] == 0 and not value['worker_alive_after_cleanup'] and
            (directory / 'worker.rc').read_text().strip() == '0', 'worker exit/cleanup')
    checked(row['terminal_status'] in ('OPTIMALITY_CERTIFIED', 'INFEASIBLE_CERTIFIED')
            and row['right_censored'] is False and row['timing_status'] == 'UNCENSORED', 'certified uncensored result')
    checked(row['planner_budget_seconds'] == 180 and row['outer_watchdog_seconds'] == 195, 'budgets')
    checked(row['T_total'] == (row['terminal_completion_ns'] - row['method_start_ns']) / 1e9
            and row['T_total'] < 180, 'actual complete method elapsed')
    checked(row['llm_calls'] == row['experimental_llm_calls'] == row['api_key_reads'] == 0, 'no providers')
    unhashed = dict(row)
    expected = unhashed.pop('result_hash')
    checked(hashlib.sha256(canonical(unhashed).encode()).hexdigest() == expected, 'canonical result hash')
    rounds = row['rounds']
    checked(rounds and rounds[0]['S_k'] == row['initial_S0'] and row['refinement_rounds'] == len(rounds) - 1, 'complete refinement trace')
    for left, right in zip(rounds, rounds[1:]):
        checked(set(left['S_k']) < set(right['S_k']), 'strict precision growth')
    for round_row in rounds:
        checked(all(round_row[key] == val for key, val in descriptor.items()), 'round version identity')
        checked(round_row['terminal_claim_valid'] and round_row['semantic_contract_id'] == 'INITIAL_LABEL_V1', 'round semantic claims')
    if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
        checked(row['certificate_valid_for_terminal'] and row['certificate_verifier_status'] == 'PASS', 'feasible certificate authority')
        cert_path = directory / 'certificates' / row['certificate_path']
        checked(digest(cert_path) == row['certificate_hash'], 'persisted certificate bytes')
        cert = read(cert_path)
        checked(cert['execution_commit'] == plan['execution_identity'] and cert['gamma'] == '10', 'certificate version/objective')
        checked(cert['instance_id'] == row['instance_id'] and cert['method'] == row['method'], 'certificate cell')
        check_lasso(cert['full_model_lasso'], cert['accepting_buchi_states'], row['objective'], cert)
        check_lasso(value['transport']['concrete_lasso'], value['transport']['accepting_buchi_states'], row['objective'])
    else:
        checked(row['objective'] is None and value['transport'] is None
                and not row['certificate_valid_for_terminal'], 'infeasible has no executable witness')
        checked(row['infeasibility_certificate_type'] == 'REDUCED_PRODUCT_EXACT_EMPTY', 'original exact-empty proof')
        checked(row['certificate_verifier_status'] == row['certificate_hash'] == row['certificate_path'] == 'NOT_AVAILABLE',
                'no invented infeasible lasso certificate')
    manifest = read(directory / 'preflight.json')
    checked(len(manifest['source_checks']) == 40 and manifest['bound_runner']['other_ast_unchanged'], 'science preflight')
    for source in manifest['source_checks']:
        checked(source['match'] and source['actual_sha256'] == source['expected_sha256'] == digest(native(source['path'])), 'science source bytes')
    for key, count in (('imports', 8), ('runner_imports', 6)):
        checked(len(manifest[key]) == count, 'import count')
        for source in manifest[key].values():
            checked(source['__file__'] == source['expected_path'] and source['sha256'] ==
                    source['expected_sha256'] == digest(native(source['__file__'])), 'actual import bytes')
    config = value['backend_configuration']
    checked(all(config[k] for k in ('original_loop_code_preserved', 'original_local_code_preserved',
                                    'original_builder_global_preserved')), 'original runner code/global identities')
    checked(config['backend_id'] == row['backend_id'] and config['backend_sha256'] == row['backend_sha256'], 'actual backend configuration')
    schema_binding = read(directory / 'schema_binding.json')
    normalized = copy.deepcopy(schema_binding['schemas'])
    for kind, schema in normalized.items():
        checked(schema['properties']['backend_sha256']['const'] == row['backend_sha256'], 'schema backend identity')
        source = receipt['scientific_source_refs'][kind + '_schema']
        checked(schema_binding['source_hashes'][kind] == source['sha256'] == digest(native(source['path'])), 'original schema bytes')
        schema.pop('$id')
        schema['properties']['backend_sha256'].pop('const')
    if source_schemas is None:
        source_schemas = normalized
    checked(normalized == source_schemas, 'only schema ID/backend SHA specialized')
    if backend == 'ros2-v6':
        checked(len(value['build_work']) == len(value['search_work']) == len(rounds), 'one rebuild/search per round')
        for build, search, round_row in zip(value['build_work'], value['search_work'], rounds):
            checked(build['completed'] and build['full_ts_rebuild_calls'] == 1 and
                    build['precision'] == search['precision'] == round_row['S_k'], 'full TS rebuilt every round')
            checked(build['buchi_queries'] == build['cache_hits'] + build['cache_misses'] and
                    build['cache_entries'] == build['cache_misses'], 'local cache accounting')
            for field, original in (('product_states', 'product_unique_states'), ('product_edges', 'product_unique_edges'),
                                    ('reachable_ts_states', 'reduced_ts_states'), ('reduced_ts_edges', 'reduced_ts_edges')):
                checked(build[field] == round_row[original], 'original graph accounting')
            checked(search['tracemalloc_enabled'] and search['completed'] and
                    not search['deadline_observed_exceeded'], 'qualified search instrumentation')
            checked(search['candidate_entries'] == search['exact_entry_searches'] + search['bound_pruned_entries'], 'entry accounting')
            targets = search.get('target_searches', [])
            checked(len(targets) == search['exact_entry_searches'], 'target search count')
            for target in targets:
                checked(target['target_settled'] and target['stop_reason'] == 'target_finalized'
                        and Fraction(target['target_distance']) >= 0, 'exact target stopping')
            for phase in ('prefix', 'lower_bound', 'suffix'):
                checked(search[phase + '_settled'] == sum(h['returned_len'] for h in search['helpers'] if h['phase'] == phase), 'helper work accounting')
    return row, source_schemas


def main(output):
    plan, version = (read(output / name) for name in ('plan.json', 'backend_binding.json'))
    original = read(output / 'qualification.json')
    correction_path = output / 'validation_correction.json'
    correction = read(correction_path) if correction_path.exists() else None
    report = read(output / 'qualified_replay.json') if correction else original
    checked(report['status'] == 'PASSED' and report['plan'] == plan, 'completed qualification')
    checked(plan['scope'] == 'CMR_UNIFIED_BACKEND_SUBSET_QUALIFICATION' and plan['formal_campaign'] is False,
            'separate small qualification scope')
    checked(plan['expected_method_workers'] == 24 and len(plan['cells']) == 12
            and plan['backends'] == ['reference', 'ros2-v6'], 'fixed 12 paired cells')
    checked(plan['expected_dds_workers'] == 2 and plan['attempts_per_cell_backend'] == 1, 'fixed attempts/DDS')
    checked(plan['version_binding_sha256'] == digest(output / 'backend_binding.json')
            and plan['version_binding_id'] == version['binding_id'], 'plan independent binding bytes')
    body = dict(version)
    body.pop('binding_id')
    checked(version['binding_id'] == 'CMR_UNIFIED_BACKENDS_V1-' + hashlib.sha256(canonical(body).encode()).hexdigest()[:16], 'version canonical identity')
    for name, expected in plan['source_closure'].items():
        frozen = output / 'frozen_adapter' / name
        checked(digest(frozen) == expected, 'executed source bytes retained')
        if correction and name == 'experiments/cmr_ros2_backend/dds.py':
            checked(original['status'] == 'FAILED' and
                    correction['original_qualification_sha256'] == digest(output / 'qualification.json') and
                    correction['original_dds_report_sha256'] == digest(output / 'dds/dds_report.json'), 'original failed records retained')
            checked(correction['status'] == 'PASSED' and correction['validation_replay_only'] and
                    correction['additional_solver_workers'] == correction['additional_dds_runs'] == 0,
                    'assertion correction only; no scientific retry')
            checked(correction['original_dds_sha256'] == expected and
                    correction['corrected_dds_sha256'] == digest(ROOT / name), 'corrected validator bytes')
            def outside_validator(path):
                tree = ast.parse(path.read_bytes())
                tree.body = [node for node in tree.body if not
                    (isinstance(node, ast.FunctionDef) and node.name == '_validate_case')]
                return ast.dump(tree, include_attributes=False)
            checked(outside_validator(frozen) == outside_validator(ROOT / name), 'transport/worker code AST unchanged')
        else:
            checked(digest(ROOT / name) == expected, 'unchanged execution code')
    for name, expected in version['source_closure'].items():
        checked(plan['source_closure'][name] == expected, 'binding source subset')
    before, after = [read(output / ('frozen_inputs_' + when + '.json')) for when in ('before', 'after')]
    checked(before == after and len(before) == 58, '58 immutable inputs')
    for name, expected in before.items():
        path = native(name)
        checked(path.stat().st_size == expected['size'] and digest(path) == expected['sha256'], 'frozen input bytes')
    fixtures = read(output / 'fixtures.json')
    checked(fixtures['status'] == 'PASSED' and fixtures['check_count'] == 16 and
            fixtures['planner_calls'] == fixtures['dds_calls'] == 0, 'offline interface fixtures')
    checked(fixtures['execution_identity'] == plan['execution_identity'] and
            fixtures['version_binding_sha256'] == plan['version_binding_sha256'], 'fixtures tied to binding')
    receipt = read(native(plan['authority_receipt']))
    checked(digest(native(plan['authority_receipt'])) == plan['receipt_sha256'], 'authority receipt')
    checked([(c['instance_id'], c['method']) for c in report['cells']] ==
            [(c['instance_id'], c['method']) for c in plan['cells']], 'fixed complete coverage')
    source_schemas, summary, certificates, infeasible, total_rounds = None, [], 0, 0, 0
    for cell, item in zip(plan['cells'], report['cells']):
        checked(item['status'] == 'PASSED', 'paired cell accepted')
        rows, entry = {}, dict(instance_id=cell['instance_id'], method=cell['method'], backends={})
        for backend in plan['backends']:
            value = item['backends'][backend]
            directory = output / (cell['instance_id'] + '_' + cell['method']) / backend
            row, source_schemas = check_attempt(directory, value, plan, version, receipt, source_schemas)
            rows[backend] = row
            replay = item['certificate_replays'][backend]
            if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
                checked(replay['status'] == 'PASS', 'independent persisted certificate replay')
                certificates += 1
            else:
                checked(replay['status'] == 'NOT_APPLICABLE', 'infeasible replay stays unavailable')
                infeasible += 1
            total_rounds += len(row['rounds'])
            entry['backends'][backend] = {k: row[k] for k in ('terminal_status', 'objective', 'T_total', 'T_product', 'T_search', 'refinement_rounds')}
            entry['backends'][backend]['build_rounds'] = len(row['rounds'])
        checked(rows['reference']['terminal_status'] == rows['ros2-v6']['terminal_status']
                and rows['reference']['initial_S0'] == rows['ros2-v6']['initial_S0']
                and rows['reference']['objective'] == rows['ros2-v6']['objective'], 'paired exact verdict/objective')
        if rows['reference']['terminal_status'] == 'INFEASIBLE_CERTIFIED':
            checked(all(rows['reference'][key] == rows['ros2-v6'][key] for key in (
                'infeasibility_certificate_type', 'infeasibility_proof_basis', 'infeasibility_precision',
                'lower_precision_infeasibility')), 'paired original exact-empty proof metadata')
        summary.append(entry)
    dds = report['dds']
    checked(dds['status'] == 'PASSED' and len(dds['cases']) == 2 and dds['domain_id'] == 219, 'actual DDS cases')
    dds_summary = []
    for case, selected in zip(dds['cases'], plan['dds_cases']):
        directory = output / 'dds' / selected['request_id']
        value = read(directory / 'cmr_attempt/result.json')
        row, source_schemas = check_attempt(directory / 'cmr_attempt', value, plan, version, receipt, source_schemas)
        checked(case['status'] == 'PASSED' and case['server_rc'] == case['driver_rc'] == 0, 'DDS process exits')
        checked(len({case['server_pid'], case['driver_pid'], value['worker_pid']}) == 3, 'three real processes')
        checked(case['request']['backend'] == 'ros2-v6' and case['request']['request_id'] == selected['request_id'], 'actual DDS selected backend')
        checked(all(case['request'][key] == value['backend_binding'][key] for key in value['backend_binding']), 'DDS envelope identity')
        received = case['driver']['result']
        checked(received['backend_binding'] == value['backend_binding'] and
                all(received[key] == val for key, val in row.items()), 'DDS actual result/worker row identity')
        checked(received['execution_commit'] == plan['execution_identity'] and received['population'] == plan['scope'], 'DDS execution scope')
        checked(received['terminal_status'] == row['terminal_status'] == selected['expected_terminal'], 'DDS terminal verdict')
        names = [event['event'] for event in case['server']['events']]
        order = ('request_received', 'cmr_solver_started', 'cmr_solver_completed', 'result_published')
        checked(all(names.count(name) == 1 for name in order) and
                [names.index(name) for name in order] == sorted(names.index(name) for name in order), 'real DDS starts worker after request')
        driver = case['driver']
        checked(driver['module_identity_match'], 'DDS actual execution imports')
        for name, path in driver['module_resolved_paths'].items():
            checked(digest(native(path)) == driver['module_sha256'][name], 'DDS imported bytes')
        if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
            certificates += 1
            checked(case['certificate_replay']['status'] == 'PASS', 'DDS independent certificate replay')
            lasso = received['concrete_lasso']
            check_lasso(lasso, received['accepting_buchi_states'], row['objective'])
            edges = lasso['prefix_edges'] + lasso['suffix_edges']
            actions = [edge['action'] for edge in edges]
            targets = [[str(x) for x in edge['target'][0]] for edge in edges]
            checked(driver['commands'] == actions and actions, 'complete prefix/one suffix execution')
            for field in ('completion_count', 'observer_feedback_count', 'abstraction_feedback_count', 'ts_state_receive_count'):
                checked(driver[field] == len(edges), 'DDS execution counts')
            for field in ('observed_ts_states', 'observer_feedback_states', 'abstraction_feedback_states'):
                checked(driver[field] == targets, 'independent TS feedback')
            terminal = [e for e in driver['events'] if e['event'] == 'observation_received' and not e['has_next_action']]
            checked(terminal and terminal[-1]['step'] == len(edges), 'terminal DDS step')
            events = driver['events']
            dispatches = [e for e in events if e['event'] == 'dispatch']
            wrong = [e for e in events if e['event'] == 'wrong_generation_published']
            checked(len(wrong) == 1 and wrong[0]['generation'] == 0 and
                    wrong[0]['accepted_generation'] == 1 and wrong[0]['invalid_generation'] and
                    events.index(dispatches[0]) < events.index(wrong[0]), 'old-generation injection after real authority')
            observations = [e for e in events if e['event'] == 'observation_received']
            stale = [e for e in observations if e['generation'] == 0]
            current = [e for e in observations if e['generation'] == 1]
            checked(len(stale) == 1 and stale[0]['step'] == 0 and
                    len(observations) == len(stale) + len(current) and
                    [e['step'] for e in current] == list(range(len(edges) + 1)) and
                    [e['execution_step_seq'] for e in dispatches] == list(range(len(edges))),
                    'stale ignored without duplicate dispatch')
            steps = len(edges)
        else:
            infeasible += 1
            checked(case['certificate_replay']['status'] == 'NOT_APPLICABLE', 'no fabricated infeasible replay')
            checked(not driver['commands'] and all(driver[k] == 0 for k in (
                'completion_count', 'observer_feedback_count', 'abstraction_feedback_count', 'ts_state_receive_count')), 'infeasible zero dispatch')
            checked(received.get('concrete_lasso') is None and 'snapshot_served' not in names, 'infeasible no snapshot')
            steps = 0
        total_rounds += len(row['rounds'])
        dds_summary.append(dict(instance_id=row['instance_id'], method=row['method'],
            terminal_status=row['terminal_status'], objective=row['objective'], executed_steps=steps))
    checked(certificates == 19 and infeasible == 7, '19 feasible certificates and seven exact-empty outcomes')
    result = dict(schema='cmr-unified-native-readback-v1', status='PASSED', planner_imported=False,
        version_binding_id=plan['version_binding_id'], version_binding_sha256=plan['version_binding_sha256'],
        cells=summary, dds=dds_summary, method_workers=24, dds_workers=2,
        independent_feasible_certificate_replays=certificates, exact_empty_outcomes=infeasible,
        total_build_rounds=total_rounds, frozen_inputs=58, offline_checks=16,
        original_driver_rc=1 if correction else 0, original_qualification_status=original['status'],
        validation_only_correction=correction)
    (output / 'native_readback.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
