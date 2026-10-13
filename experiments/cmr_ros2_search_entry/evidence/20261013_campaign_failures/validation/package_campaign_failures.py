from pathlib import Path
import hashlib, json, shutil, subprocess, zipfile

REPO = Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/ltl_automaton_core-ros2')
GIT_REPO = Path('/mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2')
TARGET = REPO / 'experiments/cmr_ros2_search_entry/evidence/20261013_campaign_failures'
if TARGET.exists():
    raise RuntimeError(f'target already exists: {TARGET}')
TARGET.mkdir(parents=True)

def sha(data):
    return hashlib.sha256(data).hexdigest()
def copy_bytes(src, dst):
    data = Path(src).read_bytes()
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_bytes(data)
    return data

sources = [
    ('before', Path('/tmp/cmr_current_campaign_failure_20261013_before')),
    ('after', Path('/tmp/cmr_current_campaign_failure_20261013_after')),
    ('fixed', Path('/tmp/cmr_current_campaign_failure_20261013_fixed')),
]
for _, root in sources:
    if not root.is_dir():
        raise RuntimeError(f'missing namespace: {root}')

zip_path = TARGET / 'raw_attempts.zip'
members = {}
with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for prefix, root in sources:
        for path in sorted(root.rglob('*')):
            if not path.is_file():
                continue
            name = f'{prefix}/{path.relative_to(root).as_posix()}'
            data = path.read_bytes()
            zf.writestr(name, data)
            members[name] = {'size': len(data), 'sha256': sha(data)}

# Preserve every external command/helper/log byte under validation.
ext = Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/campaign_failure_20261013')
validation = TARGET / 'validation'
for path in sorted(ext.iterdir()):
    if path.is_file():
        copy_bytes(path, validation / path.name)

# Exact source snapshots from the stated Git objects.
harness = TARGET / 'harness_sources'
for commit, label in [('40975b7', 'campaign_v7_40975b7.py'),
                      ('01b5d77', 'campaign_v7_01b5d77.py'),
                      ('09cab5f', 'campaign_v7_09cab5f.py'),
                      ('f1bcae9', 'campaign_v7_f1bcae9.py')]:
    data = subprocess.check_output(['git', '-C', str(GIT_REPO), 'show', f'{commit}:experiments/cmr_ros2_search_entry/campaign_v7.py'])
    (harness / label).parent.mkdir(parents=True, exist_ok=True)
    (harness / label).write_bytes(data)
for path, label in [
    ('experiments/cmr_ros2_search_entry/entry.py', 'entry_f1bcae9.py'),
    ('experiments/cmr_ros2_search_entry/entry_fixtures.py', 'entry_fixtures_f1bcae9.py'),
    ('experiments/cmr_ros2_search_entry/runner.py', 'runner_f1bcae9.py'),
]:
    data = subprocess.check_output(['git', '-C', str(GIT_REPO), 'show', f'f1bcae9:{path}'])
    (harness / label).write_bytes(data)

# Minimal sidecars are byte copies of the raw namespace members.
sidecar_sources = {
    'failure_readback.json': Path('/tmp/cmr_current_campaign_failure_20261013_fixed/failure_readback.json'),
    'fixed_normal_report.json': Path('/tmp/cmr_current_campaign_failure_20261013_fixed/normal_corrected/campaign_report.json'),
    'before_fatal.json': Path('/tmp/cmr_current_campaign_failure_20261013_before/late_delivery/fatal.json'),
    'after_watchdog_fatal.json': Path('/tmp/cmr_current_campaign_failure_20261013_after/watchdog/fatal.json'),
    'fixed_importguard_fatal.json': Path('/tmp/cmr_current_campaign_failure_20261013_fixed/normal/fatal.json'),
    'fixed_watchdog_fault_report.json': Path('/tmp/cmr_current_campaign_failure_20261013_fixed/watchdog/fault_test_report.json'),
}
sidecars = {}
for name, src in sidecar_sources.items():
    if not src.is_file():
        raise RuntimeError(f'missing sidecar source: {src}')
    data = copy_bytes(src, TARGET / name)
    sidecars[name] = {'path': name, 'size': len(data), 'sha256': sha(data), 'source': str(src)}

# Read plan identities without rewriting any raw namespace.
plans = {}
for label, root in sources:
    candidates = sorted(root.rglob('plan.json'))
    if not candidates:
        plans[label] = {'status': 'MISSING'}
        continue
    p = candidates[0]
    d = json.loads(p.read_bytes())
    binding_path = Path(d['version_binding_path'])
    binding = json.loads(binding_path.read_bytes()) if binding_path.is_file() else {}
    plans[label] = {
        'path': f'{label}/{p.relative_to(root).as_posix()}',
        'sha256': sha(p.read_bytes()),
        'source_head': d.get('source_head'),
        'execution_identity': d.get('execution_identity'),
        'version_binding_id': d.get('version_binding_id'),
        'version_binding_sha256': d.get('version_binding_sha256'),
        'binding_id': binding.get('binding_id'),
        'backend_sha256': binding.get('backends', {}).get('ros2-v7', {}).get('backend_sha256'),
    }

