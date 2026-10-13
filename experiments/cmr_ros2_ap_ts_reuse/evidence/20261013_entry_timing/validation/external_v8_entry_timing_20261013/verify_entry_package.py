"""Standard-library archive readback; imports no planner or verifier."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

repo = Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/ltl_automaton_core-ros2')
root = repo/'experiments/cmr_ros2_ap_ts_reuse/evidence/20261013_entry_timing'
source = Path('/tmp/cmr_v8_entry_source_eb5e689_20261013')
outside = repo.parent/'v8_entry_timing_20261013'
def read(path): return json.loads(path.read_bytes())
def sha(data): return hashlib.sha256(data).hexdigest()
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def normalize(value):
    if isinstance(value, dict):
        return {k:normalize(v) for k,v in value.items() if not(k.startswith('T_') or k.endswith('_ns') or k.endswith('_sha256') or 'backend' in k or k in ('result_hash','row_hash','execution_commit','certificate_path','certificate_hash','certificate_objective','search_counter_basis','qualification_scope','population','version_binding_id','version_binding_sha256'))}
    if isinstance(value,list): return [normalize(v) for v in value]
    return value

index=read(root/'index.json'); artifacts=read(root/'artifact_manifest.json')
assert artifacts['file_count']==len(artifacts['files'])
assert set(artifacts['files'])=={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}-set(artifacts['excludes'])
for name,expected in artifacts['files'].items():
    data=(root/name).read_bytes()
    assert len(data)==expected['size'] and sha(data)==expected['sha256'], name
assert sha((root/'artifact_manifest.json').read_bytes())==index['artifact_manifest']['sha256']
assert sha((root/'raw_attempts.zip').read_bytes())==index['archive']['sha256']
archive_manifest=read(root/'archive_manifest.json')
old=repo/'experiments/cmr_ros2_ap_ts_reuse/evidence/20261013/raw_attempts.zip'
assert sha(old.read_bytes())=='5c30760ae6af2a7cb1c7296c32517cb41ea2c66d1763ad88a13974c76026f335'
with zipfile.ZipFile(root/'raw_attempts.zip') as archive:
    assert archive.testzip() is None
    assert len(archive.namelist())==len(set(archive.namelist()))==224
    assert set(archive.namelist())=={r['path'] for r in archive_manifest['members']}
    for row in archive_manifest['members']:
        data=archive.read(row['path'])
        assert len(data)==row['size'] and sha(data)==row['sha256'], row['path']
        assert data==Path(row['source']).read_bytes(), row['path']
    for prefix in ('intermediate_111ae6c','final_eb5e689'):
        def get(name): return json.loads(archive.read(prefix+'/'+name))
        plan=get('plan.json'); binding=get('backend_binding.json'); report=get('comparison.json')
        assert report['status']=='PASSED' and plan['formal_campaign'] is False
        assert plan['planner_budget_seconds']==180 and plan['outer_watchdog_seconds']==195
        assert len(plan['source_closure'])==60
        for name,digest in plan['source_closure'].items():
            assert sha(archive.read(prefix+'/frozen_adapter/'+name))==digest
        inputs=get('frozen_inputs_before.json')
        assert len(inputs)==56 and inputs==get('frozen_inputs_after.json')
        assert sha(archive.read(prefix+'/backend_binding.json'))==plan['version_binding_sha256']
        body=dict(binding); body.pop('binding_id')
        assert binding['binding_id']==plan['version_binding_id']=='CMR_AP_TS_REUSE_V1-'+sha(canonical(body).encode())[:16]
        body=dict(plan); body.pop('execution_identity')
        assert plan['execution_identity']==plan['source_head']+'+cmr-ap-ts-reuse-'+sha(canonical(body).encode())[:16]
        results={}
        for backend in ('reference','ros2-v7','ros2-v8'):
            value=get(backend+'/result.json'); row=value['row']; results[backend]=value
            assert row==report['backends'][backend]['row']
            assert get('dispatches/'+backend+'.json')==get(backend+'/request.json')
            assert value['worker_exitcode']==0 and value['worker_alive_after_cleanup'] is False
            assert row['terminal_status']=='OPTIMALITY_CERTIFIED' and Fraction(row['objective'])==12
            assert len(row['rounds'])==6 and row['initial_S0']==[3] and row['final_precision']==list(range(6))
            assert row['execution_commit']==plan['execution_identity'] and row['version_binding_id']==plan['version_binding_id']
            body=dict(row); digest=body.pop('result_hash'); assert sha(canonical(body).encode())==digest
            assert sha(archive.read(prefix+'/'+backend+'/certificates/'+row['certificate_path']))==row['certificate_hash']
            replay=report['certificate_replays'][backend]
            assert replay['status']=='PASS' and Fraction(replay['objective'])==12 and replay['certificate_hash']==row['certificate_hash']
            worker=get(backend+'/worker_timing.json'); parent=get(backend+'/parent_timing.json')
            assert worker['entry_metrics']['schema_builds']==parent['entry_metrics']['schema_builds']==1
            assert worker['entry_timing']['schema_validate_result']['calls']==1
            assert parent['entry_timing']['schema_validate_result']['calls']==2
            assert worker['entry_metrics']['release_checks']==parent['entry_metrics']['release_checks']==1
            for key in ('preflight','load_instance','_payload_for_ai','persist_and_verify_certificate','certificate_canonical_record','certificate__certificate_payload','certificate_fsync','certificate_sha256_file','certificate_verify_bound_certificate'):
                assert worker['core_timing'][key]['calls']==1
            assert all(worker['core_timing']['original_function_code_preserved'].values())
            if prefix=='final_eb5e689':
                checkpoint=parent['entry_timing']['delivery_checkpoint']; interval=row['phase_intervals_ns']['ROS_result_delivery']
                assert interval[0]<=checkpoint['release_started_ns']<checkpoint['release_completed_ns']==interval[1]==row['terminal_completion_ns']
                assert row['T_total']==(interval[1]-row['method_start_ns'])/1e9
                assert row['post_runner_delivery_seconds']>=parent['entry_timing']['release_check']['elapsed_ns']/1e9
        v7=results['ros2-v7']; v8=results['ros2-v8']
        assert normalize(v7['row']['rounds'])==normalize(v8['row']['rounds'])
        assert normalize(v7['search_work'])==normalize(v8['search_work']) and v7['transport']==v8['transport']
        assert [r['full_ts_rebuild_calls'] for r in v7['build_work']]==[1]*6
        assert [r['full_ts_rebuild_calls'] for r in v8['build_work']]==[1,0,0,0,0,0]
        assert [r['full_ts_cache_hits'] for r in v8['build_work']]==[0,1,1,1,1,1]
for name,record in index['source_snapshots'].items():
    blob=subprocess.check_output(['git','-C',str(source),'show',record['commit']+':'+record['source_path']])
    assert blob==(root/'source_snapshots'/name).read_bytes()
    assert sha(blob)==record['sha256'] and len(blob)==record['size']
for path in index['validation_paths']:
    assert (root/path).read_bytes()==(outside/Path(path).name).read_bytes(), path
assert read(outside/'entry_checks.json')['status']=='PASSED'
assert read(outside/'hook_check.json')['status']=='PASSED'
assert read(outside/'readback_final.json')['status']=='PASSED'
result=dict(status='PASSED',archive_members=224,artifact_files=artifacts['file_count'],namespaces=2,source_files_per_namespace=60,frozen_inputs_per_namespace=56,exact_git_blobs=3,certified_rows=6,recorded_extra_replays_pass=6,full_ts_reuse='1 build + 5 hits in both V8 namespaces',final_delivery_guard_charged=True,old_archive_unchanged=True,actual_workers_started=0,actual_solver_calls=0,actual_verifier_calls=0,dds_requests=0,provider_calls=0)
(outside/'package_readback.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,sort_keys=True))
