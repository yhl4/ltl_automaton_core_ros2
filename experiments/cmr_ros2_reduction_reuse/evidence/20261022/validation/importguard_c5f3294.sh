#!/usr/bin/env bash
cd /tmp/cmr_v9_source_c5f3294_20261022
printf 'HEAD '; git rev-parse HEAD
printf 'STATUS '; git status --porcelain
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="/tmp/cmr_v9_source_c5f3294_20261022/ltl_automaton_planner_core:/tmp/cmr_v9_source_c5f3294_20261022/ltl_automaton_planner:/tmp/cmr_v9_source_c5f3294_20261022/ltl_automaton_core:/tmp/cmr_v9_source_c5f3294_20261022:${PYTHONPATH:-}"
python3 -B - <<'PY'
import hashlib
import pathlib
from ltl_automaton_planner_core.ltl_tools import discrete_plan
p = pathlib.Path(discrete_plan.__file__).resolve()
print('DISCRETE_PLAN', p)
print('DISCRETE_PLAN_SHA256', hashlib.sha256(p.read_bytes()).hexdigest())
PY
