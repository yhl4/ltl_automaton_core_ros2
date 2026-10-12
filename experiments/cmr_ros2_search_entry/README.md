# CMR V7: exact search arithmetic and repeated entry work

V7 is an explicitly selected **isolated candidate**, compared with the original
solver and the unchanged V6 unified entry on three fixed cells. It keeps
INITIAL_LABEL_V1, exact `prefix_cost + 10*suffix_cost`, the nonempty accepting
suffix, every-round full TS rebuild/refinement, tracemalloc, 180 s method budget,
195 s outer watchdog and the original independent certificate acceptance.
The production planner and frozen CMR default are unchanged. No formal campaign,
DDS run, provider call or hardware execution was started in this qualification.

## Pinned audit control baseline (2026-10-12)

The repair-control baseline is commit
[`00fc5a91383b24f85d33aa81682af22e531234cf`](https://github.com/yhl4/ltl_automaton_core_ros2/commit/00fc5a91383b24f85d33aa81682af22e531234cf),
pinned locally as `cmr-v7-baseline-00fc5a9`. An independent worktree on
`codex/v7-audit-dds-regression` is prepared at that same commit. The final audit
patch branch, full commit, patch path and application order are **pending**;
no patch has been applied and no new comparison or DDS regression has started.

Baseline byte verification passed for all 38 files in the V7 source closure,
the V7 archive's 306 members and the V6 acceptance archive's 796 members.
Archive members were checked by size and SHA256 against their manifests;
the corresponding evidence files also match the pinned Git blobs.

| Preserved archive | Bytes | SHA256 |
| --- | ---: | --- |
| [V7 evidence](evidence/20261012/index.json) | 937685 | `399653ff5db57d8aed078f327e35671ddd0255385a500e1ad63ad6f6febea1a6` |
| [V6 acceptance evidence](../cmr_ros2_backend/evidence/20261012_acceptance/index.json) | 2216897 | `2e393d8a55c91c0eaab550f4adc355b9e3a4df9d65c5ee798a4f4bf5a82b8d92` |

All existing results, failures, certificates and bindings retain their original
bytes and identities. In particular, the historical V7 execution identity is
`2934ec788e3b662111d378fd4b1a12ce6a459eee+cmr-search-entry-2135437e8cbf9959`;
pinning commit `00fc5a9` does not relabel those records or constitute another
solver/certificate run. The nine qualified results and certificate replays
below remain the earlier qualification.

The expected repair base is `2934ec7`. Once its exact handoff is available,
first check the patch against `2934ec7..00fc5a9` for conflicts with the V7
changes, then apply it only in the independent branch with a new source/version
binding. The pending acceptance checks are:

- Repeated cycle-entry occurrences remain in the complete execution sequence.
- Expired and duplicate feedback cannot advance execution or dispatch again.
- Integer and Fraction paths retain the same exact objective and witness costs.
- Legal zero-cost outcomes are accepted without a truthiness-based rejection.

After patch identity and conflicts are resolved, prefer a small actual DDS
regression using the existing ROS2/WSL environment and compare pre-repair versus
repaired verdicts, exact costs and independent persisted-certificate replay.
These checks are **NOT_RUN**. Keep INITIAL_LABEL_V1, 180/195 s budgets and the
original certificate rules; do not switch defaults, merge the PR or start the
formal campaign.

## Changes and boundaries

`backend.py` changes only the numeric representation of weights on a fresh,
private compact search graph: denominator-one `Fraction` weights become Python
integers. This preserves exact addition, ordering and equality, including values
larger than machine integers. Nonintegral weights remain `Fraction`. Canonical
parallel-edge selection and the original edge/witness objects remain untouched;
V6's prefix/lower-bound/suffix helpers, target-settled stopping, pruning and path
restoration are reused unchanged. Returned costs retain the original Fraction
representation.

`entry.py` verifies a binding/source boundary once for a single process attempt,
then derives descriptors and reuses one schema per backend/receipt. Before
release it reads the binding again and rechecks the full source closure; any
change invalidates the context. Parent and worker verify separately. There is
no cache across attempts, models or refinement rounds.

The frozen formal `run_one`, its preflight and instance loader are unchanged.
Input construction stays inside the original 180 s interval. This iteration
reduces repeated wrapper descriptor/schema work; it does **not** establish a
speedup of `T_input_preprocess`. `VerifiedEntry` records two binding reads and
two source-closure checks, including release, and one schema build per context.
Other original authority/preflight checks remain and are not included in those
local counters.

The candidate clones the qualified unified `run_isolated` code object, replacing
only its selected entry dependencies. Process-group cleanup, timeout/infrastructure
serialization, worker-result provenance, late-result invalidation and deadline
predicates remain from V6. V7 has not repeated V6's full DDS/failure-path/default
qualification; this small performance qualification does not make V7 the default.

## Fixed comparison, 2026-10-12

The targets were fixed before candidate outcomes: the existing minimum A/FULL,
B-D-BRANCH scale S2/FULL and C3-T4/AP-D. Each has one accepted reference, V6 and
V7 result. All three exact objectives and initial precisions agree; **9 persisted
certificates independently replay PASS**. There are **24 accepted rebuild rounds**.
V6/V7 complete lasso payloads, normalized scientific rounds, heap/settlement and
pruning counts agree. Fourteen directed arithmetic/witness checks also pass,
including nonintegral weights, zero cycles, parallel ties, invalid costs and
integers above 2^80; separate entry fixtures reject changed bindings, requests,
receipts and sources.

| Cell | Objective | Reference total s | V6 total s | V7 total s | V6 search s | V7 search s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A-T1-M0-A-S-BRANCH / FULL | 12 | 2.646128 | 2.219885 | 2.087386 | 0.767309 | 0.614951 |
| B-D-BRANCH-S2 / FULL | 15 | 3.685563 | 2.729630 | 2.314885 | 1.365683 | 0.862993 |
| C3-T4 / AP-D | 12 | 1.404217 | 1.470336 | 1.442596 | 0.210951 | 0.167791 |

Relative to this V6 observation, search falls 19.86%, 36.81% and 20.46%; method
total falls 5.97%, 15.19% and 1.89%. These are single observations, not a stable
or general speedup. C3/AP-D V7 remains slower than the original solver.

The following decomposition reads the original timestamps. Pre-method time is
`method_start_ns - outer_start_ns`; post-method delivery is final completion
minus the raw formal runner's completion. Neither replaces a scientific phase.
Pre-method startup is outside successful method time but inside the watchdog.
Post-method delivery remains charged to the method and its deadline.

| Cell | V6 / V7 pre-method s | V6 / V7 delivery s | V6 / V7 T_other s | V6 / V7 harness wall s |
| --- | ---: | ---: | ---: | ---: |
| A / FULL | 12.508487 / 11.584646 | 0.493980 / 0.433511 | 0.511302 / 0.448585 | 15.511619 / 13.828617 |
| B-S2 / FULL | 11.654572 / 11.852387 | 0.399700 / 0.459393 | 0.415622 / 0.474820 | 15.053481 / 14.317744 |
| C3 / AP-D | 15.056815 / 13.169487 | 0.442738 / 0.409147 | 0.448831 / 0.415559 | 17.424141 / 14.764086 |

Entry wall time and delivery do not improve on every cell: B's delivery and
T_other increase. Startup remains large, and unchanged formal input preprocessing
does not improve in these observations. Reduced repeated work is verified by
the local entry counters; its independent runtime contribution is not isolated
from the search change or process/filesystem variation.

## Retained failure and continuation

The first integration run exposed a schema facade argument-order error. Its
A reference and V6 controls completed successfully; the candidate worker wrote
a certified raw result, but the parent rejected delivery and serialized an
infrastructure failure. That candidate result is excluded from qualified counts.

The facade was corrected under a new independent source/version binding. The
two completed controls were checked file by file and carried forward byte for
byte with their original execution/version identities; neither was rerun or
relabeled. Seven new workers completed the remaining slots. The final nine
accepted records therefore consist of two continued controls and seven new
workers. Ten actual method attempts occurred across both namespaces, including
the rejected first candidate. All original failed artifacts are retained.

The old V6 authority/source binding stays unchanged. The V7 candidate has a
separate canonical `CMR_SEARCH_ENTRY_V1` binding, saved with source snapshots,
plans, every raw result and persisted certificate in
[the evidence index](evidence/20261012/index.json). The readback runs with only
the Python standard library and verifies bytes/identities without a solver.

The accepted [binding bytes](backend_binding.json) have ID
`CMR_SEARCH_ENTRY_V1-fc03c25f03e4e809`, SHA256
`741acdfcfe5f4aa0de31c74e09f834a89a37c47179a76710e4021d08fbdce82d`.
V7's implementation SHA is
`3baf355f1e7ce39219d4c6d2faf22ef5bf346ed2824593ccc2a753aa0e5cdc4d`.

## Reproduce

Use the matching frozen CMR receipt, kernel and qualified ROS Humble overlay.
Choose a fresh `/tmp` output. `--prepare` also creates an unchanged V6 plan,
whose 15 permitted cells provide source identity; the outer plan dispatches
**only the three cells above**, nine workers, not the full permitted matrix.

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_search_entry_fresh
python3 -B experiments/cmr_ros2_search_entry/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_search_entry/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_search_entry/readback.py --output "$out"
```

The recorded continuation additionally binds the original failed directory and
the two control directories' complete file hashes. Fresh reproduction uses the
fixed entry and needs no continuation. The worker CLI requires explicit
`--backend reference|ros2-v6|ros2-v7`, plan, request and version binding.
