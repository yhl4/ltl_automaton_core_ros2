"""Persisted-byte audit only; no method, verifier, ROS or provider imports."""
import hashlib
import json
from pathlib import Path

read = lambda p: json.loads(Path(p).read_bytes())
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
canonical = lambda v: json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
raw = lambda v: (canonical(v) + '\n').encode()
roots = {name: Path('/tmp/cmr_current_campaign_failure_20261013_' + name)
         for name in ('before', 'after', 'fixed')}
heads = dict(before='40975b7cf63e8f525c0b24309ca71c11fe78bc83',
             after='09cab5f0b40d2bd2b917e8376f8b26877509bf9e',
             fixed='f1bcae9867ab6a83aef63ccc12da02764d6d5274')
cases, internal_verifiers, controller_verifiers, publications = [], 0, 0, 0
plans = {}
for namespace, root in roots.items():
    plan = read(root / 'plan/plan.json')
    plans[namespace] = plan
    assert plan['source_head'] == heads[namespace]
    assert plan['planner_budget_seconds'] == 180 and plan['outer_watchdog_seconds'] == 195
    assert plan['formal_campaign'] is False and plan['expected_method_workers'] == 9
    before = read(root / 'plan/frozen_inputs_before.json')
    after = {p: dict(size=Path(p).stat().st_size, sha256=sha(p)) for p in before}
    assert after == before and len(before) == 60
    (root / 'plan/frozen_inputs_after.json').write_bytes(raw(after))
    for p, expected in plan['source_closure'].items():
        assert sha(root / 'plan/frozen_adapter' / p) == expected
    binding = read(root / 'plan/backend_binding.json')
    assert sha(root / 'plan/backend_binding.json') == plan['version_binding_sha256']
    assert binding['binding_id'] == plan['version_binding_id']
    assert len(plan['source_closure']) == 56
    modes = ['late_delivery'] if namespace == 'before' else ['normal', 'late_delivery', 'crash', 'watchdog']
    for mode in modes:
        campaign = root / ('normal_corrected' if namespace=='fixed' and mode=='normal' else mode)
        attempts = list((campaign / 'attempts').glob('*/*/request.json'))
        assert len(attempts) == 1
        attempt = attempts[0].parent
        request, value = read(attempts[0]), read(attempt / 'result.json')
        row = value['row']
        assert (row['instance_id'], row['method']) == ('C3-T4', 'AP-D')
        assert request['backend'] == 'ros2-v7' and value['worker_alive_after_cleanup'] is False
        assert row['execution_commit'] == plan['execution_identity']
        assert row['result_hash'] == hashlib.sha256(canonical({k:v for k,v in row.items() if k!='result_hash'}).encode()).hexdigest()
        assert float((row['terminal_completion_ns']-row['method_start_ns'])/1e9) == row['T_total']
        assert row['planner_budget_seconds'] == 180 and row['outer_watchdog_seconds'] == 195
        assert value['worker_exitcode'] == int((attempt / 'worker.rc').read_text().strip())
        for item in [row, *(row.get('rounds') or [])]:
            assert all(item[k] == v for k,v in value['backend_binding'].items())
        if namespace == 'fixed':
            expected_sha = next(r['instance_sha256'] for r in plan['records'] if r['instance_id']=='C3-T4')
            assert request['instance_sha256'] == row['instance_sha256'] == row['benchmark_payload_sha256'] == expected_sha
        raw_method = attempt / 'runner_raw_result.json'
        inside = 0
        if raw_method.exists():
            original = read(raw_method)
            assert original['terminal_status'] == 'OPTIMALITY_CERTIFIED' and original['certificate_verifier_status'] == 'PASS'
            assert original['objective'] == '12'
            assert sha(attempt / 'certificates' / original['certificate_path']) == original['certificate_hash']
            inside = 1  # Frozen persist_and_verify_certificate invokes its verifier exactly once.
        internal_verifiers += inside
        terminal = 'OPTIMALITY_CERTIFIED' if mode=='normal' else 'INFRASTRUCTURE_FAILURE' if mode=='crash' else 'TIMEOUT'
        assert row['terminal_status'] == terminal
        final_list = list((campaign / 'completed').glob('*')) if (campaign / 'completed').exists() else []
        published = not (mode=='crash' or namespace=='after' and mode=='watchdog')
        assert len(final_list) == int(published)
        count = 0
        if published:
            publications += 1
            final = final_list[0]
            assert read(final / 'validated_result.json') == row
            for name, expected in read(final / 'commit_manifest.json').items():
                assert sha(final / name) == expected
            record, ledger = read(final / 'pilot_record.json'), read(final / 'ledger_entry.json')
            assert ledger['previous_ledger_sha256'] is None
            assert hashlib.sha256(raw(ledger)).hexdigest() == record['ledger_commit_sha256']
            assert hashlib.sha256(raw({k:v for k,v in record.items() if k!='ledger_commit_sha256'})).hexdigest() == ledger['record_payload_sha256']
            assert (campaign / 'core_results.jsonl').read_bytes() == raw(record)
            receipt = read(campaign / 'ledger.jsonl')
            assert {k:v for k,v in receipt.items() if k not in ('directory_commit_manifest_sha256','ledger_commit_sha256')} == ledger
            assert receipt['directory_commit_manifest_sha256'] == sha(final / 'commit_manifest.json')
            if mode=='normal':
                report = read(campaign / 'campaign_report.json')
                assert len(report['verifications']) == 2 and all(v['status']=='PASS' for v in report['verifications'])
                count = 2
                assert sha(final / 'certificate.json') == row['certificate_hash']
                assert len(row['rounds']) == len(value['build_work']) == 6 and row['initial_S0'] == [3]
            else:
                assert (final / 'certificate.json').read_bytes() == b'null'
        controller_verifiers += count
        if terminal!='OPTIMALITY_CERTIFIED':
            assert row['objective'] is None and not row['certificate_valid_for_terminal'] and value['transport'] is None
            assert row['certificate_verifier_status'] == 'NOT_AVAILABLE'
            assert row['certificate_hash'] == row['certificate_path'] == 'NOT_AVAILABLE'
            for key in ('infeasibility_certificate_type','infeasibility_proof_basis','infeasibility_precision','lower_precision_infeasibility'):
                assert row.get(key) is None and all(r.get(key) is None for r in row.get('rounds') or [])
            if terminal=='TIMEOUT':
                assert row['right_censored'] is True and row['timing_status']=='RIGHT_CENSORED' and row['T_total']>=180
            else:
                assert row['right_censored'] is False and value['worker_exitcode']==23
                assert read(campaign / 'fault_test_report.json')['crash_retry']=='REJECTED_BEFORE_WORKER'
        if namespace=='before':
            assert 'publication/restore independent certificate verification incomplete' in read(campaign / 'fatal.json')['traceback']
        elif namespace=='after' and mode=='watchdog':
            assert 'result instance/method/payload mismatch' in read(campaign / 'fatal.json')['traceback']
            assert row['instance_sha256'] is row['benchmark_payload_sha256'] is None
        elif mode!='crash':
            report = read(campaign / 'campaign_report.json')
            assert report['status']=='PASSED' and report['resume_method_workers']==0 and not (campaign/'fatal.json').exists()
        if mode=='watchdog':
            assert value['worker_exitcode']==-9 and row['T_total']>=195 and row['timeout_stage']=='outer_watchdog'
            if namespace=='fixed':
                envelope = read(final_list[0] / 'result.json')
                record = read(final_list[0] / 'pilot_record.json')
                assert envelope['timed_out_outer'] is True and envelope['process_group_absent'] is True
                assert envelope['delivered_row_source']=='qualified_parent_outer_timeout'
                assert envelope['t_plan_wall_lower_bound_seconds']==row['T_total']
                assert record['result_delivery']=='V7_QUALIFIED_PARENT_OUTER_TIMEOUT_SERIALIZATION'
                assert record['frozen_gate_result_delivery']=='P2b_worker_record'
        cases.append(dict(namespace=namespace, mode=mode, terminal=terminal, published=published,
            instance_sha256=row['instance_sha256'], T_total=row['T_total'], worker_pid=value['worker_pid'],
            worker_exitcode=value['worker_exitcode'], run_one_calls=inside,
            worker_internal_persist_verify_calls=inside, publication_restore_verifier_calls=count))
