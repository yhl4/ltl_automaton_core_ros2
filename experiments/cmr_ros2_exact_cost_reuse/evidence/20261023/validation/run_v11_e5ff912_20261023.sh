#!/usr/bin/env bash
set -e
src=/mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2
clone=/tmp/cmr_v11_source_e5ff912_20261023
out=/tmp/cmr_v11_exact_cost_e5ff912_20261023
log=/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v11_hotspot_20261023
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
mkdir -p "$log"
test ! -e "$clone"
test ! -e "$out"
{
  echo "source=$src"
  echo "clone=$clone"
  echo "expected_head=e5ff91294b373a1f33e7ae9458641e4a2200ab56"
  git -C "$src" show-ref --verify refs/heads/codex/v11-exact-cost-reuse
  git clone --branch codex/v11-exact-cost-reuse --single-branch "$src" "$clone"
  test "$(git -C "$clone" rev-parse HEAD)" = e5ff91294b373a1f33e7ae9458641e4a2200ab56
  test -z "$(git -C "$clone" status --porcelain)"
  git -C "$clone" status --short --branch
} > "$log/clone_v11_e5ff912.log" 2>&1
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$clone/ltl_automaton_execution:$clone/ltl_automaton_planner:$clone/ltl_automaton_planner_core:$clone:$kernel:${PYTHONPATH:-}"
{
  python3 -B - "$clone" "$receipt" "$kernel" <<'PY'
import hashlib, importlib, json, pathlib, sys
clone=pathlib.Path(sys.argv[1]).resolve()
receipt=pathlib.Path(sys.argv[2]).resolve()
kernel=pathlib.Path(sys.argv[3]).resolve()
assert receipt.is_file() and kernel.is_dir()
mod=importlib.import_module('ltl_automaton_planner_core.ltl_tools.discrete_plan')
path=pathlib.Path(mod.__file__).resolve()
expected=clone/'ltl_automaton_planner_core'/'ltl_automaton_planner_core'/'ltl_tools'/'discrete_plan.py'
assert path == expected, (path, expected)
sha=hashlib.sha256(path.read_bytes()).hexdigest()
assert sha=='556b6925a61ce408a0b42d56da45138fcdf3c7c7655e7850eb17b551996df31b', sha
print(json.dumps({'module':mod.__name__,'file':str(path),'sha256':sha,'receipt':str(receipt),'kernel':str(kernel)}))
PY
} > "$log/importguard_v11_e5ff912.log" 2>&1
set +e
python3 -B "$clone/experiments/cmr_ros2_exact_cost_reuse/runner.py" --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out" > "$log/prepare_v11_e5ff912.stdout" 2> "$log/prepare_v11_e5ff912.stderr"
prepare_rc=$?
printf '%s\n' "$prepare_rc" > "$log/prepare_v11_e5ff912.rc"
if [ "$prepare_rc" -ne 0 ]; then
  exit "$prepare_rc"
fi
python3 -B "$clone/experiments/cmr_ros2_exact_cost_reuse/runner.py" --binding "$receipt" --kernel-root "$kernel" --output "$out" > "$log/run_v11_e5ff912.stdout" 2> "$log/run_v11_e5ff912.stderr"
run_rc=$?
printf '%s\n' "$run_rc" > "$log/run_v11_e5ff912.rc"
exit "$run_rc"