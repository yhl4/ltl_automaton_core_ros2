from pathlib import Path
import hashlib
import json
import shutil
import zipfile

REPO = Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/ltl_automaton_core-ros2')
DEST = REPO / 'experiments/cmr_ros2_exact_cost_reuse/evidence/20261023'
RUNTIME = Path('/tmp/cmr_v11_exact_cost_e5ff912_20261023')
VALIDATION = Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v11_hotspot_20261023')
CLONE = Path('/tmp/cmr_v11_source_e5ff912_20261023')
PRODUCER = Path('/mnt/c/Users/Yuhling/AppData/Local/Temp/archive_v11_e5ff912_20261023.py')
COMMIT = 'e5ff91294b373a1f33e7ae9458641e4a2200ab56'
V10_ARCHIVE_SHA = 'c9b7f66b55f4e149949c8a1f10e472ab8b47fd5b1484a52fba1ace1638c86440'

if DEST.exists():
    raise SystemExit(f'destination exists: {DEST}')
for path in (RUNTIME, VALIDATION, CLONE, PRODUCER):
    if not path.exists():
        raise FileNotFoundError(path)
DEST.mkdir(parents=True)
entries = []
checks = {'copied_original_and_archive': 0, 'generated_single': 0}

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def clean_files(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')

def copy_entry(source, relative, kind, original_path=None):
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    size = source.stat().st_size
    source_sha = digest(source)
    target_sha = digest(target)
    if size != target.stat().st_size or source_sha != target_sha:
        raise RuntimeError(f'copy mismatch: {source} -> {target}')
    checks['copied_original_and_archive'] += 2
    entries.append({
        'kind': kind,
        'name': relative.as_posix(),
        'original_path': str(source if original_path is None else original_path),
        'size': size,
        'sha256': source_sha,
    })

for source in clean_files(RUNTIME):
    copy_entry(source, Path('namespace') / source.relative_to(RUNTIME), 'runtime_namespace')
for source in clean_files(VALIDATION):
    copy_entry(source, Path('validation') / source.relative_to(VALIDATION), 'development_artifact')
copy_entry(PRODUCER, Path('validation') / PRODUCER.name, 'development_artifact')

snapshot_files = (
    'experiments/cmr_ros2_exact_cost_reuse/backend.py',
    'experiments/cmr_ros2_exact_cost_reuse/search.py',
    'experiments/cmr_ros2_exact_cost_reuse/fixtures.py',
    'experiments/cmr_ros2_exact_cost_reuse/runner.py',
)
for relative_name in snapshot_files:
    source = CLONE / relative_name
    copy_entry(source, Path('source_snapshots') / Path(relative_name).name, 'source_snapshot',
               f'git:{COMMIT}:{relative_name}')

raw_zip = DEST / 'raw_attempts.zip'
with zipfile.ZipFile(raw_zip, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for source in clean_files(DEST / 'namespace'):
        archive.write(source, source.relative_to(DEST).as_posix())
raw_zip_entry = {
    'kind': 'generated',
    'name': 'raw_attempts.zip',
    'original_path': 'generated:zip(namespace)',
    'size': raw_zip.stat().st_size,
    'sha256': digest(raw_zip),
}
checks['generated_single'] += 1

context = {
    'schema': 'cmr-v11-exact-cost-reuse-archive-context-v1',
    'source_commit': COMMIT,
    'source_closure': 73,
    'inputs': 57,
    'cells': 3,
    'workers': 9,
    'recorded_rounds': 24,
    'certificate_replays_internal': 9,
    'certificate_replays_additional': 9,
    'worker_exit0_cleanup': 9,
    'dds_requests': 0,
    'provider_calls': 0,
    'formal_calls': 0,
    'old_source_files_preserved': 69,
    'prior_v10_archive_sha256': V10_ARCHIVE_SHA,
    'prior_v10_archive_path': 'experiments/cmr_ros2_suffix_reuse/evidence/20261022/raw_attempts.zip',
    'binding_id': 'CMR_EXACT_COST_REUSE_V1-d7ddeec3931b21e0',
    'binding_sha256': 'c68af7a505b584e645025581428ac10619680069b2ddda1ea2f900c87271eebd',
    'v10_backend_sha256': '336d2bec6b66d179a3b03eb3d68e2dc2c88304a846655a486c8c41494533dbe5',
    'v11_backend_sha256': '35838cf764a85cd04e3376825d1f807bbb458bb2c39418046bd2f2624abb9cd4',
    'comparison_sha256': '531284c1f779d09e4919cb1ddd92ba06b5d026562014e6052ddd32014e8365d9',
    'status': 'PASSED',
}
context_path = DEST / 'context.json'
context_path.write_text(json.dumps(context, sort_keys=True, indent=2) + '\n', encoding='utf-8')
context_entry = {
    'kind': 'generated',
    'name': 'context.json',
    'original_path': 'generated:archive_context',
    'size': context_path.stat().st_size,
    'sha256': digest(context_path),
}
checks['generated_single'] += 1
entries.extend([raw_zip_entry, context_entry])
entries.sort(key=lambda item: item['name'])

archive_manifest = {
    'schema': 'cmr-v11-exact-cost-reuse-archive-manifest-v1',
    'source_commit': COMMIT,
    'member_count': len(entries),
    'members': entries,
    'verification': {
        'copied_original_and_archive_checks': checks['copied_original_and_archive'],
        'generated_single_checks': checks['generated_single'],
        'total_checks': checks['copied_original_and_archive'] + checks['generated_single'],
        'mismatch_count': 0,
    },
}
archive_manifest_path = DEST / 'archive_manifest.json'
archive_manifest_path.write_text(json.dumps(archive_manifest, sort_keys=True, indent=2) + '\n', encoding='utf-8')

receipt = {
    'schema': 'cmr-v11-exact-cost-reuse-archive-receipt-v1',
    'status': 'PASSED',
    'member_count': len(entries),
    'copied_original_and_archive_checks': checks['copied_original_and_archive'],
    'generated_single_checks': checks['generated_single'],
    'total_checks': checks['copied_original_and_archive'] + checks['generated_single'],
    'mismatch_count': 0,
    'archive_manifest': {'path': 'archive_manifest.json', 'size': archive_manifest_path.stat().st_size, 'sha256': digest(archive_manifest_path)},
    'raw_attempts': {'path': 'raw_attempts.zip', 'size': raw_zip.stat().st_size, 'sha256': digest(raw_zip)},
    'context': {'path': 'context.json', 'size': context_path.stat().st_size, 'sha256': digest(context_path)},
}
receipt_path = DEST / 'archive_receipt.json'
receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n', encoding='utf-8')

artifact = {
    'schema': 'cmr-v11-exact-cost-reuse-artifact-manifest-v1',
    'excludes': ['index.json', 'artifact_manifest.json'],
    'files': [
        {'path': 'raw_attempts.zip', 'size': raw_zip.stat().st_size, 'sha256': digest(raw_zip)},
        {'path': 'context.json', 'size': context_path.stat().st_size, 'sha256': digest(context_path)},
        {'path': 'archive_manifest.json', 'size': archive_manifest_path.stat().st_size, 'sha256': digest(archive_manifest_path)},
        {'path': 'archive_receipt.json', 'size': receipt_path.stat().st_size, 'sha256': digest(receipt_path)},
    ],
}
artifact_path = DEST / 'artifact_manifest.json'
artifact_path.write_text(json.dumps(artifact, sort_keys=True, indent=2) + '\n', encoding='utf-8')

index = {
    'schema': 'cmr-v11-exact-cost-reuse-evidence-index-v1',
    'status': 'AWAITING_ROOT_ARCHIVE_READBACK',
    'source_branch': 'codex/v11-exact-cost-reuse',
    'source_commit': COMMIT,
    'source_closure': 73,
    'inputs': 57,
    'cells': 3,
    'workers': 9,
    'recorded_rounds': {'C3-T4': 6, 'D3-1': 1, 'D3-2': 1},
    'worker_exit0_cleanup': 9,
    'certificate_replays': {'internal': 9, 'additional': 9, 'all_pass': True},
    'dds_requests': 0,
    'provider_calls': 0,
    'formal_calls': 0,
    'no_default_switch': True,
    'comparison': {'path': 'namespace/comparison.json', 'sha256': context['comparison_sha256']},
    'binding': {'id': context['binding_id'], 'sha256': context['binding_sha256']},
    'backends': {'v10_sha256': context['v10_backend_sha256'], 'v11_sha256': context['v11_backend_sha256']},
    'archive_manifest': {'path': 'archive_manifest.json', 'size': archive_manifest_path.stat().st_size, 'sha256': digest(archive_manifest_path)},
    'artifact_manifest': {'path': 'artifact_manifest.json', 'size': artifact_path.stat().st_size, 'sha256': digest(artifact_path)},
    'archive_receipt': {'path': 'archive_receipt.json', 'size': receipt_path.stat().st_size, 'sha256': digest(receipt_path)},
    'raw_attempts': {'path': 'raw_attempts.zip', 'size': raw_zip.stat().st_size, 'sha256': digest(raw_zip)},
    'context': {'path': 'context.json', 'size': context_path.stat().st_size, 'sha256': digest(context_path)},
    'old_source_files_preserved': 69,
    'prior_v10_archive_sha256': V10_ARCHIVE_SHA,
}
index_path = DEST / 'index.json'
index_path.write_text(json.dumps(index, sort_keys=True, indent=2) + '\n', encoding='utf-8')

print(json.dumps({
    'destination': str(DEST),
    'member_count': len(entries),
    'copied_checks': checks['copied_original_and_archive'],
    'generated_checks': checks['generated_single'],
    'total_checks': checks['copied_original_and_archive'] + checks['generated_single'],
    'archive_manifest_sha256': digest(archive_manifest_path),
    'artifact_manifest_sha256': digest(artifact_path),
    'archive_receipt_sha256': digest(receipt_path),
    'index_sha256': digest(index_path),
    'raw_attempts_sha256': digest(raw_zip),
}, sort_keys=True))