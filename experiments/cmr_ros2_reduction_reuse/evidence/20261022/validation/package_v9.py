from pathlib import Path
import hashlib, json, shutil, zipfile

repo = Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/ltl_automaton_core-ros2')
ext = Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v9_projection_witness_20261022')
out = repo / 'experiments/cmr_ros2_reduction_reuse/evidence/20261022'
out.mkdir(parents=True, exist_ok=False)

def sha(data):
    return hashlib.sha256(data).hexdigest()
def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
def find_head(prefix):
    matches=[]
    for p in Path('/tmp').glob('cmr_v9_projection_witness*'):
        if not p.is_dir() or not (p / 'plan.json').is_file():
            continue
        try:
            plan=json.loads((p/'plan.json').read_bytes())
        except Exception:
            continue
        if str(plan.get('source_head','')).startswith(prefix):
            matches.append(p)
    if len(matches) != 1:
        raise RuntimeError(f'expected one namespace for {prefix}: {[repr(str(x)) for x in matches]}')
    return matches[0]

namespaces = [
    ('failed_prepare_f6564fa', find_head('f6564fa1e599882ffcaf428120033d7598e3f4d2')),
    ('failed_prepare_c5f3294', find_head('c5f32946d0bd152c5cf32d174cdf68fa34326aee')),
    ('final_1e8ebc0', find_head('1e8ebc0f0e84484cca237bccfa93a83f491a7bbe')),
]

zip_path = out / 'raw_attempts.zip'
members = {}
source_paths = {}
with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for prefix, root in namespaces:
        source_paths[prefix] = str(root)
        files = sorted(p for p in root.rglob('*') if p.is_file())
        for path in files:
            rel = path.relative_to(root).as_posix()
            member = f'{prefix}/{rel}'
            data = path.read_bytes()
            zf.writestr(member, data)
            members[member] = {'size': len(data), 'sha256': sha(data), 'source_path': str(path)}

with zipfile.ZipFile(zip_path, 'r') as zf:
    if set(zf.namelist()) != set(members):
        raise RuntimeError('archive member set mismatch')
    for member, meta in members.items():
        data = zf.read(member)
        if len(data) != meta['size'] or sha(data) != meta['sha256']:
            raise RuntimeError(f'archive byte mismatch: {member}')

archive_manifest = {
    'schema': 'cmr-v9-projection-witness-archive-manifest-v1',
    'compression': 'ZIP_DEFLATED',
    'member_count': len(members),
    'members': members,
    'archive_size': zip_path.stat().st_size,
    'archive_sha256': sha(zip_path.read_bytes()),
}
write_json(out/'archive_manifest.json', archive_manifest)

validation = out / 'validation'
validation.mkdir()
for path in sorted(p for p in ext.iterdir() if p.is_file()):
    shutil.copyfile(path, validation/path.name)

snapshot_names = ('runner.py', 'backend.py', 'builder.py', 'search.py', 'fixtures.py')
snapshots = {}
for short, head in (('f6564fa','f6564fa1e599882ffcaf428120033d7598e3f4d2'),
                    ('c5f3294','c5f32946d0bd152c5cf32d174cdf68fa34326aee'),
                    ('1e8ebc0','1e8ebc0f0e84484cca237bccfa93a83f491a7bbe')):
    srcroot = Path(f'/tmp/cmr_v9_source_{short}_20261022/experiments/cmr_ros2_reduction_reuse')
    dstroot = out/'source_snapshots'/short
    dstroot.mkdir(parents=True)
    snapshots[short] = {'git_commit': head, 'files': {}}
    for name in snapshot_names:
        src = srcroot/name
        if not src.is_file():
            raise RuntimeError(f'missing source snapshot: {src}')
        dst = dstroot/name
        shutil.copyfile(src, dst)
        snapshots[short]['files'][name] = {'size': dst.stat().st_size, 'sha256': sha(dst.read_bytes())}

final_plan = json.loads((namespaces[2][1]/'plan.json').read_bytes())
final_binding = json.loads((namespaces[2][1]/'backend_binding.json').read_bytes())
validation_files = {}
for p in sorted(validation.rglob('*')):
    if p.is_file():
        validation_files[p.relative_to(out).as_posix()] = {'size': p.stat().st_size, 'sha256': sha(p.read_bytes())}

