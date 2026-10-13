"""One C3-T4/AP-D comparison: reference, unchanged V7, opt-in V8.

Reuse the qualified process lifecycle, original run_one, schema and certificate
gate. This is a bounded implementation experiment outside the formal ledger.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_ap_ts_reuse import backend, fixtures
from experiments.cmr_ros2_search_entry import runner as v7

NAMES = ('reference', 'ros2-v7', 'ros2-v8')
TARGET = ('C3-T4', 'AP-D')
SCOPE = 'CMR_AP_FULL_TS_REUSE_SINGLE_CELL_QUALIFICATION'
VERSION = 'CMR_AP_TS_REUSE_V1'
BASELINE = '5ac80ee5f8e622a7f929eb848627c9a5ebf6cf01'
FULL_TS_POLICY = {'reference': 'every_round', 'ros2-v7': 'every_round',
                  'ros2-v8': 'once_per_AP_method; FULL/DEP-D every_round'}
CACHE_SCOPE = 'one static bound model in one method invocation; disposed in finally'
adapter, original, write = v7.adapter, v7.old_runner, v7.write


def source_closure():
    value = v7.source_closure()
    for name in ('builder.py', 'backend.py', 'fixtures.py', 'runner.py'):
        value[str((HERE / name).relative_to(ROOT))] = v7.digest(HERE / name)
    return value


def implementations():
    old = v7.implementations()
    return dict(reference=old['reference'], **{'ros2-v7': old['ros2-v7'],
        'ros2-v8': dict(backend_id=backend.ID, backend_sha256=backend.identity())})


def selected(receipt):
    prior = v7.acceptance.selection(receipt)
    record = next(r for r in prior['records'] if r['instance_id'] == TARGET[0])
    cell = next(c for c in prior['cells'] if (c['instance_id'], c['method']) == TARGET)
    return [record], [cell]


def load_binding(path):
    value = json.loads(Path(path).read_bytes())
    body = dict(value); binding_id = body.pop('binding_id')
    expected = VERSION + '-' + hashlib.sha256(v7.canonical(body).encode()).hexdigest()[:16]
    if (binding_id != expected or value['source_closure'] != source_closure()
            or value['schema'] != 'cmr-ap-ts-reuse-binding-v1'
            or value['backends'] != implementations()
            or value['full_ts_rebuild_every_round'] is not False
            or value['full_ts_policy'] != FULL_TS_POLICY or value['cache_scope'] != CACHE_SCOPE
            or value['semantic_contract_id'] != 'INITIAL_LABEL_V1'
            or value['objective'] != 'prefix_cost + 10*suffix_cost'
            or value['nonempty_accepting_suffix'] is not True
            or value['planner_budget_seconds'] != 180 or value['outer_watchdog_seconds'] != 195
            or value['formal_campaign'] is not False):
        raise ValueError('AP reuse binding identity/policy mismatch')
    return value


def load_plan(path):
    plan = json.loads(Path(path).read_bytes())
    records, cells = selected(plan['authority_receipt'])
    body = dict(plan); execution = body.pop('execution_identity')
    binding = load_binding(plan['version_binding_path'])
    if (plan['schema'] != 'cmr-ap-ts-reuse-plan-v1' or plan['scope'] != SCOPE
            or plan['baseline_commit'] != BASELINE or plan['cells'] != cells or plan['records'] != records
            or plan['backends'] != list(NAMES) or plan['source_closure'] != source_closure()
            or plan['formal_campaign'] is not False or plan['expected_method_workers'] != 3
            or plan['attempts_per_cell_backend'] != 1 or plan['planner_budget_seconds'] != 180
            or plan['outer_watchdog_seconds'] != 195
            or execution != plan['source_head'] + '+cmr-ap-ts-reuse-' + hashlib.sha256(v7.canonical(body).encode()).hexdigest()[:16]
            or v7.digest(Path(plan['version_binding_path'])) != plan['version_binding_sha256']
            or binding['binding_id'] != plan['version_binding_id']
            or binding['source_closure'] != plan['source_closure']
            or any(binding[k] != plan[k] for k in ('receipt_sha256', 'original_execution_binding_sha256', 'manifest_sha256'))):
        raise ValueError('fixed AP reuse plan changed')
    return plan


def describe(path, name):
    if name not in NAMES:
        raise ValueError('backend outside AP reuse comparison')
    binding = load_binding(path)
    return dict(backend=name, **binding['backends'][name],
        version_binding_id=binding['binding_id'], version_binding_sha256=v7.digest(Path(path)))


def schema_for(receipt, name):
    if name != 'ros2-v8':
        return v7.schema_for(receipt, name)
    fn = adapter._clone_function(v7.schema_for, {'ID': backend.ID, 'identity': backend.identity})
    schema = fn(receipt, 'ros2-v7')
    schema.binding_id = 'CMR_AP_TS_REUSE_P2C_BACKEND_BINDING_V8'
    return schema


def configure(formal, name, path):
    descriptor = describe(path, name)
    capture = (backend.configure(formal) if name == 'ros2-v8'
               else v7.configure(formal, name, descriptor))
    if any(capture[k] != descriptor[k] for k in ('backend_id', 'backend_sha256')):
        raise ValueError('configured AP backend differs from binding')
    capture['backend_binding'] = descriptor
    return capture


def request_for(plan, name):
    return dict(plan['cells'][0], instance_sha256=plan['records'][0]['instance_sha256'],
        **describe(plan['version_binding_path'], name), qualification_id=plan['qualification_id'],
        population=SCOPE, formal_campaign=False, execution_identity=plan['execution_identity'],
        planner_budget_seconds=180, outer_watchdog_seconds=195)


def validate_request(plan, request, name):
    if request != request_for(plan, name):
        raise ValueError('request is not the fixed C3/AP-D instance and backend')


def timed(function, records, name):
    """Diagnostic-only wall time, with the original call/exception preserved."""
    def call(*args, **kwargs):
        started = time.perf_counter_ns()
        try:
            return function(*args, **kwargs)
        finally:
            row = records.setdefault(name, dict(calls=0, elapsed_ns=0))
            row['calls'] += 1
            row['elapsed_ns'] += time.perf_counter_ns() - started
    return call


class AttemptEntry:
    """Binding/schema reuse within one parent or worker attempt only."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.plan = copy.deepcopy(load_plan(self.path))
        self.binding_path = Path(self.plan['version_binding_path']).resolve()
        self.binding_bytes = self.binding_path.read_bytes()
        if hashlib.sha256(self.binding_bytes).hexdigest() != self.plan['version_binding_sha256']:
            raise ValueError('binding changed during entry construction')
        self.binding = json.loads(self.binding_bytes)
        self.descriptors = {name: dict(backend=name, **self.binding['backends'][name],
            version_binding_id=self.plan['version_binding_id'],
            version_binding_sha256=self.plan['version_binding_sha256']) for name in NAMES}
        self.schemas = {}
        self.receipt_identity = None
        self.metrics = dict(binding_reads=1, schema_builds=0, descriptor_requests=0,
                            release_checks=0, schema_requests=0)
        self.timing = {}
        self.core_timing = {}

    def describe(self, path, name):
        if Path(path).resolve() != self.binding_path or name not in NAMES:
            raise ValueError('entry binding path/backend differs')
        self.metrics['descriptor_requests'] += 1
        return dict(self.descriptors[name])

    def request(self, name):
        return dict(copy.deepcopy(self.plan['cells'][0]),
            instance_sha256=self.plan['records'][0]['instance_sha256'],
            **self.describe(self.binding_path, name), qualification_id=self.plan['qualification_id'],
            population=SCOPE, formal_campaign=False, execution_identity=self.plan['execution_identity'],
            planner_budget_seconds=180, outer_watchdog_seconds=195)

    def validate(self, plan, request, name):
        if plan != self.plan or request != self.request(name):
            raise ValueError('entry request/plan changed')

    def schema(self, receipt, name):
        identity = hashlib.sha256(v7.canonical(receipt).encode()).hexdigest()
        if self.receipt_identity is not None and identity != self.receipt_identity:
            raise ValueError('entry receipt changed')
        self.receipt_identity = identity
        if name not in self.schemas:
            # The SHA is from this verified source snapshot. Source bytes are
            # rechecked before publication, rather than rehashed by every factory.
            if name == 'reference':
                result = schema_for(receipt, name)
            else:
                impl = self.binding['backends'][name]
                fn = adapter._clone_function(v7.schema_for,
                    {'ID': impl['backend_id'], 'identity': lambda: impl['backend_sha256']})
                result = fn(receipt, 'ros2-v7')
                if name == 'ros2-v8':
                    result.binding_id = 'CMR_AP_TS_REUSE_P2C_BACKEND_BINDING_V8'
            result.validate_result = timed(result.validate_result, self.timing, 'schema_validate_result')
            self.schemas[name] = result
            self.metrics['schema_builds'] += 1
        self.metrics['schema_requests'] += 1
        return self.schemas[name]

    def release_check(self):
        if self.binding_path.read_bytes() != self.binding_bytes:
            raise ValueError('binding changed before publication')
        self.metrics['binding_reads'] += 1
        if source_closure() != self.plan['source_closure']:
            raise ValueError('source changed before publication')
        if v7.digest(adapter._native_path(self.plan['authority_receipt'])) != self.plan['receipt_sha256']:
            raise ValueError('authority receipt changed before publication')
        self.metrics['release_checks'] += 1

    def configure(self, formal, name, path):
        descriptor = self.describe(path, name)
        capture = (backend.configure(formal) if name == 'ros2-v8'
                   else v7.configure(formal, name, descriptor))
        if any(capture[k] != descriptor[k] for k in ('backend_id', 'backend_sha256')):
            raise ValueError('configured backend differs from entry')
        capture['backend_binding'] = descriptor
        # Clone after configuration so run_one sees the selected solver/IDs.
        instrument_formal(formal, self.core_timing)
        return capture

    def proxy(self):
        return SimpleNamespace(**dict(vars(v7.old_backends), NAMES=NAMES,
            describe=timed(self.describe, self.timing, 'describe'), configure=self.configure,
            schema_for=timed(self.schema, self.timing, 'schema_for')))

    def guarded_write(self, path, value):
        if Path(path).name == 'worker_result.json':
            timed(self.release_check, self.timing, 'release_check')()
        return timed(write, self.timing, 'write')(path, value)

    def checked_delivery(self, row, completion, *, outer_start, forced_timeout=False):
        # Charge the new source/binding check before sampling the completion
        # passed to the unchanged delivery/deadline classifier.
        release_started = time.perf_counter_ns()
        timed(self.release_check, self.timing, 'release_check')()
        checked_completion = time.perf_counter_ns()
        self.timing['delivery_checkpoint'] = dict(release_started_ns=release_started,
            release_completed_ns=checked_completion)
        return original.terminal_delivery(row, checked_completion,
            outer_start=outer_start, forced_timeout=forced_timeout)


