# Product construction and refinement qualification

This opt-in V6 prototype optimizes one complete Product build. It reuses the
previously selected `B-D-BRANCH-S1`, `C1-T1`, `D3-1` instances and all three
methods (`FULL`, `AP-D`, `DEP-D`). The nine cells are frozen before execution;
each runs one fresh original-solver, current V5 and candidate V6 worker.
This is `FIXED_SUBSET_PRODUCT_REFINEMENT_QUALIFICATION`, outside the formal ledger.

## Change and semantic boundary

The frozen grouped builder is copied with two Product changes: `deque.popleft()`
preserves FIFO discovery order, and a local `(Buchi state, task label)` cache
reuses sorted unique successors. Initial-label consumption uses the same cache.
Every call still rebuilds the full reachable TS, reduction and reachable Product.
The cache disappears when that build returns; refinement rounds do not share it.

The qualified `e2_2_runner.py` monitor computes successors from state/label.
Its idempotent accepting-set insertion is already complete: it enumerates the
monitor language over all formula AP valuations before returning the model
(lines 475–529). The prototype is limited to these bound models; arbitrary
stateful transition callbacks are outside its scope. Accepting membership is
checked unchanged before/after the real-model fixtures.

Full TS/reduction statements, labels and disagreement guards, supports, action
and edge multiplicity, exact Fraction costs, complete ordered witnesses and
result construction remain the original builder's behavior. FIFO order and
final sorting are unchanged. All work remains inside the complete method;
original phase intervals and timing keys are retained, with cache counters
stored separately. Search is exactly V5, including finalized-target suffix
stopping. The frozen scientific files and default ROS2 planner are untouched.

## One attempt per arm/cell, 2026-10-12

All values are seconds. Product columns sum **all** construction rounds.

| Instance / method | Reference total | V5 total | V6 total | V5 Product | V6 Product |
| --- | ---: | ---: | ---: | ---: | ---: |
| B-D-BRANCH-S1 / FULL | 1.087880299 | 1.300303707 | 0.996779207 | 0.341229402 | 0.026989001 |
| B-D-BRANCH-S1 / AP-D | 0.973507502 | 1.116969705 | 1.031928010 | 0.131141900 | 0.012071200 |
| B-D-BRANCH-S1 / DEP-D | 0.824129508 | 0.778020925 | 0.803913717 | 0.088876702 | 0.010613400 |
| C1-T1 / FULL | 0.615746405 | 0.780816406 | 0.698797405 | 0.047025100 | 0.004632400 |
| C1-T1 / AP-D | 1.084072407 | 0.890709405 | 0.817043904 | 0.084250100 | 0.010731300 |
| C1-T1 / DEP-D | 0.747471504 | 0.877738106 | 0.758886604 | 0.077566600 | 0.010190400 |
| D3-1 / FULL | 0.540596550 | 0.610154208 | 0.598036700 | 0.001157000 | 0.001087200 |
| D3-1 / AP-D | 0.550333503 | 0.591987095 | 0.740679700 | 0.001048700 | 0.001135400 |
| D3-1 / DEP-D | 0.694464595 | 0.707858024 | 0.637544099 | 0.001253199 | 0.000858900 |

B/FULL Product time decreases **92.09%**, and complete time decreases **23.34%**
against this run's V5. Its 2,593 successor queries require only seven actual
evaluations, with 2,586 cache hits; Product size remains 512 states / 5,808 edges.
This is a single observation, without separate ablations of the two changes.

Product time decreases in the six B/C cells and two D cells. D/AP-D increases
from 1.049 to 1.135 ms. Complete methods are slower in B/DEP-D (**3.33%**) and
D/AP-D (**25.12%**) despite the B construction improvement. Search and other
phases vary; no pooled, stable or universal speedup is claimed. No methods were
rerun or excluded, and earlier measurements are not combined with this table.

Every arm certifies the exact objectives B=15, C=13, D=20. Build-round counts
are B=`1/4/1`, C=`1/6/4`, D=`1/1/1` for FULL/AP-D/DEP-D: 20 per arm, 60 total.
The **entire V5/V6 scientific round trace** agrees after removing only backend
metadata and time, including precision, bounds, concretization/refinement,
actions, graph sizes and heap/target decisions. Reference comparison requires
the same initial precision, certified verdict and exact objective, with its
counter basis retained separately.

Ten directed checks pass, covering initial labels, duplicate/empty successors,
multiple initial states, Fraction/action preservation, unreachable Buchi states,
label disagreement, same-shaped different models and fresh caches on repeated
builds. Five additional real-model structural pairs cover S_phi/full precision
(D's precisions coincide), comparing every Product field and witness sequence.
Each witness must be the original full-TS edge object from its own build. AST
checks bind the unchanged pre-Product region, result constructor and timing
write block; actual full-TS calls and transition/cache accounting are checked.

All 27 persisted certificates pass additional independent P2e/verifier replay.
Original P2f `run_one`/refinement, INITIAL_LABEL_V1, nonempty accepting suffix,
Fraction objective `prefix + 10 × suffix`, tracemalloc, measured 180 s method
deadline, 195 s worker watchdog and terminal delivery remain. Worker startup
and preflight precede the qualified method start; delivery/logging are charged.
P2c specialization changes only backend SHA and schema ID. V6 identity is
`ROS2-DISCRETE-PLAN-CMR-PRODUCT-V6`; it binds the V5 search lineage, authority
builder SHA and new builder/caller bytes. V5 is pinned to its qualified archive.

A standard-library Windows reader independently checks all 27 rows, exact
lassos, round traces, hashes, schemas, counters, exits, source/import identity
and 55 unchanged frozen inputs. Driver, fixture, WSL wrapper, native reader
and every worker return 0. [Complete raw evidence](evidence/20261012/index.json)
includes frozen code/plans, every attempt, certificates, logs and read-back.

## Reproduce

Use the existing qualified ROS2 Humble environment and matching external frozen
receipt/kernel/benchmark; authority mismatches fail closed. From the repo root:

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_product_perf_fresh
python3 -B experiments/cmr_ros2_product_perf/compare.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_product_perf/fixtures.py --binding "$receipt" --kernel-root "$kernel" --output "$out/fixtures.json"
python3 -B experiments/cmr_ros2_product_perf/compare.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```

For native read-back from Windows, use a Python interpreter and the actual
fresh output's `\\wsl.localhost\Ubuntu-22.04-D\tmp\...` path with
`python -B experiments/cmr_ros2_product_perf/native_readback.py --output PATH`.

No formal 170 × 3 campaign, extra DDS, providers, robot execution or historical
136/754-test reruns were started. This qualification does not switch the
default planner, legacy DDS worker or formal campaign solver to V6.
