"""Explicit reference / ROS2 V6 selection for a bound CMR runner."""

import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.cmr_ros2_product_perf import compare as v6

NAMES = ('reference', 'ros2-v6')
VERSION = 'CMR_UNIFIED_BACKENDS_V2'
QUALIFIED_V6_ARCHIVE_SHA = 'fe4b6759890a4a6f8175792e8d5dab13c8d60dd37a7e56e5efe5769f01333f44'
digest = v6.real.digest
canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def source_closure():
    closure = v6.source_closure()
    archive = v6.HERE / 'evidence/20261012/raw_attempts.zip'
    if digest(archive) != QUALIFIED_V6_ARCHIVE_SHA:
        raise ValueError('qualified V6 archive bytes changed')
    with zipfile.ZipFile(archive) as zipped:
        expected = json.loads(zipped.read('plan.json'))['source_closure']
    if closure != expected:
        raise ValueError('qualified V6 source bytes changed')
    for name in ('backends.py', 'runner.py', 'acceptance.py', 'lifecycle.py', 'offline_chain.py'):
        path = HERE / name
        closure[str(path.relative_to(ROOT))] = digest(path)
    return closure


def create_binding(receipt_path):
    receipt_path = v6.adapter._native_path(receipt_path)
    receipt = json.loads(receipt_path.read_bytes())
    authority = v6.real.load_selection()
    if digest(receipt_path) != authority['receipt_sha256']:
        raise ValueError('qualified authority receipt mismatch')
    content = dict(schema='cmr-unified-backend-binding-v2', version=VERSION,
        qualification_only=True, formal_campaign=False,
        semantic_contract_id='INITIAL_LABEL_V1', objective='prefix_cost + 10*suffix_cost',
        nonempty_accepting_suffix=True, full_ts_rebuild_every_round=True,
        methods=['FULL', 'AP-D', 'DEP-D'], planner_budget_seconds=180,
        outer_watchdog_seconds=195, receipt_sha256=authority['receipt_sha256'],
        original_execution_binding_sha256=authority['binding_sha256'],
        manifest_sha256=authority['manifest_sha256'], source_closure=source_closure(),
        backends={
            'reference': dict(backend_id='ECC-P1-SCC-INITIAL_LABEL_V1',
                backend_sha256=receipt['scientific_source_refs']['SCC_solver']['sha256']),
            'ros2-v6': dict(backend_id=v6.ID, backend_sha256=v6.identity()),
        })
    identity = hashlib.sha256(canonical(content).encode()).hexdigest()
    return dict(content, binding_id=VERSION + '-' + identity[:16])


def load_binding(path, expected_sha256=None):
    path = Path(path)
    if expected_sha256 is not None and digest(path) != expected_sha256:
        raise ValueError('backend version binding hash mismatch')
    value = json.loads(path.read_bytes())
    content = dict(value)
    binding_id = content.pop('binding_id')
    if binding_id != VERSION + '-' + hashlib.sha256(canonical(content).encode()).hexdigest()[:16]:
        raise ValueError('backend version binding identity mismatch')
    if (value['schema'] != 'cmr-unified-backend-binding-v2' or value['version'] != VERSION
            or value['source_closure'] != source_closure()
            or value['methods'] != ['FULL', 'AP-D', 'DEP-D']
            or value['semantic_contract_id'] != 'INITIAL_LABEL_V1'
            or value['objective'] != 'prefix_cost + 10*suffix_cost'
            or value['planner_budget_seconds'] != 180 or value['outer_watchdog_seconds'] != 195
            or not value['nonempty_accepting_suffix'] or not value['full_ts_rebuild_every_round']
            or value['formal_campaign'] is not False or value['qualification_only'] is not True
            or set(value['backends']) != set(NAMES)):
        raise ValueError('unsupported backend version or semantic contract')
    # A valid file cannot advertise different implementations under the names.
    authority = v6.real.load_selection()
    if (value['receipt_sha256'] != authority['receipt_sha256']
            or value['original_execution_binding_sha256'] != authority['binding_sha256']
            or value['manifest_sha256'] != authority['manifest_sha256']
            or value['backends']['ros2-v6'] != dict(backend_id=v6.ID, backend_sha256=v6.identity())
            or value['backends']['reference'] != dict(backend_id='ECC-P1-SCC-INITIAL_LABEL_V1',
                backend_sha256='3f0c3775febe070699e9e353a5183aad24b569303547f77e1ea07d0e853ed1a3')):
        raise ValueError('backend implementation or science authority mismatch')
    return value


def describe(path, backend):
    if backend not in NAMES:
        raise ValueError('backend must be reference or ros2-v6; no fallback')
    value = load_binding(path)
    return dict(value['backends'][backend], backend=backend,
                version_binding_id=value['binding_id'], version_binding_sha256=digest(path))


def configure(formal, backend, path):
    descriptor = describe(path, backend)
    capture = v6.configure(formal, 'reference' if backend == 'reference' else 'optimized')
    if any(capture[key] != descriptor[key] for key in ('backend_id', 'backend_sha256')):
        raise ValueError('configured backend differs from explicit version binding')
    capture['backend_binding'] = descriptor
    return capture


def schema_for(receipt, backend):
    if backend not in NAMES:
        raise ValueError('unknown backend')
    return v6.schema_for(receipt, 'reference' if backend == 'reference' else 'optimized')
