# CMR V7: exact search arithmetic and repeated entry work

V7 is an explicitly selected **isolated candidate**, compared with the original
solver and the unchanged V6 unified entry on three fixed cells. It keeps
INITIAL_LABEL_V1, exact `prefix_cost + 10*suffix_cost`, the nonempty accepting
suffix, every-round full TS rebuild/refinement, tracemalloc, 180 s method budget,
195 s outer watchdog and the original independent certificate acceptance.
The production planner and frozen CMR default are unchanged. The 2026-10-12
search/entry qualification did not dispatch DDS. The isolated repair and later
three-cell DDS qualification are recorded below; neither starts a formal
campaign, provider call or hardware execution.

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

## Isolated audit repair (2026-10-13)

Branch `codex/v7-audit-dds-regression` starts at the preserved control
`00fc5a91383b24f85d33aa81682af22e531234cf`. The new production repair is
`d958cdff90a8c1d27dfb1663e1ccced19e39cdc0`; test corrections follow in
`a1cbf590bbd77ebdad8e853599907df25796642d` and
`96e9d36c03439f71d0549e44e144db32b865e4ce`, in that order. No unidentified
external patch was applied. Original V7/V6 results, failures and bindings retain
their original bytes and execution identities.

The execution snapshot stores one real node occurrence per suffix edge, with
one implicit final-to-first edge. For example, certified CMR states `[P,P,P]`
convert to snapshot `[P,P]` and retain two self-loop actions. The serializer and
resolver accept this sequence only when its real closing edge exists; they do
not strip further repeats. Message fields and the wire layout are unchanged.

The CMR DDS server checks TS feedback timestamps before target matching. It
rejects stamps at or before the current step's first publication, and stamps at
or before the last accepted feedback. Republishing the same command does not
move that boundary. Distinct fresh feedback for the same state still advances
consecutive self-loop steps. This isolated transport requires a common ROS
clock and preservation of the original feedback timestamp. Raw observer events
reissued with a new timestamp are outside this check's qualification.

The [new evidence index](../cmr_ros2_integration/evidence/20261013_audit_repair/index.json)
records the separate `CMR_V7_AUDIT_REPAIR-6d0f6577e0d3c123` check binding,
source identities, raw negative controls and retained fixture failures.
77 native resolver/manager/feedback checks and 12 ROS snapshot/node boundary
checks pass. Fourteen existing arithmetic fixtures still compare exact V6/V7
costs, witnesses and search traces, including fractional weights, zero cycles
and large integers. Their original per-run binding is preserved separately.

Two fixed **synthetic transport fixtures over actual DDS** use zero-cost actions
and the production execution node. Against `00fc5a9`, repeated feedback advances
the cursor from 1 to 2 and the repeated-entry snapshot is refused. The repaired
source passes both fixtures: actions dispatch at steps `[0,1]`, replay does not
advance, and new feedback does. DDS domain 226 is isolated. The earlier ROS-array
test assertion failure and intermediate attempts are retained; final assertions
check the cursor after actual message receipt. There were 12 DDS fixture
invocations across all retained attempts, with two final qualified fixture pairs.

These checks do **not** run real CMR instances or replay persisted certificates.
They do not grant a new CMR backend/default qualification. The unchanged
historical V7 binding must not be reused for modified source; any later real CMR
comparison needs a newly prepared canonical backend binding and source checks.
INITIAL_LABEL_V1, exact objective, nonempty accepting suffix, 180/195-second
budgets and certificate acceptance are unchanged. No default switch, PR merge,
formal campaign, provider or hardware run occurred.

Run the native feedback/resolver tests with this checkout on `PYTHONPATH`.
For the two DDS fixtures, source ROS Humble and the existing message overlay,
then prepend this checkout's package sources to avoid importing older Python
modules from the overlay:

```bash
export PYTHONDONTWRITEBYTECODE=1 ROS_DOMAIN_ID=226 ROS_LOCALHOST_ONLY=1
export PYTHONPATH="$PWD/ltl_automaton_execution:$PWD/ltl_automaton_planner:$PWD/ltl_automaton_planner_core:$PWD:$PYTHONPATH"
python3 -B -m pytest -q -p no:cacheprovider experiments/cmr_ros2_integration/test_feedback_dds.py
```

## Real-instance and DDS qualification (2026-10-13)

