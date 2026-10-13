"""Synthetic zero-cost qualification through the frozen run_one/verifier ABI.

This derived input is never a Core instance or a unified-entry production cell.
It lives in its own benchmark directory and manifest; frozen data is read only.
"""

import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from experiments.cmr_ros2_search_entry import runner


INSTANCE = 'SYNTHETIC-ZERO-COST-A-T1'


def run(args, plan, output):
    output = Path(output).resolve()
    if not str(output).startswith('/tmp/'):
        raise ValueError('synthetic qualification must use a fresh /tmp namespace')
    output.mkdir(parents=True, exist_ok=False)
    formal, bound, authority, _ = runner.old_runner.authority(
        plan, args.binding, args.kernel_root)
    record = next(item for item in plan['records']
                  if item['instance_id'] == 'A-T1-M0-A-S-BRANCH')
    source = runner.adapter._native_path(bound['benchmark_root']) / record['path']
    before = runner.digest(source)
    payload = copy.deepcopy(json.loads(source.read_bytes()))
    payload['instance_id'] = INSTANCE
    costs = 0
    for action in payload['model']['actions']:
        for row in action['cost_table']:
            row['value'] = '0'
            costs += 1
    if not costs:
        raise AssertionError('source has no explicit action costs')
    benchmark = output / 'synthetic_benchmark'
    relative = 'instances/' + INSTANCE + '.json'
    runner.write(benchmark / relative, payload)
    synthetic = dict(record, instance_id=INSTANCE, path=relative,
                     source='SYNTHETIC_QUALIFICATION', cohort='SYNTHETIC',
                     dataset_revision='SYNTHETIC_ZERO_COST_V1',
                     instance_sha256=runner.digest(benchmark / relative),
                     model_sha256=hashlib.sha256(runner.canonical(payload['model']).encode()).hexdigest(),
                     parent_instance_sha256=before)
    manifest = benchmark / 'manifests/manifest.json'
    runner.write(manifest, [synthetic])
    # Keep the certificate ABI's expected contract/benchmark constants. The
    # test namespace and synthetic manifest bind this input, outside Core.
    identity = plan['source_head'] + '+synthetic-zero-' + synthetic['instance_sha256'][:16]
    cell = dict(instance_id=INSTANCE, method='FULL', canonical_instance_index=0,
                method_order_position=0, population='SYNTHETIC_QUALIFICATION',
                formal_campaign=False)
    entry = runner.VerifiedEntry(plan, runner.source_closure, runner.schema_for)
    receipt = json.loads(runner.adapter._native_path(args.binding).read_bytes())
    results = {}
    for name in runner.NAMES:
        formal, _, _, _ = runner.old_runner.authority(plan, args.binding, args.kernel_root)
        descriptor = entry.describe(name)
        capture = runner.configure(formal, name, descriptor)
        directory = output / name
        directory.mkdir()
        row = formal.run_one(cell, {INSTANCE: synthetic}, directory / 'certificates',
                             benchmark_root=benchmark, execution_commit=identity,
                             planner_budget_seconds=180)
        row.update(**descriptor, qualification_scope='SYNTHETIC_ZERO_COST_V1',
                   formal_campaign=False)
        for round_row in row.get('rounds') or []:
            round_row.update(**descriptor)
        row.pop('result_hash', None)
        row['result_hash'] = formal.sha256_bytes(formal.canonical_json(row).encode())
        entry.schema(name, receipt).validate_result(row)
        lasso = capture['lasso']
        if row['terminal_status'] != 'OPTIMALITY_CERTIFIED' or lasso is None:
            raise AssertionError('zero-cost input was not certified: ' + name)
        if Fraction(row['objective']) != 0 or Fraction(row['certificate_objective']) != 0:
            raise AssertionError('nonzero certified objective: ' + name)
        if not lasso.suffix_edges:
            raise AssertionError('zero cost removed the nonempty suffix')
        transport = dict(concrete_lasso=runner.v6.real.runtime.lasso_payload(lasso))
        runner.old_runner.terminal_delivery(row, formal.time.perf_counter_ns(),
                                           outer_start=row['method_start_ns'])
        if row['terminal_status'] != 'OPTIMALITY_CERTIFIED' or not row['certificate_valid_for_terminal']:
            raise AssertionError('legal zero-cost delivery rejected: ' + name)
        entry.schema(name, receipt).validate_result(row)
        cert = directory / 'certificates' / row['certificate_path']
        replay = formal.verify_certificate_file(cert, row['certificate_hash'],
            benchmark, manifest, identity, formal.EXECUTION_CONTRACT_COMMIT,
            formal.BENCHMARK_COMMIT)
        if replay['status'] != 'PASS' or Fraction(replay['objective']) != 0:
            raise AssertionError('independent zero-cost replay failed: ' + name)
        runner.write(directory / 'result.json', dict(row=row, transport=transport))
        runner.write(directory / 'certificate_replay.json', replay)
        results[name] = dict(status=row['terminal_status'], objective=row['objective'],
                             suffix_edges=len(lasso.suffix_edges), replay=replay,
                             certificate_hash=row['certificate_hash'])
    negatives = []
    certificate = json.loads(cert.read_bytes())
    for name in ('objective_plus_one', 'empty_suffix'):
        altered = copy.deepcopy(certificate)
        if name == 'objective_plus_one':
            altered['objective'] = '1'
        else:
            altered['full_model_lasso']['suffix_edges'] = []
        path = output / 'negative_certificates' / (name + '.json')
        runner.write(path, altered)
        try:
            formal.verify_certificate_file(path, runner.digest(path), benchmark,
                manifest, identity, formal.EXECUTION_CONTRACT_COMMIT,
                formal.BENCHMARK_COMMIT)
        except ValueError as error:
            negatives.append(dict(case=name, status='REJECTED', reason=str(error),
                                  sha256=runner.digest(path)))
        else:
            raise AssertionError('invalid zero-cost certificate accepted: ' + name)
    entry.release_check()
    if runner.digest(source) != before:
        raise AssertionError('original Core input changed')
    report = dict(schema='cmr-v7-zero-certificate-qualification-v1', status='PASSED',
                  population='SYNTHETIC_QUALIFICATION', core_instances=0,
                  formal_campaign=False, source_head=plan['source_head'],
                  execution_identity=identity, version_binding_id=plan['version_binding_id'],
                  version_binding_sha256=plan['version_binding_sha256'],
                  authority=authority, harness_sha256=runner.digest(Path(__file__)),
                  source_instance_sha256=before, synthetic_instance=synthetic,
                  explicit_cost_rows_zeroed=costs, results=results,
                  planner_budget_seconds=180, outer_watchdog_seconds=195,
                  process_watchdog_exercised=False,
                  unified_candidate_isolated_exercised=False,
                  positive_independent_replays=6, rejected_certificate_checks=negatives,
                  verifier_invocations=8, provider_calls=0)
    runner.write(output / 'zero_certificate.json', report)
    return report
