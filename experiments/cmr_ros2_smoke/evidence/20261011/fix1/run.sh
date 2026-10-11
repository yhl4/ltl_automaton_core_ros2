#!/bin/bash
set -e
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
WORK=/tmp/ltl_cmr_ros2_smoke_1228773_20261011_fix1
CORE=/mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2
mkdir "$WORK"
python3 -B - "$WORK" "$CORE" <<'PY'
import hashlib, json, pathlib, subprocess, sys
import networkx
work, core = map(pathlib.Path, sys.argv[1:])
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=core, text=True).strip()
assert head == '1228773e50e2920dd0811b92d4d64890799e8b47'
assert networkx.__version__ == '2.4'
expected = json.loads(pathlib.Path('/tmp/ltl_replan_type_tuple_regression_fa9c990/expected_inputs.json').read_bytes())
rows = []
for name, entry in expected.items():
    raw = pathlib.Path(name).read_bytes()
    observed = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    assert observed == entry, name
    rows.append(dict(path=name, role='unchanged_core_or_test', **observed))
for name in ('backend.py', 'smoke.py', 'README.md'):
    path = core / 'experiments/cmr_ros2_smoke' / name
    raw = path.read_bytes()
    rows.append(dict(path=str(path), role='new_experiment_source', size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
work.joinpath('frozen_inputs.json').write_text(json.dumps(dict(head=head, python=sys.version, networkx=networkx.__version__, rows=rows), indent=2)+'\n')
PY
set +e
python3 -B "$CORE/experiments/cmr_ros2_smoke/smoke.py" \
  --binding /mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json \
  --kernel-root /mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel \
  --output "$WORK/result.json" >"$WORK/stdout.txt" 2>"$WORK/stderr.txt"
rc=$?
printf '%s\n' "$rc" >"$WORK/smoke.rc"
python3 -B - "$WORK" <<'PY'
import hashlib, json, pathlib, sys
work = pathlib.Path(sys.argv[1])
frozen = json.loads(work.joinpath('frozen_inputs.json').read_bytes())
for row in frozen['rows']:
    raw = pathlib.Path(row['path']).read_bytes()
    assert row['size'] == len(raw) and row['sha256'] == hashlib.sha256(raw).hexdigest(), row['path']
work.joinpath('source_after.json').write_text(json.dumps(dict(all_match=True, files=len(frozen['rows'])), indent=2)+'\n')
PY
verify_rc=$?
printf '%s\n' "$verify_rc" >"$WORK/source_after.rc"
if [ "$verify_rc" -ne 0 ]; then exit "$verify_rc"; fi
exit "$rc"
