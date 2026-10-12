# B/FULL suffix search stops at the finalized closed-walk target

This opt-in V5 prototype changes only suffix distance search. It compares one
fixed `B-D-BRANCH-S1 / FULL` cell with fresh reference, current V4 and candidate
V5 workers, one attempt each. The production planner, V4 sources, frozen CMR
runner/model/data and previous qualifications are unchanged.

V5 adapts the production component-distance Dijkstra loop with an explicit
target. It stops only after a non-stale heap item is popped and its distance
is written to the settled-distance map. Finding or enqueuing the target does
not stop the search. All abstract edge costs are validated as exact and
nonnegative before this search, so the minimum popped target distance is final.
Unreachable targets still exhaust the heap. The adapted loop retains source,
component, default/None weight, heap sequence, duplicate-entry and equal-cost
behavior, with the original NetworkX BSD notice.

Only settled distances are returned. A shortest route to the target exists
through already settled predecessors: each predecessor was popped before
relaxing its next edge. The original tight-path helper can recover a finite
route even if other equal-distance states remain unvisited or zero-cost cycles
exist. V4's separate dummy source still makes every suffix non-empty; both
accepting and non-accepting entries retain their original acceptance semantics.

Each solve clones V4's unchanged code/globals and uses local target-registration
hooks. Only its suffix helper changes. There is no global target registry or
cross-solve cache. Graph construction/reuse, SCC qualification, all-entry lower
bounds and pruning, Fraction costs, gamma 10 and original transition/witness
reconstruction remain V4 behavior. Prefix and lower-bound distances still use
the complete production helpers.

## Fixed triple, 2026-10-12

| Arm | Complete method seconds | Search seconds | Exact objective |
| --- | ---: | ---: | ---: |
| Original solver | 1.161949800 | 0.200860200 | 15 |
| Current V4 | 1.435035192 | 0.352131340 | 15 |
| Finalized-target V5 | 1.434955907 | 0.318007381 | 15 |

Search time is **9.69% lower** in this single triple. Complete method times are
effectively equal at **1.435 s** (difference about 0.079 ms); this is not evidence
of an end-to-end speedup. Product construction and other phases vary between
the arms. Do not combine these observations with earlier runs or generalize
them to other instances/methods. V5 remains slower than the reference.

The unchanged suffix graph has 513 nodes / 5,827 edges. V5 settles 11 suffix
states instead of V4's 513, discovers 51 and stops with 40 heap entries remaining
at exact suffix distance 1. Prefix/lower-bound settled counts remain 512/1,024;
both ROS2 arms search one entry and prune 511. Overall heap pushes/pops decrease
from 2,241/2,241 to 1,779/1,739. Reference's suffix count 7 uses its own state
representation and counter basis. Original Product size remains 512/5,808.

Eighteen final checks pass: 10 hand-calculated lasso cases, three invalid-cost
rejections, two graph/view checks and three target-specific checks. The target
checks require a first-discovered cost 10 to improve to final cost 2, recover a
finite zero-cost route while another tied state remains unvisited, and exhaust
an unreachable target's heap with exactly the full helper's distance map.
They also preserve original edge/witness identity, input immutability, non-empty
zero-cost suffixes and loose-bound continuation. Sources and plan are frozen
before this suite and the real triple.

All three complete methods certify objective 15 and independently replay their
persisted full-model certificates. Original P2f `run_one`, concretization,
tracemalloc, heap instrumentation, 180 s method budget, 195 s watchdog, P2e
binding and certificate acceptance remain. V5 uses
`ROS2-DISCRETE-PLAN-CMR-SETTLED-TARGET-V5`; the versioned P2c specialization
changes only backend SHA and schema ID. A standard-library native reader checks
exact costs/closure, target settlement and remaining frontier, accounting,
source/import identities, schemas, hashes and actual worker exits. All 55
frozen inputs remain unchanged.

## Reproduce

From the repository root in the qualified WSL/ROS2 Humble environment, with
the external, hash-matching CMR receipt/kernel/benchmark:

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_bfull_target_fresh
python3 -B experiments/cmr_ros2_bfull_target/compare.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_bfull_target/fixtures.py --output "$out/fixtures.json"
python3 -B experiments/cmr_ros2_bfull_target/compare.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```

Output must be fresh. `baseline` is the qualified current V4, pinned to its
archived source closure. The reused experimental worker/scientific runner,
timing and terminal-delivery rules remain unchanged; there are no automatic
method retries. Scope is `SINGLE_INSTANCE_PERFORMANCE_REGRESSION` and does not
qualify a formal campaign solver replacement.

[Raw artifacts and independent read-back](evidence/20261012/index.json) include
the source/plan, raw/delivered rows, schemas, certificates, stopping counters,
wrapper, logs, reader and observed return codes. Driver, WSL wrapper, fixtures,
native reader and all three workers return 0. No further instances/methods,
formal batch, DDS, provider or historical 136/754 test reruns were started.
