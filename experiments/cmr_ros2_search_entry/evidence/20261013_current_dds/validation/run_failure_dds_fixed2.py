import json
from pathlib import Path
from types import SimpleNamespace
from experiments.cmr_ros2_search_entry import failure_dds, runner
root = Path('/tmp/cmr_v7_current_dds_20261013_failure_fixed2')
plan = runner.load_plan(root / 'plan' / 'plan.json')
args = SimpleNamespace(
    binding='/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json',
    kernel_root='/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel',
    version_binding=plan['version_binding_path'],
    plan=root / 'plan' / 'plan.json',
    output=root / 'plan',
)
report = failure_dds.run(args, plan, root / 'dds_failures')
print(json.dumps(report, sort_keys=True))
