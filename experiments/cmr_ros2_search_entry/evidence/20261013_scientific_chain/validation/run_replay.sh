set -eo pipefail
repo=/tmp/cmr_v7_scientific_source_f588c3e_20261013_r1
out=/tmp/cmr_v7_scientific_replay_20261013_r1
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/scientific_replay_20261013
if [ -e "$repo" ] || [ -e "$out" ]; then
    echo FRESH_NAMESPACE_REQUIRED >&2
    exit 69
fi
git clone --no-hardlinks --single-branch --branch codex/v7-audit-dds-regression /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/.git "$repo" 2>&1 | tee "$log/clone.txt"
cd "$repo"
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1 ROS_LOCALHOST_ONLY=1
export PYTHONPATH="$repo/ltl_automaton_execution:$repo/ltl_automaton_planner:$repo/ltl_automaton_planner_core:$repo:$PYTHONPATH"
python3 -B - <<'PY' | tee "$log/source.txt"
import json,pathlib,subprocess,hashlib
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
assert head=='f588c3ebb1745d93003654b4fdda826f0a0d2fe3'
assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip()
p=pathlib.Path('experiments/cmr_ros2_search_entry/scientific_chain_v7.py')
print(json.dumps({'harness_head':head,'harness_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'tree':'CLEAN','new_method_workers':0,'formal_campaign':False}))
PY
python3 -u -B -m experiments.cmr_ros2_search_entry.scientific_chain_v7 \
 --archive "$repo/experiments/cmr_ros2_search_entry/evidence/20261013_audit_real/raw_attempts.zip" \
 --binding /mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json \
 --kernel-root /mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel \
 --output "$out" 2>&1 | tee "$log/replay.txt"