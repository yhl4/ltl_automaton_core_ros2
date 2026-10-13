"""Explicit backend routing for one isolated, current-version CMR campaign cell.

The real constructor binds the existing worker lifecycle and frozen scientific
publication/restore functions. Only the previously selected C3-T4/AP-D cell is
enabled here. This qualification entry does not authorize a formal campaign.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time
import traceback
from types import CodeType, FunctionType, MethodType, SimpleNamespace

sys.dont_write_bytecode = True
from experiments.cmr_ros2_search_entry import runner, publication_v7 as helpers
from experiments.cmr_ros2_search_entry.entry import VerifiedEntry

raw, sha, digest, read, require = helpers.raw, helpers.sha, helpers.digest, helpers.read, helpers.require
SCOPE = 'CMR_V7_CURRENT_CAMPAIGN_SINGLE_CELL_QUALIFICATION'
TARGET = ('C3-T4', 'AP-D')
VERSION = 'CMR_QUALIFIED_CAMPAIGN_V1'


class Campaign:
    def __init__(self, args, *, resume=False):
        require(args.backend in runner.NAMES, 'unknown explicit backend')
        self.args, self.root = args, args.output.resolve()
        require(str(self.root).startswith('/tmp/'), 'isolated campaign must be under /tmp/')
        if resume:
            require(self.root.is_dir(), 'resume directory unavailable')
        else:
            require(not self.root.exists() or not any(self.root.iterdir()), 'fresh campaign directory required')
            self.root.mkdir(parents=True, exist_ok=True)
        self.plan = runner.load_plan(args.plan)
        require(args.plan.resolve() == (args.plan.parent / 'plan.json').resolve(),
                'worker lifecycle requires the canonical plan.json filename')
        require(self.plan['scope'] == runner.SCOPE and self.plan['formal_campaign'] is False,
                'campaign requires the existing isolated search plan')
        selected = [c for c in self.plan['cells'] if (c['instance_id'], c['method']) == TARGET]
        require(len(selected) == 1, 'fixed metadata-selected AP-D cell missing')
        self.entry = VerifiedEntry(self.plan, runner.source_closure, runner.schema_for)
        self.descriptor = self.entry.describe(args.backend)
        self.receipt = read(runner.adapter._native_path(args.binding))
        schema = self.entry.schema(args.backend, self.receipt)
        self.formal, original, preflight, records = runner.old_runner.authority(
            self.plan, args.binding, args.kernel_root)
        self.method_workers, self.verifications = 0, []
        self.original = original
        self.cell = next(copy.deepcopy(c) for c in original['cells']
                         if (c['instance_id'], c['method']) == TARGET)
        require(self.cell['cell_id'] == selected[0]['source_cell_id'], 'frozen cell identity mismatch')
        instance = self.formal.load_instance(records[TARGET[0]],
                                            runner.adapter._native_path(original['benchmark_root']))
        require(sorted(self.formal.initial_precision(instance, TARGET[1])) == selected[0]['expected_initial_S0'],
                'constructor initial precision mismatch')
        original_verify = self.formal.verify_bound_certificate

        def verify(*pos, **kw):
            event = dict(path=str(pos[1]), sha256=pos[2], instance=kw['expected_instance_id'],
                         method=kw['expected_method'])
            self.verifications.append(event)
            try:
                result = original_verify(*pos, **kw)
            except Exception as exc:
                event.update(status='REJECTED_EXCEPTION', error=str(exc))
                raise
            event['status'] = result['status']
            return result
        self.formal.verify_bound_certificate = verify
        execution_root = runner.adapter._native_path(self.receipt['execution_binding']['path']).parent
        driver_path = execution_root / 'driver_core_r2.py'
        require(sha(driver_path) == helpers.DRIVER_SHA and
                sha(driver_path.with_name('campaign_adapter_core_r2.py')) == helpers.ADAPTER_SHA,
                'frozen driver source changed')
        sys.path.insert(0, str(execution_root))
        self.driver = helpers.load('current_v7_campaign_driver', driver_path)
        self.coordinator = helpers.load('current_v7_campaign_coordinator', self.driver.PRIOR_COORDINATOR)
        require(sha(self.driver.PRIOR_COORDINATOR) == self.driver.PRIOR_COORDINATOR_SHA, 'coordinator changed')
        validation_ref = original['sources']['bound_validation_adapter']
        validation_path = runner.adapter._native_path(validation_ref['path'])
        require(sha(validation_path) == validation_ref['sha256'], 'bound validation adapter changed')
        self.validation = helpers.load('current_v7_campaign_validation', validation_path)
        validate = self.validation.validate_bound_result
        self.binding_path = self.root / 'campaign_binding.json'

        def bound_validate(row, path):
            require(Path(path).resolve() == self.binding_path, 'campaign validation binding path mismatch')
            self.check_result(row)
            return validate(row, path)
        self.validation.validate_bound_result = bound_validate
        gate_paths = [Path(__file__), Path(helpers.__file__), Path(helpers.metadata.__file__),
                      driver_path, driver_path.with_name('campaign_adapter_core_r2.py'),
                      self.driver.PRIOR_DRIVER, self.driver.PRIOR_COORDINATOR, validation_path]
        self.gate_sources = {str(p.resolve()): sha(p) for p in gate_paths}
        binding = copy.deepcopy(original)
        binding.pop('_binding_path', None)
        source_binding_id = binding.pop('binding_id', None)
        binding.update(schema='cmr-qualified-campaign-binding-v1', scope=SCOPE,
                       qualification_only=True, formal_campaign=False, real_execution_authorized=False,
                       backend_binding=self.descriptor, method_attempts=1, cells=[self.cell], cell_count=1,
                       planner_budget_seconds=180, outer_watchdog_seconds=195,
                       source_original_binding_id=source_binding_id,
                       source_original_execution_binding_sha256=self.plan['original_execution_binding_sha256'],
                       source_plan_sha256=sha(args.plan), source_plan_execution_identity=self.plan['execution_identity'],
                       runtime_source_closure=self.plan['source_closure'], gate_source_closure=self.gate_sources,
                       benchmark_root=str(runner.adapter._native_path(original['benchmark_root'])),
                       manifest_path=str(runner.adapter._native_path(original['manifest_path'])))
        if not resume:
            (self.root / 'validation').mkdir()
            runner.write(self.root / 'constructor_preflight.json', preflight)
        for label, key in [('result_schema', 'result'), ('round_schema', 'round')]:
            source = runner.adapter._native_path(self.receipt['scientific_source_refs'][label]['path'])
            expected = read(source)
            candidate = copy.deepcopy(schema.schemas[key])
            require(candidate['properties']['backend_sha256']['const'] == self.descriptor['backend_sha256'],
                    'schema backend differs from explicit selector')
            stripped = copy.deepcopy(candidate)
            stripped['properties']['backend_sha256']['const'] = expected['properties']['backend_sha256']['const']
            stripped.pop('$id', None)
            expected.pop('$id', None)
            require(stripped == expected, 'schema changes beyond implementation identity')
            path = self.root / 'validation' / (label + '.json')
            if resume:
                require(path.read_bytes() == raw(candidate), 'persisted schema changed')
            else:
                path.write_bytes(raw(candidate))
            binding['active_validation'][label] = dict(path=str(path), sha256=sha(path),
                                                       schema_id=candidate.get('$id', 'urn:cmr-ltl:p2c:' + key + ':v1'))
        ref = binding['active_validation']['validation_contract']
        ref['path'] = str(runner.adapter._native_path(ref['path']))
        binding['binding_id'] = VERSION + '-' + digest(helpers.metadata.canonical(binding).encode())[:16]
        if resume:
            require(self.binding_path.read_bytes() == raw(binding), 'resume binding/source identity mismatch')
        else:
            self.binding_path.write_bytes(raw(binding))
        self.binding, self.binding_sha = binding, sha(self.binding_path)
        self.state = self.scientific_state()
        self.active()
        if resume:
            self.driver.Campaign.restore_receipts(self.state.owner)

    def active(self):
        self.entry.release_check()
        require(sha(self.binding_path) == self.binding_sha, 'campaign binding changed')
        require(self.gate_sources == {p: sha(Path(p)) for p in self.gate_sources}, 'campaign gate source changed')
        require(sha(self.args.plan) == self.binding['source_plan_sha256'], 'source plan changed')

    def check_result(self, row):
        for target in [row, *(row.get('rounds') or [])]:
            for key, value in self.descriptor.items():
                require(target.get(key) == value, 'campaign result/round descriptor mismatch: ' + key)
        require((row['instance_id'], row['method']) == TARGET, 'campaign result cell mismatch')
        require(row['execution_commit'] == self.plan['execution_identity'] and row.get('formal_campaign') is False
                and row.get('qualification_scope') == self.plan['scope'], 'campaign result scope/execution mismatch')

    def scientific_state(self):
        self.coordinator.HERE = self.root
        state = self.coordinator.Campaign.__new__(self.coordinator.Campaign)
        state.records, state.ledger, state.current = [], [], None
        state.binding, state.binding_sha = self.binding, self.binding_sha
        state.adapter, state.runner = self.validation, self.formal
        state.allowed_statuses = set(self.original['allowed_terminal_statuses'])
        state.original_publish = self.driver.atomic_publish
        state.expectations = {self.cell['cell_id']: dict(initial=self.cell['expected_initial_S0'],
            n=next(r for r in self.plan['records'] if r['instance_id'] == TARGET[0])['N'], ai=None)}
        old = runner.adapter._clone_function(self.coordinator.Campaign.checked_record, dict(
            BINDING_PATH=self.binding_path, SOLVER_SHA=self.descriptor['backend_sha256'],
            RUNNER_SHA=sha(self.formal.HERE)))
        owner = self.driver.Campaign.__new__(self.driver.Campaign)
        owner.binding_path, owner.binding_sha, owner.binding = self.binding_path, self.binding_sha, self.binding
        owner.runner, owner.result_root, owner.campaign = self.formal, self.root, state
        owner.verify_active = self.active
        codes = [c for c in self.driver.Campaign.__init__.__code__.co_consts
                 if isinstance(c, CodeType) and c.co_name == 'checked']
        require(len(codes) == 1 and set(codes[0].co_freevars) == {'old_check', 'self'}, 'R2 gate closure changed')
        context = dict(old_check=MethodType(old, state), self=owner)
        cells = tuple((lambda value: lambda: value)(context[name]).__closure__[0] for name in codes[0].co_freevars)
        checked = FunctionType(codes[0], self.driver.Campaign.__init__.__globals__, closure=cells)

        def current_checked(campaign, cell, envelope, files, expected):
            self.active()
            self.check_result(envelope['worker_result'])
            record, row = checked(campaign, cell, envelope, files, expected)
            if envelope.get('timed_out_outer'):
                record.update(frozen_gate_result_delivery=record['result_delivery'],
                              result_delivery='V7_QUALIFIED_PARENT_OUTER_TIMEOUT_SERIALIZATION',
                              outer_timeout_delivered_row_preserved=True)
            record.update(campaign_scope=SCOPE, formal_campaign=False, campaign_binding_id=self.binding['binding_id'],
                          campaign_binding_sha256=self.binding_sha, backend_binding=self.descriptor)
            return record, row
        state.checked_record = MethodType(current_checked, state)
        return SimpleNamespace(owner=owner, campaign=state)

    def run_cell(self):
        self.active()
        if self.state.campaign.records:
            require(len(self.state.campaign.records) == 1, 'unexpected committed cell count')
            return dict(status='ALREADY_COMPLETE', skipped_existing=True, new_method_workers=0)
        marker = self.root / 'dispatch.json'
        require(not marker.exists(), 'incomplete prior dispatch retained; automatic retry forbidden')
        attempt = 'a-' + str(time.perf_counter_ns())
        target = self.root / 'attempts' / self.cell['cell_id'] / attempt
        target.parent.mkdir(parents=True, exist_ok=True)
        with marker.open('x', encoding='utf-8') as stream:
            stream.write(helpers.metadata.canonical(dict(campaign_binding_sha256=self.binding_sha,
                backend_binding=self.descriptor, source_cell_id=self.cell['cell_id'], attempt_id=attempt)) + '\n')
        worker_args = SimpleNamespace(binding=self.args.binding, kernel_root=self.args.kernel_root,
                                      output=self.args.plan.parent)
        selected = next(c for c in self.plan['cells'] if (c['instance_id'], c['method']) == TARGET)
        self.method_workers += 1
        value = runner.candidate_isolated(worker_args, self.plan, selected, target, backend_name=self.args.backend)
        self.active()
        self.check_result(value['row'])
        row = value['row']
        require(value['worker_alive_after_cleanup'] is False, 'worker cleanup incomplete')
        try:
            os.killpg(value['worker_pid'], 0)
        except ProcessLookupError:
            pass
        else:
            raise ValueError('worker process group still present; terminal publication refused')
        require(row['terminal_status'] in {'OPTIMALITY_CERTIFIED', 'INFEASIBLE_CERTIFIED', 'CERTIFICATE_GAP', 'TIMEOUT'},
                'failure worker retained before scientific publication')
        cert = b'null'
        if row['terminal_status'] == 'OPTIMALITY_CERTIFIED':
            require(value['worker_exitcode'] == 0, 'nonzero worker cannot authorize an optimal result')
            path = target / 'certificates' / row['certificate_path']
            require(sha(path) == row['certificate_hash'], 'persisted worker certificate changed')
            cert = path.read_bytes()
        outer_timeout = row['terminal_status'] == 'TIMEOUT' and row.get('error') == 'watchdog'
        if outer_timeout:
            require(row.get('timeout_stage') == 'outer_watchdog' and row['T_total'] >= 195
                    and row['method_start_ns'] == value['outer_start_ns'] and value['worker_exitcode'] != 0,
                    'outer timeout supervisor provenance mismatch')
        envelope = dict(cell_id=self.cell['cell_id'], cell_identity_sha256=self.cell['cell_identity_sha256'],
                        terminal_status=row['terminal_status'], worker_result=row, attempt_id=attempt,
                        worker_pid=value['worker_pid'], worker_exit_code=value['worker_exitcode'],
                        timed_out_outer=outer_timeout, timing_status=row['timing_status'],
                        delivered_row_source=('qualified_parent_outer_timeout' if outer_timeout
                                              else 'qualified_worker_delivery'),
                        process_group_absent=True,
                        t_plan_wall_lower_bound_seconds=row['T_total'] if outer_timeout else None)
        files = {'result.json': raw(envelope), 'rounds.jsonl': b''.join(raw(r) for r in row.get('rounds') or []),
                 'stdout.log': (target / 'stdout.txt').read_bytes(), 'stderr.log': (target / 'stderr.txt').read_bytes(),
                 'certificate.json': cert, 'environment.json': raw(dict(campaign_scope=SCOPE,
                        backend_binding=self.descriptor, campaign_binding_sha256=self.binding_sha))}
        self.state.campaign.current = self.cell
        try:
            self.coordinator.Campaign.publication_gate(self.state.campaign,
                self.root / 'completed' / self.cell['cell_id'], files)
        finally:
            self.state.campaign.current = None
        record, entry = self.coordinator.Campaign.receipt(self.state.campaign, self.cell)
        self.state.campaign.records.append(record)
        self.state.campaign.ledger.append(entry)
        self.coordinator.write_atomic(self.root / 'ledger.jsonl',
            b''.join(raw(item) for item in self.state.campaign.ledger))
        self.coordinator.write_atomic(self.root / 'core_results.jsonl',
            b''.join(raw(item) for item in self.state.campaign.records))
        require(read(self.root / 'completed' / self.cell['cell_id'] / 'validated_result.json') == row,
                'scientific publication changed the delivered method row')
        self.active()
        return dict(status='COMMITTED', objective=row['objective'], terminal_status=row['terminal_status'],
                    new_method_workers=self.method_workers, attempt_directory=str(target))


def qualify(args):
    campaign = Campaign(args)
    first = campaign.run_cell()
    resumed = Campaign(args, resume=True)
    second = resumed.run_cell()
    require(first['status'] == 'COMMITTED' and second['status'] == 'ALREADY_COMPLETE', 'commit/resume path incomplete')
    require(campaign.method_workers == 1 and resumed.method_workers == 0, 'resume launched a worker')
    for name, values in [('ledger.jsonl', resumed.state.campaign.ledger),
                         ('core_results.jsonl', resumed.state.campaign.records)]:
        require((args.output / name).read_bytes() == b''.join(raw(item) for item in values),
                'restored aggregate differs from committed records: ' + name)
    optimal = first['terminal_status'] == 'OPTIMALITY_CERTIFIED'
    required_verifications = int(optimal)
    verifications = campaign.verifications + resumed.verifications
    require(len(campaign.verifications) == len(resumed.verifications) == required_verifications
            and all(event['status'] == 'PASS' for event in verifications),
            'publication/restore independent certificate verification incomplete')
    report = dict(schema='cmr-current-v7-campaign-qualification-v1', status='PASSED', scope=SCOPE,
                  backend_binding=campaign.descriptor, campaign_binding_id=campaign.binding['binding_id'],
                  campaign_binding_sha256=campaign.binding_sha, source_plan_sha256=sha(args.plan),
                  source_execution_identity=campaign.plan['execution_identity'], source_head=campaign.plan['source_head'],
                  target=list(TARGET), new_method_workers=1, resume_method_workers=0,
                  constructor_instances=2, worker_routing='EXECUTED', scientific_publication='PASS',
                  scientific_restore='PASS', verifications=verifications,
                  certificate_replay='PASS' if optimal else 'NOT_APPLICABLE_NONOPTIMAL_TERMINAL',
                  certificate_verifier_calls=len(verifications),
                  aggregate_readback='PASS',
                  committed=first, resumed=second, formal_campaign=False, default_changed=False,
                  provider_calls=0, dds_calls=0, frozen_formal_Campaign_constructor='UNRUN',
                  full_510_cell_chain='UNVERIFIED', delivered_row_unchanged=True,
                  gate_source_closure=campaign.gate_sources)
    (args.output / 'campaign_report.json').write_bytes(raw(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'binding', 'kernel-root', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--backend', choices=runner.NAMES, required=True)
    args = parser.parse_args()
    fresh = not args.output.exists() or not any(args.output.iterdir())
    try:
        report = qualify(args)
    except Exception as exc:
        if fresh and args.output.is_dir():
            (args.output / 'fatal.json').write_bytes(raw(dict(status='FAILED', traceback=traceback.format_exc())))
        print(json.dumps(dict(status='FAILED', error=str(exc))), file=sys.stderr)
        return 1
    print(json.dumps({k: report[k] for k in ('status', 'target', 'new_method_workers', 'resume_method_workers', 'committed')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
