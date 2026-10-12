# B/FULL compact graph optimization

This is a second opt-in, isolated optimization of the fixed
`B-D-BRANCH-S1 / FULL` cell. The baseline is the qualified SCC/pruning V2
adapter; the original solver is a separate reference. Each runs once in a
fresh worker with the same P2f runner, tracemalloc, 180 s method budget,
195 s watchdog and independent persisted-certificate replay. The default
Planner and prior qualification sources are unchanged.

V2 spends time building and searching an edge-node graph even after pruning
511 of the 512 entries. V3 instead uses original node IDs for prefix distance
and two acceptance-memory layers for suffix distance. Parallel arcs retain
the minimum exact cost and the canonical first original transition at that
cost. This preserves the minimum accepting-lasso objective because endpoint
Product states, including Büchi states, are identical; a higher-cost arc cannot
improve it. The selected action and witness objects remain the original objects.
Different equal-objective witnesses are permitted and must independently verify.

Each suffix search starts from a separate dummy source whose outgoing edges
copy the entry's actual outgoing transitions. No edge enters the dummy. The
target is the original entry with acceptance seen. Thus returning to the target
requires at least one original transition even if the entry already accepts;
zero-cost self-loops and cycles still count as non-empty walks. SCC qualification,
all-entry lower bounds, gamma 10 and pruning rules remain those of V2. Distance
and path restoration still use the production ROS2 helpers.

## Fixed triple, 2026-10-12

| Arm | Complete method seconds | Search seconds | Exact objective |
| --- | ---: | ---: | ---: |
| Original solver | 1.626859833 | 0.320487734 | 15 |
| Qualified SCC V2 | 2.237633583 | 1.102624648 | 15 |
| Compact V3 | 1.734620945 | 0.632011194 | 15 |

In this triple V3 reduced complete method time by **22.48%** and search time by
**42.68%** relative to V2. It remains slower than the reference. These are single
observations; compare arms within this run rather than mixing timings across
the previous qualification runs.

The original Product is unchanged at 512 states / 5,808 transitions. Prefix
distance graph nodes fall from 6,320 to 512; suffix graph nodes from 12,640 to
1,025 (11,635 edges). V3 settles 512 prefix, 1,024 lower-bound and 513 suffix
states. Heap pushes/pops fall from 13,856 to 2,241. All arms search one exact
entry and prune 511. The reference's suffix count of 7 uses original search
states; V3's 513 includes acceptance-memory states and the dummy source.

Ten deterministic semantic cases compare V3 with V2 and unpruned reference
search and hand-calculated objectives. They check non-accepting entries,
zero-cost loops, parallel witness identity, multiple initial states, accepting
entries without self-loops, unreachable accepting SCCs and a loose-bound case
requiring two entry searches. Three invalid-cost checks also pass. The final
13-case suite runs after the source closure and plan are frozen.

All three full-model certificates pass original runner validation and an extra
independent persisted replay. A standard-library native reader checks exact
cost/closure, source bytes, row hashes, schema differences, observed exits and
phase accounting. All 55 frozen inputs are unchanged; 40 science mapping rows
and 8+6 actual import identities match per worker. The reused experimental
driver is pinned with the V2 source closure and never changes its original
module or the scientific runner. V3 uses `ROS2-DISCRETE-PLAN-CMR-COMPACT-V3`;
its versioned P2c specialization changes only backend SHA and schema ID.

## Reproduce

From the repository root in the qualified WSL/ROS2 Humble environment, with
the external, hash-matching CMR receipt/kernel/benchmark:

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_bfull_compact_fresh
python3 -B experiments/cmr_ros2_bfull_compact/compare.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_bfull_compact/fixtures.py --output "$out/fixtures.json"
python3 -B experiments/cmr_ros2_bfull_compact/compare.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```

Output must be fresh; no automatic method retries. `baseline` means qualified
V2 here. Scope remains `SINGLE_INSTANCE_PERFORMANCE_REGRESSION`, with the
original qualification result vocabulary. This does not qualify other
instances/methods or replace the formal campaign solver. No formal batch,
provider, DDS rerun or physical robot execution was started.

[Raw records and independent read-back](evidence/20261012/index.json) preserve
the plan, source snapshots, runner/delivery rows, schemas, certificates, wrapper,
logs and actual return codes. Driver, WSL wrapper, fixtures, native reader and
all three workers returned 0. The earlier preliminary fixture output is retained
as exploratory evidence; only the frozen final 13-case suite qualifies V3.
