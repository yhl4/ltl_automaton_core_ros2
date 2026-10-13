"""Read immutable DDS evidence with the standard library; never dispatch work."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

SOURCE = 'a6c2394e93ed2826d9b2f93bf0b824d85cee9546'
BINDING = 'CMR_SEARCH_ENTRY_V1-a429239e4704ea06'
BINDING_SHA = '50c5d930f07b953f63eddd9b7c0e095424d3dd555cc8627d2a45e23962302204'
BACKEND_SHA = 'c7548808c9fbdd9b69ca4f6ece242b5bfe2b194b8828041b8c6c5d987c009458'
TARGETS = [('A-T1-M0-A-S-BRANCH', 'FULL', '12'),
           ('B-D-BRANCH-S2', 'FULL', '15'), ('C3-T4', 'AP-D', '12')]

def digest(data):
    return hashlib.sha256(data).hexdigest()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def read(path):
    return json.loads(Path(path).read_bytes())

def require(value, description):
    if not value:
        raise AssertionError(description)

def main(args):
    evidence = Path(args.evidence)
    index = read(evidence/'index.json')
    manifest = read(evidence/'archive_manifest.json')
    archive = evidence/'raw_attempts.zip'
    raw_bytes = archive.read_bytes()
    require(len(raw_bytes) == manifest['archive']['size'], 'archive size')
    require(digest(raw_bytes) == manifest['archive']['sha256'], 'archive digest')
    totals = dict(actual_dds_requests=0, actual_planner_workers=0, actual_formal_run_one=0,
                  optimality_certificate_replays_pass=0, dispatch_actions=0)
    cases, after_inputs, plans, history = [], {}, {}, {}
    live_source = Path(args.source_root)
    require(subprocess.check_output(['git','-C',str(live_source),'rev-parse','HEAD'], text=True).strip() == SOURCE,
            'live clone commit')
    require(not subprocess.check_output(['git','-C',str(live_source),'status','--porcelain'],text=True).strip(),
            'live clone clean')
    previous_archives = {'20261012': '399653ff5db57d8aed078f327e35671ddd0255385a500e1ad63ad6f6febea1a6',
                         '20261013_audit_real': '3626a630cccaae0d3f4e765455ddc43cb220a47c149ed84ab89cfce4bcb505d6'}
    for label, expected in previous_archives.items():
        old_path = evidence.parent/label/'raw_attempts.zip'
        require(digest(old_path.read_bytes()) == expected, 'preserved archive '+label)
        if label == '20261013_audit_real':
            with zipfile.ZipFile(old_path) as old:
                for name in old.namelist():
                    if name.endswith('/reference/result.json'):
                        value = json.loads(old.read(name)); row = value['row']
                        if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
                            history[(row['instance_id'],row['method'])] = row
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        expected_members = {m['path']:m for m in manifest['members']}
        require(len(names)==len(set(names))==len(expected_members)==manifest['archive']['member_count'],
                'unique archive membership')
        require(set(names)==set(expected_members), 'archive member inventory')
        for name in names:
            data = z.read(name); item = expected_members[name]
            require(len(data)==item['size'] and digest(data)==item['sha256'], 'member bytes '+name)
        def raw(name):
            return json.loads(z.read(name))
        for attempt in index['attempts']:
            prefix = attempt['prefix']; plan = raw(prefix+'/plan/plan.json'); plans[prefix]=plan
            require(plan['source_head']==SOURCE and plan['formal_campaign'] is False, 'source/scope '+prefix)
            require(plan['planner_budget_seconds']==180 and plan['outer_watchdog_seconds']==195, 'budgets '+prefix)
            body=dict(plan); body.pop('execution_identity')
            require(plan['execution_identity']==SOURCE+'+cmr-search-entry-'+digest(canonical(body).encode())[:16],
                    'canonical execution identity '+prefix)
            require(plan['version_binding_id']==BINDING and plan['version_binding_sha256']==BINDING_SHA,
                    'new runtime identity '+prefix)
            binding_member=prefix+'/'+str(Path(plan['version_binding_path']).relative_to(Path(attempt['namespace'])))
            binding_bytes=z.read(binding_member); binding=json.loads(binding_bytes)
            require(digest(binding_bytes)==BINDING_SHA, 'binding bytes '+prefix)
            bbody=dict(binding); bbody.pop('binding_id')
            require(binding['binding_id']==BINDING=='CMR_SEARCH_ENTRY_V1-'+digest(canonical(bbody).encode())[:16],
                    'canonical binding '+prefix)
            require(binding['semantic_contract_id']=='INITIAL_LABEL_V1' and binding['nonempty_accepting_suffix'] is True
                    and binding['full_ts_rebuild_every_round'] is True, 'semantic contract '+prefix)
            require(binding['source_closure']==plan['source_closure'] and len(plan['source_closure'])==56,
                    '56-source closure '+prefix)
            for name, expected in plan['source_closure'].items():
                require(digest(z.read(prefix+'/plan/frozen_adapter/'+name))==expected, 'frozen source '+name)
                require(digest((live_source/name).read_bytes())==expected, 'live source '+name)
            before=raw(prefix+'/plan/frozen_inputs_before.json')
            expected_count=60 if prefix.startswith('search') else 61
            require(len(before)==expected_count, 'frozen input population '+prefix)
            actual={name:dict(size=Path(name).stat().st_size, sha256=digest(Path(name).read_bytes())) for name in before}
            require(actual==before, 'frozen input bytes '+prefix)
            after_inputs[prefix]=actual
            arithmetic=raw(prefix+'/plan/search_fixtures.json'); interface=raw(prefix+'/plan/entry_fixtures.json')
            require(arithmetic['status']=='PASSED' and len(arithmetic['cases'])==14, '14 arithmetic fixtures '+prefix)
            require(interface['status']=='PASSED' and len(interface['checks'])==16, '16 interface checks '+prefix)
        artifacts=[n for n in names if n.endswith('/dds_artifact.json')]
        for name in artifacts:
            a=raw(name); prefix=name.split('/')[0]; directory=name.rsplit('/',1)[0]
            driver=a.get('driver',{}); server=a.get('server',{}); request=raw(directory+'/request.json')
            if prefix=='search_import_failure':
                require(a['status']=='FAILED' and a['driver_rc']==a['server_rc']==1, 'retained import failure')
                require(not driver and not server, 'import failed before ROS events')
                require(all(b"No module named 'rclpy'" in z.read(directory+'/'+role+'.stderr') for role in ('driver','server')),
                        'retained rclpy cause')
                continue
            require(prefix in ('search_fixed','failure_fixed2') and a['status']=='PASSED', 'qualified artifact '+name)
            require(a['server_rc']==a['driver_rc']==0, 'DDS child rc '+name)
            plan=plans[prefix]; descriptor=a['descriptor']; result=driver['result']
            record=next(r for r in plan['records'] if r['instance_id']==request['instance_id'])
            cell=next(c for c in plan['cells'] if (c['instance_id'],c['method'])==(request['instance_id'],request['method']))
            expected=dict(cell, **descriptor, instance_sha256=record['instance_sha256'], qualification_id=plan['qualification_id'],
                          population=plan['scope'], formal_campaign=False, execution_identity=plan['execution_identity'],
                          planner_budget_seconds=180, outer_watchdog_seconds=195, request_id=request['request_id'])
            require(request==expected==a['request'], 'exact wire request '+name)
            require(descriptor['backend_sha256']==BACKEND_SHA and descriptor['version_binding_id']==BINDING
                    and descriptor['version_binding_sha256']==BINDING_SHA and result['backend_binding']==descriptor,
                    'descriptor '+name)
            events=driver['events']; se=server['events']
            require(sum(e['event']=='request_published' for e in events)==1, 'one request publication '+name)
            require(sum(e['event']=='request_received' for e in se)==1, 'one server request '+name)
            totals['actual_dds_requests']+=1
            require(driver['module_identity_match'] is True, 'runtime execution import '+name)
            for key, sha in driver['module_sha256'].items():
                require(digest(Path(driver['module_resolved_paths'][key]).read_bytes())==sha, 'execution module '+key)
            status=result['terminal_status']; details=dict(instance_id=request['instance_id'],method=request['method'],status=status)
            if isinstance(result.get('worker_pid'),int):
                totals['actual_planner_workers']+=1
                value=raw(directory+'/cmr_attempt/result.json'); row=value['row']
                require(all(result.get(k)==v for k,v in row.items()), 'wire preserves delivered row '+name)
                require(row['instance_sha256']==row['benchmark_payload_sha256']==record['instance_sha256']
                        and row['execution_commit']==plan['execution_identity'], 'result identity '+name)
                if status in ('OPTIMALITY_CERTIFIED','INFEASIBLE_CERTIFIED') or 'initial_S0' in row:
                    require(row['initial_S0']==cell['expected_initial_S0'], 'initial precision '+name)
                require(value['worker_pid']==result['worker_pid'] and value['worker_alive_after_cleanup'] is False, 'worker identity/cleanup '+name)
                code=23 if status=='INFRASTRUCTURE_FAILURE' else 0
                require(result['worker_exitcode']==code and z.read(directory+'/cmr_attempt/worker.rc').strip()==str(code).encode(), 'worker rc '+name)
                body=dict(row); recorded=body.pop('result_hash')
                require(digest(canonical(body).encode())==recorded, 'row result_hash '+name)
                if directory+'/cmr_attempt/runner_raw_result.json' in names:
                    totals['actual_formal_run_one']+=1
            if status=='OPTIMALITY_CERTIFIED':
                expected_objective=next(o for i,m,o in TARGETS if (i,m)==(request['instance_id'],request['method']))
                historical=history[(request['instance_id'],request['method'])]
                require(Fraction(result['objective'])==Fraction(expected_objective)==Fraction(historical['objective']), 'exact objective/history '+name)
                require(result['instance_sha256']==historical['instance_sha256'] and result['initial_S0']==historical['initial_S0'], 'same historical input '+name)
                lasso=result['concrete_lasso']; suffix=lasso['suffix_edges']
                require(suffix and suffix[-1]['target']==suffix[0]['source'], 'nonempty closed suffix '+name)
                cert_member=directory+'/cmr_attempt/certificates/'+result['certificate_path']
                require(digest(z.read(cert_member))==result['certificate_hash'], 'certificate bytes '+name)
                replay=a['certificate_replay']
                require(replay['status']=='PASS' and Fraction(replay['objective'])==Fraction(expected_objective)
                        and replay['certificate_hash']==result['certificate_hash'], 'persisted independent replay '+name)
                totals['optimality_certificate_replays_pass']+=1
                actions=driver['expected_actions']; dispatch=[e for e in events if e['event']=='dispatch']
                require(driver['commands']==actions==[e['action'] for e in dispatch], 'complete actions '+name)
                require([e['execution_step_seq'] for e in dispatch]==list(range(len(actions))), 'step progression '+name)
                require([e['source_state'] for e in dispatch]==driver['expected_sources']
                        and [e['target_state'] for e in dispatch]==driver['expected_targets'], 'action witness '+name)
                for key in ('completion_count','ts_state_receive_count','observer_feedback_count','abstraction_feedback_count'):
                    require(driver[key]==len(actions), 'feedback count '+key)
                observations=[e for e in events if e['event']=='observation_received']
                require([e['step'] for e in observations if e['generation']==1]==list(range(len(actions)+1)), 'accepted observations '+name)
                require(len([e for e in observations if e['generation']==0])==1
                        and observations[-1]['has_next_action'] is False, 'stale observation and final stop '+name)
                require(len(value['build_work'])==len(row['rounds']), 'complete rebuild rounds '+name)
                require(all(b['completed'] and b['full_ts_rebuild_calls']==1 and b['precision']==r['S_k']
                            for b,r in zip(value['build_work'],row['rounds'])), 'full rebuild each round '+name)
                totals['dispatch_actions']+=len(actions)
                details.update(objective=result['objective'],actions=len(actions),rounds=len(row['rounds']),T_total=result['T_total'])
            else:
                require(status in ('TIMEOUT','INFRASTRUCTURE_FAILURE','ERROR','INFEASIBLE_CERTIFIED'), 'nonoptimal terminal '+name)
                require(result['objective'] is None and result.get('concrete_lasso') is None
                        and result.get('certificate_valid_for_terminal') is False, 'no optimal authority '+name)
                require(not driver['commands'] and all(driver[k]==0 for k in ('completion_count','observer_feedback_count','abstraction_feedback_count')),
                        'no execution '+name)
                require(not any(e['event'] in ('dispatch','observation_received') for e in events)
                        and not any(e['event']=='snapshot_served' for e in se), 'no served snapshot/dispatch '+name)
                if status=='TIMEOUT':
                    fault=raw(directory+'/cmr_attempt/fault_qualification.json')
                    require(result['right_censored'] is True and result['T_total']>=180 and fault['simulated_clock'] is True
                            and fault['injected_offset_ns']==180_000_000_000, 'simulated censored timeout '+name)
                    details.update(simulated_clock=True,T_total=result['T_total'])
                elif status=='ERROR':
                    require(result.get('worker_pid') is None and not any(n.startswith(directory+'/cmr_attempt/') for n in names),
                            'server error before worker '+name)
            cases.append(details)
        ref=raw('failure_fixed2/dds_failures/reference_D1/result.json'); reference=ref['row']
        require(reference['terminal_status']=='INFEASIBLE_CERTIFIED' and ref['worker_exitcode']==0
                and ref['worker_alive_after_cleanup'] is False, 'fresh D1 reference')
        totals['actual_planner_workers']+=1
        totals['actual_formal_run_one']+=1
        empty=raw('failure_fixed2/dds_failures/dds_none/cmr_attempt/result.json')['row']
        fields=('infeasibility_certificate_type','infeasibility_proof_basis','infeasibility_precision','lower_precision_infeasibility')
        require(all(empty[k]==reference[k] for k in fields), 'exact empty proof agrees with original')
        require(raw('search_fixed/dds/dds_report.json')['status']=='PASSED'
                and raw('failure_fixed2/dds_failures/failure_dds_report.json')['status']=='PASSED', 'persisted reports')
        require(not any(n.endswith('/worker.rc') and n.split('/')[0] in ('search_import_failure','failure_prepare','failure_args_output') for n in names),
                'no dispatched workers in failed/prepared namespaces')
    require(totals==dict(actual_dds_requests=7,actual_planner_workers=7,actual_formal_run_one=6,
                        optimality_certificate_replays_pass=3,dispatch_actions=10), 'actual totals')
    result=dict(schema='cmr-current-dds-stdlib-readback-v1',status='PASSED',source_head=SOURCE,
                version_binding_id=BINDING,version_binding_sha256=BINDING_SHA,archive_sha256=digest(raw_bytes),
                archive_members=len(names),source_closure_files=56,totals=totals,cases=cases,
                frozen_inputs_after_readback=after_inputs,old_archive_hashes=previous_archives,
                solver_imported=False,dispatches_started=0,independent_verifier_calls=0,
                historical_reference_comparison='persisted verdict, exact objective, model hash and initial S0; no new paired timing claim')
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(canonical({k:v for k,v in result.items() if k!='frozen_inputs_after_readback'}))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence',required=True)
    parser.add_argument('--source-root',required=True)
    parser.add_argument('--output',required=True)
    main(parser.parse_args())
