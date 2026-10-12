# CMR selectable reference / ROS2 V6 backend

**Current interface: V2.** The three default-qualification prerequisites have
passed; see [V6 default qualification](README_acceptance.md) and the current
[`acceptance_binding.json`](acceptance_binding.json). The V1 results and binding
below are immutable historical evidence. Current code rejects stale V1
bindings; reproduce V1 from commit `a920af8d3930637c304533f3f77f595a0c5f20ab`.
V2 accepts the original 12-cell qualification plan or the new 15-cell plan;
both keep formal execution disabled. The existing formal default is unchanged.

CMR now has one explicit backend interface: `reference` or `ros2-v6`.
`backends.configure(fresh_bound_runner, backend, version_binding_path)` selects
the implementation; `runner.py --backend ...` provides the same bounded worker
and result path. DDS requests use this worker API and carry the selected backend
and independent version binding. There is no automatic fallback.

The backend registry is independent of instance selection. This qualification's
execution plan deliberately permits only the 12 cells below; it cannot launch
the formal 170 × 3 campaign. The existing formal runner and production ROS2
planner retain their defaults. CMR initialization, refinement, concretization
and independent verifier still come from the bound original kernel.

## Independent version binding

[`backend_binding.json`](backend_binding.json) is a separate, canonical version
record, with ID `CMR_UNIFIED_BACKENDS_V1-491909e686b46c61` and file SHA256
`273bb7c1752cd2e5302dd778927e76bff22d78877183a29d729c9b9b0ad668c8`.
It binds both algorithm IDs/SHAs, the complete qualified V6 source lineage,
the common selector/worker, original receipt/binding/manifest authority,
INITIAL_LABEL_V1, methods, full rebuild and 180/195 s budgets. Unknown names,
stale hashes, substituted algorithms and changed contracts fail closed.

V6's algorithm ID remains `ROS2-DISCRETE-PLAN-CMR-PRODUCT-V6`; its algorithm SHA
is the previously qualified V6 SHA. The new interface has its own version ID,
rather than claiming that the old solver or qualification bytes changed.
Request, result and every round carry `backend`, `backend_id`, `backend_sha256`,
`version_binding_id`, `version_binding_sha256`. The execution identity binds
version-file bytes, selected cells and executed code. Original P2c schemas
change only backend SHA and schema ID; original persisted certificate format,
P2e path/byte checks and verifier remain. Certificate execution identity binds
the separate version without editing the frozen certificate contract.

## Fixed small qualification, 2026-10-12

Keep three previously qualified anchors: B-D-BRANCH-S1/FULL, C1-T1/AP-D,
D3-1/FULL. From the immutable Core170 metadata, add minimum
`(nominal_cartesian_state_count, instance_id)` B excluding the old B, C with a
different temporal family, and D declared INFEASIBLE: **B-D-CHAIN-S1**, **C1-T2**,
**D1-1**. Each new instance runs FULL/AP-D/DEP-D. Selection/source/binding and
all 12 cells are frozen before any method; historical outcomes do not select
the extensions. One reference and one V6 worker per cell, 24 workers total.

| Instance / method | Exact objective, both arms | Reference total seconds | V6 total seconds | Build rounds ref / V6 |
| --- | ---: | ---: | ---: | ---: |
| B-D-BRANCH-S1 / FULL | 15 | 1.169437561 | 1.008087230 | 1 / 1 |
| C1-T1 / AP-D | 13 | 0.780417005 | 0.856721304 | 6 / 6 |
| D3-1 / FULL | 20 | 0.502626002 | 0.616861102 | 1 / 1 |
| B-D-CHAIN-S1 / FULL | 15 | 1.450930505 | 1.607757884 | 1 / 1 |
| B-D-CHAIN-S1 / AP-D | 15 | 1.146459506 | 1.029749606 | 4 / 4 |
| B-D-CHAIN-S1 / DEP-D | 15 | 0.740500904 | 0.770590871 | 1 / 1 |
| C1-T2 / FULL | 13 | 0.725896403 | 0.721219602 | 1 / 1 |
| C1-T2 / AP-D | 13 | 0.988904906 | 0.902131106 | 5 / 5 |
| C1-T2 / DEP-D | 13 | 0.924219305 | 0.884239304 | 4 / 4 |
| D1-1 / FULL | INFEASIBLE, objective null | 0.485468203 | 0.589909602 | 1 / 1 |
| D1-1 / AP-D | INFEASIBLE, objective null | 0.509868002 | 0.589082703 | 1 / 1 |
| D1-1 / DEP-D | INFEASIBLE, objective null | 0.468641302 | 0.629336603 | 1 / 1 |