def instrument_formal(formal, records):
    persist = formal.persist_and_verify_certificate
    persist_globals = {'os': SimpleNamespace(**dict(vars(persist.__globals__['os']),
        fsync=timed(persist.__globals__['os'].fsync, records, 'certificate_fsync')))}
    for name in ('canonical_record', '_certificate_payload', 'sha256_file', 'verify_bound_certificate'):
        persist_globals[name] = timed(persist.__globals__[name], records, 'certificate_' + name)
    measured_persist = adapter._clone_function(persist, persist_globals)
    replacements = {name: timed(formal.run_one.__globals__[name], records, name)
                    for name in ('preflight', 'load_instance', '_payload_for_ai')}
    replacements['persist_and_verify_certificate'] = timed(measured_persist, records, 'persist_and_verify_certificate')
    original_one = formal.run_one
    formal.run_one = adapter._clone_function(original_one, replacements)
    records['original_function_code_preserved'] = dict(
        run_one=formal.run_one.__code__ is original_one.__code__,
        persist_and_verify_certificate=measured_persist.__code__ is persist.__code__)


def worker(args):
    entry = AttemptEntry(args.plan)
    fn = adapter._clone_function(original.worker, dict(load_plan=lambda path: entry.plan,
        validate_request=entry.validate, backends=entry.proxy(),
        write=entry.guarded_write))
    try:
        fn(args)
    finally:
        write(args.output/'worker_timing.json', dict(entry_metrics=entry.metrics,
            entry_timing=entry.timing, core_timing=entry.core_timing,
            metrics_scope='AttemptEntry only; load_plan and frozen authority checks also execute',
            version_binding_id=entry.plan['version_binding_id']))


