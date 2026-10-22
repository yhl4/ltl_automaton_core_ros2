# V9: precision projection and witness canonicalization reuse

This optional prototype starts from pinned V8 publication
`f3232b0c13bc306a0e1e683dda7f83194bf2337f`. It changes only two repeated
computations inside the planner. It does not select a new default or run a
formal campaign. The bounded target remains **C3-T4 / AP-D**.

## Mechanism and invariants

`builder.py` clones the unchanged V6 grouped builder used by V8, replacing only
the full-TS and `project_state` callbacks. Within one precision build, it
computes the selected dimension positions once and memoizes each full state's
projection. The map starts cold for every build and is disposed with the
method's context. Labels, label-disagreement rejection, projection buckets,
minimum costs, complete ordered witnesses, reduction and Product are rebuilt
by the original body. Model callbacks and labels are not cached.

The V8 full-TS context still constructs the complete reachable TS once inside
the AP-D method budget and reuses it in later refinement rounds. A failed
construction publishes no partial cache; different models and attempts cannot
share it. This prototype accepts only the fixed AP-D qualification request.

`search.py` retains V7's integer/Fraction arithmetic, compact parallel-edge
selection, SCCs, lower bounds, arbitrary cycle entries, target-settled stopping
and path restoration. Its only search-input change is a solve-local cache of
the canonical sorted key for the **same witness tuple object**. A strong
reference prevents object-ID recycling. Different tuples are not conflated;
lists and generators use the uncached normalization path. Original edge and
witness objects remain the ones returned in the lasso. The cache disappears
after the solve, including exceptions.

The exact objective `prefix_cost + 10*suffix_cost`, INITIAL_LABEL_V1, nonempty
accepting closed suffix, complete refinement, tracemalloc, **180 s method /
195 s watchdog**, and original certificate persistence/fsync/hash/independent
verification remain. No preprocessing or acceptance work is moved outside the
method to improve reported timing.

## Four-arm comparison

The comparison uses one new process attempt each for the original solver,
pinned V7, pinned V8, and V9, through the guarded V8 entry. V8 adds **counters
only** for projection and witness normalization; V9 uses the same counters and
enables the two caches. The original component IDs and hashes remain pinned,
and the independent comparison binding also hashes all five new files.
Reference/V7 do not collect the new operation counters. This observation
instrumentation is part of the comparison, not a rewrite of historical V8
results. Timed workers execute sequentially to avoid mutual resource contention.

The parent source/binding/authority release check remains before the sampled
terminal completion, so its cost is charged to total time and deadline
classification. Each worker validates its result once; each parent validates
twice, reusing its schema. Additional persisted-certificate replays run after
delivery and are timed separately from row `T_total`.

## Bounded qualification, 2026-10-22

Executed source: `1e8ebc0f0e84484cca237bccfa93a83f491a7bbe`.
The source closure has 65 files: the unchanged 60 V8 sources and five new V9
files. All 56 bound input files remain unchanged before and after execution.

- Binding: `CMR_PROJECTION_WITNESS_REUSE_V1-a679aaebf90ab9a8`
- Binding SHA256: `1b50bdc1036e6faae6cfcd36757f72a7a9e51bee5d639ca8dacace1e16953217`
- V9 backend SHA256: `f4fb6a2dff6fe4fe881b2909dbeb70b254977fa7c74fa39d06863141cd001259`
- Pinned V8 component SHA256: `5207a536472ad501184513c50c7b80641c186af36e24edd8fbd4f7f5576a2e34`

| Backend | `T_total` s | `T_reduction` s | `T_search` s | Full TS builds / hits | Exact objective | Additional replay |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| Original solver | 1.966871199 | 0.080802700 | 0.279955800 | Not instrumented | 12 | PASS |
| Unchanged V7 | 1.169734293 | 0.059965500 | 0.208020297 | 6 / 0 | 12 | PASS |
| V8 with counters | 1.252232999 | 0.075960600 | 0.244801800 | 1 / 5 | 12 | PASS |
| V9 with counters | 0.976564697 | 0.029402700 | 0.155792499 | 1 / 5 | 12 | PASS |

| Actual operation, summed over six rounds | V8 | V9 |
| --- | ---: | ---: |
| Projection requests | 5382 | 5382 |
| Projection computations | 5382 | 384 |
| Witness-key requests | 3531 | 3531 |
| Witness-key computations | 3531 | 757 |
| Witness items normalized | 10752 | 2304 |

Projection computations decrease **92.87%** and witness-key computations
**78.56%**; request counts remain identical. Normalized witness items decrease
78.57%. V8/V9 have identical complete scientific round traces, search decisions,
heap/settlement/pruning counts and concrete lasso. Every backend completes all
six rounds, initial precision `[3]`, final precision `[0,1,2,3,4,5]`, and certifies
objective 12. All four workers exit zero and are no longer alive after cleanup.

In this observation V9's reduction phase is 61.29% shorter and search 36.36%
shorter than the counter-equipped V8 control; complete total is **22.01% lower**.
The two changes are combined, without a separate timing ablation. Preflight,
certificate and delivery times also differ, so the total difference cannot be
assigned entirely to the caches. These are single observations under the same
entry, not a stable or population-wide speedup. Historical V8 timings are not
pooled with this comparison. Memory reduction was not measured.

Directed fixtures compare full abstraction fields and witness identities,
two precisions, changed-model isolation, invalid precision/label rejection,
failed construction without partial cache, shared versus distinct witness
tuples, list/generator fallback, fresh solve caches, exact nonintegral/zero and
large integer costs, and negative-cost rejection. The counter-only control is
also compared with V7's result and search work. These fixtures invoke synthetic
small-graph solvers; they are not real Experiment A workers. Offline entry
checks cover all four descriptors/schemas, same-context schema reuse and
rejection of changed method budgets.

The [evidence index](evidence/20261022/index.json) retains **4 real workers /
4 original `run_one` calls / 4 observed internal certificate verifications /
4 additional persisted-certificate replays**. Independent standard-library
readback validates source/input identities, exact row and certificate hashes,
complete round/search/build equivalence, operation counts and inclusion of
release checks in all terminal timestamps. Readback starts no solver/verifier.

Two earlier source revisions failed **before dispatch** and are retained:
`f6564fa` could not serialize a fixture-only `AbstractTransition` summary with
the original JSON writer; `c5f3294` rejected the fourth backend in an inherited
descriptor method whose name set had not been rebound. Both earlier helper
scripts created namespaces with trailing CRs; their original paths and bytes are retained.
The final source fixes only the fixture summary and four-name binding, and uses
an LF-verified script. Each revision has a separate namespace; neither failed
preparation started a real worker. Development fixture/helper failures and
their retained logs remain in the evidence package.

The original V7/V8 sources, evidence and `00fc5a9` baseline remain intact. No
default switch, PR merge, DDS/provider request, physical execution or formal
batch was performed. This does not qualify V9 as a default backend or establish
its behavior outside the stated fixed-model AP-D scope.

## Reproduction

Use a clean source checkout, the existing WSL Humble/message overlay and a
fresh `/tmp` output directory. Keep the sourced ROS `PYTHONPATH`. Immutable
dispatch markers forbid repeating a comparison in the same namespace.

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/ltl_automaton_execution:$PWD/ltl_automaton_planner:$PWD/ltl_automaton_planner_core:$PWD:$PYTHONPATH"
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_v9_projection_witness_fresh
python3 -B experiments/cmr_ros2_reduction_reuse/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_reduction_reuse/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```
