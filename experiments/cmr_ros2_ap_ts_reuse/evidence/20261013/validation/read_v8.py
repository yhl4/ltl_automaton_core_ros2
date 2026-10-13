"""Standard-library readback of the one-cell AP TS reuse experiment."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path('/tmp/cmr_v8_ap_ts_reuse_20261013')
SOURCE=Path('/tmp/cmr_v8_ap_ts_source_db82366_20261013')
OUT=Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v8_ap_ts_reuse_20261013')
BASELINE='5ac80ee5f8e622a7f929eb848627c9a5ebf6cf01'
def read(p): return json.loads(p.read_bytes())
def sha(raw): return hashlib.sha256(raw).hexdigest()
def canonical(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def normalized(v):
    if isinstance(v,dict):
        return {k:normalized(x) for k,x in v.items() if not (
            k.startswith('T_') or k.endswith('_ns') or k.endswith('_sha256') or 'backend' in k
            or k in ('result_hash','row_hash','execution_commit','certificate_path','certificate_hash',
                     'certificate_objective','search_counter_basis','qualification_scope','population',
                     'version_binding_id','version_binding_sha256'))}
    if isinstance(v,list): return [normalized(x) for x in v]
    return v
plan=read(ROOT/'plan.json'); binding=read(ROOT/'backend_binding.json'); report=read(ROOT/'comparison.json')
assert report['status']=='PASSED' and plan['formal_campaign'] is False
assert plan['source_head']==subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()
assert not subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain'],text=True).strip()
assert plan['baseline_commit']==BASELINE
body=dict(binding); body.pop('binding_id')
assert binding['binding_id']=='CMR_AP_TS_REUSE_V1-'+sha(canonical(body).encode())[:16]
assert binding['binding_id']==plan['version_binding_id']
assert sha((ROOT/'backend_binding.json').read_bytes())==plan['version_binding_sha256']
body=dict(plan); body.pop('execution_identity')
assert plan['execution_identity']==plan['source_head']+'+cmr-ap-ts-reuse-'+sha(canonical(body).encode())[:16]
assert binding['full_ts_rebuild_every_round'] is False
assert binding['nonempty_accepting_suffix'] is True and binding['objective']=='prefix_cost + 10*suffix_cost'
assert binding['semantic_contract_id']=='INITIAL_LABEL_V1'
assert plan['planner_budget_seconds']==binding['planner_budget_seconds']==180
assert plan['outer_watchdog_seconds']==binding['outer_watchdog_seconds']==195
assert len(plan['source_closure'])==60 and binding['source_closure']==plan['source_closure']
for name,digest in plan['source_closure'].items():
    assert sha((SOURCE/name).read_bytes())==digest==sha((ROOT/'frozen_adapter'/name).read_bytes()),name
    if not name.startswith('experiments/cmr_ros2_ap_ts_reuse/'):
        assert subprocess.check_output(['git','-C',str(SOURCE),'show',BASELINE+':'+name])==(SOURCE/name).read_bytes(),name
before=read(ROOT/'frozen_inputs_before.json'); after=read(ROOT/'frozen_inputs_after.json')
assert before==after
for name,value in before.items():
    p=Path(name); assert p.stat().st_size==value['size'] and sha(p.read_bytes())==value['sha256'],name
assert read(ROOT/'fixture_details.json')['status']=='PASSED'
fake=read(OUT/'fake_precheck_assertions.json')
assert fake['status']=='PASSED' and fake['solver_calls']==fake['run_one_calls']==0
results={}; stages=('T_input_preprocess','T_initialization','T_full_ts','T_reduction','T_product',
                    'T_search','T_concretization','T_certification','T_refinement','T_logging','T_other','T_total')
for name in ('reference','ros2-v7','ros2-v8'):
    d=ROOT/name; value=read(d/'result.json'); row=value['row']; raw=read(d/'worker_result.json')
    assert value['row']==report['backends'][name]['row']
    assert value['worker_exitcode']==0 and value['worker_alive_after_cleanup'] is False
    assert (d/'worker.rc').read_text().strip()=='0'
    assert raw['worker_pid']==value['worker_pid'] and raw['backend_binding']==value['backend_binding']
    assert row['terminal_status']=='OPTIMALITY_CERTIFIED' and Fraction(row['objective'])==12
    assert row['instance_id']=='C3-T4' and row['method']=='AP-D' and row['initial_S0']==[3]
    assert row['instance_sha256']==row['benchmark_payload_sha256']==plan['records'][0]['instance_sha256']
    assert row['execution_commit']==plan['execution_identity'] and row['version_binding_id']==plan['version_binding_id']
    assert row['planner_budget_seconds']==180 and row['outer_watchdog_seconds']==195
    assert len(row['rounds'])==6 and row['final_precision']==[0,1,2,3,4,5]
    body=dict(row); hashed=body.pop('result_hash'); assert sha(canonical(body).encode())==hashed
    cert=d/'certificates'/row['certificate_path']; assert sha(cert.read_bytes())==row['certificate_hash']
    replay=report['certificate_replays'][name]
    assert replay['status']=='PASS' and Fraction(replay['objective'])==12 and replay['certificate_hash']==row['certificate_hash']
    suffix=value['transport']['concrete_lasso']['suffix_edges']
    assert suffix and suffix[-1]['target']==suffix[0]['source']
    if name!='reference':
        assert len(value['build_work'])==6 and all(b['completed'] for b in value['build_work'])
        assert [b['precision'] for b in value['build_work']]==[r['S_k'] for r in row['rounds']]
        assert all(value['backend_configuration'][k] for k in ('original_loop_code_preserved',
               'original_local_code_preserved','original_builder_global_preserved'))
        assert all(w['completed'] and w['tracemalloc_enabled'] and not w['deadline_observed_exceeded'] for w in value['search_work'])
    results[name]={k:row[k] for k in stages}
old=report['backends']['ros2-v7']; new=report['backends']['ros2-v8']
assert normalized(old['row']['rounds'])==normalized(new['row']['rounds'])
assert normalized(old['search_work'])==normalized(new['search_work'])
assert old['transport']==new['transport']
assert [b['full_ts_rebuild_calls'] for b in old['build_work']]==[1]*6
assert [b['full_ts_rebuild_calls'] for b in new['build_work']]==[1,0,0,0,0,0]
assert [b['full_ts_cache_hits'] for b in new['build_work']]==[0,1,1,1,1,1]
assert {b['full_ts_source_states'] for b in new['build_work']}=={64}
assert {b['full_ts_source_edges'] for b in new['build_work']}=={384}
assert new['row']['T_full_ts']==sum(r['timings']['T_full_ts'] for r in new['row']['rounds'])
delta={k:results['ros2-v8'][k]-results['ros2-v7'][k] for k in stages}
result=dict(status='PASSED',schema='cmr-ap-ts-reuse-readback-v1',source_head=plan['source_head'],
    baseline_commit=BASELINE,version_binding_id=plan['version_binding_id'],
    version_binding_sha256=plan['version_binding_sha256'],source_files=60,frozen_inputs=len(before),
    actual_workers=3,actual_run_one=3,persisted_optimal_replays_pass=3,readback_verifier_calls=0,
    full_ts_builds=dict(v7=6,v8=1),v8_cache_hits=5,results=results,phase_delta_v8_minus_v7=delta,
    full_ts_decrease_percent=100*(1-results['ros2-v8']['T_full_ts']/results['ros2-v7']['T_full_ts']),
    total_increase_percent=100*(results['ros2-v8']['T_total']/results['ros2-v7']['T_total']-1),
    solver_imported=False,dds_requests=0,provider_calls=0,formal_campaign=False,
    verdict='semantic qualification passed; complete runtime improvement not demonstrated by this observation')
(OUT/'readback.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,sort_keys=True))
