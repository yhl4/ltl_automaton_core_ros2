# V6 default qualification — 2026-10-12

The three requested prerequisites pass: unified-entry failure handling, a fixed
small real-instance comparison, and offline formal runner/result-chain checks.
V6 is eligible to be the default backend of the **next separately bound CMR
version**. The existing frozen campaign and its default remain unchanged.
No formal 170 × 3 campaign was run. This qualification makes no general speedup
claim and does not establish hardware execution.

The current independent record is [`acceptance_binding.json`](acceptance_binding.json):
`CMR_UNIFIED_BACKENDS_V2-fa29b6da9213da25`, SHA256
`b61af330bed131b875661f66952526e1ab8263b05582314f3616598c13e9dc3a`.
V6's algorithm ID/SHA and complete previously qualified builder/search lineage
are unchanged. INITIAL_LABEL_V1, exact `prefix + 10*suffix`, a nonempty accepting
suffix, full rebuild/refinement, 180 s method budget, 195 s watchdog and original
certificate acceptance rules remain.

This binding is qualification-only. Setting the default for a new formal run
requires its own execution binding/configuration; old results cannot be
relabeled as V6. `reference` remains available explicitly. The unified CLI
continues to require an explicit `--backend`.

## Real instances

Selection was frozen before execution using immutable metadata: minimum
`(Cartesian size, ID)` A and EXT, the next B-D-BRANCH scale S2, and C2/T3 plus
C3/T4 to expand worlds and temporal families. The instances are
**A-T1-M0-A-S-BRANCH, EXT-L2L-G01, B-D-BRANCH-S2, C2-T3, C3-T4**.
B S2 has 1024 nominal Cartesian states, four times S1's 256. C's frozen worlds
all have 64 nominal states; these two choices expand structure, not scale.

Each runs FULL/AP-D/DEP-D with one fresh reference and one fresh V6 worker:
**15 pairs, 30 workers, 78 rebuild rounds**. All certified verdicts, original
initial precisions and exact objectives agree: A 12, EXT 11, B 15, C2 13, C3 12.
All 30 persisted feasible certificates independently replay PASS.
[Every single timing and round count](acceptance_timings.md) is retained,
including slower V6 cells. Startup/preflight precede the original method start;
all method rebuilds, refinement, certification, logging and result delivery
remain charged as before.

## Unified entry and DDS failures

Eleven offline boundary checks cover both feasible and exact-empty delivery
just before, exactly at, and after 180 s, plus original planner/watchdog/
infrastructure serialization. Four real-worker phase faults exercise late
solver completion, certificate verification, logging and delivery. They use
explicitly labeled offset clocks to test the unchanged deadline predicates;
their elapsed values are **simulated**, not runtime measurements.

Five further paths exercise crash, missing result, malformed JSON, crash after
writing a certified result, and an uncooperative worker. The actual watchdog
uses the unchanged 195 s wait, then SIGTERM/SIGKILL and reaps the worker. Final
observed elapsed after cleanup, source verification and delivery is
**205.525632222 s**, retained as right-censored TIMEOUT; overall harness wall
time is 206.274735121 s. No timeout is reported as an exact completion at 195 s.

The unified entry now serializes pre-deadline worker/transport failures using
the original INFRASTRUCTURE_FAILURE rule. Nonzero exit, missing/malformed
result, wrong provenance or wrong result hash cannot authorize a certificate.
Raw worker bytes are retained. Timeout clears the objective, proof claims,
certificate authority and executable lasso; infrastructure failures remain
distinct from right-censored planning timeouts.

Actual localhost DDS domain 219 covers four scenarios: success, late delivery
TIMEOUT, worker crash/INFRASTRUCTURE_FAILURE, and server ERROR. Success executes
the complete selected prefix plus one closed suffix with independent TS
observer/abstraction feedback; its extra persisted certificate independently
replays PASS. All three failure scenarios have no commands, dispatch,
completion, observer/abstraction feedback or execution snapshot. The timeout
driver's deliberately late TS message is received and ignored.

Total accepted evidence is **31 independently replayed feasible certificates
and 79 rebuild rounds** across the paired methods and successful DDS case.
Discarded late/crashed certificate attempts are preserved and excluded from
this count. Prior V1 exact-empty qualification remains separate; no new
infeasibility certificate rule is introduced. All 60 frozen inputs match and
final `/proc` readback finds no owned workers or DDS nodes remaining.

## Formal runner/result-chain offline checks

Frozen Core170 metadata maps to exactly 510 unique ordered cells,
FULL/AP-D/DEP-D, each with denominator 170. A clearly labeled synthetic 510-row
fixture passes the frozen analysis program's validation-only path and produces
16 tables. Original schemas change only their backend SHA binding; source
files remain untouched. Duplicate commits, interrupted attempts, stale
identities, wrong cell/payload and corrupt round/ledger provenance are rejected.
Synthetic rows stay outside real scientific results.

The original P2c checked-record, publication and receipt methods also replay
two genuine V6 feasible rows and one TIMEOUT row. The R2 nested checked wrapper
uses its **original code object**, with only its original closure values
supplied. Its independent P2e certificate gate, atomic publication, ledger
receipt and R2 restore-receipts method pass. Corrupt certificate bytes and
round backend identities are rejected. Replay trees, canonical certificates,
ten-file publications and hash receipts are retained. Global substitutions are
limited to bound identity/schema metadata and isolated paths. Full Campaign
construction and dispatch are NOT_RUN_BY_DESIGN.

## Preserved failures and narrow recovery

The first preflight passed the offline 510 checks but exposed a null phase
interval bug before any real method worker. The unified delivery wrapper now
records only the observed delivery interval without inventing solver timings;
the failed preflight/source snapshot remains archived.

The main run then passed every method pair, all four late paths, and DDS
success/timeout/server-error. Its fault harness incorrectly intercepted the
`git` command used by the original source preflight after a crash/watchdog,
so the original `acceptance.json` and lifecycle report remain FAILED.
Only two test-harness Popen forwarding guards were added; AST checks prove the
rest of the harness identical, and worker/solver/transport bytes are identical.

Six affected cases were continued under the new independent binding: five
direct failures plus DDS crash. All pass. **No successful method worker or
successful fault/DDS scenario was repeated.** Both version identities remain
on their original records; no row is relabeled. Supplemental
`qualified_recovery.json` and standard-library Windows readback are PASSED.
Offline gate startup/normalization failures and their corrected zero-worker
replays are also preserved.

[Full raw evidence, source snapshots and readback](evidence/20261012_acceptance/index.json)
bind this qualification and its retained failures.
The archive contains 796 members, 2,216,897 bytes, SHA256
`2e393d8a55c91c0eaab550f4adc355b9e3a4df9d65c5ee798a4f4bf5a82b8d92`;
every member was independently read back by size and SHA256.

## Reproduce

Use the matching external frozen CMR receipt/kernel/benchmark and the qualified
WSL Humble overlay. Choose a new output directory; the plan permits only the
15 pairs above and the four qualification DDS cases.

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_v6_acceptance_fresh
python3 -B experiments/cmr_ros2_backend/acceptance.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_backend/acceptance.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_backend/formal_gate.py --plan "$out/plan.json" --receipt "$receipt" --kernel-root "$kernel" --qualification-output "$out" --output "$out/formal_gate"
```

The archive contains `preflight_failure/`, `main/` and `recovery/`. For native
readback of these recorded original/recovery directories, run
`acceptance_readback.py --output MAIN_PATH --recovery RECOVERY_PATH`.
Fresh full reproduction uses the fixed harness and does not need the recovery
CLI; that CLI is restricted to the six failures recorded in this archive.
