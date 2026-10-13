#!/usr/bin/env bash
set -euo pipefail
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v8_entry_timing_20261013
repo=/mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2
clone=/tmp/cmr_v8_entry_source_111ae6c_20261013
out=/tmp/cmr_v8_entry_timing_20261013
if [ ! -d "$clone/.git" ]; then
  git clone --branch codex/v8-entry-timing --single-branch "$repo" "$clone" 2>&1 | tee "$log/clone.txt"
else
  echo REUSING_EXISTING_CLONE | tee "$log/clone.txt"
fi
cd "$clone"
git rev-parse HEAD | tee "$log/clone_head.txt"
git status --short --branch | tee "$log/clone_status.txt"
set +u
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
set -u
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$clone/ltl_automaton_execution:$clone/ltl_automaton_planner:$clone/ltl_automaton_planner_core:$clone:/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel:$PYTHONPATH"
python3 -B - <<'PY' 2>&1 | tee "$log/importguard.txt"
import hashlib
import subprocess
from pathlib import Path
from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp
print("python_executable", __import__("sys").executable)
print("cwd", Path.cwd())
print("git_head", subprocess.check_output(["git","rev-parse","HEAD"], text=True).strip())
print("discrete_plan", dp.__file__)
print("discrete_plan_sha256", hashlib.sha256(Path(dp.__file__).read_bytes()).hexdigest())
PY
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
python3 -B experiments/cmr_ros2_ap_ts_reuse/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out" 2>&1 | tee "$log/prepare.txt"
python3 -B experiments/cmr_ros2_ap_ts_reuse/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out" 2>&1 | tee "$log/run.txt"
