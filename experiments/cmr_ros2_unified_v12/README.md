# Explicit CMR unified V12 backend

This independently bound entry exposes `reference` and `ros2-v12` for
FULL, AP-D and DEP-D. It preserves the published compact-cost V12 component
`0011e57e2828ad699c72bb2c25a1b15a3b181681` and its archived evidence.
The existing V6/V7 entries, frozen campaign and default selection are unchanged.

## Method policy

| Method | Construction | Search |
| --- | --- | --- |
| FULL | Original grouped builder and full precision | Published V12 exact search |
| AP-D | One complete reachable TS per method; fresh reduction/Product each round; V9 projection reuse | Published V12 exact search |
| DEP-D | Original grouped builder each round and original dependency precision/refinement | Published V12 exact search |

The unified adapter has a new backend/runtime identity. Its binding separately
records the unchanged V12 component identity and the method-specific construction
policy. It does not claim the old every-round-rebuild binding applies to AP-D.
AP-D reuse remains limited to static bound models with pure action callbacks.
No cache survives its owning build/solve/method or is shared across requests.
Construction counters cover the planner builder. Independent certificate
construction/verification remains unchanged and is charged separately.

INITIAL_LABEL_V1, exact `prefix_cost + 10*suffix_cost`, nonempty accepting closed
suffixes, nonaccepting/repeated loop entries, full refinement, tracemalloc,
**180 s method / 195 s outer watchdog**, and the original independent certificate
persistence/fsync/hash/verification rules remain. Preflight source/path checks
remain fresh. The final runtime binding/source/authority check runs before
sampling the terminal delivery timestamp and remains charged to the deadline.

## Bounded qualification scope

The normal profile fixes A-T1-M0-A-S-BRANCH, B-D-BRANCH-S2 and C3-T4 across all
three methods, D3-1/AP-D for multi-entry/Fraction behavior, and D1-1 across all
three methods for original exact-empty comparison. Each has one reference and
one unified V12 attempt: 13 cells and 26 method workers, not a formal campaign.

The separate synthetic-zero profile derives the fixed A model by replacing its
explicit action cost rows with exact zero. It preserves the original input and
uses a new CONTROL record, benchmark directory, manifest and execution binding.
Its three-method results are synthetic qualification records with zero Core
results. The frozen `run_one`, unified worker/watchdog, schema, persisted
certificate and independent verifier are exercised without changing their rules.

The localhost DDS adapter uses isolated domain 231, the existing symbolic
FakeBackend and production execution node. Method/watchdog limits stay 180/195 s;
server/transport windows stay 205/210 s. No physical robot or provider is used.
Feedback checks assume a common ROS clock and preserved original timestamps.
The test-only lifecycle harness labels clock-offset checks as simulated and
retains actual watchdog elapsed time after cleanup. Failed attempts are retained.

`campaign.py` constructs a separately bound controller for one explicitly selected
plan cell, routes the unified worker and invokes the frozen scientific publication,
receipt and restore functions. It refuses incomplete prior dispatches, confirms
process-group cleanup, retains the delivered row, and restores committed cells
without launching workers. The original frozen formal Campaign constructor and
the complete real 510-cell execution remain outside this bounded qualification.
`offline_chain.py` generates explicitly synthetic 510-row analyzer/ledger checks;
those rows are never real experiment results.

## Qualification identities and completed method checks, 2026-10-25

Executed source: `d79653300e7bed556a4d1583562e09f3c1dd6f88`.
The runtime closure contains 84 files: the unchanged 77-file compact-cost V12
closure and seven new adapter/qualification files.

- Runtime binding: `CMR_UNIFIED_V12_V1-b9ad1c00e62d5ccc`
- Binding SHA256: `198ec92af99a40196657bb38fb8227ed4ad5a241270f28ae1d9d0a4a60e75075`
- Unified backend SHA256: `709e0b8742d2644c618142f9e18bad07b3afb4d3631141af4819773e0c396861`
- Preserved V12 component SHA256: `10f0c455ab1088e6ac702268489b96c5f26ffd84308987a7eef69555f7a190ee`

