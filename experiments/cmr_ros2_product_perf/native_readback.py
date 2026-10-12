"""Read persisted qualification artifacts using only the standard library."""

import argparse
import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native(value):
    if value.startswith('/mnt/'):
        return Path(value[5].upper() + ':/' + value[7:])
    return Path(value)


def checked(condition, message):
    if not condition:
        raise AssertionError(message)


def check_lasso(lasso, accepting, objective, supplied_costs=None):
    costs = {}
    for group in ('prefix', 'suffix'):
        states, edges = lasso[group], lasso[group + '_edges']
        checked(len(states) == len(edges) + 1, group + ' structure')
        for source, edge, target in zip(states, edges, states[1:]):
            checked(edge['source'] == source and edge['target'] == target, 'edge adjacency')
        costs[group] = sum((Fraction(e['cost']) for e in edges), Fraction(0))
        checked(costs[group] == Fraction((supplied_costs or lasso)[group + '_cost']), 'exact cost')
    checked(lasso['suffix_edges'] and lasso['suffix'][0] == lasso['suffix'][-1], 'nonempty closed suffix')
    checked(lasso['prefix'][-1] == lasso['suffix'][0], 'entry identity')
    checked(any((s['buchi_state'] if isinstance(s, dict) else s[1]) in accepting
                for s in lasso['suffix']), 'acceptance')
    checked(costs['prefix'] + 10 * costs['suffix'] == Fraction(objective), 'objective')