artifact_manifest = {'schema':'cmr-v9-projection-witness-artifact-manifest-v1','files':{}}
for p in sorted(out.rglob('*')):
    if not p.is_file():
        continue
    rel=p.relative_to(out).as_posix()
    if rel in ('index.json','artifact_manifest.json'):
        continue
    artifact_manifest['files'][rel]={'size':p.stat().st_size,'sha256':sha(p.read_bytes())}
artifact_manifest['file_count']=len(artifact_manifest['files'])
write_json(out/'artifact_manifest.json', artifact_manifest)

index = {
    'schema':'cmr-v9-projection-witness-evidence-index-v1',
    'status':'PACKAGED',
    'scope':'V9 projection and witness reuse; fixed C3-T4/AP-D single-cell comparison',
    'source_head': final_plan.get('source_head'),
    'source_closure_count': len(final_plan.get('source_closure',{})),
    'frozen_input_count': len(json.loads((namespaces[2][1]/'frozen_inputs_before.json').read_bytes())),
    'final_binding_id': final_plan.get('version_binding_id'),
    'final_binding_sha256': final_plan.get('version_binding_sha256'),
    'final_backend_binding_id': final_binding.get('binding_id'),
    'namespaces': {
        prefix:{'path':source_paths[prefix], 'source_head':json.loads((root/'plan.json').read_bytes()).get('source_head'),
                'dispatches_present':(root/'dispatches').exists(),
                'real_worker_count':4 if prefix=='final_1e8ebc0' else 0,
                'raw_zip_prefix':prefix}
        for prefix,root in namespaces
    },
    'actual_counts': {
        'prepare_failures':2, 'new_workers':4, 'run_one':4,
        'worker_internal_certificate_verification':4, 'independent_replays':4,
        'dds_requests':0, 'provider_calls':0, 'formal_campaign':False,
        'package_solver_workers':0, 'package_workers':0, 'package_verifiers':0,
    },
    'final_verdicts':'all four reference/ros2-v7/ros2-v8/ros2-v9 attempts PASSED with six rounds and independent replay',
    'optimization_counters': {
        'v8_projection_computations':5382, 'v9_projection_computations':384,
        'v8_witness_key_computations':3531, 'v9_witness_key_computations':757,
        'v8_witness_items_normalized':10752, 'v9_witness_items_normalized':2304,
        'full_ts':'one build plus five hits per arm', 'guard_charged':True,
    },
    'v8_observation':'V8 is counter-only observation; V9 enables projection and witness caches.',
    'scientific_limits': {
        'timing':'single-run observation; not a stable performance conclusion',
        'ablation':'projection and witness optimizations were combined; no separated ablation',
        'development_fixtures_solver_calls':'unknown; fixtures invoke the synthetic small-graph solver and were not globally counted',
        'real_cmr_workers':4,
        'package_execution_workers':0,
        'old_v8_control_archive_sha256':'0a923837...',
        'full_batch':False,
    },
    'source_snapshots':snapshots,
    'validation_paths':validation_files,
    'archive_manifest':{'path':'archive_manifest.json','size':(out/'archive_manifest.json').stat().st_size,'sha256':sha((out/'archive_manifest.json').read_bytes())},
    'artifact_manifest':{'path':'artifact_manifest.json','size':(out/'artifact_manifest.json').stat().st_size,'sha256':sha((out/'artifact_manifest.json').read_bytes()),'file_count':artifact_manifest['file_count']},
    'raw_archive':{'path':'raw_attempts.zip','size':zip_path.stat().st_size,'sha256':sha(zip_path.read_bytes()),'member_count':len(members)},
}
write_json(out/'index.json', index)
# Parse every JSON artifact and verify the manifest's files after index creation.
for p in out.rglob('*.json'):
    json.loads(p.read_bytes())
for rel, meta in artifact_manifest['files'].items():
    p=out/rel
    if p.stat().st_size != meta['size'] or sha(p.read_bytes()) != meta['sha256']:
        raise RuntimeError(f'artifact mismatch: {rel}')
print(json.dumps({'output':str(out),'raw_archive_size':zip_path.stat().st_size,'raw_archive_sha256':sha(zip_path.read_bytes()),'member_count':len(members),'artifact_file_count':artifact_manifest['file_count'],'f656_path':source_paths['failed_prepare_f6564fa'],'c5_path':source_paths['failed_prepare_c5f3294'],'final_path':source_paths['final_1e8ebc0']}, sort_keys=True))