assert len(cases)==9 and internal_verifiers==5 and controller_verifiers==4 and publications==6
changed = {p for p,h in plans['fixed']['source_closure'].items() if h!=plans['after']['source_closure'][p]}
assert changed == {'experiments/cmr_ros2_search_entry/runner.py', 'experiments/cmr_ros2_search_entry/entry.py',
                   'experiments/cmr_ros2_search_entry/entry_fixtures.py'}
assert plans['before']['version_binding_id']==plans['after']['version_binding_id']=='CMR_SEARCH_ENTRY_V1-2325092433cf5abc'
assert plans['fixed']['version_binding_id']!='CMR_SEARCH_ENTRY_V1-2325092433cf5abc'
preflight_failure = roots['fixed'] / 'normal'
assert 'ROS2 discrete_plan import/hash mismatch' in read(preflight_failure / 'fatal.json')['traceback']
assert not list(preflight_failure.rglob('request.json')) and not (preflight_failure/'dispatch.json').exists()
result = dict(status='PASSED', kind='STDLIB_READBACK_NO_NEW_METHOD_OR_VERIFIER_CALLS', cases=cases,
    actual_process_workers=9, formal_run_one_calls=5, actual_watchdog_attempts=2,
    worker_internal_persist_verify_calls=5, controller_publication_restore_verifier_calls=4,
    total_independent_verifier_calls_from_bound_code_and_persisted_records=9, publications=publications,
    initial_fixed_import_guard_failure_workers=0,
    runtime_closure_changed_files=sorted(changed), fixed_runtime_binding_id=plans['fixed']['version_binding_id'],
    fixed_backend_sha256=read(roots['fixed']/'plan/backend_binding.json')['backends']['ros2-v7']['backend_sha256'],
    new_reference_workers=0, provider_calls=0, dds_calls=0, formal_campaign=False, default_changed=False,
    original_formal_Campaign_constructor='UNRUN', full_510_cell_chain='UNVERIFIED')
(roots['fixed']/'failure_readback.json').write_bytes(raw(result))
print(json.dumps(result))
