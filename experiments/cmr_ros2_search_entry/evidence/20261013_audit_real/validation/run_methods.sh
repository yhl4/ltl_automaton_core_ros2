set -eo pipefail
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1 ROS_LOCALHOST_ONLY=1
source_dir=/tmp/cmr_v7_audit_source_14b2c80_20261013_r1
out=/tmp/cmr_v7_audit_real_20261013_r1
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/real_qualification_20261013
if [ -e "$source_dir" ] || [ -e "$out" ]; then exit 70; fi
git clone --no-hardlinks --single-branch --branch codex/v7-audit-dds-regression /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/.git "$source_dir" 2>&1 | tee "$log/clone.txt"
cd "$source_dir"
[ "$(git rev-parse HEAD)" = 14b2c806beecca27f855f32ab79be154e7011de7 ]
[ -z "$(git status --porcelain=v1)" ]
export PYTHONPATH="$source_dir/ltl_automaton_execution:$source_dir/ltl_automaton_planner:$source_dir/ltl_automaton_planner_core:$source_dir:$PYTHONPATH"
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
python3 -B experiments/cmr_ros2_search_entry/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out" 2>&1 | tee "$log/prepare.txt"
python3 -B experiments/cmr_ros2_search_entry/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out" 2>&1 | tee "$log/methods.txt"
python3 -B experiments/cmr_ros2_search_entry/readback.py --output "$out" 2>&1 | tee "$log/readback.txt"
