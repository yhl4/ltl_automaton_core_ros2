#!/usr/bin/env bash
set -o pipefail
cd "$(dirname "$0")/../.."
source /opt/ros/humble/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=174
export ROS_LOCALHOST_ONLY=1
colcon build --packages-select ltl_automaton_cmr > ltl_automaton_cmr/validation/build.log 2>&1
task_build=$?
tail -n 10 ltl_automaton_cmr/validation/build.log
if [ "$task_build" -ne 0 ]; then exit "$task_build"; fi
source install/setup.bash
colcon test --packages-select ltl_automaton_cmr --return-code-on-test-failure > ltl_automaton_cmr/validation/cmr-colcon-test.log 2>&1
task_test=$?
tail -n 22 ltl_automaton_cmr/validation/cmr-colcon-test.log
colcon test-result --test-result-base build/ltl_automaton_cmr --verbose > ltl_automaton_cmr/validation/cmr-test-result.log 2>&1
tail -n 8 ltl_automaton_cmr/validation/cmr-test-result.log
python3 ltl_automaton_cmr/scripts/verify_vendor.py
exit "$task_test"
