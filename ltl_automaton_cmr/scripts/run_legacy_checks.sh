#!/usr/bin/env bash
set -o pipefail
cd "$(dirname "$0")/../.."
source /opt/ros/humble/setup.bash
source install/setup.bash
export PATH="/home/yuhling/.local/bin:$PATH"
export PYTHONPATH="$PWD/ltl_automaton_cmr:$PWD/ltl_automaton_execution:$PWD/ltl_automaton_planner_core:$PWD/ltl_automaton_planner:$PYTHONPATH"
(cd ltl_automaton_planner_core && python3 -m pytest -q test --junitxml=../ltl_automaton_cmr/validation/legacy-core.xml) > ltl_automaton_cmr/validation/legacy-core.log 2>&1
task_core=$?
tail -n 20 ltl_automaton_cmr/validation/legacy-core.log
(cd ltl_automaton_execution && python3 -m pytest -q test/test_accepted_run_resolver.py test/test_backend.py --junitxml=../ltl_automaton_cmr/validation/legacy-execution.xml) > ltl_automaton_cmr/validation/legacy-execution.log 2>&1
task_execution=$?
tail -n 10 ltl_automaton_cmr/validation/legacy-execution.log
exit "$((task_core || task_execution))"