def isolated(request, receipt, kernel, binding_path, plan_path, output):
    entry = AttemptEntry(plan_path)
    fn = adapter._clone_function(original.run_isolated, dict(HERE=HERE,
        load_plan=lambda path: entry.plan, validate_request=entry.validate,
        backends=entry.proxy(), write=entry.guarded_write,
        terminal_delivery=entry.checked_delivery))
    started = time.perf_counter_ns()
    value = fn(request, receipt, kernel, binding_path, plan_path, output)
    write(Path(output)/'parent_timing.json', dict(entry_metrics=entry.metrics,
        entry_timing=entry.timing, isolated_wall_ns=time.perf_counter_ns()-started,
        version_binding_id=entry.plan['version_binding_id']))
    return value


def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    records, cells = selected(args.binding)
    authority = v7.v6.real.load_selection()
    closure = source_closure()
    head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    # This is a new implementation binding; it does not relax or relabel V7.
    binding = dict(schema='cmr-ap-ts-reuse-binding-v1', source_closure=closure,
        semantic_contract_id='INITIAL_LABEL_V1', objective='prefix_cost + 10*suffix_cost',
        nonempty_accepting_suffix=True, full_ts_rebuild_every_round=False,
        full_ts_policy=FULL_TS_POLICY, cache_scope=CACHE_SCOPE,
        planner_budget_seconds=180, outer_watchdog_seconds=195, formal_campaign=False,
        backends=implementations(), receipt_sha256=authority['receipt_sha256'],
        original_execution_binding_sha256=authority['binding_sha256'], manifest_sha256=authority['manifest_sha256'])
    binding['binding_id'] = VERSION + '-' + hashlib.sha256(v7.canonical(binding).encode()).hexdigest()[:16]
    binding_path = args.output / 'backend_binding.json'; write(binding_path, binding)
    plan = dict(schema='cmr-ap-ts-reuse-plan-v1', scope=SCOPE,
        qualification_id='CMR_AP_TS_REUSE_20261013', source_head=head,
        baseline_commit=BASELINE, records=records, cells=cells, source_closure=closure,
        selection_rule='Fixed C3-T4/AP-D regression for the previously observed six full TS builds; no population claim',
        backends=list(NAMES), expected_method_workers=3, attempts_per_cell_backend=1,
        planner_budget_seconds=180, outer_watchdog_seconds=195, formal_campaign=False,
        authority_receipt=str(adapter._native_path(args.binding)), receipt_sha256=authority['receipt_sha256'],
        original_execution_binding_sha256=authority['binding_sha256'], manifest_sha256=authority['manifest_sha256'],
        version_binding_path=str(binding_path), version_binding_sha256=v7.digest(binding_path),
        version_binding_id=binding['binding_id'])
    plan['execution_identity'] = head + '+cmr-ap-ts-reuse-' + hashlib.sha256(v7.canonical(plan).encode()).hexdigest()[:16]
    write(args.output/'plan.json', plan)
    write(args.output/'frozen_inputs_before.json', v7.qualification.frozen_inputs(plan))
    for name in closure:
        destination=args.output/'frozen_adapter'/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,destination)
    result=fixtures.run(args.kernel_root)
    write(args.output/'fixture_details.json',result)
    write(args.output/'fixtures.json',dict(status=result['status'],execution_identity=plan['execution_identity'],
        version_binding_id=plan['version_binding_id'],version_binding_sha256=plan['version_binding_sha256']))
    print(json.dumps(dict(prepared=True,workers=3,binding=plan['version_binding_id'])),flush=True)


