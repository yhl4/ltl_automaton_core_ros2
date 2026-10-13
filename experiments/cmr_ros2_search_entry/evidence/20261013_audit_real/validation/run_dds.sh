set -eo pipefail
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1 ROS_LOCALHOST_ONLY=1
repo=/tmp/cmr_v7_audit_source_14b2c80_20261013_r1
out=/tmp/cmr_v7_audit_real_20261013_r1
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/real_qualification_20261013
cd "$repo"
export PYTHONPATH="$repo/ltl_automaton_execution:$repo/ltl_automaton_planner:$repo/ltl_automaton_planner_core:$repo:$PYTHONPATH"
python3 -B - <<'PY' 2>&1 | tee "$log/dds.txt"
import json,pathlib,inspect,hashlib
from types import SimpleNamespace
from experiments.cmr_ros2_search_entry import runner,dds
root=pathlib.Path.cwd(); output=pathlib.Path('/tmp/cmr_v7_audit_real_20261013_r1'); plan=runner.load_plan(output/'plan.json')
assert plan['source_head']=='14b2c806beecca27f855f32ab79be154e7011de7'
assert runner.source_closure()==plan['source_closure']
print(json.dumps({'source_head':plan['source_head'],'binding_id':plan['version_binding_id'],'source_files':len(plan['source_closure']),'dds_module':inspect.getfile(dds),'dds_module_sha256':hashlib.sha256(pathlib.Path(inspect.getfile(dds)).read_bytes()).hexdigest()}),flush=True)
args=SimpleNamespace(binding='/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json',kernel_root='/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel',version_binding=pathlib.Path(plan['version_binding_path']),plan=output/'plan.json')
report=dds.run_dds(args,plan,output/'dds')
print(json.dumps({'status':report['status'],'cases':[{'instance':case.get('request',{}).get('instance_id'),'method':case.get('request',{}).get('method'),'status':case['status'],'error':case.get('error'),'certificate_replay':case.get('certificate_replay')} for case in report['cases']]}),flush=True)
assert report['status']=='PASSED'
PY
