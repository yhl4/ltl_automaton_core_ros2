"""Fault qualification of the real unified entry, isolated from ordinary CLI.

Offset clocks test the unchanged 180-second predicates, not measured runtime.
One non-cooperative child really waits for the unchanged 195-second watchdog.
"""

import argparse
import copy
import inspect
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from experiments.cmr_ros2_backend import backends, runner

REAL_TIME = time
REAL_POPEN = subprocess.Popen
UNIFIED_RUN = runner.run_isolated
PROOFS = runner.real.PROOF_FIELDS
MODES = ('late_solver', 'late_certificate', 'late_logging', 'late_delivery',
         'crash', 'missing_result', 'malformed_result', 'crash_after_result', 'watchdog')


class OffsetClock:
    def __init__(self, mode=''):
        self.offset_ns = 0
        self.mode = mode

    def perf_counter_ns(self):
        if self.mode == 'late_logging' and not self.offset_ns:
            frame = inspect.currentframe().f_back
            if frame.f_code.co_name == 'run_one' and 'logging_started_ns' in frame.f_locals:
                self.offset_ns = 180_000_000_000
        return REAL_TIME.perf_counter_ns() + self.offset_ns

    def __getattr__(self, name):
        return getattr(REAL_TIME, name)


def no_claims(value, expected):
    row = value['row']
    assert row['terminal_status'] == expected
    assert row['objective'] is None and value['transport'] is None
    assert row['certificate_valid_for_terminal'] is False
    assert row['certificate_verifier_status'] == 'NOT_AVAILABLE'
    assert row.get('certificate_path', 'NOT_AVAILABLE') == row.get('certificate_hash', 'NOT_AVAILABLE') == 'NOT_AVAILABLE'
    assert all(row.get(k) is None for k in PROOFS)
    assert all(r.get('terminal_claim_valid') is False and all(r.get(k) is None for k in PROOFS)
               for r in row.get('rounds') or [])
    assert row['planner_budget_seconds'] == 180 and row['outer_watchdog_seconds'] == 195
    assert row['T_total'] == (row['terminal_completion_ns'] - row['method_start_ns']) / 1e9
    assert row['right_censored'] is (expected == 'TIMEOUT')
    assert not value.get('worker_alive_after_cleanup', False)
    if expected == 'TIMEOUT':
        assert row['T_total'] >= 180 and row['timing_status'] == 'RIGHT_CENSORED'
    else:
        assert row['T_total'] < 180 and row['timing_status'] == 'ANOMALY'


def boundary_checks(plan, receipt, kernel_root, output):
    checks = []
    archive = HERE / 'evidence/20261012/raw_attempts.zip'
    with zipfile.ZipFile(archive) as zipped:
        samples = [json.loads(zipped.read(member))['row'] for member in (
            'B-D-BRANCH-S1_FULL/ros2-v6/result.json', 'D1-1_FULL/ros2-v6/result.json')]
    start = 1_000_000_000
    for sample in samples:
        for elapsed in (179_999_999_999, 180_000_000_000, 180_000_000_001, 195_000_000_000):
            row = copy.deepcopy(sample)
            row.update(method_start_ns=start, terminal_completion_ns=start + 100,
                       qualified_runner_completion_ns=start + 100)
            runner.terminal_delivery(row, start + elapsed, outer_start=start)
            value = dict(row=row, transport=None)
            if elapsed >= 180_000_000_000:
                no_claims(value, 'TIMEOUT')
            else:
                assert row['terminal_status'] == sample['terminal_status']
            checks.append(dict(name=sample['terminal_status'] + '_' + str(elapsed), status='PASSED'))
    formal, _, _, _ = runner.authority(plan, receipt, kernel_root)
    backends.configure(formal, 'ros2-v6', plan['version_binding_path'])
    cell = runner.make_request(plan, 'C2-T3', 'FULL', 'ros2-v6')
    for stage in ('planner', 'outer_watchdog', 'infrastructure'):
        elapsed = 195_000_000_000 if stage == 'outer_watchdog' else (180_000_000_000 if stage == 'planner' else 100)
        row = formal.timeout_serialization(cell, stage, method_start_ns=start, terminal_completion_ns=start + elapsed)
        runner.terminal_delivery(row, start + elapsed, outer_start=start, forced_timeout=stage == 'outer_watchdog')
        no_claims(dict(row=row, transport=None), 'INFRASTRUCTURE_FAILURE' if stage == 'infrastructure' else 'TIMEOUT')
        checks.append(dict(name='original_' + stage + '_serialization', status='PASSED'))
    result = dict(status='PASSED', checks=checks, count=len(checks), simulated_clock=True,
                  solver_calls=0, planner_budget_seconds=180, outer_watchdog_seconds=195)
    runner.write(output, result)
    return result


