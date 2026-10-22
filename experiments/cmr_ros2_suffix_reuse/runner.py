"""Three fixed AP-D cells, three backends, one attempt per cell/backend."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from experiments.cmr_ros2_reduction_reuse import runner as previous
from experiments.cmr_ros2_suffix_reuse import backend,fixtures

base=previous.base
v7,adapter,original,write=previous.v7,previous.adapter,previous.original,previous.write
NAMES=('reference','ros2-v9','ros2-v10')
BASELINE='d3f12e932f5eb6ceda1dc42686d6fffdb2bd144e'
PINNED_V9_SHA='f4fb6a2dff6fe4fe881b2909dbeb70b254977fa7c74fa39d06863141cd001259'
SCOPE='CMR_SUFFIX_GRAPH_REUSE_THREE_CELL_QUALIFICATION'
VERSION='CMR_SUFFIX_GRAPH_REUSE_V1'
RULE=('C3-T4/AP-D anchor and historical multi-entry D3-1/AP-D; add minimum '
      '(Cartesian size, ID) feasible D3/T4 excluding D3-1, before candidate outcomes. '
      'Three cells, nine fresh workers; no formal population claim.')
OBSERVATION='V9 adds suffix construction counters only; V10 enables solve-local graph reuse; V9 projection/witness/full-TS reuse stays enabled'


def selected(receipt_path):
    prior=v7.v6.real.load_selection()
    path=adapter._native_path(receipt_path)
    if v7.digest(path)!=prior['receipt_sha256']:
        raise ValueError('receipt authority changed')
    receipt=json.loads(path.read_bytes())
    binding_path=adapter._native_path(receipt['execution_binding']['path'])
    if v7.digest(binding_path)!=prior['binding_sha256']:
        raise ValueError('original binding changed')
    bound=json.loads(binding_path.read_bytes())
    manifest=adapter._native_path(bound['manifest_path'])
    if v7.digest(manifest)!=prior['manifest_sha256']:
        raise ValueError('manifest changed')
    rows=json.loads(manifest.read_bytes())
    records={r['instance_id']:r for r in rows}
    sibling=min((r for r in rows if r['instance_id'].startswith('D3-')
        and r['instance_id']!='D3-1' and r['feasibility_class']=='FEASIBLE' and r['temporal_family']=='T4'),
        key=lambda r:(r['nominal_cartesian_state_count'],r['instance_id']))
    if len(rows)!=170 or sibling['instance_id']!='D3-2':
        raise ValueError('fixed metadata extension changed')
    chosen=[records[n] for n in ('C3-T4','D3-1',sibling['instance_id'])]
    source_cells={(c['instance_id'],c['method']):c for c in bound['cells']}
    cells=[]
    for record in chosen:
        name=record['instance_id'];source=source_cells[(name,'AP-D')]
        cells.append(dict(instance_id=name,method='AP-D',source_cell_id=source['cell_id'],
            canonical_instance_index=source['canonical_instance_index'],execution_index=source['execution_index'],
            method_order_position=source['method_order_position'],expected_initial_S0=bound['expected_initialization'][name]['AP-D']))
    return chosen,cells


def source_closure():
    result=previous.source_closure()
    for name in ('backend.py','search.py','fixtures.py','runner.py'):
        p=HERE/name;result[str(p.relative_to(ROOT))]=v7.digest(p)
    return result


def implementations():
    prior=previous.implementations()
    if prior['ros2-v9']['backend_sha256']!=PINNED_V9_SHA:
        raise ValueError('pinned V9 source changed')
    return dict(reference=prior['reference'],**{'ros2-v9':prior['ros2-v9'],
        'ros2-v10':dict(backend_id=backend.ID,backend_sha256=backend.identity())})


def load_binding(path):
    value=json.loads(Path(path).read_bytes());body=dict(value);identifier=body.pop('binding_id')
    expected=VERSION+'-'+hashlib.sha256(v7.canonical(body).encode()).hexdigest()[:16]
    if (identifier!=expected or value['schema']!='cmr-suffix-reuse-binding-v1'
            or value['source_closure']!=source_closure() or value['backends']!=implementations()
            or value['observation_policy']!=OBSERVATION
            or value['semantic_contract_id']!='INITIAL_LABEL_V1' or value['objective']!='prefix_cost + 10*suffix_cost'
            or value['nonempty_accepting_suffix'] is not True or value['full_ts_policy']!='one full TS per AP-D invocation for V9/V10'
            or value['planner_budget_seconds']!=180 or value['outer_watchdog_seconds']!=195 or value['formal_campaign'] is not False):
        raise ValueError('suffix reuse binding identity mismatch')
    return value


def load_plan(path):
    plan=json.loads(Path(path).read_bytes());records,cells=selected(plan['authority_receipt'])
    body=dict(plan);execution=body.pop('execution_identity');binding=load_binding(plan['version_binding_path'])
    if (plan['schema']!='cmr-suffix-reuse-plan-v1' or plan['scope']!=SCOPE or plan['baseline_commit']!=BASELINE
            or plan['records']!=records or plan['cells']!=cells or plan['selection_rule']!=RULE
            or plan['source_closure']!=source_closure() or plan['backends']!=list(NAMES)
            or plan['observation_policy']!=OBSERVATION or plan['expected_method_workers']!=9
            or plan['attempts_per_cell_backend']!=1 or plan['planner_budget_seconds']!=180
            or plan['outer_watchdog_seconds']!=195 or plan['formal_campaign'] is not False
            or execution!=plan['source_head']+'+cmr-suffix-reuse-'+hashlib.sha256(v7.canonical(body).encode()).hexdigest()[:16]
            or v7.digest(Path(plan['version_binding_path']))!=plan['version_binding_sha256']
            or binding['binding_id']!=plan['version_binding_id']
            or any(binding[k]!=plan[k] for k in ('receipt_sha256','original_execution_binding_sha256','manifest_sha256'))):
        raise ValueError('fixed three-cell plan changed')
    return plan


describe=adapter._clone_function(base.describe,dict(NAMES=NAMES,load_binding=load_binding))


def make_request(plan,name,cell,descriptor):
    record=next(r for r in plan['records'] if r['instance_id']==cell['instance_id'])
    return dict(copy.deepcopy(cell),instance_sha256=record['instance_sha256'],**descriptor,
        qualification_id=plan['qualification_id'],population=SCOPE,formal_campaign=False,
        execution_identity=plan['execution_identity'],planner_budget_seconds=180,outer_watchdog_seconds=195)


class AttemptEntry(previous.AttemptEntry):
    __init__=adapter._clone_function(base.AttemptEntry.__init__,dict(load_plan=load_plan,NAMES=NAMES))
    describe=adapter._clone_function(base.AttemptEntry.describe,dict(NAMES=NAMES))
    proxy=adapter._clone_function(base.AttemptEntry.proxy,dict(NAMES=NAMES))
    release_check=adapter._clone_function(base.AttemptEntry.release_check,dict(source_closure=source_closure))

    def request(self,name,cell):
        return make_request(self.plan,name,cell,self.describe(self.binding_path,name))

    def validate(self,plan,request,name):
        cells=[c for c in self.plan['cells'] if (c['instance_id'],c['method'])==(request.get('instance_id'),request.get('method'))]
        if len(cells)!=1 or plan!=self.plan or request!=self.request(name,cells[0]):
            raise ValueError('entry request or cell changed')
        key=(request['instance_id'],request['method'])
        if hasattr(self,'cell_key') and self.cell_key!=key:
            raise ValueError('attempt entry cannot change cells')
        self.cell_key=key

    def configure(self,formal,name,path):
        descriptor=self.describe(path,name)
        capture=(v7.configure(formal,name,descriptor) if name=='reference'
                 else backend.configure(formal,optimized=name=='ros2-v10'))
        if any(capture[k]!=descriptor[k] for k in ('backend_id','backend_sha256')):
            raise ValueError('configured backend differs from entry')
        capture['backend_binding']=descriptor
        base.instrument_formal(formal,self.core_timing)
        return capture

    def schema(self,receipt,name):
        schema=super().schema(receipt,name)
        if name=='ros2-v10':
            schema.binding_id='CMR_SUFFIX_REUSE_P2C_BACKEND_BINDING_V10'
        return schema


worker=adapter._clone_function(base.worker,dict(AttemptEntry=AttemptEntry))
isolated=adapter._clone_function(base.isolated,dict(AttemptEntry=AttemptEntry,HERE=HERE))


def prepare(args):
    args.output.mkdir(parents=True,exist_ok=False)
    records,cells=selected(args.binding);authority=v7.v6.real.load_selection();closure=source_closure()
    head=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    binding=dict(schema='cmr-suffix-reuse-binding-v1',source_closure=closure,
        semantic_contract_id='INITIAL_LABEL_V1',objective='prefix_cost + 10*suffix_cost',nonempty_accepting_suffix=True,
        full_ts_policy='one full TS per AP-D invocation for V9/V10',observation_policy=OBSERVATION,
        planner_budget_seconds=180,outer_watchdog_seconds=195,formal_campaign=False,backends=implementations(),
        receipt_sha256=authority['receipt_sha256'],original_execution_binding_sha256=authority['binding_sha256'],manifest_sha256=authority['manifest_sha256'])
    binding['binding_id']=VERSION+'-'+hashlib.sha256(v7.canonical(binding).encode()).hexdigest()[:16]
    binding_path=args.output/'backend_binding.json';write(binding_path,binding)
    plan=dict(schema='cmr-suffix-reuse-plan-v1',scope=SCOPE,qualification_id='CMR_SUFFIX_REUSE_20261022',
        source_head=head,baseline_commit=BASELINE,records=records,cells=cells,selection_rule=RULE,
        source_closure=closure,backends=list(NAMES),expected_method_workers=9,attempts_per_cell_backend=1,
        planner_budget_seconds=180,outer_watchdog_seconds=195,formal_campaign=False,observation_policy=OBSERVATION,
        authority_receipt=str(adapter._native_path(args.binding)),receipt_sha256=authority['receipt_sha256'],
        original_execution_binding_sha256=authority['binding_sha256'],manifest_sha256=authority['manifest_sha256'],
        version_binding_path=str(binding_path),version_binding_sha256=v7.digest(binding_path),version_binding_id=binding['binding_id'])
    plan['execution_identity']=head+'+cmr-suffix-reuse-'+hashlib.sha256(v7.canonical(plan).encode()).hexdigest()[:16]
    write(args.output/'plan.json',plan)
    write(args.output/'frozen_inputs_before.json',v7.qualification.frozen_inputs(plan))
    for name in closure:
        target=args.output/'frozen_adapter'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    result=fixtures.run(args.kernel_root)
    if result['status']!='PASSED':raise ValueError('directed suffix fixtures failed')
    write(args.output/'fixture_details.json',result)
    receipt=json.loads(adapter._native_path(args.binding).read_bytes());entries=[]
    for cell in cells:
        entry=AttemptEntry(args.output/'plan.json')
        for name in NAMES:
            req=entry.request(name,cell);entry.validate(plan,req,name)
            try:entry.validate(plan,dict(req,planner_budget_seconds=179),name)
            except ValueError:pass
            else:raise ValueError('changed budget accepted')
            schema=entry.schema(receipt,name)
            if schema is not entry.schema(receipt,name):raise ValueError('same-entry schema not reused')
        other=next(c for c in cells if c['instance_id']!=cell['instance_id'])
        try:entry.validate(plan,entry.request(NAMES[0],other),NAMES[0])
        except ValueError:pass
        else:raise ValueError('attempt accepted a different cell')
        entry.release_check();entries.append(dict(cell=cell['instance_id'],metrics=entry.metrics))
    write(args.output/'entry_fixture_details.json',dict(status='PASSED',entries=entries))
    write(args.output/'fixtures.json',dict(status='PASSED',execution_identity=plan['execution_identity'],
        version_binding_id=plan['version_binding_id'],version_binding_sha256=plan['version_binding_sha256']))
    print(json.dumps(dict(prepared=True,workers=9,binding=plan['version_binding_id'])),flush=True)


def compare_cell(cell):
    ref,old,new=(cell['backends'][n] for n in NAMES)
    for value in (old,new):v7.qualification.check_pair(ref,value,'AP-D')
    if old['transport']!=new['transport'] or v7.normalized(old['row']['rounds'])!=v7.normalized(new['row']['rounds']):
        raise ValueError('complete scientific rounds or lasso changed')
    def without_counters(v):
        if isinstance(v,dict):return {k:without_counters(x) for k,x in v.items() if not k.startswith('suffix_graph_')}
        if isinstance(v,list):return [without_counters(x) for x in v]
        return v
    if v7.normalized(without_counters(old['search_work']))!=v7.normalized(without_counters(new['search_work'])):
        raise ValueError('search decisions or heap/settlement changed')
    if v7.normalized(old['build_work'])!=v7.normalized(new['build_work']):
        raise ValueError('V9 projection/full-TS build work changed')
    for value in (old,new):
        builds=value['build_work'];rounds=len(value['row']['rounds'])
        if ([b['full_ts_rebuild_calls'] for b in builds]!=[1]+[0]*(rounds-1)
                or [b['full_ts_cache_hits'] for b in builds]!=[0]+[1]*(rounds-1)):
            raise ValueError('full TS reuse changed')
        if not all(value['backend_configuration'][k] for k in ('original_loop_code_preserved','original_local_code_preserved','original_builder_global_preserved')):
            raise ValueError('frozen method bytecode/global changed')
    counts={}
    for label,value in (('v9',old),('v10',new)):
        for key in ('requests','materializations','reuses','source_edge_scans','component_indexes','dummy_rebinds'):
            counts[label+'_'+key]=sum(s['suffix_graph_'+key] for s in value['search_work'])
    if counts['v9_requests']!=counts['v10_requests'] or counts['v10_materializations']>counts['v9_materializations']:
        raise ValueError('suffix graph accounting changed')
    cell['operation_counts']=counts


def run(args):
    plan=load_plan(args.output/'plan.json')
    if (args.output/'dispatches').exists():raise ValueError('retained dispatches forbid a repeat')
    (args.output/'dispatches').mkdir()
    report=dict(schema='cmr-suffix-reuse-comparison-v1',status='RUNNING',cells={},formal_campaign=False,dds_requests=0,provider_calls=0)
    try:
        for cell in plan['cells']:
            key=cell['instance_id']+'_'+cell['method'];item=dict(backends={},certificate_replays={});report['cells'][key]=item
            for name in NAMES:
                req=make_request(plan,name,cell,describe(plan['version_binding_path'],name))
                write(args.output/'dispatches'/(key+'__'+name+'.json'),req)
                out=args.output/key/name
                value=isolated(req,args.binding,args.kernel_root,Path(plan['version_binding_path']),args.output/'plan.json',out)
                item['backends'][name]=value;write(args.output/'comparison.json',report)
                started=time.perf_counter_ns()
                item['certificate_replays'][name]=original.replay(plan,args.binding,args.kernel_root,value,out)
                write(out/'external_replay_timing.json',dict(elapsed_ns=time.perf_counter_ns()-started,scope='additional replay after delivered T_total'))
                print(json.dumps(dict(cell=key,backend=name,status=value['row']['terminal_status'],objective=value['row']['objective'],seconds=value['row']['T_total'])),flush=True)
            compare_cell(item)
        if not any(c['operation_counts']['v10_materializations']<c['operation_counts']['v9_materializations'] for c in report['cells'].values()):
            raise ValueError('no real suffix graph reuse was observed')
        report['status']='PASSED'
    finally:
        after=v7.qualification.frozen_inputs(plan);write(args.output/'frozen_inputs_after.json',after)
        if after!=json.loads((args.output/'frozen_inputs_before.json').read_bytes()) or source_closure()!=plan['source_closure']:
            report['status']='FAILED_SOURCE_OR_INPUT_CHANGED'
        write(args.output/'comparison.json',report)
    if report['status']!='PASSED':raise ValueError('three-cell comparison failed')


main=adapter._clone_function(base.main,dict(NAMES=NAMES,worker=worker,prepare=prepare,run=run))
if __name__=='__main__':main()
