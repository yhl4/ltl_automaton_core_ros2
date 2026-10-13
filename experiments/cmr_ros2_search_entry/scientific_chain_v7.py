"""Bounded, read-only scientific publication replay of three existing V7 runs.

This reuses the frozen scientific checked_record, R2 persisted-certificate gate,
publication_gate and restore_receipts code. It does not construct or run a
formal Campaign, launch a method worker, rebrand an old result, or change the
default backend. The input archive and old execution binding are immutable.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import sys
import traceback
from types import CodeType, FunctionType, MethodType, SimpleNamespace
import zipfile

sys.dont_write_bytecode = True
from experiments.cmr_ros2_search_entry import publication_v7 as helpers
from experiments.cmr_ros2_backend import runner as backend_runner

adapter = backend_runner.adapter
raw, sha, digest, read, require = helpers.raw, helpers.sha, helpers.digest, helpers.read, helpers.require
ARCHIVE_SHA = '3626a630cccaae0d3f4e765455ddc43cb220a47c149ed84ab89cfce4bcb505d6'
SCOPE = 'CMR_V7_REAL_SCIENTIFIC_PUBLICATION_REPLAY_ONLY'
TARGETS = [('A-T1-M0-A-S-BRANCH', 'FULL'), ('B-D-BRANCH-S2', 'FULL'), ('C3-T4', 'AP-D')]


def closure_cell(value):
    return (lambda: value).__closure__[0]


class Replay:
    def __init__(self, args):
        self.output = args.output.resolve()
        require(not self.output.exists() or not any(self.output.iterdir()), 'output must be fresh or empty')
        self.output.mkdir(parents=True, exist_ok=True)
        require(sha(args.archive) == ARCHIVE_SHA, 'old real evidence archive changed')
        self.archive = zipfile.ZipFile(args.archive)
        self.plan = json.loads(self.archive.read('plan.json'))
        self.version = json.loads(self.archive.read('backend_binding.json'))
        require([(c['instance_id'], c['method']) for c in self.plan['cells']] == TARGETS,
                'fixed three-cell scope changed')
        require(self.plan['source_head'] == '14b2c806beecca27f855f32ab79be154e7011de7' and
                self.plan['formal_campaign'] is False and self.plan['planner_budget_seconds'] == 180 and
                self.plan['outer_watchdog_seconds'] == 195, 'source plan contract changed')
        require(self.version['source_closure'] == self.plan['source_closure'] and
                len(self.plan['source_closure']) == 56, 'old runtime closure changed')
        for path, expected in self.plan['source_closure'].items():
            require(digest(self.archive.read('frozen_adapter/' + path)) == expected, 'archived source changed')
        require(digest(self.archive.read('backend_binding.json')) == self.plan['version_binding_sha256'],
                'version binding SHA changed')
        version_body = dict(self.version)
        version_id = version_body.pop('binding_id')
        require(version_id == 'CMR_SEARCH_ENTRY_V1-' + digest(helpers.metadata.canonical(version_body).encode())[:16],
                'canonical old binding identity changed')
        self.descriptor = dict(self.version['backends']['ros2-v7'], backend='ros2-v7',
                               version_binding_id=version_id,
                               version_binding_sha256=self.plan['version_binding_sha256'])
        self.receipt = read(args.binding)
        self.formal, self.original, self.preflight, _ = backend_runner.authority(
            self.plan, args.binding, args.kernel_root)
        self.forbidden_calls, self.verifier_calls = 0, []

        def deny_planner(*pos, **kw):
            self.forbidden_calls += 1
            raise RuntimeError('new method execution forbidden during replay')
        for name in ('run_one', 'run_method_local', '_run_kernel_loop', 'solve_exact_abstract_lasso'):
            setattr(self.formal, name, deny_planner)
        original_verify = self.formal.verify_bound_certificate

        def verify(*pos, **kw):
            proof = original_verify(*pos, **kw)
            self.verifier_calls.append(dict(path=str(pos[1]), expected_sha256=pos[2],
                                            instance=kw['expected_instance_id'], method=kw['expected_method'],
                                            status=proof['status']))
            return proof
        self.formal.verify_bound_certificate = verify
        binding = copy.deepcopy(self.original)
        binding.pop('_binding_path', None)
        binding.update(scope=SCOPE, formal_campaign=False, real_execution_authorized=False,
                       source_real_archive_sha256=ARCHIVE_SHA, source_v7_binding=self.descriptor,
                       benchmark_root=str(adapter._native_path(binding['benchmark_root'])),
                       manifest_path=str(adapter._native_path(binding['manifest_path'])))
        self.cells = [next(copy.deepcopy(c) for c in self.original['cells']
                          if (c['instance_id'], c['method']) == target) for target in TARGETS]
        binding['cells'] = self.cells
        binding['cell_count'] = len(self.cells)
        self.binding_path = self.output / 'replay_binding.json'
        (self.output / 'validation').mkdir()
        schema_binding = json.loads(self.archive.read(TARGETS[0][0] + '_FULL/ros2-v7/schema_binding.json'))
        for name, schema_key in [('result_schema', 'result'), ('round_schema', 'round')]:
            original_ref = self.receipt['scientific_source_refs'][name]
            original_schema = read(adapter._native_path(original_ref['path']))
            require(sha(adapter._native_path(original_ref['path'])) == original_ref['sha256'], 'source schema changed')
            expected = copy.deepcopy(original_schema)
            expected['properties']['backend_sha256']['const'] = self.descriptor['backend_sha256']
            expected['$id'] = f'urn:cmr-ltl:p2c:{schema_key}:v1:ros2-scc-bound-v2'
            require(schema_binding['schemas'][schema_key] == expected, 'schema changed beyond implementation identity')
            path = self.output / 'validation' / (name + '.json')
            path.write_bytes(raw(expected))
            binding['active_validation'][name] = dict(path=str(path), sha256=sha(path), schema_id=expected['$id'])
        contract_ref = binding['active_validation']['validation_contract']
        contract_ref['path'] = str(adapter._native_path(contract_ref['path']))
        self.binding_path.write_bytes(raw(binding))
        self.binding_sha = sha(self.binding_path)
        self.binding = binding
        execution_root = adapter._native_path(self.receipt['execution_binding']['path']).parent
        driver_path = execution_root / 'driver_core_r2.py'
        require(sha(driver_path) == helpers.DRIVER_SHA and
                sha(driver_path.with_name('campaign_adapter_core_r2.py')) == helpers.ADAPTER_SHA,
                'frozen driver/adapter changed')
        sys.path.insert(0, str(execution_root))
        self.driver = helpers.load('v7_scientific_frozen_driver', driver_path)
        require(sha(self.driver.PRIOR_COORDINATOR) == self.driver.PRIOR_COORDINATOR_SHA, 'coordinator changed')
        self.coordinator = helpers.load('v7_scientific_frozen_coordinator', self.driver.PRIOR_COORDINATOR)
        validation_ref = self.original['sources']['bound_validation_adapter']
        validation_path = adapter._native_path(validation_ref['path'])
        require(sha(validation_path) == validation_ref['sha256'], 'bound validation adapter changed')
        self.validation = helpers.load('v7_scientific_bound_validation', validation_path)
        original_validate = self.validation.validate_bound_result

        def validate_bound_result(row, binding_path):
            require(Path(binding_path).resolve() == self.binding_path, 'unexpected replay binding path')
            self.check_descriptor(row)
            return original_validate(row, binding_path)
        self.validation.validate_bound_result = validate_bound_result
        self.source_paths = [args.archive.resolve(), args.binding.resolve(), driver_path,
                             driver_path.with_name('campaign_adapter_core_r2.py'), self.driver.PRIOR_DRIVER,
                             self.driver.PRIOR_COORDINATOR, validation_path]
        self.sources = {str(p): sha(p) for p in self.source_paths}
        self.values = []
        for cell in self.cells:
            prefix = cell['instance_id'] + '_' + cell['method'] + '/ros2-v7/'
            value = json.loads(self.archive.read(prefix + 'result.json'))
            require(value['backend_binding'] == self.descriptor and value['worker_exitcode'] == 0 and
                    value['worker_alive_after_cleanup'] is False, 'original terminal worker state changed')
            self.check_descriptor(value['row'])
            require(json.loads(self.archive.read(prefix + 'schema_binding.json')) == schema_binding,
                    'per-worker schema binding changed')
            self.values.append(value)
        self.state = self.new_state(self.output)

    def active(self):
        require(sha(self.binding_path) == self.binding_sha, 'replay binding changed')
        require(self.sources == {str(p): sha(p) for p in self.source_paths}, 'frozen source/input changed')

    def check_descriptor(self, row):
        for target in [row, *(row.get('rounds') or [])]:
            for key, expected in self.descriptor.items():
                require(target.get(key) == expected, f'V7 descriptor mismatch: {key}')
        require(row['execution_commit'] == self.plan['execution_identity'], 'old execution identity changed')
        require(row.get('formal_campaign') is False and row.get('qualification_scope') == self.plan['scope'],
                'old qualification scope changed')

    def new_state(self, root):
        coordinator = self.coordinator
        coordinator.HERE = root
        state = coordinator.Campaign.__new__(coordinator.Campaign)
        state.records, state.ledger, state.current = [], [], None
        state.binding, state.binding_sha = self.binding, self.binding_sha
        state.adapter, state.runner = self.validation, self.formal
        state.allowed_statuses = set(self.original['allowed_terminal_statuses'])
        state.original_publish = self.driver.atomic_publish
        state.expectations = {c['cell_id']: dict(initial=c['expected_initial_S0'],
                              n=next(r for r in self.plan['records'] if r['instance_id'] == c['instance_id'])['N'],
                              ai=None) for c in self.cells}
        old = adapter._clone_function(coordinator.Campaign.checked_record, dict(
            BINDING_PATH=self.binding_path, SOLVER_SHA=self.descriptor['backend_sha256'],
            RUNNER_SHA=sha(self.formal.HERE)))
        owner = self.driver.Campaign.__new__(self.driver.Campaign)
        owner.binding_path, owner.binding_sha, owner.binding = self.binding_path, self.binding_sha, self.binding
        owner.runner, owner.result_root, owner.campaign = self.formal, root, state
        owner.verify_active = self.active
        code = [c for c in self.driver.Campaign.__init__.__code__.co_consts
                if isinstance(c, CodeType) and c.co_name == 'checked']
        require(len(code) == 1 and set(code[0].co_freevars) == {'old_check', 'self'}, 'R2 gate closure changed')
        closure = {'old_check': MethodType(old, state), 'self': owner}
        checked = FunctionType(code[0], self.driver.Campaign.__init__.__globals__, closure=tuple(
            closure_cell(closure[name]) for name in code[0].co_freevars))

        def bound_checked(campaign, cell, envelope, files, expected):
            self.check_descriptor(envelope['worker_result'])
            record, row = checked(campaign, cell, envelope, files, expected)
            record.update(replay_scope=SCOPE, formal_campaign=False,
                          source_archive_sha256=ARCHIVE_SHA, source_version_binding=self.descriptor)
            return record, row
        state.checked_record = MethodType(bound_checked, state)
        return SimpleNamespace(owner=owner, campaign=state, root=root)

    def publish(self, index, *, override=None, certificate_override=None, suffix='source'):
        self.active()
        cell, value = self.cells[index], self.values[index]
        row = copy.deepcopy(value['row'] if override is None else override)
        attempt = 'offline-replay-' + suffix
        cert_root = self.output / 'attempts' / cell['cell_id'] / attempt / 'certificates'
        cert_root.mkdir(parents=True, exist_ok=False)
        name = self.values[index]['row']['certificate_path']
        require(isinstance(name, str) and Path(name).name == name and '/' not in name and '\\' not in name,
                'source certificate filename changed')
        prefix = cell['instance_id'] + '_' + cell['method'] + '/ros2-v7/'
        cert_bytes = (self.archive.read(prefix + 'certificates/' + name)
                      if certificate_override is None else certificate_override)
        (cert_root / name).write_bytes(cert_bytes)
        (cert_root.parent / 'gate_input.json').write_bytes(raw(row))
        self.check_descriptor(row)
        envelope = dict(cell_id=cell['cell_id'], cell_identity_sha256=cell['cell_identity_sha256'],
                        terminal_status=row['terminal_status'], worker_result=row, attempt_id=attempt,
                        worker_pid=value['worker_pid'], worker_exit_code=value['worker_exitcode'],
                        timed_out_outer=False, timing_status=row['timing_status'])
        files = {'result.json': raw(envelope), 'rounds.jsonl': b''.join(raw(r) for r in row['rounds']),
                      'stdout.log': b'existing real V7 result replay; no method worker\n', 'stderr.log': b'',
                      'certificate.json': cert_bytes, 'environment.json': raw(dict(scope=SCOPE, method_workers=0))}
        self.state.campaign.current = cell
        final = self.output / 'completed' / cell['cell_id']
        try:
            self.coordinator.Campaign.publication_gate(self.state.campaign, final, files)
        finally:
            self.state.campaign.current = None
        record, entry = self.coordinator.Campaign.receipt(self.state.campaign, cell)
        self.state.campaign.records.append(record)
        self.state.campaign.ledger.append(entry)
        require(read(final / 'validated_result.json') == value['row'], 'published original row changed')
        return final

    def restore(self):
        restored = self.new_state(self.output)
        self.driver.Campaign.restore_receipts(restored.owner)
        require(len(restored.campaign.records) == 3 and len(restored.campaign.ledger) == 3, 'restore count mismatch')
        return restored


def qualify(args):
    replay = None
    safe_to_record = not args.output.exists() or not any(args.output.iterdir())
    try:
        replay = Replay(args)
        negatives = {}

        def rejected(label, fn, expected):
            try:
                fn()
            except (ValueError, RuntimeError) as exc:
                require(expected in str(exc), f'unexpected {label} rejection: {exc}')
                negatives[label] = dict(status='REJECTED', error=str(exc))
                (args.output / (label + '_rejection.json')).write_bytes(raw(negatives[label]))
            else:
                raise ValueError('invalid scientific result accepted: ' + label)

        row = copy.deepcopy(replay.values[0]['row'])
        row['version_binding_id'] = 'STALE-V7-VERSION'
        row.pop('result_hash')
        row['result_hash'] = digest(helpers.metadata.canonical(row).encode())
        rejected('stale_publication_version', lambda: replay.publish(0, override=row, suffix='stale_version'),
                 'V7 descriptor mismatch: version_binding_id')
        row = copy.deepcopy(replay.values[0]['row'])
        row['objective'] = '13'
        row.pop('result_hash')
        row['result_hash'] = digest(helpers.metadata.canonical(row).encode())
        rejected('row_objective', lambda: replay.publish(0, override=row, suffix='row_objective'),
                 'certificate identity/objective mismatch')
        cell = replay.cells[0]
        cert_name = replay.values[0]['row']['certificate_path']
        prefix = cell['instance_id'] + '_' + cell['method'] + '/ros2-v7/certificates/'
        cert = json.loads(replay.archive.read(prefix + cert_name))
        cert['objective'] = '13'
        bad_certificate = raw(cert)
        row = copy.deepcopy(replay.values[0]['row'])
        row.update(objective='13', certificate_hash=digest(bad_certificate))
        row.pop('result_hash')
        row['result_hash'] = digest(helpers.metadata.canonical(row).encode())
        rejected('rehash_certificate_objective', lambda: replay.publish(0, override=row,
                 certificate_override=bad_certificate, suffix='bad_certificate'),
                 'P2e independent persisted certificate gate failed')
        require(not (args.output / 'completed').exists(), 'invalid record reached atomic publication')
        negative_verifier_count = len(replay.verifier_calls)
        for i in range(3):
            replay.publish(i)
        replay.restore()
        restore_root = args.output / 'stale_restore'
        shutil.copytree(args.output / 'completed', restore_root / 'completed')
        folder = restore_root / 'completed' / replay.cells[0]['cell_id']
        row = read(folder / 'validated_result.json')
        row['version_binding_id'] = 'STALE-V7-VERSION'
        for rr in row['rounds']:
            rr['version_binding_id'] = 'STALE-V7-VERSION'
        row.pop('result_hash')
        row['result_hash'] = digest(helpers.metadata.canonical(row).encode())
        (folder / 'validated_result.json').write_bytes(raw(row))
        envelope = read(folder / 'result.json')
        envelope['worker_result'] = row
        (folder / 'result.json').write_bytes(raw(envelope))
        (folder / 'rounds.jsonl').write_bytes(b''.join(raw(rr) for rr in row['rounds']))
        record, body = read(folder / 'pilot_record.json'), read(folder / 'ledger_entry.json')
        record['worker_result'] = row
        body['validated_result_hash'] = row['result_hash']
        body['record_payload_sha256'] = digest(raw({k: v for k, v in record.items() if k != 'ledger_commit_sha256'}))
        body['validated_input_file_hashes'] = {name: sha(folder / name) for name in body['validated_input_file_hashes']}
        record['ledger_commit_sha256'] = digest(raw(body))
        (folder / 'pilot_record.json').write_bytes(raw(record))
        (folder / 'ledger_entry.json').write_bytes(raw(body))
        manifest = read(folder / 'commit_manifest.json')
        (folder / 'commit_manifest.json').write_bytes(raw({name: sha(folder / name) for name in manifest}))
        stale_state = replay.new_state(restore_root)
        rejected('stale_restore_version', lambda: replay.driver.Campaign.restore_receipts(stale_state.owner),
                 'V7 descriptor mismatch: version_binding_id')
        require(replay.forbidden_calls == 0, 'method execution attempted')
        require(negative_verifier_count == 1 and replay.verifier_calls[0]['status'] != 'PASS',
                'forged certificate did not reach independent rejection')
        require(len(replay.verifier_calls) == 7 and all(c['status'] == 'PASS' for c in replay.verifier_calls[1:]),
                'independent scientific certificate replay incomplete')
        replay.active()
        report = dict(schema='cmr-v7-real-scientific-chain-replay-v1', status='PASSED', scope=SCOPE,
                      source_archive_sha256=ARCHIVE_SHA, source_head=replay.plan['source_head'],
                      source_execution_identity=replay.plan['execution_identity'], version_binding=replay.descriptor,
                      new_method_workers=0, planner_calls=0, formal_campaign=False, default_changed=False,
                      provider_calls=0, dds_calls=0, published=3, restored=3,
                      independent_verifier_calls=replay.verifier_calls,
                      positive_verifier_calls=6, rejected_certificate_calls=1, negative_checks=negatives,
                      objectives=[v['row']['objective'] for v in replay.values],
                      original_rows_unchanged=True, source_hashes=replay.sources,
                      original_coordinator_code_preserved=True, original_R2_gate_code_preserved=True,
                      original_restore_code_preserved=True, original_campaign_constructor='UNRUN',
                      worker_routing='UNRUN', full_formal_campaign='UNVERIFIED',
                      helper_sha256=sha(Path(__file__)), replay_binding_sha256=replay.binding_sha)
        (args.output / 'scientific_chain_report.json').write_bytes(raw(report))
        return report
    except Exception:
        if safe_to_record and args.output.is_dir():
            (args.output / 'fatal.json').write_bytes(raw(dict(status='FAILED', traceback=traceback.format_exc(),
                verifier_calls=getattr(replay, 'verifier_calls', None),
                forbidden_method_calls=getattr(replay, 'forbidden_calls', None))))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'binding', 'kernel-root', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        report = qualify(args)
    except Exception as exc:
        print(json.dumps(dict(status='FAILED', error=str(exc))), file=sys.stderr)
        return 1
    print(json.dumps({k: report[k] for k in ('status', 'published', 'restored', 'objectives', 'new_method_workers')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