| Fixed input | Methods | Reference / unified V12 terminal and exact objective |
| --- | --- | --- |
| A-T1-M0-A-S-BRANCH | FULL, AP-D, DEP-D | OPTIMALITY_CERTIFIED / 12 |
| B-D-BRANCH-S2 | FULL, AP-D, DEP-D | OPTIMALITY_CERTIFIED / 15 |
| C3-T4 | FULL, AP-D, DEP-D | OPTIMALITY_CERTIFIED / 12 |
| D3-1 | AP-D | OPTIMALITY_CERTIFIED / 20 |
| D1-1 | FULL, AP-D, DEP-D | INFEASIBLE_CERTIFIED / null |
| Synthetic zero-cost A CONTROL | FULL, AP-D, DEP-D | OPTIMALITY_CERTIFIED / 0 |

The final normal comparison uses **26 fresh workers, 54 recorded rounds**,
20 additional persisted feasible-certificate replays PASS, and six original
exact-empty records whose proof fields agree with reference. Exact-empty
records do not have a feasible lasso certificate and are not counted as replay
PASS. The separate zero profile uses **six fresh workers, six rounds and six
additional independent replays PASS**, with a nonempty closed suffix. There
are 59 unchanged frozen input entries in the normal profile and 61 in zero.

The retained AP-D operation counts include:

| Operation | C3-T4, six rounds | D3-1, one round |
| --- | ---: | ---: |
| Planner full TS builds / cache hits | 1 / 5 | 1 / 0 |
| Projection requests / computations | 5382 / 384 | 11 / 2 |
| Witness-key requests / computations | 3531 / 757 | 14 / 3 |
| Exact-cost requests / direct reuses | 5852 / 5852 | 23 / 23 |
| Suffix graph requests / materializations / full source scans | 6 / 6 / 6 | 3 / 2 / 1 |

These are operation counts, not distinct experiment attempts or memory
measurements. The small qualification does not establish a general speedup.

C3-T4/AP-D and D3-1/AP-D retain the published compact-cost V12's exact lasso,
normalized scientific rounds, and all build/search counters after removing
only timing and execution-identity metadata. FULL/DEP-D's construction counters
confirm the original per-round build policy.

## Transport, failure and publication results

| Check | Observed result |
| --- | --- |
| Unified worker lifecycle | All 10 checks PASS: four late phases and crash/missing/malformed/crash-after-result on A/FULL, plus AP-D/DEP-D late-solver checks |
| Deadline boundaries | 11 deterministic checks PASS, using explicitly simulated timestamps; no new workers |
| Feedback regressions | Six checks PASS, including two real DDS zero-cost/repeated-entry fixtures rejecting replayed feedback and accepting fresh feedback |
| Unified DDS | Eight cases PASS: C3 across all methods, D1 exact empty, A late delivery/crash/server error, and synthetic zero/FULL; four additional feasible-certificate replays PASS |
| Scientific publication/restore | Three C3 methods and D1 exact empty commit/restore; simulated late delivery and both real watchdog TIMEOUTs commit/restore; crash refused before publication |
| Publication/restore negatives | Six controls reject wrong rehashed objective, rehashed corrupt certificate, stale version, partial files, incomplete-dispatch retry and rehashed stale-version restore; zero new method workers |
| Offline analysis/ledger | 510 synthetic rows/commits and 16 tables PASS; zero real results or planner/provider/DDS calls |

Every successful DDS action sequence and feedback progression is checked by the
original transport validator. Non-executable terminals issue no actions or
snapshots. Wrong-generation observations remain rejected. The zero-cost DDS
case is synthetic; the feedback fixtures are transport controls, not Core data.

The controller phase uses eight actual child attempts: four normal cases and
four fault cases. Seven scientific terminal records commit and restore with
zero resumed workers; the infrastructure crash retains its dispatch and is
refused publication. The three optimal records each pass the frozen independent
certificate gate on publication and restoration. Negative-control copies are
kept separate and are not counted as fresh worker attempts.

| Real watchdog branch | Child exit | Delivered `T_total` s | Actual harness wall s | Terminal |
| --- | ---: | ---: | ---: | --- |
| Ignores SIGTERM, needs SIGKILL | -9 | 204.738646301 | 205.037224502 | Right-censored TIMEOUT |
| Exits zero on SIGTERM | 0 | 204.072698493 | 204.410109291 | Right-censored TIMEOUT |

