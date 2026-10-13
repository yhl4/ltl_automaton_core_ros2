set -eo pipefail
repo=/tmp/cmr_v7_publication_source_9094907_20261013_r1
out=/tmp/cmr_v7_publication_probe_20261013_r1
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/publication_probe_20261013
if [ -e "$repo" ] || [ -e "$out" ]; then
    echo 'FRESH_NAMESPACE_REQUIRED' >&2
    exit 69
fi
git clone --no-hardlinks --single-branch --branch codex/v7-audit-dds-regression /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/.git "$repo" 2>&1 | tee "$log/clone.txt"
cd "$repo"
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$repo"
python3 -B - <<'PY' | tee "$log/source.txt"
import json,pathlib,subprocess,hashlib
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
assert head=='90949079a77e26a36eceb1bd38a30b4858f1c3f8'
assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip()
harness=pathlib.Path('experiments/cmr_ros2_search_entry/publication_v7.py')
print(json.dumps({'harness_head':head,'harness_sha256':hashlib.sha256(harness.read_bytes()).hexdigest(),'source_tree':'CLEAN','method_workers':0,'formal_campaign':False}))
PY
python3 -u -B -m experiments.cmr_ros2_search_entry.publication_v7 \
 --plan /tmp/cmr_v7_failure_dds_chain_20261013_r2/plan.json \
 --version-binding /tmp/cmr_v7_failure_dds_chain_20261013_r2/backend_binding.json \
 --binding /mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json \
 --synthetic-results /tmp/cmr_v7_failure_dds_chain_20261013_r2/offline_chain/synthetic_results.jsonl \
 --repo-root "$repo" --output "$out" 2>&1 | tee "$log/probe.txt"