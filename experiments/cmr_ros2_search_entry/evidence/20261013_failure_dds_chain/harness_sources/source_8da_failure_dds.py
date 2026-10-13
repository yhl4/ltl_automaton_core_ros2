"""Four isolated V7 DDS failure/empty cases; no campaign entry."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

DOMAIN_ID = 228
CASES = (('late_delivery', 'A-T1-M0-A-S-BRANCH', 'TIMEOUT'),
         ('crash', 'A-T1-M0-A-S-BRANCH', 'INFRASTRUCTURE_FAILURE'),
         ('server_error', 'A-T1-M0-A-S-BRANCH', 'ERROR'),
         ('none', 'D1-1', 'INFEASIBLE_CERTIFIED'))


def child(mode, argv):
    from experiments.cmr_ros2_search_entry import runner, dds, lifecycle
    original = runner.candidate_isolated
    def candidate(args, plan, cell, output):
        if mode == 'server_error':
            raise RuntimeError('qualification-injected V7 server error; no worker dispatched')
        if mode == 'none':
            return original(args, plan, cell, output)
        entry = runner.VerifiedEntry(plan, runner.source_closure, runner.schema_for)
        request = runner.request_for(plan, entry, cell, 'ros2-v7')
        return lifecycle.run_fault(request, args.binding, args.kernel_root,
            Path(plan['version_binding_path']), args.output/'plan.json', output, mode)
    runner.candidate_isolated = candidate
    try:
        return dds.main(argv)
    finally:
        runner.candidate_isolated = original


def run(args, plan, output):
    from experiments.cmr_ros2_search_entry import runner, dds
    plan = runner.load_plan(args.plan)
    if plan['scope'] != runner.DDS_FAILURE_SCOPE:
        raise ValueError('a separately prepared failure qualification plan is required')
    cells = dds._fixed_cells(plan)
    output = Path(output).resolve()
    if not str(output).startswith('/tmp/'):
        raise ValueError('DDS qualification requires a fresh /tmp namespace')
    output.mkdir(parents=True, exist_ok=False)
    entry = runner.VerifiedEntry(plan, runner.source_closure, runner.schema_for)
    descriptor = entry.describe('ros2-v7')
    dcell = cells[('D1-1', 'FULL')]
    reference = runner.candidate_isolated(args, plan, dcell,
                                         output/'reference_D1', backend_name='reference')
    if reference['row']['terminal_status'] != 'INFEASIBLE_CERTIFIED':
        raise AssertionError('original D1 exact-empty control failed')
    report = dict(schema='cmr-v7-failure-dds-qualification-v1', status='RUNNING',
                  source_head=plan['source_head'], execution_identity=plan['execution_identity'],
                  descriptor=descriptor, domain_id=DOMAIN_ID, cases=[],
                  reference=reference, method_workers=4, dds_cases=4,
                  harness_sha256=runner.digest(Path(__file__)),
                  lifecycle_harness_sha256=runner.digest(HERE/'lifecycle.py'),
                  planner_budget_seconds=180, outer_watchdog_seconds=195,
                  formal_campaign=False, provider_calls=0)
    dds._write_json(output/'failure_dds_report.json', report)
    real_popen = subprocess.Popen
    old_domain = dds.DOMAIN_ID
    for mode, instance, terminal in CASES:
        directory = output/('dds_'+mode)
        request = dict(runner.request_for(plan, entry, cells[(instance,'FULL')], 'ros2-v7'),
                       request_id='cmr-v7-failure-'+mode)
        case = dict(request, expected_terminal=terminal)
        artifact = dict(status='FAILED', request=request)
        def popen(command, **kwargs):
            command = list(command)
            path = str(dds.HERE/'dds.py')
            if path in command:
                command[command.index(path)] = str(HERE/'failure_dds.py')
                command.extend(['--dds-fault', mode])
            return real_popen(command, **kwargs)
        try:
            dds.DOMAIN_ID = DOMAIN_ID
            subprocess.Popen = popen
            artifact = dds._run_case(request, args, directory, descriptor)
            dds._validate_case(case, artifact, descriptor)
            if mode == 'none':
                value = json.loads((directory/'cmr_attempt/result.json').read_bytes())
                runner.qualification.check_pair(reference, value, 'FULL')
                artifact['certificate_replay'] = runner.old_runner.replay(
                    plan, args.binding, args.kernel_root, value, directory/'cmr_attempt')
            artifact['status'] = 'PASSED'
        except Exception:
            artifact.update(status='FAILED', traceback=traceback.format_exc())
        finally:
            subprocess.Popen = real_popen
            dds.DOMAIN_ID = old_domain
        directory.mkdir(parents=True, exist_ok=True)
        dds._write_json(directory/'dds_artifact.json', artifact)
        report['cases'].append(dict(mode=mode, expected_terminal=terminal, artifact=artifact))
        dds._write_json(output/'failure_dds_report.json', report)
        print(json.dumps(dict(mode=mode, status=artifact['status'])), flush=True)
    entry.release_check()
    report['status'] = 'PASSED' if all(c['artifact']['status']=='PASSED' for c in report['cases']) else 'FAILED'
    dds._write_json(output/'failure_dds_report.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--dds-fault', choices=[c[0] for c in CASES], required=True)
    special, remaining = parser.parse_known_args()
    raise SystemExit(child(special.dds_fault, remaining))
