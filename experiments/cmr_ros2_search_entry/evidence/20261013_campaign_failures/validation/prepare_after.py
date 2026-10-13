from pathlib import Path
from types import SimpleNamespace
from experiments.cmr_ros2_search_entry import runner, fixtures, entry_fixtures

root = Path('/tmp/cmr_current_campaign_failure_20261013_after')
runner.prepare(SimpleNamespace(output=root / 'plan', continue_from=None, qualification_profile='search',
    binding='/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json',
    kernel_root='/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel'))
plan = runner.load_plan(root / 'plan/plan.json')
runner.write(root / 'plan/search_fixtures.json', fixtures.run())
runner.write(root / 'plan/entry_fixtures.json', entry_fixtures.run_fixtures())
runner.write(root / 'plan/fixtures.json', dict(status='PASSED', execution_identity=plan['execution_identity'],
    version_binding_id=plan['version_binding_id'], version_binding_sha256=plan['version_binding_sha256']))
