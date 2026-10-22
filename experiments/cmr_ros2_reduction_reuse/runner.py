"""Four-arm C3-T4/AP-D qualification, outside the frozen formal campaign."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_ap_ts_reuse import runner as base
from experiments.cmr_ros2_reduction_reuse import backend, fixtures

v7, adapter, original, write = base.v7, base.adapter, base.original, base.write
NAMES = ('reference', 'ros2-v7', 'ros2-v8', 'ros2-v9')
SCOPE = 'CMR_PROJECTION_WITNESS_REUSE_SINGLE_CELL_QUALIFICATION'
VERSION = 'CMR_PROJECTION_WITNESS_REUSE_V1'
BASELINE = 'f3232b0c13bc306a0e1e683dda7f83194bf2337f'
PINNED_V8_SHA = '5207a536472ad501184513c50c7b80641c186af36e24edd8fbd4f7f5576a2e34'
POLICY = dict(base.FULL_TS_POLICY, **{'ros2-v9': 'once_per_AP_method'})
OBSERVATION = 'V8 adds per-call counters only; all four share the guarded V8 entry; V9 enables two local caches'


def source_closure():
    result = base.source_closure()
    for name in ('builder.py', 'search.py', 'backend.py', 'fixtures.py', 'runner.py'):
        path = HERE/name
        result[str(path.relative_to(ROOT))] = v7.digest(path)
    return result


def implementations():
    result = base.implementations()
    if result['ros2-v8']['backend_sha256'] != PINNED_V8_SHA:
        raise ValueError('pinned V8 source identity changed')
    result['ros2-v9'] = dict(backend_id=backend.ID, backend_sha256=backend.identity())
    return result


def load_binding(path):
    value = json.loads(Path(path).read_bytes())
    body = dict(value); identifier = body.pop('binding_id')
    expected = VERSION+'-'+hashlib.sha256(v7.canonical(body).encode()).hexdigest()[:16]
    if (identifier != expected or value['schema'] != 'cmr-projection-witness-binding-v1'
            or value['source_closure'] != source_closure() or value['backends'] != implementations()
            or value['full_ts_policy'] != POLICY or value['observation_policy'] != OBSERVATION
            or value['semantic_contract_id'] != 'INITIAL_LABEL_V1'
            or value['objective'] != 'prefix_cost + 10*suffix_cost'
            or value['nonempty_accepting_suffix'] is not True
            or value['planner_budget_seconds'] != 180 or value['outer_watchdog_seconds'] != 195
            or value['formal_campaign'] is not False):
        raise ValueError('projection/witness binding identity mismatch')
    return value


def load_plan(path):
    plan = json.loads(Path(path).read_bytes())
    records, cells = base.selected(plan['authority_receipt'])
    body = dict(plan); execution = body.pop('execution_identity')
    binding = load_binding(plan['version_binding_path'])
    if (plan['schema'] != 'cmr-projection-witness-plan-v1' or plan['scope'] != SCOPE
            or plan['baseline_commit'] != BASELINE or plan['records'] != records or plan['cells'] != cells
            or plan['backends'] != list(NAMES) or plan['source_closure'] != source_closure()
            or plan['formal_campaign'] is not False or plan['expected_method_workers'] != 4
            or plan['attempts_per_cell_backend'] != 1 or plan['planner_budget_seconds'] != 180
            or plan['outer_watchdog_seconds'] != 195 or plan['observation_policy'] != OBSERVATION
            or execution != plan['source_head']+'+cmr-projection-witness-'+hashlib.sha256(v7.canonical(body).encode()).hexdigest()[:16]
            or v7.digest(Path(plan['version_binding_path'])) != plan['version_binding_sha256']
            or binding['binding_id'] != plan['version_binding_id']
            or any(binding[k] != plan[k] for k in ('receipt_sha256', 'original_execution_binding_sha256', 'manifest_sha256'))):
        raise ValueError('fixed four-arm plan changed')
    return plan


describe = adapter._clone_function(base.describe, dict(NAMES=NAMES, load_binding=load_binding))
request_for = adapter._clone_function(base.request_for, dict(describe=describe, SCOPE=SCOPE))


def configure_descriptor(formal, name, descriptor):
    capture = (backend.configure(formal, optimized=name == 'ros2-v9')
               if name in ('ros2-v8', 'ros2-v9') else v7.configure(formal, name, descriptor))
    if any(capture[k] != descriptor[k] for k in ('backend_id', 'backend_sha256')):
        raise ValueError('configured backend differs from binding')
    capture['backend_binding'] = descriptor
    return capture


class AttemptEntry(base.AttemptEntry):
    __init__ = adapter._clone_function(base.AttemptEntry.__init__, dict(load_plan=load_plan, NAMES=NAMES))
    describe = adapter._clone_function(base.AttemptEntry.describe, dict(NAMES=NAMES))
    request = adapter._clone_function(base.AttemptEntry.request, dict(SCOPE=SCOPE))
    release_check = adapter._clone_function(base.AttemptEntry.release_check, dict(source_closure=source_closure))
    proxy = adapter._clone_function(base.AttemptEntry.proxy, dict(NAMES=NAMES))

    def configure(self, formal, name, path):
        capture = configure_descriptor(formal, name, self.describe(path, name))
        base.instrument_formal(formal, self.core_timing)
        return capture

    def schema(self, receipt, name):
        schema = super().schema(receipt, name)
        if name == 'ros2-v9':
            schema.binding_id = 'CMR_PROJECTION_WITNESS_P2C_BACKEND_BINDING_V9'
        return schema


worker = adapter._clone_function(base.worker, dict(AttemptEntry=AttemptEntry))
isolated = adapter._clone_function(base.isolated, dict(AttemptEntry=AttemptEntry, HERE=HERE))


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    records, cells = base.selected(args.binding)
    authority = v7.v6.real.load_selection()
    closure = source_closure()
    head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    binding = dict(schema='cmr-projection-witness-binding-v1', source_closure=closure,
        semantic_contract_id='INITIAL_LABEL_V1', objective='prefix_cost + 10*suffix_cost',
        nonempty_accepting_suffix=True, full_ts_policy=POLICY, observation_policy=OBSERVATION,
        planner_budget_seconds=180, outer_watchdog_seconds=195, formal_campaign=False,
        backends=implementations(), receipt_sha256=authority['receipt_sha256'],
        original_execution_binding_sha256=authority['binding_sha256'], manifest_sha256=authority['manifest_sha256'])
    binding['binding_id'] = VERSION+'-'+hashlib.sha256(v7.canonical(binding).encode()).hexdigest()[:16]
    binding_path = args.output/'backend_binding.json'; write(binding_path, binding)
    plan = dict(schema='cmr-projection-witness-plan-v1', scope=SCOPE,
        qualification_id='CMR_PROJECTION_WITNESS_20261022', source_head=head,
        baseline_commit=BASELINE, records=records, cells=cells, source_closure=closure,
        selection_rule='Fixed existing C3-T4/AP-D six-round regression; no population claim',
        backends=list(NAMES), expected_method_workers=4, attempts_per_cell_backend=1,
        planner_budget_seconds=180, outer_watchdog_seconds=195, formal_campaign=False,
        observation_policy=OBSERVATION,
        authority_receipt=str(adapter._native_path(args.binding)), receipt_sha256=authority['receipt_sha256'],
        original_execution_binding_sha256=authority['binding_sha256'], manifest_sha256=authority['manifest_sha256'],
        version_binding_path=str(binding_path), version_binding_sha256=v7.digest(binding_path),
        version_binding_id=binding['binding_id'])
    plan['execution_identity'] = head+'+cmr-projection-witness-'+hashlib.sha256(v7.canonical(plan).encode()).hexdigest()[:16]
    write(args.output/'plan.json', plan)
    write(args.output/'frozen_inputs_before.json', v7.qualification.frozen_inputs(plan))
    for name in closure:
        destination = args.output/'frozen_adapter'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, destination)
    result = fixtures.run(args.kernel_root)
    if result['status'] != 'PASSED':
        raise ValueError('directed planner fixtures failed')
    write(args.output/'fixture_details.json', result)
    entry = AttemptEntry(args.output/'plan.json')
    receipt = json.loads(adapter._native_path(args.binding).read_bytes())
    schemas = {}
    for name in NAMES:
        request = request_for(plan, name)
        entry.validate(plan, request, name)
        changed = dict(request, planner_budget_seconds=179)
        try:
            entry.validate(plan, changed, name)
        except ValueError:
            pass
        else:
            raise ValueError('changed method budget was accepted')
        schema = entry.schema(receipt, name)
        if schema is not entry.schema(receipt, name):
            raise ValueError('schema was not reused in the same entry')
        schemas[name] = schema.binding_id
    entry.release_check()
    write(args.output/'entry_fixture_details.json', dict(status='PASSED', schemas=schemas,
        entry_metrics=entry.metrics, scope='offline entry checks; no worker, solver or verifier'))
    write(args.output/'fixtures.json', dict(status=result['status'], execution_identity=plan['execution_identity'],
        version_binding_id=plan['version_binding_id'], version_binding_sha256=plan['version_binding_sha256']))
    print(json.dumps(dict(prepared=True, workers=4, binding=plan['version_binding_id'])), flush=True)


def compare(report):
    ref = report['backends']['reference']
    for name in NAMES[1:]:
        v7.qualification.check_pair(ref, report['backends'][name], 'AP-D')
    old, new = (report['backends'][n] for n in ('ros2-v8', 'ros2-v9'))
    if old['transport'] != new['transport'] or v7.normalized(old['row']['rounds']) != v7.normalized(new['row']['rounds']):
        raise ValueError('complete scientific rounds or lasso changed')
    def scientific_work(value):
        if isinstance(value, dict):
            return {k: scientific_work(v) for k, v in value.items()
                    if not k.startswith(('projection_', 'witness_', 'position_map_'))}
        if isinstance(value, list):
            return [scientific_work(v) for v in value]
        return value
    if v7.normalized(scientific_work(old['search_work'])) != v7.normalized(scientific_work(new['search_work'])):
        raise ValueError('search decisions or heap/settlement trace changed')
    for value in (old, new):
        builds = value['build_work']
        if (len(builds) != 6 or [b['full_ts_rebuild_calls'] for b in builds] != [1,0,0,0,0,0]
                or [b['full_ts_cache_hits'] for b in builds] != [0,1,1,1,1,1]
                or any(not b['completed'] for b in builds)):
            raise ValueError('full TS once and complete refinement accounting changed')
        if not all(value['backend_configuration'][k] for k in ('original_loop_code_preserved','original_local_code_preserved','original_builder_global_preserved')):
            raise ValueError('frozen method bytecode/global changed')
    old_projections = sum(b['projection_computations'] for b in old['build_work'])
    new_projections = sum(b['projection_computations'] for b in new['build_work'])
    old_witness = sum(b['witness_key_computations'] for b in old['search_work'])
    new_witness = sum(b['witness_key_computations'] for b in new['search_work'])
    if not (new_projections < old_projections and new_witness < old_witness):
        raise ValueError('actual repeated computations did not decrease')
    report['operation_counts'] = dict(v8_projection_computations=old_projections,
        v9_projection_computations=new_projections, v8_witness_key_computations=old_witness,
        v9_witness_key_computations=new_witness)


def run(args):
    plan = load_plan(args.output/'plan.json')
    if (args.output/'dispatches').exists():
        raise ValueError('retained dispatch markers prevent a repeat')
    (args.output/'dispatches').mkdir()
    report = dict(schema='cmr-projection-witness-comparison-v1', status='RUNNING', backends={},
        certificate_replays={}, formal_campaign=False, provider_calls=0, dds_requests=0)
    try:
        for name in NAMES:
            request = request_for(plan, name)
            write(args.output/'dispatches'/(name+'.json'), request)
            value = isolated(request, args.binding, args.kernel_root, Path(plan['version_binding_path']), args.output/'plan.json', args.output/name)
            report['backends'][name] = value; write(args.output/'comparison.json', report)
            started = time.perf_counter_ns()
            report['certificate_replays'][name] = original.replay(plan, args.binding, args.kernel_root, value, args.output/name)
            write(args.output/name/'external_replay_timing.json', dict(elapsed_ns=time.perf_counter_ns()-started,
                scope='additional replay after delivered T_total; outside result row'))
            print(json.dumps(dict(backend=name, status=value['row']['terminal_status'],
                objective=value['row']['objective'], seconds=value['row']['T_total'])), flush=True)
        compare(report)
        report['status'] = 'PASSED'
    finally:
        after = v7.qualification.frozen_inputs(plan)
        write(args.output/'frozen_inputs_after.json', after)
        if after != json.loads((args.output/'frozen_inputs_before.json').read_bytes()) or source_closure() != plan['source_closure']:
            report['status'] = 'FAILED_SOURCE_OR_INPUT_CHANGED'
        write(args.output/'comparison.json', report)
    if report['status'] != 'PASSED':
        raise ValueError('four-arm comparison failed')


main = adapter._clone_function(base.main, dict(NAMES=NAMES, worker=worker, prepare=prepare, run=run))
if __name__ == '__main__':
    main()
