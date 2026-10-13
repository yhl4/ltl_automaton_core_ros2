#!/usr/bin/env bash
set -eo pipefail
repo=/tmp/cmr_current_campaign_failure_source_40975b7_20261013_before
logs=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/campaign_failure_20261013
git clone --no-hardlinks --single-branch --branch codex/v7-audit-dds-regression /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/.git "$repo" > "$logs/before_clone.txt" 2>&1
test "$(git -C "$repo" rev-parse HEAD)" = 40975b7cf63e8f525c0b24309ca71c11fe78bc83
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1 ROS_LOCALHOST_ONLY=1
export PYTHONPATH="$repo/ltl_automaton_execution:$repo/ltl_automaton_planner:$repo/ltl_automaton_planner_core:$repo:$PYTHONPATH"
cd "$repo"
python3 -B "$logs/prepare.py" > "$logs/before_prepare.txt" 2>&1
python3 -B "$logs/fault_driver.py" --mode late_delivery --expected-exit 1 \
 --plan /tmp/cmr_current_campaign_failure_20261013_before/plan/plan.json \
 --output /tmp/cmr_current_campaign_failure_20261013_before/late_delivery > "$logs/before_fault.txt" 2>&1
cat "$logs/before_fault.txt"
