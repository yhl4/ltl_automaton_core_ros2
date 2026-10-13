"""Independent standard-library readback; no planner or verifier calls."""
from fractions import Fraction
import hashlib,json,subprocess,zipfile
from pathlib import Path
ROOT=Path('/tmp/cmr_v8_entry_timing_final_20261013')
SOURCE=Path('/tmp/cmr_v8_entry_source_eb5e689_20261013')
REPO=Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/ltl_automaton_core-ros2')
OUT=REPO.parent/'v8_entry_timing_20261013'
HEAD='eb5e6896c763559def6ac65641bb902592dd9eda'
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def normalize(v):
    if isinstance(v,dict):return {k:normalize(x) for k,x in v.items() if not(k.startswith('T_') or k.endswith('_ns') or k.endswith('_sha256') or 'backend' in k or k in('result_hash','row_hash','execution_commit','certificate_path','certificate_hash','certificate_objective','search_counter_basis','qualification_scope','population','version_binding_id','version_binding_sha256'))}
    if isinstance(v,list):return [normalize(x) for x in v]
    return v
plan=read(ROOT/'plan.json');binding=read(ROOT/'backend_binding.json');report=read(ROOT/'comparison.json')
assert report['status']=='PASSED' and plan['source_head']==HEAD
assert subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()==HEAD
assert not subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain'],text=True).strip()
assert plan['formal_campaign'] is False and plan['planner_budget_seconds']==180 and plan['outer_watchdog_seconds']==195
assert sha((ROOT/'backend_binding.json').read_bytes())==plan['version_binding_sha256']
body=dict(binding);body.pop('binding_id')
assert binding['binding_id']==plan['version_binding_id']=='CMR_AP_TS_REUSE_V1-'+sha(canonical(body).encode())[:16]
body=dict(plan);body.pop('execution_identity')
assert plan['execution_identity']==HEAD+'+cmr-ap-ts-reuse-'+sha(canonical(body).encode())[:16]
assert len(plan['source_closure'])==60
for name,digest in plan['source_closure'].items():assert sha((ROOT/'frozen_adapter'/name).read_bytes())==digest==sha((SOURCE/name).read_bytes()),name
oldroot=REPO/'experiments/cmr_ros2_ap_ts_reuse/evidence/20261013'
assert sha((oldroot/'raw_attempts.zip').read_bytes())=='5c30760ae6af2a7cb1c7296c32517cb41ea2c66d1763ad88a13974c76026f335'
with zipfile.ZipFile(oldroot/'raw_attempts.zip') as z:
    previous=json.loads(z.read('raw_attempts/plan.json'))
    oldvalue=json.loads(z.read('raw_attempts/ros2-v8/result.json'))
assert {n for n in plan['source_closure'] if previous['source_closure'][n]!=plan['source_closure'][n]}=={'experiments/cmr_ros2_ap_ts_reuse/runner.py'}
assert read(ROOT/'frozen_inputs_before.json')==read(ROOT/'frozen_inputs_after.json')
for name,v in read(ROOT/'frozen_inputs_before.json').items():
    p=Path(name);assert p.stat().st_size==v['size'] and sha(p.read_bytes())==v['sha256'],name
