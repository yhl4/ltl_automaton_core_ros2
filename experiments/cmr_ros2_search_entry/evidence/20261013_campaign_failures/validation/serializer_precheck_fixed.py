import json
from pathlib import Path
from experiments.cmr_ros2_search_entry import runner

ROOT = Path('/tmp/cmr_current_campaign_failure_20261013_fixed')
PLAN = runner.load_plan(ROOT / 'plan/plan.json')
BINDING = Path(PLAN['version_binding_path'])
RECEIPT = Path('/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json')
KERNEL = Path('/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel')
entry = runner.VerifiedEntry(PLAN, runner.source_closure, runner.schema_for)
cell = next(c for c in PLAN['cells'] if (c['instance_id'], c['method']) == ('C3-T4', 'AP-D'))
request = runner.request_for(PLAN, entry, cell, 'ros2-v7')
entry.validate_request(request)
record = next(r for r in PLAN['records'] if r['instance_id'] == cell['instance_id'])
assert request['instance_sha256'] == record['instance_sha256']
formal, bound, manifest, records = runner.old_runner.authority(PLAN, RECEIPT, KERNEL)
descriptor = entry.describe('ros2-v7')
runner.configure(formal, 'ros2-v7', descriptor)
start = 1_000_000_000
end = start + 195_000_000_001
row = formal.timeout_serialization(request, 'outer_watchdog', method_start_ns=start, terminal_completion_ns=end)
row.update(qualification_scope=PLAN['scope'], formal_campaign=False,
           execution_commit=PLAN['execution_identity'], **descriptor,
           certificate_path='NOT_AVAILABLE', certificate_hash='NOT_AVAILABLE',
           certificate_schema='NOT_AVAILABLE', certificate_objective=None)
runner.old_runner.terminal_delivery(row, end, outer_start=start, forced_timeout=True)
assert row['instance_sha256'] == record['instance_sha256']
assert row['benchmark_payload_sha256'] == record['instance_sha256']
assert row['backend_id'] == descriptor['backend_id']
assert row['backend_sha256'] == descriptor['backend_sha256']
assert row['execution_commit'] == PLAN['execution_identity']
assert row['T_total'] >= 195.0
entry.release_check()
result = {'status':'PASSED','kind':'SYNTHETIC_IDENTITY_PRECHECK','worker_calls':0,
          'instance_id':row['instance_id'],'method':row['method'],
          'instance_sha256':row['instance_sha256'],
          'benchmark_payload_sha256':row['benchmark_payload_sha256'],
          'backend_binding':descriptor,'execution_identity':PLAN['execution_identity'],
          'terminal_status':row['terminal_status'],'T_total':row['T_total'],
          'outer_watchdog_seconds':row['outer_watchdog_seconds'],
          'formal_timeout_serialization':'called','forced_timeout':True,
          'release_check':'PASSED'}
(Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/campaign_failure_20261013/serializer_precheck_fixed.json')).write_text(json.dumps(result, sort_keys=True, indent=2)+'\n')
print(json.dumps(result, sort_keys=True))