Both retain the actual 195-second watchdog wait. Cleanup, source checks and
delivery explain elapsed times above 195 seconds; these are censored lower
bounds, not exact solver completion times. Clock-offset late-phase tests are
explicitly simulated and are not pooled with these wall-time observations.

The [evidence index](evidence/20261025/index.json) links the complete final,
historical and interrupted namespaces, source snapshots, helpers, certificates,
negative controls and readbacks. The
[scientific readback](evidence/20261025/root_scientific_readback.json) uses only
standard-library file/hash inspection, verifies the two source closures and
frozen inputs, and starts no planner, verifier or DDS process. Independent ZIP
member/Git-blob [readback](evidence/20261025/root_archive_readback.json) checks
all 2,445 archived members against their original files and seven Git blobs.
Archive SHA256: `9dab345be4722a3e711bdc4c7d52d09f3e196043f573f5da34568cffadbd111f`.
Runtime import provenance confirms Humble and the selected source checkout.

This establishes bounded qualification of the explicitly selectable unified
candidate. It does not promote a default, authorize the frozen formal driver,
or execute the real 170-by-three-method campaign.

## Retained interruption and qualification repairs

The initial source `44a542e741b0dda258364ffe3ec27ab4d799852a` was interrupted
after six A results and their additional replays; a B/FULL reference dispatch
had no exit code or result. Its original RUNNING report and every raw file are
preserved. No TIMEOUT or PASS was invented for that incomplete attempt.
A new namespace verified and carried the six completed A directories byte for
byte, then completed the remaining 20 workers. All source44 normal and zero
checks passed under their original identities.

That source's lifecycle qualification exposed five failed phase-injection
checks: the instrumented `run_one` had private copied globals, while the test
hook changed the module's clock/callback attributes. The offsets therefore
never reached the intended phases. The correction binds the test clock and
phase wrappers in `run_one.__globals__`, preserving the instrumented certificate
function and original bytecode. Only `lifecycle.py` changed between source44
and the final source above. No solver, budget, deadline predicate or scientific
acceptance rule was changed. All final method and lifecycle checks were rerun
under the new binding; the old successful and failed records were not relabeled.

The first final-source offline launcher passed a string where its CLI normally
provides a Path and failed before analysis. The external launcher was corrected
without changing runtime sources. Only that check was retried, in a fresh
`offline_recovery` directory; all 510 synthetic rows/ledger commits and 16 tables
passed with zero planner/provider/DDS calls. The first directory, log and exit
code remain. Exact qualified source snapshots and commits are retained; not
every intermediate development-helper revision was archived.

The first Windows UNC packaging pass failed while reading a pytest symbolic
link as a regular file. Its partial package is retained outside the repository.
Final packaging records the link and independently verifies its target through
WSL; this recovery changes no runtime source or result.

## Entry

Use the qualified WSL Humble/message overlay and prepend this clean checkout's
packages to the sourced `PYTHONPATH`. Preserve the ROS paths. Bind the matching
frozen authority receipt and formal kernel. Use fresh `/tmp` namespaces.

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/ltl_automaton_execution:$PWD/ltl_automaton_planner:$PWD/ltl_automaton_planner_core:$PWD:$kernel:$PYTHONPATH"

python3 -B -m experiments.cmr_ros2_unified_v12.runner \
  --prepare --profile main --binding "$receipt" --kernel-root "$kernel" \
  --output /tmp/<fresh-qualification>

python3 -B -m experiments.cmr_ros2_unified_v12.runner \
  --backend ros2-v12 --instance-id C3-T4 --method DEP-D \
  --plan /tmp/<fresh-qualification>/plan.json \
  --binding "$receipt" --kernel-root "$kernel" \
  --output /tmp/<fresh-single-attempt>
```

Backend selection is explicit; unknown backends or cells are rejected. The
qualification plan is deliberately limited to the cells above. It cannot
authorize a formal campaign or arbitrary new population by editing a selector.
Omitting `--backend` executes the fixed two-arm qualification matrix, once per
cell/backend, with immutable dispatch markers. A new formal population requires
its own reviewed execution binding. This entry does not switch any default.