All 12 pairs agree on certified verdict, exact objective and original initial
precision. The feasible 18 method certificates independently replay PASS.
Six method infeasible outcomes retain original `REDUCED_PRODUCT_EXACT_EMPTY`
proof metadata and match the reference; the original runner does not write
feasible-lasso certificates for these outcomes, so their replay is
NOT_APPLICABLE. No new infeasibility certificate rule is introduced.

These are single observations. V6 is faster in some cells and slower in others;
all values are retained, without performance selection or a general speed claim.
The complete method still includes input/initialization, all rebuild/refinement
rounds, certification, logging and delivery. Worker startup and preflight precede
the original method start. Full reachable TS/reduction/Product is rebuilt every
round, with V6's cache local to each build. Fraction costs, initial/successor
labels, gamma 10, nonempty accepting suffix, tracemalloc, actual 180 s deadline,
195 s watchdog and right-censored timeout handling remain original behavior.

## Actual DDS request and execution

Two fresh V6 workers start only after real DDS requests on localhost domain 219.
Reliable String request/result topics remain `/cmr_smoke/request` and
`/cmr_smoke/result`; observation/snapshot/TS interfaces reuse the existing
execution manager and independent FakeStateObserver/abstraction feedback.
The envelope is the common worker request plus `request_id`, including exact
backend/version/execution identities. No precomputed result is substituted.

- **C1-T1/AP-D:** objective 13, independent certificate replay PASS; execute
  `change_robot_location`, `change_gripper_state`, `change_object_location`,
  `wait`: complete three-step prefix plus one closed suffix. Dispatch,
  completion, observer, abstraction and TS feedback each occur four times;
  terminal observation is step 4 with no action.
- **D1-1/FULL:** INFEASIBLE_CERTIFIED, original exact-empty fields, null objective
  and no executable lasso. Zero dispatch, completion, observation/TS feedback
  and no execution snapshot. Feasible-certificate replay remains NOT_APPLICABLE.

The original driver deliberately injects generation 0 after the first accepted
generation-1 dispatch. That old observation is received and ignored: accepted
steps remain 0–4 and dispatches remain uniquely 0–3. Symbolic/FakePlant execution
is verified; this is not hardware execution. DDS discovery/execution windows
(205 s child / 210 s collection) are separate from original method budgets.

The initial new validator incorrectly rejected every received observation with
generation != 1, falsely failing the successful DDS case. The original
`qualification.json` and `dds_report.json` remain FAILED and driver/WSL rc1;
the infeasible case and all 26 workers/four DDS nodes had already exited 0.
Only `_validate_case` assertions were corrected to the existing stale-ignore
rule. An AST check proves all transport/worker code unchanged; original events
and the one pending feasible certificate were replayed, with **zero additional
solver workers or DDS runs**. Supplemental `qualified_replay.json` is PASSED;
the original failure is not overwritten. Current reproducible source contains
the corrected validator. [Correction record](evidence/20261012/validation_correction.json).

Sixteen offline binding/request/schema/configuration checks pass without planner
or DDS calls. Across methods and DDS there are **26 workers, 61 build rounds,
19 independently replayed feasible certificates and seven exact-empty outcomes**.
A standard-library Windows reader verifies hashes/source imports, requests,
version binding, exact lassos, schemas, budgets, rebuild/cache counters, actual
DDS feedback/stale-ignore behavior, retained failure and validator-only AST
change. All 58 frozen inputs remain unchanged. Corrective replay and native
reader rc0; original driver rc1 is retained. [Complete raw evidence](evidence/20261012/index.json).

## Run / reproduce

Use the qualified WSL ROS2 Humble environment and matching external frozen CMR
receipt/kernel/benchmark. From the repository root, choose a fresh output:

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_unified_fresh
python3 -B experiments/cmr_ros2_backend/qualification.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_backend/fixtures.py --plan "$out/plan.json" --binding "$receipt" --kernel-root "$kernel" --output "$out/fixtures.json"
```

Select either backend for **one permitted cell**, through the same entry:

```bash
python3 -B experiments/cmr_ros2_backend/runner.py --backend ros2-v6 \
  --instance-id B-D-CHAIN-S1 --method FULL \
  --binding "$receipt" --kernel-root "$kernel" \
  --version-binding "$out/backend_binding.json" --plan "$out/plan.json" \
  --output "$out/single_v6"
# Use --backend reference and a different fresh output for the original solver.
```

To reproduce the fixed 24-method/two-DDS qualification, use
`python3 -B experiments/cmr_ros2_backend/qualification.py --binding "$receipt" --kernel-root "$kernel" --output "$out"`.
For independent Windows read-back, use
`python -B experiments/cmr_ros2_backend/readback.py --output PATH`, where PATH
is the actual `\\wsl.localhost\Ubuntu-22.04-D\tmp\...` output.

No formal campaign, provider calls, physical robot, production-default switch
or historical 136/754-test reruns were started. A future formal switch requires
its own authorized execution binding; this optional backend and subset evidence
do not change the existing frozen campaign.