assert read(OUT/'entry_checks.json')['status']=='PASSED'
assert read(OUT/'hook_check.json')['status']=='PASSED'
values={};details={}
for name in ('reference','ros2-v7','ros2-v8'):
    directory=ROOT/name;value=read(directory/'result.json');row=value['row'];values[name]=value
    raw=read(directory/'runner_raw_result.json');worker=read(directory/'worker_result.json')
    wt=read(directory/'worker_timing.json');pt=read(directory/'parent_timing.json')
    assert row==report['backends'][name]['row']
    assert value['worker_exitcode']==0 and value['worker_alive_after_cleanup'] is False
    assert worker['worker_pid']==value['worker_pid'] and (directory/'worker.rc').read_text().strip()=='0'
    assert row['terminal_status']=='OPTIMALITY_CERTIFIED' and Fraction(row['objective'])==12
    assert row['initial_S0']==[3] and len(row['rounds'])==6 and row['final_precision']==[0,1,2,3,4,5]
    assert row['instance_sha256']==row['benchmark_payload_sha256']==plan['records'][0]['instance_sha256']
    assert row['execution_commit']==plan['execution_identity'] and row['version_binding_id']==plan['version_binding_id']
    assert row['planner_budget_seconds']==180 and row['outer_watchdog_seconds']==195
    body=dict(row);h=body.pop('result_hash');assert sha(canonical(body).encode())==h
    assert sha((directory/'certificates'/row['certificate_path']).read_bytes())==row['certificate_hash']
    replay=report['certificate_replays'][name]
    assert replay['status']=='PASS' and Fraction(replay['objective'])==12 and replay['certificate_hash']==row['certificate_hash']
    suffix=value['transport']['concrete_lasso']['suffix_edges'];assert suffix and suffix[-1]['target']==suffix[0]['source']
    assert wt['entry_metrics']['schema_builds']==pt['entry_metrics']['schema_builds']==1
    assert wt['entry_metrics']['release_checks']==pt['entry_metrics']['release_checks']==1
    assert wt['entry_timing']['schema_validate_result']['calls']==1 and pt['entry_timing']['schema_validate_result']['calls']==2
    core=wt['core_timing']
    for key in ('preflight','load_instance','_payload_for_ai','persist_and_verify_certificate','certificate_fsync','certificate_sha256_file','certificate_verify_bound_certificate'):
        assert core[key]['calls']==1 and core[key]['elapsed_ns']>=0,(name,key)
    assert all(core['original_function_code_preserved'].values())
    interval=row['phase_intervals_ns']['ROS_result_delivery']
    assert (interval[1]-interval[0])/1e9==row['post_runner_delivery_seconds']
    checkpoint=pt['entry_timing']['delivery_checkpoint']
    assert interval[0] <= checkpoint['release_started_ns'] < checkpoint['release_completed_ns']
    assert checkpoint['release_completed_ns'] == row['terminal_completion_ns'] == interval[1]
    assert row['T_total'] == (row['terminal_completion_ns']-row['method_start_ns'])/1e9
    assert checkpoint['release_completed_ns']-checkpoint['release_started_ns'] >= pt['entry_timing']['release_check']['elapsed_ns']
    assert row['post_runner_delivery_seconds'] >= pt['entry_timing']['release_check']['elapsed_ns']/1e9
    assert row['T_other'] >= raw['T_other'] + pt['entry_timing']['release_check']['elapsed_ns']/1e9
    assert row['right_censored'] is False and row['certificate_valid_for_terminal'] is True
    details[name]=dict(T_total=row['T_total'],T_other=row['T_other'],core_T_other=raw['T_other'],
        post_delivery=row['post_runner_delivery_seconds'],T_full_ts=row['T_full_ts'],
        T_input_preprocess=row['T_input_preprocess'],T_certification=row['T_certification'],
        preflight=core['preflight']['elapsed_ns']/1e9,load_instance=core['load_instance']['elapsed_ns']/1e9,
        payload=core['_payload_for_ai']['elapsed_ns']/1e9,
        certificate_total=core['persist_and_verify_certificate']['elapsed_ns']/1e9,
        certificate_fsync=core['certificate_fsync']['elapsed_ns']/1e9,
        certificate_verify=core['certificate_verify_bound_certificate']['elapsed_ns']/1e9,
        worker_schema_seconds=wt['entry_timing']['schema_for']['elapsed_ns']/1e9,
        parent_schema_seconds=pt['entry_timing']['schema_for']['elapsed_ns']/1e9,
        worker_release_seconds=wt['entry_timing']['release_check']['elapsed_ns']/1e9,
        parent_release_seconds=pt['entry_timing']['release_check']['elapsed_ns']/1e9,
        parent_release_charged=True,
        certificate_canonical_record=core['certificate_canonical_record']['elapsed_ns']/1e9,
        certificate_payload=core['certificate__certificate_payload']['elapsed_ns']/1e9,
        certificate_hash=core['certificate_sha256_file']['elapsed_ns']/1e9,
        additional_replay_seconds=read(directory/'external_replay_timing.json')['elapsed_ns']/1e9)
old=values['ros2-v7'];new=values['ros2-v8']
assert normalize(old['row']['rounds'])==normalize(new['row']['rounds'])
assert normalize(old['search_work'])==normalize(new['search_work']) and old['transport']==new['transport']
assert [b['full_ts_rebuild_calls'] for b in old['build_work']]==[1]*6
assert [b['full_ts_rebuild_calls'] for b in new['build_work']]==[1,0,0,0,0,0]
assert [b['full_ts_cache_hits'] for b in new['build_work']]==[0,1,1,1,1,1]
oldrow=oldvalue['row'];newrow=new['row']
result=dict(status='PASSED',source_head=HEAD,version_binding_id=plan['version_binding_id'],
    version_binding_sha256=plan['version_binding_sha256'],backend_sha256=newrow['backend_sha256'],
    source_files=60,frozen_inputs=56,actual_workers=3,actual_run_one=3,
    internal_certificate_verifier_calls_observed=3,additional_persisted_replays_pass=3,
    readback_verifier_calls=0,solver_imported=False,dds_requests=0,provider_calls=0,formal_campaign=False,
    old_archive_sha256='5c30760ae6af2a7cb1c7296c32517cb41ea2c66d1763ad88a13974c76026f335',details=details,
    v8_total_decrease_vs_old_percent=100*(1-newrow['T_total']/oldrow['T_total']),
    v8_delivery_decrease_vs_old_percent=100*(1-newrow['post_runner_delivery_seconds']/oldrow['post_runner_delivery_seconds']),
    v8_total_increase_vs_current_v7_percent=100*(newrow['T_total']/old['row']['T_total']-1))
(OUT/'readback_final.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,sort_keys=True))
