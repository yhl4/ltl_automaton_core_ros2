"""Independent standard-library readback; invokes no planner or verifier."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

p=argparse.ArgumentParser()
p.add_argument('--root',type=Path,required=True)
p.add_argument('--source',type=Path,required=True)
p.add_argument('--commit',required=True)
p.add_argument('--output',type=Path,required=True)
args=p.parse_args();root=args.root;source=args.source
def read(path):return json.loads(path.read_bytes())
def sha(data):return hashlib.sha256(data).hexdigest()
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def native(value):
    text=str(value)
    if len(text)>2 and text[1]==':':return Path('/mnt')/text[0].lower()/text[3:].replace('\\','/')
    return Path(text)
def norm(v):
    if isinstance(v,dict):return {k:norm(x) for k,x in v.items() if not(k.startswith('T_') or k.endswith('_ns') or k.endswith('_sha256') or 'backend' in k or k in ('result_hash','row_hash','execution_commit','certificate_path','certificate_hash','certificate_objective','search_counter_basis','qualification_scope','population','version_binding_id','version_binding_sha256'))}
    if isinstance(v,list):return [norm(x) for x in v]
    return v
def without_reuse(v):
    if isinstance(v,dict):return {k:without_reuse(x) for k,x in v.items() if not k.startswith('exact_cost_')}
    if isinstance(v,list):return [without_reuse(x) for x in v]
    return v

plan=read(root/'plan.json');binding=read(root/'backend_binding.json');report=read(root/'comparison.json')
assert report['status']=='PASSED' and plan['source_head']==args.commit
assert plan['baseline_commit']=='f4a31b1b85d2efdb6a86d3df4fa9f21fa2b22640'
assert plan['expected_method_workers']==9 and plan['attempts_per_cell_backend']==1
assert plan['planner_budget_seconds']==180 and plan['outer_watchdog_seconds']==195 and plan['formal_campaign'] is False
assert [c['instance_id'] for c in plan['cells']]==['C3-T4','D3-1','D3-2']
assert all(c['method']=='AP-D' for c in plan['cells'])
assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==args.commit
assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True).strip()
assert sha((root/'backend_binding.json').read_bytes())==plan['version_binding_sha256']
body=dict(binding);body.pop('binding_id')
assert binding['binding_id']==plan['version_binding_id']=='CMR_EXACT_COST_REUSE_V1-'+sha(canonical(body).encode())[:16]
body=dict(plan);body.pop('execution_identity')
assert plan['execution_identity']==args.commit+'+cmr-exact-cost-reuse-'+sha(canonical(body).encode())[:16]
assert len(plan['source_closure'])==73
for name,digest in plan['source_closure'].items():
    assert sha((root/'frozen_adapter'/name).read_bytes())==digest==sha((source/name).read_bytes()),name
historical=source/'experiments/cmr_ros2_suffix_reuse/evidence/20261022/raw_attempts.zip'
assert sha(historical.read_bytes())=='c9b7f66b55f4e149949c8a1f10e472ab8b47fd5b1484a52fba1ace1638c86440'
with zipfile.ZipFile(historical) as z:
    old_plan=json.loads(z.read('namespace/plan.json'))
    old_binding=json.loads(z.read('namespace/backend_binding.json'))
assert all(plan['source_closure'][n]==v for n,v in old_plan['source_closure'].items())
assert set(plan['source_closure'])-set(old_plan['source_closure'])=={
    'experiments/cmr_ros2_exact_cost_reuse/'+n for n in ('backend.py','search.py','fixtures.py','runner.py')}
for name in ('reference','ros2-v10'):assert binding['backends'][name]==old_binding['backends'][name]
inputs=read(root/'frozen_inputs_before.json')
assert inputs==read(root/'frozen_inputs_after.json')
for name,v in inputs.items():
    path=Path(name);assert path.stat().st_size==v['size'] and sha(path.read_bytes())==v['sha256'],name
receipt=read(native(plan['authority_receipt']))
authority=read(native(receipt['execution_binding']['path']))
rows=read(native(authority['manifest_path']));lookup={r['instance_id']:r for r in rows}
extra=min((r for r in rows if r['instance_id'].startswith('D3-') and r['instance_id']!='D3-1' and r['feasibility_class']=='FEASIBLE' and r['temporal_family']=='T4'),key=lambda r:(r['nominal_cartesian_state_count'],r['instance_id']))
assert extra['instance_id']=='D3-2'
assert plan['records']==[lookup[n] for n in ('C3-T4','D3-1','D3-2')]
for record in plan['records']:
    path=native(authority['benchmark_root'])/record['path']
    assert sha(path.read_bytes())==record['instance_sha256']
    assert str(path) in inputs
assert read(root/'fixtures.json')['status']=='PASSED'
assert read(root/'entry_fixture_details.json')['status']=='PASSED'
summary={};total_rounds=0
for cell in plan['cells']:
    key=cell['instance_id']+'_'+cell['method'];item=report['cells'][key];details={};values={}
    record=next(r for r in plan['records'] if r['instance_id']==cell['instance_id'])
    for name in ('reference','ros2-v10','ros2-v11'):
        directory=root/key/name;value=read(directory/'result.json');row=value['row'];values[name]=value
        assert row==item['backends'][name]['row']
        assert read(root/'dispatches'/(key+'__'+name+'.json'))==read(directory/'request.json')
        assert value['worker_exitcode']==0 and value['worker_alive_after_cleanup'] is False
        assert (directory/'worker.rc').read_text().strip()=='0'
        assert row['terminal_status']=='OPTIMALITY_CERTIFIED' and row['certificate_valid_for_terminal'] is True
        assert row['instance_id']==cell['instance_id'] and row['method']=='AP-D'
        assert row['instance_sha256']==record['instance_sha256']
        assert row['initial_S0']==cell['expected_initial_S0']
        assert row['execution_commit']==plan['execution_identity'] and row['version_binding_id']==plan['version_binding_id']
        assert row['planner_budget_seconds']==180 and row['outer_watchdog_seconds']==195
        body=dict(row);digest=body.pop('result_hash');assert sha(canonical(body).encode())==digest
        assert sha((directory/'certificates'/row['certificate_path']).read_bytes())==row['certificate_hash']
        replay=item['certificate_replays'][name]
        assert replay['status']=='PASS' and Fraction(replay['objective'])==Fraction(row['objective'])
        assert replay['certificate_hash']==row['certificate_hash']
        suffix=value['transport']['concrete_lasso']['suffix_edges']
        assert suffix and suffix[-1]['target']==suffix[0]['source']
        worker=read(directory/'worker_timing.json');parent=read(directory/'parent_timing.json')
        assert worker['entry_metrics']['schema_builds']==parent['entry_metrics']['schema_builds']==1
        assert worker['entry_metrics']['release_checks']==parent['entry_metrics']['release_checks']==1
        assert worker['entry_timing']['schema_validate_result']['calls']==1
        assert parent['entry_timing']['schema_validate_result']['calls']==2
        for field in ('preflight','load_instance','_payload_for_ai','persist_and_verify_certificate','certificate_fsync','certificate_sha256_file','certificate_verify_bound_certificate'):
            assert worker['core_timing'][field]['calls']==1
        assert all(worker['core_timing']['original_function_code_preserved'].values())
        cp=parent['entry_timing']['delivery_checkpoint'];interval=row['phase_intervals_ns']['ROS_result_delivery']
        assert interval[0]<=cp['release_started_ns']<cp['release_completed_ns']==row['terminal_completion_ns']==interval[1]
        assert row['T_total']==(row['terminal_completion_ns']-row['method_start_ns'])/1e9
        assert row['post_runner_delivery_seconds']>=parent['entry_timing']['release_check']['elapsed_ns']/1e9
        total_rounds+=len(row['rounds'])
        details[name]=dict(objective=row['objective'],rounds=len(row['rounds']),T_total=row['T_total'],T_search=row['T_search'],T_other=row['T_other'],T_input_preprocess=row['T_input_preprocess'],T_certification=row['T_certification'])
    old,new=values['ros2-v10'],values['ros2-v11']
    assert len({Fraction(v['row']['objective']) for v in values.values()})==1
    assert norm(old['row']['rounds'])==norm(new['row']['rounds']) and old['transport']==new['transport']
    assert norm(without_reuse(old['search_work']))==norm(without_reuse(new['search_work']))
    assert norm(old['build_work'])==norm(new['build_work'])
    counts={}
    for tag,value in (('v10',old),('v11',new)):
        builds=value['build_work'];n=len(builds)
        assert [b['full_ts_rebuild_calls'] for b in builds]==[1]+[0]*(n-1)
        assert [b['full_ts_cache_hits'] for b in builds]==[0]+[1]*(n-1)
        assert all(b['completed'] and b['projection_requests']==b['projection_computations']+b['projection_cache_hits'] for b in builds)
        for s in value['search_work']:
            assert s['tracemalloc_enabled'] and s['completed'] and not s['deadline_observed_exceeded']
            assert s['suffix_graph_requests']==s['exact_entry_searches']==len(s['suffix_lifts'])
            assert s['suffix_graph_requests']==s['suffix_graph_materializations']+s['suffix_graph_reuses']
            assert s['witness_key_requests']==s['witness_key_computations']+s['witness_key_cache_hits']
            assert s['suffix_graph_component_indexes']==s['suffix_graph_source_edge_scans']
            assert s['suffix_graph_dummy_rebinds']==s['suffix_graph_reuses']
            assert s['exact_cost_requests']==s['exact_cost_reuses']+s['exact_cost_fallbacks']
            if tag=='v10':
                assert s['exact_cost_reuses']==0 and s['exact_cost_requests']==s['exact_cost_fallbacks']
        for field in ('requests','reuses','fallbacks'):
            counts[tag+'_'+field]=sum(s['exact_cost_'+field] for s in value['search_work'])
        for field in ('requests','materializations','reuses','source_edge_scans','source_edges_examined','component_indexes','dummy_rebinds'):
            counts[tag+'_suffix_graph_'+field]=sum(s['suffix_graph_'+field] for s in value['search_work'])
    assert all(counts[k]==v for k,v in item['operation_counts'].items())
    assert counts['v11_requests']==counts['v10_requests'] and counts['v11_fallbacks']<=counts['v10_fallbacks']
    summary[key]=dict(details=details,operation_counts=counts,exact_searches_per_round=[s['exact_entry_searches'] for s in new['search_work']])
assert any(s['operation_counts']['v11_reuses']>0 for s in summary.values())
result=dict(status='PASSED',source_head=args.commit,version_binding_id=plan['version_binding_id'],version_binding_sha256=plan['version_binding_sha256'],backend_sha256=binding['backends']['ros2-v11']['backend_sha256'],source_files=73,frozen_inputs=len(inputs),actual_workers=9,actual_run_one=9,observed_internal_certificate_verifications=9,additional_persisted_replays_pass=9,total_rounds=total_rounds,source_and_control_identities_preserved=True,final_delivery_guard_charged=True,summary=summary,readback_solver_calls=0,readback_verifier_calls=0,dds_requests=0,provider_calls=0,formal_campaign=False)
args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,sort_keys=True))
