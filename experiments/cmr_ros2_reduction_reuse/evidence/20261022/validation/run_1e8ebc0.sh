#!/usr/bin/env bash
set -eo pipefail
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v9_projection_witness_20261022
repository=/mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2
src=/tmp/cmr_v9_source_1e8ebc0_20261022
out=/tmp/cmr_v9_projection_witness_1e8ebc0_20261022
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
test ! -e "$src"
test ! -e "$out"
git clone --branch codex/v9-projection-witness --single-branch "$repository" "$src" 2>&1 | tee "$log/clone_1e8ebc0.log"
cd "$src"
test "$(git rev-parse HEAD)" = 1e8ebc0f0e84484cca237bccfa93a83f491a7bbe
test -z "$(git status --porcelain)"
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export ROS_LOCALHOST_ONLY=1
export PYTHONPATH="$src/ltl_automaton_execution:$src/ltl_automaton_planner:$src/ltl_automaton_planner_core:$src:$kernel:${PYTHONPATH:-}"
python3 -B - <<'PY' 2>&1 | tee "$log/importguard_1e8ebc0.log"
import hashlib, subprocess, sys
from pathlib import Path
from ltl_automaton_planner_core.ltl_tools import discrete_plan as dp
from experiments.cmr_ros2_ap_ts_reuse.backend import identity
root=Path.cwd()
assert Path(dp.__file__).resolve().is_relative_to(root)
assert hashlib.sha256(Path(dp.__file__).read_bytes()).hexdigest()=='556b6925a61ce408a0b42d56da45138fcdf3c7c7655e7850eb17b551996df31b'
assert identity()=='5207a536472ad501184513c50c7b80641c186af36e24edd8fbd4f7f5576a2e34'
print('source_head',subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
print('source_status',repr(subprocess.check_output(['git','status','--porcelain'],text=True)))
print('discrete_plan',dp.__file__)
print('python',sys.executable)
PY
python3 -B experiments/cmr_ros2_reduction_reuse/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out" 2>&1 | tee "$log/prepare_1e8ebc0.log"
python3 -B experiments/cmr_ros2_reduction_reuse/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out" 2>&1 | tee "$log/run_1e8ebc0.log"