def main(output):
    plan = read(output / 'plan.json')
    selection = read(ROOT / 'experiments/cmr_ros2_real/selection.json')
    checked(plan['cells'] == selection['cells'] and len(plan['cells']) == 9, 'fixed selected cells')
    checked(plan['arms'] == ['reference', 'baseline', 'optimized'] and plan['attempts_per_arm'] == 1, 'three arms once')
    checked(plan['planner_budget_seconds'] == 180 and plan['outer_watchdog_seconds'] == 195
            and plan['formal_campaign'] is False and plan['full_ts_rebuild_every_round'], 'protocol')
    for name, expected in plan['source_closure'].items():
        checked(digest(ROOT / name) == expected, 'current source closure')
        checked(digest(output / 'frozen_adapter' / name) == expected, 'frozen source bytes')
    before, after = [read(output / ('frozen_inputs_' + when + '.json')) for when in ('before', 'after')]
    checked(before == after and len(before) == 55, '55 frozen inputs before/after')
    for name, expected in before.items():
        actual = native(name)
        checked(actual.stat().st_size == expected['size'] and digest(actual) == expected['sha256'], 'qualified inputs')
    fixtures = read(output / 'fixtures.json')
    checked(fixtures['status'] == 'PASSED', 'Product equivalence fixtures')
    report = read(output / 'comparison.json')
    checked(report['status'] == 'PASSED' and report['plan'] == plan, 'completed report')
    checked([(c['instance_id'], c['method']) for c in report['cells']] ==
            [(c['instance_id'], c['method']) for c in plan['cells']], 'complete fixed coverage')
    summary, round_count, source_schemas = [], 0, None
    for cell, item in zip(plan['cells'], report['cells']):
        directory = output / (cell['instance_id'] + '_' + cell['method'])
        checked(read(directory / 'plan.json') == dict(plan, instance_id=cell['instance_id'], method=cell['method']), 'cell plan')
        rows, cell_summary = {}, dict(instance_id=cell['instance_id'], method=cell['method'], arms={})
        checked(item['status'] == 'PASSED', 'cell accepted')
        for arm in plan['arms']:
            attempt = directory / arm
            value = read(attempt / 'result.json')
            checked(value == item['arms'][arm], 'report/result bytes')
            row = rows[arm] = value['row']
            checked(row['instance_id'] == cell['instance_id'] and row['method'] == cell['method'], 'result cell')
            checked(row['execution_commit'] == plan['execution_identity'], 'result execution identity')
            checked(value['worker_exitcode'] == 0 and not value['worker_alive_after_cleanup']
                    and (attempt / 'worker.rc').read_text().strip() == '0', 'worker exit/cleanup')
            checked(row['terminal_status'] == 'OPTIMALITY_CERTIFIED' and not row['right_censored'], 'certified terminal')
            checked(row['certificate_valid_for_terminal'] and row['certificate_verifier_status'] == 'PASS', 'certificate authority')
            checked(row['T_total'] == (row['terminal_completion_ns'] - row['method_start_ns']) / 1e9
                    and row['T_total'] < 180, 'actual uncensored total')
            checked(row['planner_budget_seconds'] == 180 and row['outer_watchdog_seconds'] == 195, 'budgets')
            checked(row['llm_calls'] == row['experimental_llm_calls'] == row['api_key_reads'] == 0, 'no providers')
            unhashed = dict(row)
            expected_hash = unhashed.pop('result_hash')
            checked(hashlib.sha256(json.dumps(unhashed, sort_keys=True, ensure_ascii=False,
                    separators=(',', ':')).encode()).hexdigest() == expected_hash, 'canonical result hash')
            checked(item['certificate_replays'][arm]['status'] == 'PASS', 'independent replay')
            cert_path = attempt / 'certificates' / row['certificate_path']
            checked(digest(cert_path) == row['certificate_hash'], 'certificate bytes SHA')
            cert = read(cert_path)
            checked(cert['execution_commit'] == plan['execution_identity'] and cert['gamma'] == '10', 'certificate identity/gamma')
            checked(cert['instance_id'] == cell['instance_id'] and cert['method'] == cell['method'], 'certificate cell')
            check_lasso(cert['full_model_lasso'], cert['accepting_buchi_states'], row['objective'], cert)
            check_lasso(value['transport']['concrete_lasso'], value['transport']['accepting_buchi_states'], row['objective'])
            manifest = read(attempt / 'preflight.json')
            checked(len(manifest['source_checks']) == 40, 'scientific source count')
            for source in manifest['source_checks']:
                checked(source['match'] and source['actual_sha256'] == source['expected_sha256'] == digest(native(source['path'])), 'scientific bytes')
            for key, count in (('imports', 8), ('runner_imports', 6)):
                checked(len(manifest[key]) == count, 'actual import count')
                for source in manifest[key].values():
                    checked(source['__file__'] == source['expected_path'] and source['sha256'] ==
                            source['expected_sha256'] == digest(native(source['__file__'])), 'actual imported source')
            checked(manifest['bound_runner']['other_ast_unchanged'], 'runner AST')
            config = value['backend_configuration']
            checked(all(config[k] for k in ('original_loop_code_preserved', 'original_local_code_preserved',
                                            'original_builder_global_preserved')), 'scientific global/code identities')
            checked(config['backend_id'] == row['backend_id'] and config['backend_sha256'] == row['backend_sha256'], 'backend metadata')
            if arm != 'reference':
                checked(row['backend_id'] == plan['baseline_backend' if arm == 'baseline' else 'candidate_backend'], 'versioned arm')
            schemas = read(attempt / 'schema_binding.json')['schemas']
            normalized = copy.deepcopy(schemas)
            for schema in normalized.values():
                checked(schema['properties']['backend_sha256']['const'] == row['backend_sha256'], 'schema backend')
                schema.pop('$id')
                schema['properties']['backend_sha256'].pop('const')
            if source_schemas is None:
                source_schemas = normalized
            checked(normalized == source_schemas, 'only schema ID/backend constant changes')
            rounds = row['rounds']
            checked(row['refinement_rounds'] == len(rounds) - 1 and rounds[0]['S_k'] == row['initial_S0'], 'full rounds')
            for left, right in zip(rounds, rounds[1:]):
                checked(set(left['S_k']) < set(right['S_k']), 'strict precision growth')
            if arm != 'reference':
                checked(len(value['search_work']) == len(rounds), 'one search per build')
                for work, round_row in zip(value['search_work'], rounds):
                    checked(work['precision'] == round_row['S_k'] and work['tracemalloc_enabled']
                            and work['completed'] and not work['deadline_observed_exceeded'], 'search instrumentation')
                    checked(work['candidate_entries'] == work['exact_entry_searches'] + work['bound_pruned_entries'], 'entry accounting')
                    checked(len(work['target_searches']) == work['exact_entry_searches'], 'one suffix target per entry')
                    for target in work['target_searches']:
                        checked(target['target_settled'] and target['stop_reason'] == 'target_finalized'
                                and Fraction(target['target_distance']) >= 0, 'exact finalized target')
                    for phase in ('prefix', 'lower_bound', 'suffix'):
                        checked(work[phase + '_settled'] == sum(h['returned_len'] for h in work['helpers'] if h['phase'] == phase), 'helper accounting')
                        checked(work[phase + '_settled'] == round_row[phase + '_settled'], 'round accounting')
            if arm == 'optimized':
                checked(len(value['build_work']) == len(rounds), 'one independent Product rebuild per round')
                for work, round_row in zip(value['build_work'], rounds):
                    checked(work['completed'] and work['full_ts_rebuild_calls'] == 1 and work['precision'] == round_row['S_k'], 'full TS rebuilt')
                    checked(work['buchi_queries'] == work['cache_hits'] + work['cache_misses']
                            and work['cache_misses'] == work['cache_entries'], 'local cache accounting')
                    for a, b in (('product_states', 'product_unique_states'), ('product_edges', 'product_unique_edges'),
                                 ('reachable_ts_states', 'reduced_ts_states'), ('reduced_ts_edges', 'reduced_ts_edges')):
                        checked(work[a] == round_row[b], 'same original Product/TS counts')
            round_count += len(rounds)
            cell_summary['arms'][arm] = {k: row[k] for k in ('T_total', 'T_product', 'T_search', 'objective', 'refinement_rounds')}
            cell_summary['arms'][arm]['build_rounds'] = len(rounds)
        checked(all(Fraction(row['objective']) == Fraction(rows['reference']['objective'])
                    and row['initial_S0'] == rows['reference']['initial_S0'] for row in rows.values()), 'paired exact outcomes')
        normalized = [[{k: v for k, v in r.items() if k not in ('backend_id', 'backend_sha256', 'timings', 'phase_intervals_ns')}
                        for r in rows[arm]['rounds']] for arm in ('baseline', 'optimized')]
        checked(normalized[0] == normalized[1], 'V5/V6 complete scientific trace')
        checked([w['target_searches'] for w in item['arms']['baseline']['search_work']] ==
                [w['target_searches'] for w in item['arms']['optimized']['search_work']], 'same V5 target decisions')
        for phase in ('T_total', 'T_product'):
            cell_summary[phase + '_reduction_percent'] = 100 * (1 - rows['optimized'][phase] / rows['baseline'][phase])
        summary.append(cell_summary)
    result = dict(schema='cmr-product-native-readback-v1', status='PASSED', planner_imported=False,
                  cells=summary, frozen_inputs=55, workers=27, independent_certificate_replays=27,
                  total_build_rounds=round_count, fixtures=fixtures)
    (output / 'native_readback.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'fixtures'}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
