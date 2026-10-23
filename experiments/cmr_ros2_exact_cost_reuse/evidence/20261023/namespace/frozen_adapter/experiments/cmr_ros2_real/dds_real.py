"""One actual DDS request for the preselected C1-T1/AP-D real instance."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import runner
import dds_smoke as transport

DOMAIN_ID = 219


class RealServer(transport._Server):
    def _request(self, message):
        if self.done:
            return
        request = json.loads(message.data)
        transport._event(self.events, 'request_received', request_id=request.get('request_id'))
        if request != self.request:
            raise ValueError('DDS request differs from the frozen real-instance plan')
        self.done = True
        transport._event(self.events, 'cmr_solver_started')
        plan = runner.load_selection()['dds_plan']
        cell = runner.request_for(plan['instance_id'], plan['method'], 'ros2')
        value = runner.run_isolated(cell, self.binding, self.kernel_root,
                                    self.work_dir / 'cmr_attempt')
        row = value['row']
        self.result = dict(row, schema=transport.SCHEMA, population=runner.SCOPE,
                           request_id=request['request_id'], variant='real',
                           worker_pid=value['worker_pid'],
                           worker_exitcode=value['worker_exitcode'],
                           worker_alive_after_cleanup=value['worker_alive_after_cleanup'],
                           concrete_lasso=None, accepting_buchi_states=[])
        if value['transport'] is not None:
            self.result.update(value['transport'])
        transport._event(self.events, 'cmr_solver_completed', status=row['terminal_status'])
        outgoing = json.dumps(self.result, sort_keys=True, separators=(',', ':'))
        self.result_pub.publish(self.String(data=outgoing))
        transport._event(self.events, 'result_published', status=row['terminal_status'])
        if not row['certificate_valid_for_terminal']:
            self._grace_deadline = time.monotonic() + 0.5
            return
        self.snapshot, self.transitions, self.state_ids = transport._snapshot_messages(
            self.result, self.identity)
        self._publish_observation()


def child(args):
    import rclpy
    request = json.loads(args.request.read_text())
    rclpy.init()
    try:
        node = (RealServer(request, args.binding, args.kernel_root, args.output)
                if args.role == 'server' else transport._Driver(request, args.output))
        node.run(205)
        return 0
    except Exception:
        (args.output / f'{args.role}_error.txt').write_text(traceback.format_exc())
        traceback.print_exc()
        return 1
    finally:
        rclpy.shutdown()


def run_dds(binding, kernel_root, output):
    output = Path(output)
    output.mkdir(exist_ok=False)
    plan = runner.load_selection()['dds_plan']
    request = dict(request_id='cmr-real-C1-T1-AP-D', instance_id=plan['instance_id'],
                   method=plan['method'], planner_budget_seconds=180,
                   outer_watchdog_seconds=195)
    runner.runtime.write_json(output / 'request.json', request)
    env = dict(os.environ, ROS_DOMAIN_ID=str(DOMAIN_ID), ROS_LOCALHOST_ONLY='1',
               PYTHONDONTWRITEBYTECODE='1')
    processes = {}
    streams = []
    try:
        for role in ('server', 'driver'):
            out = (output / f'{role}.stdout').open('w')
            err = (output / f'{role}.stderr').open('w')
            streams.extend((out, err))
            command = [sys.executable, '-B', str(Path(__file__).resolve()),
                       '--role', role, '--request', str(output / 'request.json'),
                       '--output', str(output), '--binding', binding, '--kernel-root', kernel_root]
            processes[role] = subprocess.Popen(command, env=env, stdout=out, stderr=err)
        processes['driver'].wait(timeout=210)
        processes['server'].wait(timeout=3)
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
        for stream in streams:
            stream.close()
        for role, process in processes.items():
            (output / f'{role}.rc').write_text(str(process.returncode) + '\n')
    artifact = dict(schema='cmr-ros2-real-dds-v1', status='RUNNING', population=runner.SCOPE,
                    domain_id=DOMAIN_ID, request=request,
                    pids={role:process.pid for role, process in processes.items()},
                    rc={role:process.returncode for role, process in processes.items()})
    for role in ('server', 'driver'):
        path = output / f'{role}_events.json'
        artifact[role] = json.loads(path.read_text()) if path.exists() else {}
    runner.runtime.write_json(output / 'dds_artifact.json', artifact)
    try:
        if artifact['rc'] != dict(server=0, driver=0):
            raise AssertionError('DDS child failure')
        driver, server = artifact['driver'], artifact['server']
        result = driver.get('result')
        if (not isinstance(result, dict) or result['terminal_status'] != 'OPTIMALITY_CERTIFIED'
                or result['certificate_verifier_status'] != 'PASS'
                or result['instance_id'] != plan['instance_id']):
            raise AssertionError('real DDS result is not independently certified')
        required = ['request_received', 'cmr_solver_started', 'cmr_solver_completed',
                    'result_published']
        names = [event['event'] for event in server['events']]
        if any(names.count(name) != 1 for name in required):
            raise AssertionError('DDS request/solver/publication not exactly once')
        if [names.index(name) for name in required] != sorted(names.index(name) for name in required):
            raise AssertionError('DDS solver event order')
        lasso = result['concrete_lasso']
        edges = lasso['prefix_edges'] + lasso['suffix_edges']
        expected = [edge['action'] for edge in edges]
        targets = [[str(item) for item in edge['target'][0]] for edge in edges]
        sources = [[str(item) for item in edge['source'][0]] for edge in edges]
        if not expected or driver['commands'] != expected:
            raise AssertionError('DDS did not execute the entire prefix and one suffix')
        for name in ('completion_count', 'observer_feedback_count', 'abstraction_feedback_count',
                     'ts_state_receive_count'):
            if driver[name] != len(edges):
                raise AssertionError(f'DDS {name} mismatch')
        for name in ('observed_ts_states', 'observer_feedback_states', 'abstraction_feedback_states'):
            if driver[name] != targets:
                raise AssertionError(f'DDS {name} target mismatch')
        dispatches = [e for e in driver['events'] if e['event'] == 'dispatch']
        if ([e['action'] for e in dispatches] != expected
                or [e['source_state'] for e in dispatches] != sources
                or [e['target_state'] for e in dispatches] != targets
                or [e['execution_step_seq'] for e in dispatches] != list(range(len(edges)))):
            raise AssertionError('DDS actual backend dispatch mismatch')
        terminal = [e for e in driver['events']
                    if e['event'] == 'observation_received' and not e['has_next_action']]
        if not terminal or terminal[-1]['step'] != len(edges):
            raise AssertionError('DDS terminal step is missing')
        if not driver['module_identity_match'] or result['worker_alive_after_cleanup']:
            raise AssertionError('DDS runtime import or cleanup mismatch')
        if len({*artifact['pids'].values(), result['worker_pid']}) != 3:
            raise AssertionError('DDS solver is not a separate worker')
        artifact.update(status='PASSED', executed_steps=len(edges), prefix_steps=len(lasso['prefix_edges']),
                        suffix_steps=len(lasso['suffix_edges']))
    except Exception as error:
        artifact.update(status='FAILED', error=repr(error))
        runner.runtime.write_json(output / 'dds_artifact.json', artifact)
        raise
    runner.runtime.write_json(output / 'dds_artifact.json', artifact)
    return artifact


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--role', choices=('server', 'driver'), required=True)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--kernel-root', required=True)
    raise SystemExit(child(parser.parse_args()))
