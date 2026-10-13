set -eo pipefail
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/failure_zero_qualification_20261013
repo=/tmp/cmr_v7_lifecycle_source_01f0fcb_20261013_r1
out=/tmp/cmr_v7_lifecycle_zero_20261013_r1
git clone --no-hardlinks --single-branch --branch codex/v7-audit-dds-regression /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/.git "$repo" 2>&1 | tee "$log/clone.txt"
cd "$repo"
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$repo/ltl_automaton_execution:$repo/ltl_automaton_planner:$repo/ltl_automaton_planner_core:$repo:$PYTHONPATH"
python3 -u -B - <<'PY' 2>&1 | tee "$log/qualification.txt"
import json,pathlib,subprocess,traceback
from types import SimpleNamespace
from experiments.cmr_ros2_search_entry import runner,fixtures,entry_fixtures,lifecycle,zero_certificate
out=pathlib.Path('/tmp/cmr_v7_lifecycle_zero_20261013_r1')
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()=='01f0fcbad5e01449941d38fe665b4c9984e70083'
assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip()
args=SimpleNamespace(binding='/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json',kernel_root='/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel',output=out,continue_from=None)
runner.prepare(args)
args.plan=out/'plan.json'; plan=runner.load_plan(args.plan); args.version_binding=pathlib.Path(plan['version_binding_path'])
runner.write(out/'search_fixtures.json',fixtures.run())
runner.write(out/'entry_fixtures.json',entry_fixtures.run_fixtures())
runner.write(out/'fixtures.json',dict(status='PASSED',execution_identity=plan['execution_identity'],version_binding_id=plan['version_binding_id'],version_binding_sha256=plan['version_binding_sha256']))
print(json.dumps({'source_head':plan['source_head'],'binding':plan['version_binding_id'],'closure':len(plan['source_closure'])}),flush=True)
boundary=lifecycle.boundary_checks(args,plan,out/'boundary.json')
print(json.dumps({'boundary_status':boundary['status'],'checks':boundary['count']}),flush=True)
zero=None
try:
    zero=zero_certificate.run(args,plan,out/'zero')
    print(json.dumps({'zero_status':zero['status'],'objectives':{k:v['objective'] for k,v in zero['results'].items()},'positive_replays':zero['positive_independent_replays'],'negative_checks':zero['rejected_certificate_checks']}),flush=True)
except Exception:
    runner.write(out/'zero_failure.json',dict(status='FAILED',traceback=traceback.format_exc()))
    traceback.print_exc()
lc=lifecycle.run(args,plan,out/'lifecycle')
after=runner.qualification.frozen_inputs(plan)
runner.write(out/'frozen_inputs_after.json',after)
assert after==json.loads((out/'frozen_inputs_before.json').read_bytes())
assert runner.source_closure()==plan['source_closure']
assert lc['status']=='PASSED' and zero is not None and zero['status']=='PASSED'
print(json.dumps({'status':'PASSED','lifecycle_cases':len(lc['cases']),'zero_arms':len(zero['results']),'frozen_inputs':len(after),'formal_campaign_workers':0,'provider_calls':0}),flush=True)
PY
