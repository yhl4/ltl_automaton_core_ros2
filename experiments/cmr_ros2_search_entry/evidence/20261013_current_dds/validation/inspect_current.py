import json
from pathlib import Path

for label in ('search_fixed', 'failure_fixed2'):
    root = Path('/tmp/cmr_v7_current_dds_20261013_' + label)
    plan = json.loads((root / 'plan/plan.json').read_bytes())
    binding = json.loads(Path(plan['version_binding_path']).read_bytes())
    print(label, 'plan_keys', list(plan))
    print('binding_keys', list(binding))
    print('closure_example', list(plan['source_closure'].items())[:2])
    print('record_example', plan['records'][0])
    print('input_example', list(plan.get('frozen_inputs', {}).items())[:2])
    reports = list(root.rglob('*report.json'))
    print('reports', [str(p.relative_to(root)) for p in reports])
    cases = sorted(root.rglob('dds_artifact.json'))
    for path in cases:
        a = json.loads(path.read_bytes())
        print('artifact', path.relative_to(root), 'keys', list(a))
        print('driver_keys', list(a.get('driver', {})), 'server_keys', list(a.get('server', {})))
        print('attempt_files', [str(p.relative_to(path.parent)) for p in path.parent.rglob('*') if p.is_file()][:35])
        print('compact', a.get('status'), a.get('driver', {}).get('result', {}).get('terminal_status'), a.get('driver', {}).get('expected_actions'), a.get('server', {}).get('served_snapshot_count'))
        if a.get('driver', {}).get('result', {}).get('worker_pid'):
            v = json.loads((path.parent/'cmr_attempt/result.json').read_bytes())
            print('value_keys', list(v), 'request', json.loads((path.parent/'request.json').read_bytes()))
        break
