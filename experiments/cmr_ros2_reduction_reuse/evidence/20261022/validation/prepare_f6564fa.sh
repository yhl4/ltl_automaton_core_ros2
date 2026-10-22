#!/usr/bin/env bash
cd /tmp/cmr_v9_source_f6564fa_20261022
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="/tmp/cmr_v9_source_f6564fa_20261022/ltl_automaton_planner_core:/tmp/cmr_v9_source_f6564fa_20261022/ltl_automaton_planner:/tmp/cmr_v9_source_f6564fa_20261022/ltl_automaton_core:/tmp/cmr_v9_source_f6564fa_20261022:${PYTHONPATH:-}"
python3 -B experiments/cmr_ros2_reduction_reuse/runner.py --prepare --binding /mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json --kernel-root /mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel --output /tmp/cmr_v9_projection_witness_20261022
