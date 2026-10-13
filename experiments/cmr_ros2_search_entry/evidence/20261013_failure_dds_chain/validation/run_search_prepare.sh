set -eo pipefail
cd /tmp/cmr_v7_failure_source_6f60801_20261013_r2
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/ltl_automaton_execution:$PWD/ltl_automaton_planner:$PWD/ltl_automaton_planner_core:$PWD:$PYTHONPATH"
python3 -B - <<'PY'
import pathlib,json
from types import SimpleNamespace
from experiments.cmr_ros2_search_entry import runner
out=pathlib.Path('/tmp/cmr_v7_search_plan_no_dispatch_20261013_r2')
args=SimpleNamespace(binding='/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json',kernel_root='/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel',output=out,continue_from=None,qualification_profile='search')
runner.prepare(args); plan=runner.load_plan(out/'plan.json')
assert plan['scope']==runner.SCOPE and [(c['instance_id'],c['method']) for c in plan['cells']]==list(runner.TARGETS)
assert plan['expected_method_workers']==9 and len(plan['records'])==5
report={'status':'PASSED','cells':plan['cells'],'expected_method_workers':9,'actual_method_workers':0,'scope':plan['scope'],'source_head':plan['source_head'],'version_binding_id':plan['version_binding_id'],'source_closure_files':len(plan['source_closure']),'provider_calls':0}
path=pathlib.Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/failure_dds_chain_20261013/search_default_prepare.json')
path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8'); print(json.dumps(report))
PY