def fault_child(mode):
    """Call runner.main/worker with test-only hooks after real binding checks."""
    original_worker = runner.worker
    original_configure = backends.configure
    clock = OffsetClock(mode)

    def configure(formal, *args):
        capture = original_configure(formal, *args)
        formal.time = clock
        if mode == 'late_solver':
            original = formal.run_method_local
            def late_solver(*args, **kwargs):
                answer = original(*args, **kwargs)
                clock.offset_ns = 180_000_000_000
                return answer
            formal.run_method_local = late_solver
        elif mode == 'late_certificate':
            original = formal.persist_and_verify_certificate
            def late_certificate(*args, **kwargs):
                answer = original(*args, **kwargs)
                clock.offset_ns = 180_000_000_000
                return answer
            formal.persist_and_verify_certificate = late_certificate
        return capture

    def worker(args):
        plan = runner.load_plan(args.plan)
        request = json.loads(args.request.read_bytes())
        runner.validate_request(plan, request, args.backend)
        if mode in ('crash', 'missing_result', 'malformed_result', 'watchdog'):
            formal, _, manifest, _ = runner.authority(plan, args.binding, args.kernel_root)
            original_configure(formal, args.backend, args.version_binding)
            runner.write(args.output / 'fault_preflight.json', manifest)
            runner.write(args.output / 'fault_marker.json', dict(mode=mode, budget=180, watchdog=195, pid=os.getpid()))
            if mode == 'crash':
                os._exit(23)
            if mode == 'missing_result':
                return
            if mode == 'malformed_result':
                (args.output / 'worker_result.json').write_text('{broken', encoding='utf-8')
                return
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            while True:
                REAL_TIME.sleep(1)
        original_worker(args)
        runner.write(args.output / 'fault_clock.json', dict(mode=mode, offset_ns=clock.offset_ns,
                     measurement='simulated deadline predicate; not wall runtime'))
        if mode == 'crash_after_result':
            os._exit(23)

    backends.configure = configure
    runner.worker = worker
    return runner.main()


def run_fault(request, receipt, kernel_root, version_path, plan_path, output, mode):
    """Use actual run_isolated; replace only its test child's entry and clock."""
    clock = OffsetClock()
    old_time = runner.time
    old_popen = runner.subprocess.Popen
    output = Path(output)
    wall_start = REAL_TIME.perf_counter_ns()

    def popen(command, **kwargs):
        command = list(command)
        if str(HERE / 'runner.py') not in command:
            return REAL_POPEN(command, **kwargs)
        command[command.index(str(HERE / 'runner.py'))] = str(HERE / 'lifecycle.py')
        command.extend(['--fault-child', mode])
        process = REAL_POPEN(command, **kwargs)
        original_wait = process.wait
        def wait(*args, **kwargs):
            rc = original_wait(*args, **kwargs)
            clock_path = output / 'fault_clock.json'
            if clock_path.exists():
                clock.offset_ns = json.loads(clock_path.read_bytes())['offset_ns']
            if mode == 'late_delivery':
                clock.offset_ns = 180_000_000_000
            return rc
        process.wait = wait
        return process

    runner.time = clock
    runner.subprocess.Popen = popen
    try:
        value = UNIFIED_RUN(request, receipt, kernel_root, version_path, plan_path, output)
    finally:
        runner.time = old_time
        runner.subprocess.Popen = old_popen
    value['fault_qualification'] = dict(mode=mode, simulated_clock=mode.startswith('late_'),
        actual_wall_seconds=(REAL_TIME.perf_counter_ns() - wall_start) / 1e9,
        injected_offset_ns=clock.offset_ns, planner_budget_seconds=180, outer_watchdog_seconds=195)
    runner.write(output / 'fault_qualification.json', value['fault_qualification'])
    return value


