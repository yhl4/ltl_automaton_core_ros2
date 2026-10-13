"""Replay two existing V7 synthetic rows through frozen publication functions.

This WSL-only probe invokes no Campaign constructor, scientific gate, model,
worker or certificate verifier. The actual coordinator receipt is exercised;
V7 identity checks belong to this wrapper, not the frozen publisher.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import traceback

sys.dont_write_bytecode = True
from experiments.cmr_ros2_search_entry import offline_chain_v7 as metadata
from experiments.cmr_ros2_backend import offline_chain as base

raw = lambda value: (metadata.canonical(value) + '\n').encode('utf-8')
digest = metadata.sha256_bytes
sha = metadata.sha256_file
read = lambda path: json.loads(Path(path).read_bytes())
DRIVER_SHA = 'd319bc0c48cbd0639279f35bacca5ab34e73af639f6f9e90c55b4e1596dcd4a4'
ADAPTER_SHA = '1c7c37ccb792ad3e923d0151fef6650079b1bd3cf058dda5f1bf7392d7885718'
ROWS_SHA = '136ea3abb28642e9c6533f49255d991a0d04a606a10b20cb2de856de4e2c0b01'
BINDING_ID = 'CMR_SEARCH_ENTRY_V1-2325092433cf5abc'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_row(row, descriptor):
    require(row['result_hash'] == digest(metadata.canonical(
        {k: v for k, v in row.items() if k != 'result_hash'}).encode()), 'row hash mismatch')
    extra = dict(fixture_label=metadata.FROZEN_SYNTHETIC_LABEL,
                 provenance_kind=metadata.FROZEN_SYNTHETIC_PROVENANCE,
                 v7_scope=metadata.V7_SCOPE, v7_provenance=metadata.V7_PROVENANCE,
                 v7_version_binding_id=descriptor['version_binding_id'],
                 v7_version_binding_sha256=descriptor['version_binding_sha256'])
    for key, value in dict(descriptor, **extra, formal_campaign=False,
                           planner_budget_seconds=180, outer_watchdog_seconds=195,
                           provider_calls=0, dds_calls=0).items():
        require(row.get(key) == value, f'row identity mismatch: {key}')
    require(isinstance(row.get('rounds'), list) and row['rounds'], 'missing rounds')
    for i, round_row in enumerate(row['rounds']):
        require(round_row.get('round_index') == i, 'round index mismatch')
        for key, value in dict(descriptor, **{k: v for k, v in extra.items()
                                             if k != 'fixture_label'}).items():
            require(round_row.get(key) == value, f'round identity mismatch: {key}')


def qualify(args):
    output = args.output.resolve()
    require(not output.exists() or not any(output.iterdir()), 'output must be fresh or empty')
    output.mkdir(parents=True, exist_ok=True)
    calls = dict(external_process=0, network=0, kernel_loader=0)
    invoked = {}

    def audit(event, event_args):
        if event == 'subprocess.Popen' or event == 'os.system':
            calls['external_process'] += 1
            raise RuntimeError('external process forbidden')
        if event in ('socket.connect', 'socket.getaddrinfo'):
            calls['network'] += 1
            raise RuntimeError('network forbidden')
    sys.addaudithook(audit)
    sys.dont_write_bytecode = True

    def invoke(label, fn, *pos, **kw):
        invoked[label] = invoked.get(label, 0) + 1
        return fn(*pos, **kw)

    try:
        plan, binding, identity = metadata._check_plan_and_binding(args)
        require(binding['binding_id'] == BINDING_ID, 'unexpected binding')
        backends = metadata._V7Backends(args.version_binding)
        descriptor = backends.describe(args.version_binding, 'ros2-v7')
        receipt, execution, execution_path = base.load_authority(args.binding, binding, backends)
        source_paths = [args.plan.resolve(), args.version_binding.resolve(), args.binding.resolve(),
                        execution_path, args.synthetic_results.resolve()]
        require(sha(args.synthetic_results) == ROWS_SHA, 'synthetic source SHA changed')
        lines = args.synthetic_results.read_bytes().splitlines(keepends=True)
        require(len(lines) == 510, 'expected existing 510-row synthetic source')
        rows = [json.loads(line) for line in lines[:2]]
        for i, row in enumerate(rows):
            validate_row(row, descriptor)
            require(raw(row) == lines[i], 'source canonical bytes mismatch')
            (output / f'source_row_{i}.jsonl').write_bytes(lines[i])

        driver_path = execution_path.parent / 'driver_core_r2.py'
        adapter_path = driver_path.with_name('campaign_adapter_core_r2.py')
        require(sha(driver_path) == DRIVER_SHA and sha(adapter_path) == ADAPTER_SHA,
                'frozen driver/adapter changed')
        sys.path.insert(0, str(driver_path.parent))
        driver = load('v7_publication_frozen_driver', driver_path)
        require(sha(driver.PRIOR_DRIVER) == driver.PRIOR_DRIVER_SHA and
                sha(driver.PRIOR_COORDINATOR) == driver.PRIOR_COORDINATOR_SHA, 'prior source changed')

        def deny_loader(*pos, **kw):
            calls['kernel_loader'] += 1
            raise RuntimeError('kernel loader forbidden')
        driver.adapter._load_runner = deny_loader
        coordinator = load('v7_publication_frozen_coordinator', driver.PRIOR_COORDINATOR)
        source_paths += [driver_path, adapter_path, driver.PRIOR_DRIVER,
                         driver.PRIOR_COORDINATOR, Path(metadata.__file__), Path(base.__file__)]
        before = {str(path): sha(path) for path in source_paths}

        def plain_receipt(root, cell, ledger):
            coordinator.HERE = root
            campaign = coordinator.Campaign.__new__(coordinator.Campaign)
            campaign.ledger = ledger
            return invoke('coordinator.Campaign.receipt', coordinator.Campaign.receipt, campaign, cell)

        def bound_receipt(root, cell, index, ledger):
            folder = root / 'completed' / cell['cell_id']
            published = read(folder / 'validated_result.json')
            validate_row(published, descriptor)
            require((folder / 'validated_result.json').read_bytes() == lines[index], 'row bytes changed')
            record = read(folder / 'pilot_record.json')
            for key, value in dict(descriptor, **cell).items():
                require(record.get(key) == value, f'record identity mismatch: {key}')
            require((folder / 'rounds.jsonl').read_bytes() == b''.join(raw(r) for r in published['rounds']),
                    'persisted rounds changed')
            return plain_receipt(root, cell, ledger)

        ledger, cells, finals = [], [], []
        for i, row in enumerate(rows):
            cell = dict(cell_id=f'SYNTHETIC-V7-PUBLICATION-{i}',
                        execution_identity_sha256=digest(raw(dict(
                            source_plan=sha(args.plan), source_row=digest(lines[i]), index=i))))
            record = dict(descriptor, **cell, provenance_kind=metadata.FROZEN_SYNTHETIC_PROVENANCE,
                          scope='SYNTHETIC_PUBLICATION_ONLY', scientific_gate='UNRUN',
                          certificate_replay='UNRUN', validated_result_hash=row['result_hash'])
            body = dict(cell_id=cell['cell_id'], previous_ledger_sha256=(
                ledger[-1]['ledger_commit_sha256'] if ledger else None),
                record_payload_sha256=digest(raw(record)), validated_result_hash=row['result_hash'])
            record['ledger_commit_sha256'] = digest(raw(body))
            files = {'result.json': raw(dict(scope='SYNTHETIC_PUBLICATION_ONLY', worker_result=row)),
                     'rounds.jsonl': b''.join(raw(r) for r in row['rounds']), 'stdout.log': b'',
                     'stderr.log': b'', 'certificate.json': b'"NOT_AVAILABLE"\n',
                     'environment.json': raw(dict(scope='SYNTHETIC_PUBLICATION_ONLY', **calls)),
                     'validated_result.json': lines[i], 'pilot_record.json': raw(record),
                     'ledger_entry.json': raw(body)}
            final = output / 'completed' / cell['cell_id']
            invoke('driver.atomic_publish', driver.atomic_publish, final, files)
            require(driver.REQUIRED_FILES == {p.name for p in final.iterdir()}, 'required files differ')
            require(invoke('driver._read_committed', driver._read_committed, final, cell)['status']
                    == 'ALREADY_COMPLETE', 'committed readback failed')
            _, entry = bound_receipt(output, cell, i, ledger)
            ledger.append(entry)
            cells.append(cell)
            finals.append(final)
        success_hashes = {str(p.relative_to(output)): sha(p) for f in finals for p in f.iterdir()}
        negatives = {}

        def reject(name, folder, fn, expected):
            try:
                fn()
            except (ValueError, RuntimeError) as exc:
                require(expected in str(exc), f'{name}: unexpected rejection: {exc}')
                negatives[name] = dict(status='REJECTED', error_type=type(exc).__name__, error=str(exc))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / 'rejection.json').write_bytes(raw(negatives[name]))
            else:
                raise ValueError(f'negative accepted: {name}')

        def copied(name, index=0):
            root = output / 'negative' / name
            folder = root / 'completed' / cells[index]['cell_id']
            shutil.copytree(finals[index], folder)
            return root, folder

        def rehash(folder, *, record_payload=False, ledger_hash=False):
            record, body = read(folder / 'pilot_record.json'), read(folder / 'ledger_entry.json')
            if record_payload:
                body['record_payload_sha256'] = digest(raw({k: v for k, v in record.items()
                                                           if k != 'ledger_commit_sha256'}))
            if ledger_hash:
                record['ledger_commit_sha256'] = digest(raw(body))
            (folder / 'pilot_record.json').write_bytes(raw(record))
            (folder / 'ledger_entry.json').write_bytes(raw(body))
            manifest = read(folder / 'commit_manifest.json')
            (folder / 'commit_manifest.json').write_bytes(raw({name: sha(folder / name) for name in manifest}))

        reject('duplicate', output / 'negative/duplicate',
               lambda: invoke('driver.atomic_publish', driver.atomic_publish, finals[0], {}),
               'duplicate terminal publication rejected')
        reject('bad_filename', output / 'negative/bad_filename',
               lambda: invoke('driver.atomic_publish', driver.atomic_publish,
                              output / 'negative/bad_filename/final', {'../escape': b'x'}),
               'canonical basenames')
        for name, expected in [('wrong_identity', 'Cell identity mismatch'),
                               ('partial', 'Partial output rejected'),
                               ('file_tamper', 'Commit readback mismatch'),
                               ('ledger_hash', 'Terminal ledger hash mismatch')]:
            root, folder = copied(name)
            cell = dict(cells[0])
            if name == 'wrong_identity':
                cell['execution_identity_sha256'] = '0' * 64
            elif name == 'partial':
                (folder / 'ledger_entry.json').unlink()
            elif name == 'file_tamper':
                (folder / 'stdout.log').write_bytes(b'tampered')
            else:
                body = read(folder / 'ledger_entry.json')
                body['tampered'] = True
                (folder / 'ledger_entry.json').write_bytes(raw(body))
                rehash(folder)
            reject(name, root, lambda: invoke('driver._read_committed', driver._read_committed, folder, cell),
                   expected)

        root, folder = copied('record_payload')
        record = read(folder / 'pilot_record.json')
        record['tampered'] = True
        (folder / 'pilot_record.json').write_bytes(raw(record))
        rehash(folder, ledger_hash=True)
        reject('record_payload', root, lambda: bound_receipt(root, cells[0], 0, []),
               'ledger scientific payload mismatch')
        root, folder = copied('previous_link', 1)
        body = read(folder / 'ledger_entry.json')
        body['previous_ledger_sha256'] = '0' * 64
        (folder / 'ledger_entry.json').write_bytes(raw(body))
        rehash(folder, record_payload=True, ledger_hash=True)
        reject('previous_link', root, lambda: bound_receipt(root, cells[1], 1, ledger[:1]), 'ledger chain mismatch')

        root, folder = copied('stale_v6')
        stale = copy.deepcopy(rows[0])
        v6 = backends.describe(args.version_binding, 'ros2-v6')
        for target in [stale, *stale['rounds']]:
            target.update(v6)
        stale.pop('result_hash')
        stale['result_hash'] = digest(metadata.canonical(stale).encode())
        (folder / 'validated_result.json').write_bytes(raw(stale))
        (folder / 'rounds.jsonl').write_bytes(b''.join(raw(r) for r in stale['rounds']))
        (folder / 'result.json').write_bytes(raw(dict(scope='SYNTHETIC_PUBLICATION_ONLY', worker_result=stale)))
        record = read(folder / 'pilot_record.json')
        record.update(v6, validated_result_hash=stale['result_hash'])
        (folder / 'pilot_record.json').write_bytes(raw(record))
        body = read(folder / 'ledger_entry.json')
        body['validated_result_hash'] = stale['result_hash']
        (folder / 'ledger_entry.json').write_bytes(raw(body))
        rehash(folder, record_payload=True, ledger_hash=True)
        # The unmodified receipt validates hashes, not the V7 descriptor. Demonstrate both layers.
        plain_receipt(root, cells[0], [])
        reject('stale_v6', root, lambda: bound_receipt(root, cells[0], 0, []), 'row identity mismatch: backend')

        guard_cell = dict(campaign_status='FROZEN', cell_id='SYNTHETIC-V7-ROUTE', method='FULL',
                          semantic_contract_sha256='ceafe2799bf469f24bb53d2fdb5070f2e11d581445d4ae47adf921c4590d4308',
                          backend_sha256=descriptor['backend_sha256'],
                          runner_source_sha256=driver._BASE.QUALIFIED_RUNNER_SHA256)
        reject('formal_v7_route', output / 'negative/formal_v7_route',
               lambda: invoke('driver._BASE.run_cell', driver._BASE.run_cell, guard_cell,
                              output / 'never_opened_manifest.json', result_root=output / 'never_dispatched',
                              p2_root=output / 'never_loaded', certificate_root=output / 'never_verified',
                              benchmark_root=output / 'never_loaded'), 'backend hash mismatch')
        require(not (output / 'never_dispatched').exists(), 'unexpected dispatch output')
        require(all(value == 0 for value in calls.values()), 'external activity attempted')
        require(before == {str(path): sha(path) for path in source_paths}, 'source/input bytes changed')
        require(success_hashes == {str(p.relative_to(output)): sha(p) for f in finals for p in f.iterdir()},
                'successful publication changed')
        _, _, after_identity = metadata._check_plan_and_binding(args)
        require(after_identity['closure_hashes'] == identity['closure_hashes'], 'runtime closure changed')
        report = dict(schema='cmr-search-entry-v7-publication-probe-v1', status='PASSED',
                      scope='SYNTHETIC_PUBLICATION_ONLY', formal_campaign=False, real_results=0,
                      formal_campaign_chain='UNVERIFIED', formal_campaign_driver_execution='UNRUN',
                      scientific_gate='UNRUN', certificate_replay='UNRUN', planner_calls=0, provider_calls=0,
                      dds_calls=0, calls=calls, functions_invoked=invoked, source_hashes=before,
                      source_and_inputs_unchanged=True, runtime_closure_files=identity['closure_files'],
                      source_plan_head=plan['source_head'], source_execution_identity=plan['execution_identity'],
                      version_binding=descriptor, helper_sha256=sha(Path(__file__)),
                      selection_rule='first two existing file rows; indices 0,1; no outcome selection',
                      source_rows_sha256=ROWS_SHA, original_row_bytes_preserved=True,
                      cells=cells, published=2, linked_receipts=2, previous_links_checked=1,
                      negative_cases=negatives, stale_v6_original_receipt='ACCEPTS_HASHES_ONLY',
                      stale_v6_wrapper='REJECTED', full_Campaign_restore_receipts='UNRUN',
                      limitation='Only publication and coordinator receipt functions; V7 scientific gates and worker routing remain unqualified')
        (output / 'publication_report.json').write_bytes(raw(report))
        return report
    except Exception:
        (output / 'fatal.json').write_bytes(raw(dict(status='FAILED', traceback=traceback.format_exc())))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'version-binding', 'binding', 'synthetic-results', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--repo-root', type=Path)
    args = parser.parse_args()
    try:
        report = qualify(args)
    except Exception as exc:
        print(json.dumps(dict(status='FAILED', error=str(exc))), file=sys.stderr)
        return 1
    print(json.dumps({k: report[k] for k in ('status', 'published', 'linked_receipts', 'calls')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
