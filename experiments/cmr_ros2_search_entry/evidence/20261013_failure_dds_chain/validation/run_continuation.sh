set -eo pipefail
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/failure_dds_chain_20261013
repo=/tmp/cmr_v7_failure_source_6f60801_20261013_r2
out=/tmp/cmr_v7_failure_dds_chain_20261013_r2
git clone --no-hardlinks --single-branch --branch codex/v7-audit-dds-regression /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/.git "$repo" 2>&1 | tee "$log/r2_clone.txt"
cd "$repo"
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1 ROS_LOCALHOST_ONLY=1
export PYTHONPATH="$repo/ltl_automaton_execution:$repo/ltl_automaton_planner:$repo/ltl_automaton_planner_core:$repo:$PYTHONPATH"
python3 -u -B - <<'PY' 2>&1 | tee "$log/r2_qualification.txt"
import json,pathlib,subprocess,traceback
from types import SimpleNamespace
from experiments.cmr_ros2_search_entry import runner,fixtures,entry_fixtures,failure_dds,offline_chain_v7
out=pathlib.Path('/tmp/cmr_v7_failure_dds_chain_20261013_r2')
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()=='6f60801afaed3da950c8d9d0646669f7777a6623'
assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip()
args=SimpleNamespace(binding='/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json',kernel_root='/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel',output=out,continue_from=None,qualification_profile='dds-failures')
runner.prepare(args)
args.plan=out/'plan.json'; plan=runner.load_plan(args.plan); args.version_binding=pathlib.Path(plan['version_binding_path'])
runner.write(out/'search_fixtures.json',fixtures.run())
runner.write(out/'entry_fixtures.json',entry_fixtures.run_fixtures())
runner.write(out/'fixtures.json',dict(status='PASSED',execution_identity=plan['execution_identity'],version_binding_id=plan['version_binding_id'],version_binding_sha256=plan['version_binding_sha256']))
print(json.dumps({'source_head':plan['source_head'],'binding':plan['version_binding_id'],'closure':len(plan['source_closure']),'frozen_inputs':len(json.loads((out/'frozen_inputs_before.json').read_bytes()))}),flush=True)
try:
    report=failure_dds.run(args,plan,out/'dds_failures',continue_from=pathlib.Path('/tmp/cmr_v7_failure_dds_chain_20261013_r1'))
except Exception:
    runner.write(out/'dds_fatal.json',dict(status='FAILED',traceback=traceback.format_exc()))
    traceback.print_exc(); report=None
try:
    offline=offline_chain_v7.qualify(SimpleNamespace(binding=pathlib.Path(args.binding),version_binding=args.version_binding,plan=args.plan,output=out/'offline_chain',repo_root=pathlib.Path.cwd()))
except Exception:
    runner.write(out/'offline_fatal.json',dict(status='FAILED',traceback=traceback.format_exc()))
    traceback.print_exc(); offline=None
after=runner.qualification.frozen_inputs(plan)
runner.write(out/'frozen_inputs_after.json',after)
assert after==json.loads((out/'frozen_inputs_before.json').read_bytes())
assert runner.source_closure()==plan['source_closure']
assert report is not None and report['status']=='PASSED' and offline is not None and offline['status']=='PASSED'
print(json.dumps({'status':'PASSED','dds_cases':len(report['cases']),'offline_synthetic_rows':offline['analysis']['rows'],'formal_campaign_workers':0,'provider_calls':0}),flush=True)
PY
