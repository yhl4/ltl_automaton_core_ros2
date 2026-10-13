#!/usr/bin/env bash
set -eo pipefail
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v8_entry_timing_20261013
repo=/mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2
clone=/tmp/cmr_v8_entry_source_eb5e689_20261013
out=/tmp/cmr_v8_entry_timing_final_20261013
git clone --branch codex/v8-entry-timing --single-branch "$repo" "$clone" 2>&1 | tee "$log/final_clone.txt"
cd "$clone"
git rev-parse HEAD | tee "$log/final_clone_head.txt"
git status --short --branch | tee "$log/final_clone_status.txt"
set +u
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
set -e
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$clone/ltl_automaton_execution:$clone/ltl_automaton_planner:$clone/ltl_automaton_planner_core:$clone:/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel:\${PYTHONPATH:-}"
python3 -B - <<'PY' 2>&1 | tee "$log/final_importguard.txt"
import hashlib, subprocess, sys
from pathlib import Path
from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp
print("python_executable", sys.executable)
print("cwd", Path.cwd())
print("git_head", subprocess.check_output(["git","rev-parse","HEAD"], text=True).strip())
print("git_status", repr(subprocess.check_output(["git","status","--short"], text=True)))
print("discrete_plan", dp.__file__)
print("discrete_plan_sha256", hashlib.sha256(Path(dp.__file__).read_bytes()).hexdigest())
PY
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
python3 -B experiments/cmr_ros2_ap_ts_reuse/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out" 2>&1 | tee "$log/final_prepare.txt"
python3 -B experiments/cmr_ros2_ap_ts_reuse/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out" 2>&1 | tee "$log/final_run.txt"
