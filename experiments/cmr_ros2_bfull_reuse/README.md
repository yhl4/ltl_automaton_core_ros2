# B/FULL graph reuse and accepting-layer simplification

This opt-in prototype implements only two changes to the qualified compact V3
adapter: reduce copies within one search and omit the unreachable False layer
when a suffix entry already accepts. The fixed comparison is
`B-D-BRANCH-S1 / FULL`, one fresh worker each for original reference, current V3
and candidate V4. No default Planner or prior qualification source is changed.

When reachable nodes or an SCC cover the entire private graph, V4 reuses that
graph. Proper subsets retain the existing `subgraph(...).copy()` behavior.
Reverse distances use `reverse(copy=False)`, a native DiGraph view that shares
the predecessor/successor maps in reverse. The distance/path helpers read these
maps without mutating them. There is no cache across searches or refinement
rounds. Node ordering, SCCs, entry bounds, pruning, Fraction costs, gamma 10,
original transitions and witness reconstruction remain those of V3.

Acceptance memory is monotone: once True it cannot become False. An already
accepting entry therefore needs only the True layer; non-accepting entries
retain both layers. The separate dummy start remains and has no incoming edges,
so reaching the original entry requires at least one real transition. Zero-cost
self-loops and cycles still form non-empty suffixes. No target early-stop or
Product/refinement optimization was added.

## Fixed triple, 2026-10-12

| Arm | Complete method seconds | Search seconds | Exact objective |
| --- | ---: | ---: | ---: |
| Original solver | 1.149286706 | 0.201930201 | 15 |
| Current compact V3 | 1.605544117 | 0.510543337 | 15 |
| Graph-reuse V4 | 1.407112306 | 0.379907402 | 15 |

In this single triple, V4 reduces complete method time by **12.36%** and search
time by **25.59%** relative to current V3. It remains slower than the reference.
Compare within this run; these observations do not establish stable or
cross-instance speed gains.

The original Product remains 512 states / 5,808 transitions. This B/FULL search
actually records two full-graph reuses, zero subgraph copies and one reverse
view. The accepting suffix graph falls from V3's 1,025 nodes / 11,635 edges to
513 nodes / 5,827 edges. Heap pushes/pops remain 2,241 in both ROS2 arms, with
settled work prefix 512, lower-bound 1,024 and suffix 513. The gain comes from
graph preparation, not fewer entry or heap searches: both arms search one entry
and prune 511. Reference suffix counts use a different original-state basis.

All three arms retain original P2f `run_one`, complete model/loop/concretization,
tracemalloc, instrumentation, 180 s method budget, 195 s watchdog, P2e authority
binding and independent certificate acceptance. Each is certified at exact
objective 15 and independently replays its persisted certificate. V4's backend
ID is `ROS2-DISCRETE-PLAN-CMR-GRAPH-REUSE-V4`; the P2c specialization changes only
backend SHA and schema ID, with all other acceptance and timing rules intact.

The final 15 checks comprise 10 hand-calculated semantic cases, three invalid
cost rejections and two structural checks. They cover partial reachable/SCC
copies, native reverse-view identities and copied-distance equality, input
immutability, single/two acceptance layers, dummy indegree zero, non-accepting
entries, zero cycles, parallel edge/witness identity and loose-bound continuation.
The suite runs after the source closure and plan are frozen. A standard-library
native reader independently checks exact lasso costs/closure, result/certificate
hashes, paired outcomes, source/import identities, schemas, structural counters
and actual worker exits. All 55 frozen inputs are unchanged.

## Reproduce

From the repository root in the qualified WSL/ROS2 Humble environment, with
the external, hash-matching CMR receipt/kernel/benchmark:

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_bfull_reuse_fresh
python3 -B experiments/cmr_ros2_bfull_reuse/compare.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_bfull_reuse/fixtures.py --output "$out/fixtures.json"
python3 -B experiments/cmr_ros2_bfull_reuse/compare.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```

Output must be fresh. `baseline` means qualified current V3, pinned to its
archived source closure. The reused experimental worker and complete scientific
runner are unchanged. No automatic retries occur. Scope is
`SINGLE_INSTANCE_PERFORMANCE_REGRESSION`, not a formal campaign qualification.
There were no additional instances/methods, DDS, providers or physical robot
runs, and no rerun of the historical 136/754 test qualifications.

[Raw artifacts and independent read-back](evidence/20261012/index.json) include
the frozen source/plan, raw and delivery rows, schemas, certificates, wrapper,
logs, reader and observed return codes. Driver, WSL wrapper, fixtures, native
reader and all three workers returned 0; no method retries or discarded failures.
