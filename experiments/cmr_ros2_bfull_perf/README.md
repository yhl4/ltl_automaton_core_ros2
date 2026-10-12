# B-D-BRANCH-S1 / FULL isolated search optimization

This opt-in prototype compares one fixed real Experiment A cell with three
fresh workers: the frozen reference solver, the previously qualified ROS2
adapter, and an SCC/lower-bound ROS2 adapter. Each arm runs once. It reuses
the original P2f `run_one`, model loader, complete kernel loop, concretization,
certificate writer, P2e path binding and independent INITIAL_LABEL_V1 verifier.
The default PlannerNode and the previous three-instance qualifier are unchanged.

The previous 98.3067 s ROS2 result came from exhaustive suffix search at all
512 reachable Product entries. The reference searched one entry after pruning.
Both built the same 512-state / 5,808-transition Product. The ROS2 edge-node
representation preserves parallel action/witness objects but enlarged each
acceptance-memory search, causing about 3.97 million heap operations.

The candidate restricts suffix transitions to reachable accepting SCCs and
orders every qualifying entry, including non-accepting entries, by
`prefix_distance + 10 * max(distance_to_accept + distance_from_accept,
minimum_internal_outgoing_cost)`. This is an admissible lower bound: any
accepting closed walk must reach an accepting state, return, and traverse at
least one outgoing edge. Entries whose bound is at least the best feasible
objective cannot improve it. Different equal-cost witnesses are permitted;
their validity and exact objective remain mandatory. SCC topology and lower
bound distances use minimum parallel costs; decoded witnesses still come from
the complete original transition objects. Zero-cost cycles and self-loops remain
non-empty walks.

## Measured fixed triple, 2026-10-12

| Arm | Complete method seconds | Search seconds | Exact entries / pruned | Exact objective |
| --- | ---: | ---: | ---: | ---: |
| Original solver | 1.244840724 | 0.191973312 | 1 / 511 | 15 |
| Previous ROS2 | 93.345968209 | 92.313485103 | 512 / 0 | 15 |
| Optimized ROS2 | 1.989992554 | 0.923917679 | 1 / 511 | 15 |

This single triple measured 46.91× lower complete method time and 99.92× lower
search time relative to the fresh ROS2 baseline. It is not a performance
campaign or a claim across the other instances/methods. The optimized adapter
still takes more time than the reference because it retains auxiliary
edge-node graphs and full distance searches inside the selected SCC.

All three arms retain the original runner's tracemalloc, full input processing,
180 s method budget, 195 s watchdog, and complete certificate acceptance.
Search counters distinguish original Product sizes from ROS2 auxiliary work:
baseline versus optimized heap pushes/pops were 3,971,248 versus 13,856;
optimized settled work was prefix 6,320, lower-bound 1,024, suffix 6,320.
The reference's suffix count of 7 is original-graph work and is not the same
counter basis. Three persisted certificates independently replayed successfully.

Seven deterministic semantic cases compare with the unpruned reference and old
ROS2 adapter, including a hand-calculated loose-bound case requiring two exact
entry searches. Three invalid-cost cases are rejected. A standard-library-only
native reader checks exact lasso costs/closure, paired objectives, source bytes,
schemas, timing hashes and worker exits. All 55 previously frozen inputs remain
unchanged; each worker pins 40 science source-map rows and 8+6 actual imports.

The optimized backend uses `ROS2-DISCRETE-PLAN-CMR-SCC-BOUND-V2`. Its source
identity binds the production distance helper, old witness adapter, new backend
and instrumented caller. The versioned P2c specialization changes only the
backend SHA constant and schema ID. No scientific or terminal acceptance rules
are relaxed.

## Reproduce the bounded comparison

Requires the external, hash-matching CMR receipt, kernel and benchmark. From
this repository root in the qualified WSL/ROS2 Humble environment:

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_bfull_perf_fresh
python3 -B experiments/cmr_ros2_bfull_perf/compare.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_bfull_perf/fixtures.py --output "$out/fixtures.json"
python3 -B experiments/cmr_ros2_bfull_perf/compare.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```

The output must be fresh. `--prepare` freezes the three-arm plan and source
closure before execution. Failures and censoring are retained; no automatic
method retries occur. Scope is `SINGLE_INSTANCE_PERFORMANCE_REGRESSION`, with
the original `CORE_SUBSET_QUALIFICATION` result vocabulary. No formal campaign,
provider, DDS rerun or physical robot execution was started in this task.

[Archived artifacts and read-back](evidence/20261012/index.json) include the
source snapshots, plan, raw/delivered rows, schemas, certificates, logs and
observed return codes. The outer WSL shell returned 2 after the completed triple
because its exit-code variable was lost in command-line quoting; its `run.rc`
was empty. The scientific comparison finished `PASSED` and all three worker
return codes were observed as 0. Two native-reader failures concerned the
certificate/transport serialization layouts; both scripts/errors remain in the
archive. The corrected reader passed with rc 0. No solver attempt was rerun.
