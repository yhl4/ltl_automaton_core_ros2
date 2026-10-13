set -eo pipefail
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/failure_zero_qualification_20261013
repo=/tmp/cmr_v7_zero_source_0a10a15_20261013_r2
out=/tmp/cmr_v7_zero_20261013_r2
git clone --no-hardlinks --single-branch --branch codex/v7-audit-dds-regression /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/.git "$repo" 2>&1 | tee "$log/zero_clone.txt"
cd "$repo"
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$repo/ltl_automaton_execution:$repo/ltl_automaton_planner:$repo/ltl_automaton_planner_core:$repo:$PYTHONPATH"
python3 -u -B - <<'PY' 2>&1 | tee "$log/zero_continuation.txt"
import json,pathlib,subprocess,traceback
from types import SimpleNamespace
from experiments.cmr_ros2_search_entry import runner,zero_certificate
out=pathlib.Path('/tmp/cmr_v7_zero_20261013_r2')
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()=='0a10a15b0fbe5cebda0c07d8905f1eb154351398'
assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip()
args=SimpleNamespace(binding='/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json',kernel_root='/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel',output=out,continue_from=None)
runner.prepare(args)
plan=runner.load_plan(out/'plan.json')
prior=json.loads(pathlib.Path('/tmp/cmr_v7_lifecycle_zero_20261013_r1/plan.json').read_bytes())
assert prior['source_closure']==plan['source_closure']
try:
    report=zero_certificate.run(args,plan,out/'zero')
except Exception:
    runner.write(out/'zero_failure.json',dict(status='FAILED',traceback=traceback.format_exc()))
    raise
runner.write(out/'frozen_inputs_after.json',runner.qualification.frozen_inputs(plan))
assert json.loads((out/'frozen_inputs_before.json').read_bytes())==json.loads((out/'frozen_inputs_after.json').read_bytes())
assert runner.source_closure()==plan['source_closure']
print(json.dumps({'status':report['status'],'source_head':plan['source_head'],'identity':report['execution_identity'],'results':report['results'],'negative_checks':report['rejected_certificate_checks'],'watchdog_exercised':report['process_watchdog_exercised'],'unified_entry_exercised':report['unified_candidate_isolated_exercised']}),flush=True)
PY
