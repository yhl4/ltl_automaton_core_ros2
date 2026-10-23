"""Execute only the outcome-blind, fixed real-instance qualification subset."""

import argparse
from fractions import Fraction
import json
from pathlib import Path
import shutil
import traceback

import runner


def check_pair(reference, ros2, method):
    left, right = reference['row'], ros2['row']
    if left['terminal_status'] != right['terminal_status']:
        raise AssertionError('reference/ROS2 terminal verdict disagreement')
    if left['terminal_status'] not in ('OPTIMALITY_CERTIFIED', 'INFEASIBLE_CERTIFIED'):
        raise AssertionError('selected comparison is not certified; retain censored/error evidence')
    if left['initial_S0'] != right['initial_S0']:
        raise AssertionError('initial precision mismatch')
    if left['terminal_status'] == 'OPTIMALITY_CERTIFIED':
        if Fraction(left['objective']) != Fraction(right['objective']):
            raise AssertionError('SCIENTIFIC_CORRECTNESS_BLOCKER: certified objective disagreement')
        for value in (reference, ros2):
            row = value['row']
            if row['certificate_verifier_status'] != 'PASS' or value['transport'] is None:
                raise AssertionError('independent persisted-certificate verification missing')
    for value in (reference, ros2):
        row = value['row']
        if value['worker_exitcode'] != 0 or value['worker_alive_after_cleanup']:
            raise AssertionError('worker failure/leak')
        if row['T_total'] != (row['terminal_completion_ns'] - row['method_start_ns']) / 1e9:
            raise AssertionError('runtime is not tied to actual terminal completion')
        rounds = row.get('rounds') or []
        for previous, current in zip(rounds, rounds[1:]):
            if not set(previous['S_k']) < set(current['S_k']):
                raise AssertionError('non-increasing refinement precision')


def run(args, report):
    selection = runner.load_selection()
    shutil.copyfile(runner.HERE / 'selection.json', args.output / 'selection.json')
    for record in selection['records']:
        for method in selection['methods']:
            pair = dict(instance_id=record['instance_id'], method=method, status='RUNNING')
            report['pairs'].append(pair)
            runner.runtime.write_json(args.output / 'qualification.json', report)
            for backend in ('reference', 'ros2'):
                request = runner.request_for(record['instance_id'], method, backend)
                attempt = args.output / f'{record["instance_id"]}_{method}_{backend}'
                pair[backend] = runner.run_isolated(request, args.binding, args.kernel_root, attempt)
                runner.runtime.write_json(args.output / 'qualification.json', report)
                print(json.dumps(dict(instance_id=record['instance_id'], method=method,
                                      backend=backend, status=pair[backend]['row']['terminal_status'],
                                      T_total=pair[backend]['row']['T_total'])), flush=True)
            check_pair(pair['reference'], pair['ros2'], method)
            pair['status'] = 'PASSED'
            runner.runtime.write_json(args.output / 'qualification.json', report)
    # The actual selected-instance DDS attempt and verifier negatives run once.
    from dds_real import run_dds
    from verifier_checks import check_negative_certificates
    report['verifier_negatives'] = check_negative_certificates(args, report)
    report['dds'] = run_dds(args.binding, args.kernel_root, args.output / 'dds')
    report['status'] = 'PASSED'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not str(args.output).startswith('/tmp/'):
        raise SystemExit('output must be a fresh /tmp directory')
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema='cmr-ros2-real-qualification-v1', scope=runner.SCOPE,
                  status='RUNNING', formal_campaign=False, pairs=[])
    try:
        run(args, report)
        code = 0
    except Exception as error:
        report.update(status='FAILED', error=repr(error), traceback=traceback.format_exc())
        traceback.print_exc()
        code = 1
    runner.runtime.write_json(args.output / 'qualification.json', report)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
