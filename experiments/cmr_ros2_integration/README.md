# CMR refinement, deadline and DDS prototype

This opt-in experiment extends the [core smoke](../cmr_ros2_smoke/README.md).
It reuses the bound CMR grouped abstraction, concretization, exact certificate
and deterministic refinement policy, with the current ROS2 distance/path
helpers. The default Planner and frozen CMR sources/results are unchanged.

The complete loop rebuilds the abstraction at each precision, solves the
accepting lasso, concretizes it and checks LB=UB. An uncertified candidate
strictly increases precision using the qualified deterministic policy. It
stops only on certification, exact emptiness, full-precision certificate gap,
error or deadline; there is no shortened round cap or successful-prefix test.

Two outcome-independent, two-factor fixtures are fixed:

| Fixture | AP-D initial round | Terminal result |
| --- | --- | --- |
| `cost_gap` | LB=10, periodic concrete UB=30; add factor1 | Two rounds, cost30 certified |
| `spurious` | LB=10, no periodic concrete lift; add factor1 | Two rounds, exact emptiness |

FULL and DEP-D start at both factors and finish in one round. Reference and
adapted runs use all three methods, six pairs in total. The existing `base`
fixture is used only for the explicit zero-budget DDS timeout case.

Method budgets count worker startup, source preflight, initialization, all
rounds, certification and result logging/delivery on one host's monotonic
`perf_counter_ns` clock. Checks run between phases and distance helpers; a
separate spawned-worker watchdog can stop a blocking phase. TIMEOUT retains
the observed elapsed lower bound as RIGHT_CENSORED, clears the terminal
objective, certificate authority, emptiness proof and executable lasso, and
preserves raw attempt evidence. A certificate saved before late logging does
not authorize a late result. Missing/interrupted work stays unknown.

Statistics distinguish original Product/reduced-TS sizes from auxiliary
edge-node/seen_accept search work. Returned distance dictionaries provide
actual settled-node counts for completed helper calls; heap push/pop counts
are unavailable, not zero. They are not interchangeable with the reference
SCC solver's SearchStats. Phase intervals include adapter recording overhead;
these checks do not make a performance claim.

DDS uses three localhost domains (216/217/218), separate server/driver/worker
processes, and exactly one publication per discovered request:

- `/cmr_smoke/request` and `/cmr_smoke/result`: `std_msgs/String` with exact
  JSON costs and CMR result/deadline/refinement fields.
- `/get_planning_graph_snapshot` and `/planning_execution_observation`:
  an execution-only conversion consumed by the existing ExecutionManagerNode.
- `/ts_state`: independent FakePlant → FakeStateObserver → abstraction → DDS
  feedback; backend completion does not supply TS truth.

The successful cost-gap request executes the entire concrete prefix and one
closed suffix period. Spurious and timeout requests dispatch nothing. An
invalid generation observation and a late timeout TS message are checked.
Snapshot `float64` costs are for execution/display only; the authoritative
objective remains an exact Fraction string. The snapshot contains the selected
lasso, not the full explored graph. Full Product identity includes both TS and
Büchi states. Witness evidence remains in the exact CMR JSON.

From the qualified local WSL Humble environment:

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/experiments/cmr_ros2_integration/verify_smoke.py \
  --binding /mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json \
  --kernel-root /mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel \
  --output /tmp/cmr_ros2_refinement_dds_fresh_attempt
```

The output directory must be fresh. Partial results and tracebacks survive
failure. The fixed qualification includes four labelled delay injections,
one exact deadline-boundary contract check and one blocking-worker watchdog
injection. Normal budgets are 10/12 seconds; short fault budgets belong only
to these synthetic checks. DDS discovery/collection has its own 15-second
window and does not change the planner budget.

All records are SYNTHETIC_SMOKE. This is a symbolic DDS prototype, not a real
robot or formal Core campaign. It does not bind the historical formal result
schemas, independent campaign certificate verifier, external supervisor memory
sampling, or production ROS Action cancellation. No benchmark populations,
provider calls, frozen data or scientific acceptance criteria are changed.