def run(args):
    plan=load_plan(args.output/'plan.json')
    if (args.output/'dispatches').exists():
        raise ValueError('retained dispatch markers prevent a repeat of this comparison')
    (args.output/'dispatches').mkdir()
    report=dict(schema='cmr-ap-ts-reuse-comparison-v1',status='RUNNING',backends={},certificate_replays={},
        formal_campaign=False,provider_calls=0,dds_requests=0)
    try:
        for name in NAMES:
            request=request_for(plan,name)
            write(args.output/'dispatches'/(name+'.json'),request)
            value=isolated(request,args.binding,args.kernel_root,Path(plan['version_binding_path']),args.output/'plan.json',args.output/name)
            report['backends'][name]=value
            write(args.output/'comparison.json',report)
            replay_started=time.perf_counter_ns()
            report['certificate_replays'][name]=original.replay(plan,args.binding,args.kernel_root,value,args.output/name)
            write(args.output/name/'external_replay_timing.json',dict(
                elapsed_ns=time.perf_counter_ns()-replay_started,
                scope='additional independent replay after delivered T_total; outside result row'))
            print(json.dumps(dict(backend=name,status=value['row']['terminal_status'],objective=value['row']['objective'],seconds=value['row']['T_total'])),flush=True)
        ref,old,new=(report['backends'][name] for name in NAMES)
        v7.qualification.check_pair(ref,old,'AP-D'); v7.qualification.check_pair(ref,new,'AP-D')
        if (old['transport'] != new['transport'] or v7.normalized(old['row']['rounds']) != v7.normalized(new['row']['rounds'])):
            raise ValueError('AP scientific rounds or concrete lasso changed')
        if (sum(b['full_ts_rebuild_calls'] for b in old['build_work']) != 6
                or sum(b['full_ts_rebuild_calls'] for b in new['build_work']) != 1
                or sum(b['full_ts_cache_hits'] for b in new['build_work']) != 5
                or len(old['build_work']) != 6 or len(new['build_work']) != 6
                or any(not b['completed'] for b in new['build_work'])):
            raise ValueError('six-round full TS reuse accounting mismatch')
        if not all(new['backend_configuration'][key] for key in ('original_loop_code_preserved','original_local_code_preserved','original_builder_global_preserved')):
            raise ValueError('original loop/local/global builder changed')
        report['status']='PASSED'
    finally:
        after=v7.qualification.frozen_inputs(plan)
        write(args.output/'frozen_inputs_after.json',after)
        if after != json.loads((args.output/'frozen_inputs_before.json').read_bytes()) or source_closure()!=plan['source_closure']:
            report['status']='FAILED_SOURCE_OR_INPUT_CHANGED'
        write(args.output/'comparison.json',report)
    if report['status']!='PASSED':
        raise ValueError('AP reuse comparison did not pass')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--binding',required=True)
    parser.add_argument('--kernel-root',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--backend',choices=NAMES)
    parser.add_argument('--request',type=Path)
    parser.add_argument('--version-binding',type=Path)
    parser.add_argument('--plan',type=Path)
    args=parser.parse_args(); args.output=args.output.resolve()
    if not str(args.output).startswith('/tmp/'):
        raise ValueError('fresh isolated output must be under /tmp/')
    if args.worker:
        worker(args)
    elif args.prepare:
        prepare(args)
    else:
        run(args)


if __name__=='__main__':
    main()