def dds_child(mode):
    from experiments.cmr_ros2_backend import dds
    original = runner.run_isolated
    if mode == 'server_error':
        def server_error(*args):
            raise RuntimeError('qualification-injected DDS server failure; no solver dispatched')
        runner.run_isolated = server_error
    else:
        runner.run_isolated = lambda *args: run_fault(*args, mode=mode) if mode != 'none' else original(*args)
    parser = argparse.ArgumentParser()
    parser.add_argument('--role', required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--seconds', type=float, required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    parser.add_argument('--version-binding', required=True)
    parser.add_argument('--plan', required=True)
    args = parser.parse_args()
    return dds._child(args.role, args.request, args.work_dir, args.seconds, args.binding,
                      args.kernel_root, args.version_binding, args.plan)


def run(args, plan, output):
    from experiments.cmr_ros2_backend import dds
    output.mkdir()
    request = runner.make_request(plan, 'C2-T3', 'FULL', 'ros2-v6')
    report = dict(status='RUNNING', cases=[], dds_cases=[])
    plan_path = args.output / 'plan.json'
    version = Path(plan['version_binding_path'])
    failures = []
    for mode in MODES:
        directory = output / mode
        try:
            value = run_fault(request, args.binding, args.kernel_root, version, plan_path, directory, mode)
            expected = 'TIMEOUT' if mode.startswith('late_') or mode == 'watchdog' else 'INFRASTRUCTURE_FAILURE'
            no_claims(value, expected)
            if mode == 'watchdog':
                assert value['fault_qualification']['actual_wall_seconds'] >= 195
                assert value['row']['timeout_stage'] == 'outer_watchdog' and value['worker_exitcode'] == -signal.SIGKILL
            try:
                os.kill(value['worker_pid'], 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError('worker survived cleanup')
            report['cases'].append(dict(mode=mode, status='PASSED', result=value))
        except Exception:
            failures.append(mode)
            report['cases'].append(dict(mode=mode, status='FAILED', traceback=traceback.format_exc()))
        runner.write(output / 'lifecycle.json', report)
        print(json.dumps(dict(fault=mode, status=report['cases'][-1]['status'])), flush=True)
    for case in plan['dds_cases']:
        mode = case['fault']
        envelope = dict(request, request_id='cmr-v2-fault-' + mode)
        directory = output / ('dds_' + mode)
        try:
            old_popen = dds.subprocess.Popen
            def popen(command, **kwargs):
                command = list(command)
                if str(HERE / 'dds.py') not in command:
                    return REAL_POPEN(command, **kwargs)
                command[command.index(str(HERE / 'dds.py'))] = str(HERE / 'lifecycle.py')
                command.extend(['--dds-fault', mode])
                return REAL_POPEN(command, **kwargs)
            dds.subprocess.Popen = popen
            try:
                artifact = dds._run_case(envelope, argparse.Namespace(binding=args.binding,
                    kernel_root=args.kernel_root, version_binding=version, plan=plan_path), directory,
                    backends.describe(version, 'ros2-v6'))
            finally:
                dds.subprocess.Popen = old_popen
            dds._validate_case(dict(envelope, expected_terminal=case['expected_terminal']), artifact,
                               backends.describe(version, 'ros2-v6'))
            if mode == 'none':
                value = json.loads((directory / 'cmr_attempt/result.json').read_bytes())
                artifact['certificate_replay'] = runner.replay(plan, args.binding, args.kernel_root,
                                                             value, directory / 'cmr_attempt')
            report['dds_cases'].append(dict(mode=mode, status='PASSED', artifact=artifact))
        except Exception:
            failures.append('dds_' + mode)
            report['dds_cases'].append(dict(mode=mode, status='FAILED', traceback=traceback.format_exc()))
        runner.write(output / 'lifecycle.json', report)
        print(json.dumps(dict(dds_fault=mode, status=report['dds_cases'][-1]['status'])), flush=True)
    report.update(status='FAILED' if failures else 'PASSED', failures=failures,
                  formal_campaign_workers=0, provider_calls=0)
    runner.write(output / 'lifecycle.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--fault-child')
    parser.add_argument('--dds-fault')
    special, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0]] + remaining
    if special.fault_child in MODES:
        raise SystemExit(fault_child(special.fault_child))
    if special.dds_fault in ('none', 'late_delivery', 'crash', 'server_error'):
        raise SystemExit(dds_child(special.dds_fault))
    raise ValueError('lifecycle is a qualification harness, not an ordinary worker entry')
