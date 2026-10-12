# Real Experiment A instance integration

This opt-in prototype loads real instances from the current receipt-bound
Experiment A `runtime_benchmark`. It extends the prior synthetic
[refinement/DDS prototype](../cmr_ros2_integration/README.md), without changing
the default PlannerNode or any frozen CMR source, manifest or result.

`selection.json` fixes the subset before any method execution. In each of
cohorts B, C and D it selects the minimum
`(nominal_cartesian_state_count, instance_id)`, independently of historical
outcomes:

| Instance | Factors | Declared Cartesian states |
| --- | ---: | ---: |
| B-D-BRANCH-S1 | 6 | 256 |
| C1-T1 | 6 | 64 |
| D3-1 | 1 | 2 |

Each uses FULL, AP-D and DEP-D, with a fresh reference and ROS2 worker per
method: nine comparison pairs, eighteen method runs. One additional actual
DDS request uses C1-T1/AP-D. The original 180-second method and 195-second
watchdog budgets are retained. No selection based on observed success or
runtime, artificial refinement cap, shortened execution or automatic retry
is used. Outputs have `CORE_SUBSET_QUALIFICATION` scope and are excluded from
the formal 170 × 3 campaign ledger and analysis.

The bound P2f `run_one` remains the scientific execution entry point. Its
model loader, initialization, grouped abstraction, concretization,
deterministic refinement and certificate writer are reused. On Linux only
two hard-coded Windows Path constants are rebased in the in-memory AST;
their source hashes and exact transformations are recorded. The source files
are never edited. The ROS2 arm clones the original loop's function code and
replaces the solver in its globals with the existing ROS2 lasso adapter.
INITIAL_LABEL_V1, exact Fraction costs, accepting nonempty closed suffixes
and `prefix + 10 × suffix` remain unchanged.

Reference rows and rounds use the original P2c schemas. Those schemas fix the
ECC backend SHA. The ROS2 arm uses an explicit
`CMR_ROS2_REAL_P2C_BACKEND_BINDING_V1`: it changes only that backend SHA constant
to the measured ROS2 source closure and gives the schema a new ID. Field types,
terminal, witness, proof and timing rules are unchanged; original schemas are
never modified. Instantiated schemas and their source hashes are saved.
The ROS2 backend has its own identity and source closure. Distance dictionaries and actual
helper heap operations populate search statistics; their basis is the
auxiliary edge-node/seen_accept graph. This backend performs no SCC,
independent lower-bound-search or bound-pruning stage, so those stage counts
are zero by construction. These counters are not interchangeable with the
reference SCC counters, and this qualification makes no speed claim.

Certified feasible results persist full-model lasso certificates, bind their
physical paths and instance metadata through P2e, then call the original
independent INITIAL_LABEL_V1 verifier. It independently replays transitions,
Fraction costs, Büchi acceptance and the formula word oracle; it does not
search again for an optimum. Exact emptiness is checked by the two solver
arms and their optimistic-abstraction proof fields; this verifier has no
infeasibility-certificate interface. Two changed-certificate checks recompute
the file hash and require semantic rejection of a wrong objective and action.

Method time starts at the original runner's clock, including its preflight,
input processing, all rounds and independent verification. Worker startup
belongs to the separately recorded outer clock. Parent delivery/logging is
included before terminal authorization; a late result loses certificate
authority, objective, emptiness proof and execution payload while preserving
attempt evidence. Unknown interrupted work is not treated as a completed
zero-work run.

The DDS attempt receives the selected-instance request before launching its
fresh ROS2 solver worker. A certified result serves an execution-only snapshot
and uses the existing ExecutionManagerNode, FakePlant, observer, abstraction
and `/ts_state` feedback. The entire returned prefix and one suffix period
are checked. Domain219 is localhost-only; discovery/execution collection has
a separate 205-second window. Snapshot float64 costs are for execution/display;
the CMR JSON and certificate retain exact authority.

Run only from the qualified local Humble environment with the matching CMR
source tree available:

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/experiments/cmr_ros2_real/verify_small.py \
  --binding /mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json \
  --kernel-root /mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel \
  --output /tmp/cmr_ros2_real_fresh_attempt
```

The directory must be fresh. The frozen dataset/kernel are external inputs,
not vendored into this ROS package. Hash or import mismatches fail closed.
This remains a bounded symbolic qualification, with no provider calls,
formal campaign, physical robot or production Action-cancellation validation.
