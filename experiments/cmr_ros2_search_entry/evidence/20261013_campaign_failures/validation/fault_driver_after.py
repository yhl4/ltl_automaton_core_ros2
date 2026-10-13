"""Bounded current-Campaign fault qualification; no production fault option."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from experiments.cmr_ros2_search_entry import campaign_v7 as campaign, runner, lifecycle

p = argparse.ArgumentParser()
p.add_argument('--mode', choices=('late_delivery', 'crash', 'watchdog'), required=True)
p.add_argument('--plan', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--expected-exit', type=int, required=True)
args = p.parse_args()
receipt = Path('/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json')
kernel = Path('/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel')
original_candidate = runner.candidate_isolated
original_init = campaign.Campaign.__init__
instances, deliveries = [], []

def observe_init(self, *pos, **kw):
    original_init(self, *pos, **kw)
    instances.append(self)

def fault(candidate_args, plan, cell, output, *, backend_name='ros2-v7'):
    assert backend_name == 'ros2-v7'
    clock = lifecycle.OffsetClock(args.mode)
    started = time.perf_counter_ns()
    with lifecycle._parent_hooks(args.mode, clock, output):
        value = original_candidate(candidate_args, plan, cell, output, backend_name=backend_name)
    marker = dict(mode=args.mode, simulated_clock=args.mode == 'late_delivery',
                  injected_offset_ns=clock.offset_ns, actual_wall_seconds=(time.perf_counter_ns()-started)/1e9,
                  planner_budget_seconds=180, outer_watchdog_seconds=195,
                  harness_path=str(Path(__file__).resolve()), harness_sha256=campaign.sha(Path(__file__)),
                  lifecycle_harness_sha256=campaign.sha(Path(lifecycle.__file__)), new_worker_pid=value['worker_pid'])
    Path(output, 'campaign_fault_qualification.json').write_bytes(campaign.raw(marker))
    deliveries.append(dict(value=value, output=output, marker=marker))
    return value

runner.candidate_isolated = fault
campaign.Campaign.__init__ = observe_init
previous_argv = sys.argv
sys.argv = [campaign.__file__, '--backend', 'ros2-v7', '--plan', str(args.plan),
            '--binding', str(receipt), '--kernel-root', str(kernel), '--output', str(args.output)]
try:
    exitcode = campaign.main()
finally:
    runner.candidate_isolated = original_candidate
    campaign.Campaign.__init__ = original_init
    sys.argv = previous_argv
assert exitcode == args.expected_exit, (exitcode, args.expected_exit)
assert len(deliveries) == 1
value, marker = deliveries[0]['value'], deliveries[0]['marker']
terminal = 'INFRASTRUCTURE_FAILURE' if args.mode == 'crash' else 'TIMEOUT'
lifecycle.no_claims(value, terminal)
group_absent = False
try:
    os.killpg(value['worker_pid'], 0)
except ProcessLookupError:
    group_absent = True
assert group_absent
finals = list((args.output / 'completed').glob('*')) if (args.output / 'completed').exists() else []
verification_calls = sum(len(c.verifications) for c in instances)
assert verification_calls == 0
retry = 'NOT_APPLICABLE_COMMITTED'
if args.mode == 'crash':
    assert not finals and value['worker_exitcode'] == 23
    retry_args = SimpleNamespace(backend='ros2-v7', plan=args.plan, binding=receipt, kernel_root=kernel, output=args.output)
    resumed = campaign.Campaign(retry_args, resume=True)
    try:
        resumed.run_cell()
    except ValueError as exc:
        assert 'incomplete prior dispatch retained; automatic retry forbidden' in str(exc)
        retry = 'REJECTED_BEFORE_WORKER'
    else:
        raise AssertionError('crash was automatically retried')
    assert resumed.method_workers == 0
else:
    assert len(finals) == 1 and len(instances) == 2
    assert campaign.read(finals[0] / 'validated_result.json') == value['row']
    assert (finals[0] / 'certificate.json').read_bytes() == b'null'
    assert sum(c.method_workers for c in instances) == 1
    if exitcode:
        fatal = campaign.read(args.output / 'fatal.json')
        assert 'publication/restore independent certificate verification incomplete' in fatal['traceback']
    else:
        report = campaign.read(args.output / 'campaign_report.json')
        assert report['status'] == 'PASSED' and report['resume_method_workers'] == 0
if args.mode == 'watchdog':
    assert not marker['simulated_clock'] and value['row']['T_total'] >= 195 and value['worker_exitcode'] < 0
result = dict(status='PASSED', mode=args.mode, cli_exit=exitcode, expected_cli_exit=args.expected_exit,
              terminal_status=value['row']['terminal_status'], objective=value['row']['objective'],
              right_censored=value['row']['right_censored'], T_total=value['row']['T_total'],
              fault=marker, new_process_workers=1, run_one_calls=int(args.mode == 'late_delivery'),
              verifier_calls=verification_calls, publications=len(finals),
              successful_constructor_instances=len(instances), crash_retry=retry,
              process_group_absent=group_absent, worker_exitcode=value['worker_exitcode'],
              source_plan_sha256=campaign.sha(args.plan), execution_identity=value['row']['execution_commit'],
              backend_binding=value['backend_binding'], campaign_source_sha256=campaign.sha(Path(campaign.__file__)),
              formal_campaign=False, provider_calls=0, dds_calls=0, default_changed=False)
(args.output / 'fault_test_report.json').write_bytes(campaign.raw(result))
print(json.dumps(result))
