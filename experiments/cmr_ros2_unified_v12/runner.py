"""Explicit unified V12 entry with a fixed, isolated qualification population."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_compact_cost import runner as previous
from experiments.cmr_ros2_unified_v12 import backend

base, v7, adapter, original, write = previous.base, previous.v7, previous.adapter, previous.original, previous.write
NAMES = ('reference', 'ros2-v12')
METHODS = backend.METHODS
SCOPE = 'CMR_UNIFIED_V12_BOUNDED_QUALIFICATION'
VERSION = 'CMR_UNIFIED_V12_V1'
BASELINE = '0011e57e2828ad699c72bb2c25a1b15a3b181681'
PINNED_COMPONENT = '10f0c455ab1088e6ac702268489b96c5f26ffd84308987a7eef69555f7a190ee'
ANCHORS = ('A-T1-M0-A-S-BRANCH', 'B-D-BRANCH-S2', 'C3-T4')
ZERO = 'SYNTHETIC-UNIFIED-V12-ZERO-A'
SOURCE_NAMES = ('backend.py', 'runner.py', 'fixtures.py', 'dds.py', 'lifecycle.py', 'campaign.py', 'offline_chain.py')
RULE = 'Fixed A/B-S2/C3 each FULL/AP-D/DEP-D; D3-1/AP-D multi-entry; D1-1 each method; no outcome selection'


def canonical(value):
    return v7.canonical(value)


def source_closure():
    closure = previous.source_closure()
    if previous.backend.identity() != PINNED_COMPONENT:
        raise ValueError('frozen V12 component changed')
    for name in SOURCE_NAMES:
        path = HERE/name
        closure[str(path.relative_to(ROOT))] = v7.digest(path)
    # These execution repairs are part of the transport/runtime closure.
    return closure


def implementations():
    return dict(reference=previous.implementations()['reference'],
        **{'ros2-v12': dict(backend_id=backend.ID, backend_sha256=backend.identity())})


def selection(receipt_path):
    prior = v7.v6.real.load_selection()
    path = adapter._native_path(receipt_path)
    if v7.digest(path) != prior['receipt_sha256']:
        raise ValueError('receipt authority changed')
    receipt = json.loads(path.read_bytes())
    original_path = adapter._native_path(receipt['execution_binding']['path'])
    if v7.digest(original_path) != prior['binding_sha256']:
        raise ValueError('frozen execution binding changed')
    bound = json.loads(original_path.read_bytes())
    manifest = adapter._native_path(bound['manifest_path'])
    if v7.digest(manifest) != prior['manifest_sha256']:
        raise ValueError('frozen manifest changed')
    rows = json.loads(manifest.read_bytes())
    if len(rows) != 170:
        raise ValueError('Core170 population changed')
    records = {r['instance_id']:r for r in rows}
    pairs = [(name, method) for name in ANCHORS for method in METHODS]
    pairs += [('D3-1', 'AP-D')] + [('D1-1', method) for method in METHODS]
    sources = {(c['instance_id'],c['method']):c for c in bound['cells']}
    cells = []
    for name, method in pairs:
        cell = sources[name, method]
        cells.append(dict(instance_id=name, method=method, source_cell_id=cell['cell_id'],
            canonical_instance_index=cell['canonical_instance_index'], execution_index=cell['execution_index'],
            method_order_position=cell['method_order_position'], expected_initial_S0=bound['expected_initialization'][name][method]))
    return [records[name] for name in (*ANCHORS,'D3-1','D1-1')], cells, bound


def zero_material(core_record, bound):
    source = adapter._native_path(bound['benchmark_root'])/core_record['path']
    if v7.digest(source) != core_record['instance_sha256']:
        raise ValueError('zero parent input changed')
    payload = copy.deepcopy(json.loads(source.read_bytes()))
    payload['instance_id'] = ZERO
    count = 0
    for action in payload['model']['actions']:
        for row in action['cost_table']:
            row['value'] = '0'
            count += 1
    if not count:
        raise ValueError('zero parent has no action costs')
    return payload


def selected(plan):
    records, cells, bound = selection(plan['authority_receipt'])
    if plan['profile'] == 'main':
        return records, cells
    if plan['profile'] != 'synthetic-zero':
        raise ValueError('unknown fixed profile')
    parent = records[0]
    payload = zero_material(parent, bound)
    benchmark = Path(plan['synthetic_benchmark'])
    path = benchmark/'instances'/f'{ZERO}.json'
    if path.read_bytes() != serialized(payload):
        raise ValueError('synthetic zero payload changed')
    record = dict(parent, instance_id=ZERO, path=f'instances/{ZERO}.json',
        source='SYNTHETIC_QUALIFICATION', cohort='CONTROL', dataset_revision='SYNTHETIC_UNIFIED_V12_ZERO_V1',
        instance_sha256=v7.digest(path), model_sha256=hashlib.sha256(canonical(payload['model']).encode()).hexdigest(),
        parent_instance_sha256=parent['instance_sha256'])
    zero_cells = [dict(c, instance_id=ZERO, source_cell_id='synthetic-zero-'+c['method'])
                  for c in cells if c['instance_id']==ANCHORS[0]]
    manifest = benchmark/'manifests/manifest.json'
    if manifest.read_bytes() != serialized([record]):
        raise ValueError('synthetic zero manifest changed')
    return [record], zero_cells


def serialized(value):
    # Match the existing evidence writer exactly without changing old code.
    return (json.dumps(value, sort_keys=True, indent=2, default=str)+'\n').encode()


def load_binding(path):
    value = json.loads(Path(path).read_bytes())
    body = dict(value); identifier = body.pop('binding_id')
    if (identifier != VERSION+'-'+hashlib.sha256(canonical(body).encode()).hexdigest()[:16]
            or value['schema'] != 'cmr-unified-v12-binding-v1'
            or value['source_closure'] != source_closure() or value['backends'] != implementations()
            or value['methods'] != list(METHODS) or value['build_policy'] != backend.BUILD_POLICY
            or value['component_v12_sha256'] != PINNED_COMPONENT
            or value['qualification_only'] is not True
            or value['semantic_contract_id'] != 'INITIAL_LABEL_V1'
            or value['objective'] != 'prefix_cost + 10*suffix_cost'
            or value['nonempty_accepting_suffix'] is not True
            or value['planner_budget_seconds'] != 180 or value['outer_watchdog_seconds'] != 195
            or value['formal_campaign'] is not False):
        raise ValueError('unified V12 binding changed')
    return value


def load_plan(path):
    plan = json.loads(Path(path).read_bytes())
    records, cells = selected(plan)
    binding = load_binding(plan['version_binding_path'])
    body = dict(plan); execution = body.pop('execution_identity')
    authority_ref = v7.v6.real.load_selection()
    if (plan['schema'] != 'cmr-unified-v12-plan-v1' or plan['scope'] != SCOPE
            or plan['baseline_commit'] != BASELINE or plan['records'] != records or plan['cells'] != cells
            or plan['selection_rule'] != RULE or plan['source_closure'] != source_closure()
            or plan['backends'] != list(NAMES) or plan['expected_method_workers'] != 2*len(cells)
            or plan['attempts_per_cell_backend'] != 1 or plan['formal_campaign'] is not False
            or plan['planner_budget_seconds'] != 180 or plan['outer_watchdog_seconds'] != 195
            or execution != plan['source_head']+'+cmr-unified-v12-'+hashlib.sha256(canonical(body).encode()).hexdigest()[:16]
            or v7.digest(Path(plan['version_binding_path'])) != plan['version_binding_sha256']
            or binding['binding_id'] != plan['version_binding_id']
            or any(binding[k] != plan[k] for k in ('receipt_sha256','original_execution_binding_sha256','manifest_sha256'))
            or plan['receipt_sha256'] != authority_ref['receipt_sha256']
            or plan['original_execution_binding_sha256'] != authority_ref['binding_sha256']
            or plan['manifest_sha256'] != authority_ref['manifest_sha256']):
        raise ValueError('unified V12 plan changed')
    return plan


describe = adapter._clone_function(base.describe, dict(NAMES=NAMES, load_binding=load_binding))


def authority(plan, receipt, kernel):
    if plan['profile'] == 'main':
        return original.authority(plan, receipt, kernel)
    records, _ = selected(plan)
    parents, _, _ = selection(receipt)
    core = dict(plan, records=[parents[0]])
    formal, bound, manifest, _ = original.authority(core, receipt, kernel)
    bound = copy.deepcopy(bound)
    bound['benchmark_root'] = plan['synthetic_benchmark']
    bound['manifest_path'] = str(Path(plan['synthetic_benchmark'])/'manifests/manifest.json')
    bound['expected_initialization'][ZERO] = bound['expected_initialization'][ANCHORS[0]]
    return formal, bound, manifest, {r['instance_id']:r for r in records}


def make_request(plan, name, cell, descriptor):
    if name not in NAMES:
        raise ValueError('unknown explicit backend')
    record = next(r for r in plan['records'] if r['instance_id']==cell['instance_id'])
    return dict(copy.deepcopy(cell), instance_sha256=record['instance_sha256'], **descriptor,
        qualification_id=plan['qualification_id'], population=SCOPE, formal_campaign=False,
        execution_identity=plan['execution_identity'], planner_budget_seconds=180, outer_watchdog_seconds=195)


class AttemptEntry(previous.AttemptEntry):
    __init__ = adapter._clone_function(base.AttemptEntry.__init__, dict(load_plan=load_plan, NAMES=NAMES))
    describe = adapter._clone_function(base.AttemptEntry.describe, dict(NAMES=NAMES))
    proxy = adapter._clone_function(base.AttemptEntry.proxy, dict(NAMES=NAMES))
    release_check = adapter._clone_function(base.AttemptEntry.release_check, dict(source_closure=source_closure))

    def request(self, name, cell):
        return make_request(self.plan, name, cell, self.describe(self.binding_path, name))

    def validate(self, plan, request, name):
        cells = [c for c in self.plan['cells'] if (c['instance_id'],c['method']) == (request.get('instance_id'),request.get('method'))]
        if len(cells)!=1 or plan!=self.plan or request!=self.request(name,cells[0]):
            raise ValueError('unified request differs from plan')
        key = (request['instance_id'],request['method'])
        if hasattr(self,'cell_key') and self.cell_key != key:
            raise ValueError('one attempt cannot change cells')
        self.cell_key = key

    def configure(self, formal, name, path):
        descriptor = self.describe(path,name)
        capture = v7.configure(formal,name,descriptor) if name=='reference' else backend.configure(formal)
        if any(capture[k]!=descriptor[k] for k in ('backend_id','backend_sha256')):
            raise ValueError('configured unified backend differs from binding')
        capture['backend_binding'] = descriptor
        base.instrument_formal(formal,self.core_timing)
        return capture

    def schema(self, receipt, name):
        result = super().schema(receipt,name)
        if name=='ros2-v12':
            result.binding_id = 'CMR_UNIFIED_V12_P2C_BACKEND_BINDING'
        return result


def schema_for(receipt,name):
    if name=='reference':
        return v7.schema_for(receipt,name)
    if name!='ros2-v12':
        raise ValueError('unknown explicit backend')
    fn = adapter._clone_function(v7.schema_for, {'ID':backend.ID,'identity':backend.identity})
    schema = fn(receipt,'ros2-v7')
    schema.binding_id = 'CMR_UNIFIED_V12_P2C_BACKEND_BINDING'
    return schema


def request_for(plan,entry,cell,name):
    return entry.request(name,cell)


def worker(args):
    entry = AttemptEntry(args.plan)
    fn = adapter._clone_function(original.worker, dict(load_plan=lambda path:entry.plan,
        validate_request=entry.validate, backends=entry.proxy(), write=entry.guarded_write, authority=authority))
    try:
        return fn(args)
    finally:
        write(args.output/'worker_timing.json', dict(entry_metrics=entry.metrics,
            entry_timing=entry.timing, core_timing=entry.core_timing,
            version_binding_id=entry.plan['version_binding_id']))


def isolated(request,receipt,kernel,binding_path,plan_path,output):
    entry = AttemptEntry(plan_path)
    fn = adapter._clone_function(original.run_isolated, dict(HERE=HERE,
        load_plan=lambda path:entry.plan, validate_request=entry.validate,
        backends=entry.proxy(), write=entry.guarded_write, authority=authority,
        terminal_delivery=entry.checked_delivery))
    started = time.perf_counter_ns()
    value = fn(request,receipt,kernel,binding_path,plan_path,output)
    write(Path(output)/'parent_timing.json',dict(entry_metrics=entry.metrics,
        entry_timing=entry.timing,isolated_wall_ns=time.perf_counter_ns()-started,
        version_binding_id=entry.plan['version_binding_id']))
    return value


def candidate_isolated(args,plan,cell,output,*,backend_name='ros2-v12'):
    entry = AttemptEntry(args.plan if hasattr(args,'plan') else args.output/'plan.json')
    return isolated(entry.request(backend_name,cell),args.binding,args.kernel_root,
        Path(plan['version_binding_path']),entry.path,output)


replay = adapter._clone_function(original.replay, dict(authority=authority))


def frozen_inputs(plan):
    values = v7.v6.foundation.frozen_inputs()
    records, _, bound = selection(plan['authority_receipt'])
    for record in records:
        path = adapter._native_path(bound['benchmark_root'])/record['path']
        values[str(path)] = dict(size=path.stat().st_size,sha256=v7.digest(path))
    if plan['profile']=='synthetic-zero':
        for path in sorted(Path(plan['synthetic_benchmark']).rglob('*.json')):
            values[str(path)] = dict(size=path.stat().st_size,sha256=v7.digest(path))
    return values


def prepare(args):
    args.output.mkdir(parents=True,exist_ok=False)
    records,cells,bound = selection(args.binding)
    authority_ref = v7.v6.real.load_selection()
    head = subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    binding = dict(schema='cmr-unified-v12-binding-v1',source_closure=source_closure(),
        semantic_contract_id='INITIAL_LABEL_V1',objective='prefix_cost + 10*suffix_cost',
        nonempty_accepting_suffix=True,methods=list(METHODS),build_policy=backend.BUILD_POLICY,
        planner_budget_seconds=180,outer_watchdog_seconds=195,formal_campaign=False,qualification_only=True,
        component_v12_sha256=PINNED_COMPONENT,backends=implementations(),
        receipt_sha256=authority_ref['receipt_sha256'],original_execution_binding_sha256=authority_ref['binding_sha256'],
        manifest_sha256=authority_ref['manifest_sha256'])
    binding['binding_id'] = VERSION+'-'+hashlib.sha256(canonical(binding).encode()).hexdigest()[:16]
    version_path = args.output/'backend_binding.json';write(version_path,binding)
    plan = dict(schema='cmr-unified-v12-plan-v1',scope=SCOPE,profile=args.profile,baseline_commit=BASELINE,
        qualification_id='CMR_UNIFIED_V12_20261023',source_head=head,source_closure=source_closure(),
        authority_receipt=str(adapter._native_path(args.binding)),receipt_sha256=authority_ref['receipt_sha256'],
        original_execution_binding_sha256=authority_ref['binding_sha256'],manifest_sha256=authority_ref['manifest_sha256'],
        selection_rule=RULE,backends=list(NAMES),planner_budget_seconds=180,outer_watchdog_seconds=195,
        formal_campaign=False,attempts_per_cell_backend=1,version_binding_path=str(version_path),
        version_binding_id=binding['binding_id'],version_binding_sha256=v7.digest(version_path))
    if args.profile=='synthetic-zero':
        benchmark = args.output/'synthetic_benchmark'
        (benchmark/'instances').mkdir(parents=True);(benchmark/'manifests').mkdir()
        payload = zero_material(records[0],bound)
        # Use explicit bytes so derivation can be rechecked on every load.
        (benchmark/'instances'/f'{ZERO}.json').write_bytes(serialized(payload))
        record = dict(records[0],instance_id=ZERO,path=f'instances/{ZERO}.json',
            source='SYNTHETIC_QUALIFICATION',cohort='CONTROL',dataset_revision='SYNTHETIC_UNIFIED_V12_ZERO_V1',
            instance_sha256=v7.digest(benchmark/'instances'/f'{ZERO}.json'),
            model_sha256=hashlib.sha256(canonical(payload['model']).encode()).hexdigest(),
            parent_instance_sha256=records[0]['instance_sha256'])
        (benchmark/'manifests/manifest.json').write_bytes(serialized([record]))
        plan['synthetic_benchmark'] = str(benchmark)
    records,cells = selected(plan)
    plan.update(records=records,cells=cells,expected_method_workers=2*len(cells))
    plan['execution_identity'] = head+'+cmr-unified-v12-'+hashlib.sha256(canonical(plan).encode()).hexdigest()[:16]
    write(args.output/'plan.json',plan)
    write(args.output/'frozen_inputs_before.json',frozen_inputs(plan))
    for name in plan['source_closure']:
        dest = args.output/'frozen_adapter'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,dest)
    from experiments.cmr_ros2_unified_v12 import fixtures
    fixtures.run(args.output/'plan.json',args.binding,args.kernel_root,args.output/'fixtures.json')
    print(json.dumps(dict(prepared=True,workers=plan['expected_method_workers'],profile=args.profile)),flush=True)


def run(args):
    args.plan = args.output/'plan.json'
    plan = load_plan(args.plan)
    report = dict(schema='cmr-unified-v12-comparison-v1',status='RUNNING',cells=[],formal_campaign=False)
    try:
        for cell in plan['cells']:
            directory = args.output/(cell['instance_id']+'_'+cell['method']);directory.mkdir()
            item = dict(instance_id=cell['instance_id'],method=cell['method'],backends={},certificate_replays={})
            report['cells'].append(item)
            for name in NAMES:
                marker = directory/('dispatch_'+name+'.json')
                with marker.open('x') as stream:
                    json.dump(dict(backend=name,execution_identity=plan['execution_identity']),stream)
                value = candidate_isolated(args,plan,cell,directory/name,backend_name=name)
                item['backends'][name] = value;write(args.output/'comparison.json',report)
                item['certificate_replays'][name] = replay(plan,args.binding,args.kernel_root,value,directory/name)
                write(directory/name/'additional_replay.json',item['certificate_replays'][name])
                write(args.output/'comparison.json',report)
                print(json.dumps(dict(instance=cell['instance_id'],method=cell['method'],backend=name,
                    status=value['row']['terminal_status'],objective=value['row']['objective'])),flush=True)
            v7.qualification.check_pair(item['backends']['reference'],item['backends']['ros2-v12'],cell['method'])
            if plan['profile']=='synthetic-zero' and any(v['row']['objective']!='0' for v in item['backends'].values()):
                raise ValueError('legal zero objective rejected')
            item['status'] = 'PASSED'
        report['status'] = 'PASSED'
    except Exception:
        report.update(status='FAILED',traceback=traceback.format_exc())
        raise
    finally:
        after = frozen_inputs(plan);write(args.output/'frozen_inputs_after.json',after)
        if after != json.loads((args.output/'frozen_inputs_before.json').read_bytes()) or source_closure()!=plan['source_closure']:
            report['status'] = 'FAILED_SOURCE_OR_INPUT_CHANGED'
        write(args.output/'comparison.json',report)
    if report['status']!='PASSED':
        raise ValueError('unified comparison failed')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--binding',required=True);parser.add_argument('--kernel-root',required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--profile',choices=('main','synthetic-zero'),default='main')
    parser.add_argument('--worker',action='store_true');parser.add_argument('--backend',choices=NAMES)
    parser.add_argument('--request',type=Path);parser.add_argument('--version-binding',type=Path)
    parser.add_argument('--plan',type=Path);parser.add_argument('--instance-id');parser.add_argument('--method',choices=METHODS)
    args = parser.parse_args(argv);args.output=args.output.resolve()
    if not str(args.output).startswith('/tmp/'):
        raise ValueError('isolated attempts must use /tmp')
    try:
        if args.worker:
            worker(args)
        elif args.prepare:
            prepare(args)
        elif args.backend:
            plan=load_plan(args.plan)
            cell=next(c for c in plan['cells'] if (c['instance_id'],c['method'])==(args.instance_id,args.method))
            candidate_isolated(args,plan,cell,args.output,backend_name=args.backend)
        else:
            run(args)
        return 0
    except Exception:
        args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'error.txt').write_text(traceback.format_exc())
        traceback.print_exc()
        return 1


if __name__=='__main__':
    raise SystemExit(main())