The repaired source at `14b2c806beecca27f855f32ab79be154e7011de7` was tested in a
clean Linux checkout using the existing ROS Humble/WSL overlay. The source
closure now includes the execution/resolver, snapshot serializer, message
definitions and new V7 DDS adapter: **56 files**, under a freshly prepared
canonical binding. The frozen CMR authority, exact arithmetic/search,
refinement, 180/195-second budgets and independent certificate rules remain
unchanged. No historical result is relabeled with the repaired source identity.

The targets are the same three cells fixed for V7 before the repair. Reference,
unchanged V6 and repaired V7 each ran once per cell: **9 fresh method workers,
zero continued controls**, 24 accepted rebuild rounds and 60 unchanged frozen
inputs. Every result is `OPTIMALITY_CERTIFIED`, with exact objectives 12, 15
and 12. All nine persisted certificates independently replay PASS. Compared
with the preserved V7 evidence, all arms retain the same verdict, exact cost,
initial precision and complete concrete witness; V7 also retains the same
normalized scientific rounds and heap/settlement/pruning counts.

| Cell | Objective | Reference total s | V6 total s | Repaired V7 total s | Prior V7 total s |
| --- | ---: | ---: | ---: | ---: | ---: |
| A-T1-M0-A-S-BRANCH / FULL | 12 | 2.232702 | 1.670048 | 1.513839 | 2.087386 |
| B-D-BRANCH-S2 / FULL | 15 | 3.307895 | 2.240552 | 1.851326 | 2.314885 |
| C3-T4 / AP-D | 12 | 1.047924 | 0.935987 | 0.864861 | 1.442596 |

These are single observations with different source storage and loading
conditions. They do not establish an algorithmic speedup from the repair.
The prior measurements keep their original execution identity.

`dds.py` invokes the V7 entry directly and reuses the qualified transport
validation rules. Domain **227** isolates three additional real-instance DDS
requests, one per fixed cell. All three pass and independently replay their
persisted certificates. Their full witnesses equal the paired V7 method
results. The imported execution node, fake runtime and models match the new
source closure. The smoke executes one prefix and one suffix traversal:
2/5/3 actions, **10 dispatched/completed/observed TS steps** in total, with
the existing old-generation injection rejected. It is symbolic execution over
actual DDS, with no physical robot. The 205/210-second server/transport windows
surround the unchanged 180/195-second method/watchdog contract. Certificate
readback runs in the parent after transport validation, outside method timing.
There are **12 method workers and 12 independent certificate replay invocations**
across this qualification; identical DDS/method certificate bytes are not counted
as distinct scientific certificates.

The first offline reader rejected this successful fresh run because it required
exactly two carried controls. `readback.py` now admits either zero controls or
the original complete two-control continuation, rejecting partial or undeclared
reuse. Three directed reader fixtures pass; the historical two-control path was
checked without rewriting its output. The initial reader failure is retained,
and no successful solver or DDS method was rerun. `audit_readback.py` additionally
checks the pinned baseline archive, paired scientific results and persisted DDS
records using only the standard library. Reader source snapshots and hashes
are separate from the method execution binding.

The [new index](evidence/20261013_audit_real/index.json) binds the raw archive,
member hashes, offline readbacks and external `validation/` logs/scripts. Runtime
identity is `14b2c806beecca27f855f32ab79be154e7011de7+cmr-search-entry-42c88be895479adf`;
binding ID is `CMR_SEARCH_ENTRY_V1-888c808d63103337`, SHA256
`52d12289c12c6dc449999d319b5ea790734f586e38c0bcd79d90dec5475d34ca`.
The original repository-level V7 control remains `00fc5a9`, while its archived
method identity remains `2934ec7...+cmr-search-entry-2135437e8cbf9959`.
Documentation/reader commits do not change the recorded runtime source head.

The exact preparation, method and DDS commands are preserved in
[run_methods.sh](evidence/20261013_audit_real/validation/run_methods.sh) and
[run_dds.sh](evidence/20261013_audit_real/validation/run_dds.sh). Reproduction
requires matching frozen inputs, a fresh output namespace and a newly verified
binding. The offline comparison can read the persisted output without a solver:

```bash
python3 -B -m experiments.cmr_ros2_search_entry.audit_readback --output /tmp/cmr_v7_audit_real_20261013_r1
```

This qualifies the three successful real-instance DDS paths only. It does not
repeat V6's full V7 timeout/failure/default qualification, certify zero-cost
results through the complete real CMR runner/verifier chain, or qualify raw
observer events reissued with new timestamps. The preserved synthetic controls
cover repeated cyclic entry and duplicate/stale original TS feedback. No default
switch, PR merge or formal batch experiment occurred.