zip_bytes = zip_path.read_bytes()
manifest = {
    'schema': 'cmr-v7-campaign-failures-archive-manifest-v1',
    'compression': 'ZIP_DEFLATED',
    'archive': {'path': 'raw_attempts.zip', 'size': len(zip_bytes), 'sha256': sha(zip_bytes)},
    'member_count': len(members),
    'members': dict(sorted(members.items())),
}
(TARGET / 'archive_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')

index = {
    'schema': 'cmr-v7-campaign-failures-index-v1',
    'status': 'PACKAGED',
    'archive': {'path': 'raw_attempts.zip', 'size': len(zip_bytes), 'sha256': sha(zip_bytes), 'member_count': len(members)},
    'namespaces': plans,
    'actual_counts': {
        'worker_processes': 9,
        'run_one_calls': 5,
        'watchdog_processes': 2,
        'publications': 6,
        'worker_internal_persist_and_verify_calls': 5,
        'controller_publication_restore_verifier_calls': 4,
        'verifier_calls_total': 9,
        'new_reference_workers': 0,
        'dds_calls': 0,
        'provider_calls': 0,
        'formal_batch': False,
    },
    'case_accounting': {
        'before': {'worker_processes': 1, 'run_one_calls': 1, 'publications': 1, 'status': 'PASSED_WITH_PRIOR_FAILURE_ARTIFACTS'},
        'after': {'worker_processes': 4, 'run_one_calls': 2, 'publications': 2, 'watchdog': {'status': 'FAILED', 'reason': 'payload instance/method mismatch; null identity serialization'}, 'status': 'FAILED_NAMESPACE'},
        'fixed': {'worker_processes': 4, 'run_one_calls': 2, 'publications': 3, 'watchdog_T_total': 199.908779952, 'status': 'PASSED'},
        'fixed_importguard': {'worker_processes': 0, 'run_one_calls': 0, 'status': 'FAILED_BEFORE_WORKER', 'retained': 'fixed/normal'},
        'crash_constructor_accounting': {'main_entry_constructor_instances': 1, 'post_failure_resume_constructor_instances': 1, 'successful_constructor_instances': 2},
        'controller_constructor_instances': {'normal_corrected': 2, 'late_delivery': 2, 'watchdog': 2},
    },
    'fixtures': {
        'search_fixture_cases': 42,
        'entry_fixture_checks': 44,
        'fixture_suite_runs': 3,
        'external_windows_checks': 16,
    },
    'protocol': {
        'semantic_contract': 'INITIAL_LABEL_V1',
        'objective': 'prefix_cost + 10*suffix_cost',
        'planner_budget_seconds': 180,
        'outer_watchdog_seconds': 195,
        'full_refinement': True,
        'default_changed': False,
        'full_formal_campaign': 'UNRUN',
        'full_510_cell_chain': 'UNVERIFIED',
        'cooperative_195_exit0_path': 'UNRUN',
    },
    'precheck': {
        'path': 'serializer_precheck_fixed.json',
        'kind': 'SYNTHETIC_IDENTITY_PRECHECK',
        'worker_calls': 0,
        'not_a_real_195_measurement': True,
    },
    'sidecars': sidecars,
    'validation_directory': 'validation',
    'harness_sources_directory': 'harness_sources',
    'limitations': [
        'The before/after/fixed namespaces are separate source identities; old records are not re-labeled.',
        'The fixed import-guard failure and earlier after watchdog payload failure remain preserved.',
        'TIMEOUT records are right-censored under the unchanged 180/195-second budgets.',
        'No new reference, DDS, provider, formal batch, or solver campaign was run.',
    ],
}
(TARGET / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')

# Byte-level readback: archive, manifest/index/sidecars, every ZIP JSON member.
assert sha(zip_path.read_bytes()) == manifest['archive']['sha256']
with zipfile.ZipFile(zip_path) as zf:
    names = set(zf.namelist())
    assert len(names) == len(members)
    for name, meta in members.items():
        data = zf.read(name)
        assert len(data) == meta['size'] and sha(data) == meta['sha256'], name
        if name.lower().endswith('.json'):
            json.loads(data)
for name, meta in sidecars.items():
    data = (TARGET / name).read_bytes()
    assert len(data) == meta['size'] and sha(data) == meta['sha256'], name
for name in ('archive_manifest.json', 'index.json'):
    json.loads((TARGET / name).read_bytes())
print(json.dumps({'target': str(TARGET), 'member_count': len(members), 'archive_size': len(zip_bytes), 'archive_sha256': sha(zip_bytes), 'sidecar_count': len(sidecars), 'validation_files': len(list(validation.iterdir())), 'harness_files': len(list(harness.iterdir()))}, sort_keys=True))