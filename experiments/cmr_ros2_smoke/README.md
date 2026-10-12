# CMR ROS2 integration smoke

This directory is an isolated research smoke adapter. It exercises the current
ROS2 `discrete_plan` distance and path restoration helpers against a small
`INITIAL_LABEL_V1` abstract Product built by the bound CMR grouped abstraction.
It does not edit or replace the default ROS2 planner, the CMR runner, DDS, the
full refinement loop, campaign execution, or any formal result schema.

The smoke is a one-shot synthetic qualification aid. It is not a formal
drop-in planner. From WSL, source ROS Humble and the verified ROS2 overlay,
then use the no-bytecode command below; `--output` must be outside the
repository, normally under `/tmp`.

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/experiments/cmr_ros2_smoke/smoke.py \
  --binding /mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json \
  --kernel-root /mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel \
  --output /tmp/cmr_ros2_integration_smoke.json
```

The one-shot artifact contains a preflight import/path/SHA record and 12
synthetic rows: `base`, `initial_goal`, `zero_cost`, and `no_accept`, each at
`FULL`, `AP-D`, and `DEP-D` precision. The fixture contract is
`FULL={0,1}`, `AP-D={0}`, and `DEP-D={0,1}`; the latter is computed by the
write-intersection/support closure. Expected objectives are respectively
`10`, `10`, `0`, and `None`. A successful artifact requires every row to pass
the reference comparison, exact-cost checks, accepting closed-walk checks,
parallel action preservation, and the appropriate concretization/certificate
check.

The backend enumerates all prefix-reachable Product entries, including
non-accepting entries. It uses explicit edge nodes and a two-layer
`seen_accept` graph, so parallel actions and witness objects remain attached to
the returned qualified `AbstractLassoResult`. Its complexity is a prototype
bound of `O(entries * (V+E) log(V+E))`; no performance claim is made, and the
tie choice need not match the qualified solver's path tie choice.

The bound execution document is checked as schema
`CMR_CORE_R2_EXECUTION_BINDING_V1` with population `Core170` and denominator
170; the receipt remains `Core` with 170 instances.

The adapter currently covers the core lasso search only. Full refinement,
`SearchStats` accounting, timeout/watchdog behavior, and formal result-schema
rebinding are not connected. It must not be used as a campaign runner or as a
default ROS2 planner replacement.
