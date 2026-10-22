"""Independent standard-library readback of one four-arm comparison."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--commit',required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
root,source=args.root,args.source
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def normal(v):
    if isinstance(v,dict):return {k:normal(x) for k,x in v.items() if not(k.startswith('T_') or k.endswith('_ns') or k.endswith('_sha256') or 'backend' in k or k in ('result_hash','row_hash','execution_commit','certificate_path','certificate_hash','certificate_objective','search_counter_basis','qualification_scope','population','version_binding_id','version_binding_sha256'))}
    if isinstance(v,list):return [normal(x) for x in v]
    return v
def work_normal(v):
    if isinstance(v,dict):return {k:work_normal(x) for k,x in v.items() if not k.startswith(('projection_','witness_','position_map_'))}
    if isinstance(v,list):return [work_normal(x) for x in v]
    return v

plan=read(root/'plan.json'); binding=read(root/'backend_binding.json'); report=read(root/'comparison.json')
assert report['status']=='PASSED' and plan['source_head']==args.commit
assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==args.commit
assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True).strip()
assert plan['formal_campaign'] is False and plan['planner_budget_seconds']==180 and plan['outer_watchdog_seconds']==195
assert plan['baseline_commit']=='f3232b0c13bc306a0e1e683dda7f83194bf2337f'
assert plan['expected_method_workers']==4 and plan['attempts_per_cell_backend']==1
assert sha((root/'backend_binding.json').read_bytes())==plan['version_binding_sha256']
body=dict(binding);body.pop('binding_id')
assert binding['binding_id']==plan['version_binding_id']=='CMR_PROJECTION_WITNESS_REUSE_V1-'+sha(canonical(body).encode())[:16]
body=dict(plan);body.pop('execution_identity')
assert plan['execution_identity']==args.commit+'+cmr-projection-witness-'+sha(canonical(body).encode())[:16]
assert len(plan['source_closure'])==65
for name,digest in plan['source_closure'].items():
    assert sha((root/'frozen_adapter'/name).read_bytes())==digest==sha((source/name).read_bytes()),name
historical=source/'experiments/cmr_ros2_ap_ts_reuse/evidence/20261013_entry_timing/raw_attempts.zip'
assert sha(historical.read_bytes())=='0a923837b0129164236046b4358c07c778354269c65d7f61e7b367d10eb416d7'
with zipfile.ZipFile(historical) as archive:
    previous=json.loads(archive.read('final_eb5e689/plan.json'))
    previous_binding=json.loads(archive.read('final_eb5e689/backend_binding.json'))
assert all(plan['source_closure'][n]==h for n,h in previous['source_closure'].items())
assert set(plan['source_closure'])-set(previous['source_closure'])=={
    'experiments/cmr_ros2_reduction_reuse/'+name for name in ('builder.py','search.py','fixtures.py','backend.py','runner.py')}
for name in ('reference','ros2-v7','ros2-v8'):
    assert binding['backends'][name]==previous_binding['backends'][name]
before=read(root/'frozen_inputs_before.json')
assert before==read(root/'frozen_inputs_after.json') and len(before)==56
for name,value in before.items():
    p=Path(name);assert p.stat().st_size==value['size'] and sha(p.read_bytes())==value['sha256'],name
assert read(root/'fixtures.json')['status']=='PASSED'
assert read(root/'entry_fixture_details.json')['status']=='PASSED'
values={};details={}
for name in ('reference','ros2-v7','ros2-v8','ros2-v9'):
    d=root/name;value=read(d/'result.json');row=value['row'];values[name]=value
    worker=read(d/'worker_result.json');raw=read(d/'runner_raw_result.json')
    wt=read(d/'worker_timing.json');pt=read(d/'parent_timing.json')
    assert row==report['backends'][name]['row']
    assert read(root/'dispatches'/(name+'.json'))==read(d/'request.json')
    assert value['worker_exitcode']==0 and value['worker_alive_after_cleanup'] is False
    assert worker['worker_pid']==value['worker_pid'] and (d/'worker.rc').read_text().strip()=='0'
    assert row['terminal_status']=='OPTIMALITY_CERTIFIED' and Fraction(row['objective'])==12
    assert row['initial_S0']==[3] and len(row['rounds'])==6 and row['final_precision']==list(range(6))
    assert row['instance_sha256']==row['benchmark_payload_sha256']==plan['records'][0]['instance_sha256']
    assert row['execution_commit']==plan['execution_identity'] and row['version_binding_id']==plan['version_binding_id']
    assert row['planner_budget_seconds']==180 and row['outer_watchdog_seconds']==195
    body=dict(row);digest=body.pop('result_hash');assert sha(canonical(body).encode())==digest
    assert sha((d/'certificates'/row['certificate_path']).read_bytes())==row['certificate_hash']
    replay=report['certificate_replays'][name]
    assert replay['status']=='PASS' and Fraction(replay['objective'])==12 and replay['certificate_hash']==row['certificate_hash']
    suffix=value['transport']['concrete_lasso']['suffix_edges']
    assert suffix and suffix[-1]['target']==suffix[0]['source']
    assert wt['entry_metrics']['schema_builds']==pt['entry_metrics']['schema_builds']==1
    assert wt['entry_metrics']['release_checks']==pt['entry_metrics']['release_checks']==1
    assert wt['entry_timing']['schema_validate_result']['calls']==1 and pt['entry_timing']['schema_validate_result']['calls']==2
    core=wt['core_timing']
    for key in ('preflight','load_instance','_payload_for_ai','persist_and_verify_certificate','certificate_canonical_record','certificate__certificate_payload','certificate_fsync','certificate_sha256_file','certificate_verify_bound_certificate'):
        assert core[key]['calls']==1,(name,key)
    assert all(core['original_function_code_preserved'].values())
    cp=pt['entry_timing']['delivery_checkpoint']; interval=row['phase_intervals_ns']['ROS_result_delivery']
    assert interval[0]<=cp['release_started_ns']<cp['release_completed_ns']==row['terminal_completion_ns']==interval[1]
    assert (interval[1]-interval[0])/1e9==row['post_runner_delivery_seconds']
    assert row['T_total']==(row['terminal_completion_ns']-row['method_start_ns'])/1e9
    assert row['T_other']>=raw['T_other']+pt['entry_timing']['release_check']['elapsed_ns']/1e9
    assert row['right_censored'] is False and row['certificate_valid_for_terminal'] is True
    details[name]={k:row[k] for k in ('T_total','T_other','T_input_preprocess','T_full_ts','T_reduction','T_product','T_search','T_certification')}
    details[name]['post_runner_delivery_seconds']=row['post_runner_delivery_seconds']
    details[name]['additional_replay_seconds']=read(d/'external_replay_timing.json')['elapsed_ns']/1e9
old,new=values['ros2-v8'],values['ros2-v9']
for key in ('search_work','build_work'):
    assert normal(work_normal(old[key]))==normal(work_normal(new[key])),key
assert normal(old['row']['rounds'])==normal(new['row']['rounds'])
assert old['transport']==new['transport']
assert [b['full_ts_rebuild_calls'] for b in values['ros2-v7']['build_work']]==[1]*6
for value in (old,new):
    builds=value['build_work'];searches=value['search_work']
    assert [b['full_ts_rebuild_calls'] for b in builds]==[1,0,0,0,0,0]
    assert [b['full_ts_cache_hits'] for b in builds]==[0,1,1,1,1,1]
    for b in builds:
        assert b['projection_requests']==b['projection_computations']+b['projection_cache_hits']
    for s in searches:
        assert s['witness_key_requests']==s['witness_key_computations']+s['witness_key_cache_hits']
        assert s['tracemalloc_enabled'] and s['completed'] and not s['deadline_observed_exceeded']
    assert sum(b['completed'] for b in builds)==6
assert sum(b['projection_cache_hits'] for b in old['build_work'])==0
assert sum(s['witness_key_cache_hits'] for s in old['search_work'])==0
counts=report['operation_counts']
assert counts['v9_projection_computations']<counts['v8_projection_computations']
assert counts['v9_witness_key_computations']<counts['v8_witness_key_computations']
for tag,value in (('v8',old),('v9',new)):
    assert counts[tag+'_projection_computations']==sum(b['projection_computations'] for b in value['build_work'])
    assert counts[tag+'_witness_key_computations']==sum(b['witness_key_computations'] for b in value['search_work'])
    counts[tag+'_projection_requests']=sum(b['projection_requests'] for b in value['build_work'])
    counts[tag+'_witness_key_requests']=sum(s['witness_key_requests'] for s in value['search_work'])
    counts[tag+'_witness_items_normalized']=sum(s['witness_items_normalized'] for s in value['search_work'])
result=dict(status='PASSED',source_head=args.commit,version_binding_id=plan['version_binding_id'],
    version_binding_sha256=plan['version_binding_sha256'],backend_sha256=binding['backends']['ros2-v9']['backend_sha256'],
    source_files=65,frozen_inputs=56,actual_workers=4,actual_run_one=4,
    internal_certificate_verifier_calls_observed=4,additional_persisted_replays_pass=4,
    details=details,operation_counts=counts,full_ts_builds_per_v8_v9=1,full_ts_hits_per_v8_v9=5,
    original_control_identities_preserved=True,final_delivery_guard_charged=True,
    readback_solver_calls=0,readback_verifier_calls=0,dds_requests=0,provider_calls=0,formal_campaign=False)
args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,sort_keys=True))
