# AP full reachable TS reuse prototype

This opt-in V8 experiment removes repeated construction of the full reachable
transition system within **one AP-D method invocation**. It starts from preserved
V7 commit `5ac80ee5f8e622a7f929eb848627c9a5ebf6cf01`; the initial implementation
executed for qualification is `db8236614c8ce4c876844127c8ce9df01c5d8507`.
The subsequent entry-timing qualification below uses
`eb5e6896c763559def6ac65641bb902592dd9eda` with a separate binding.

V7's P2f loop calls the V6 builder in every refinement round. That builder
recomputes `_reachable_full_ts(model)` before applying the new precision. The
reachable full states and edges depend on the static model and its initial
states, not on `S_k`. V8 constructs their immutable tuples once, then reuses them.
Projection, witness buckets, label consistency checks, reduction, Product and
the local Buchi successor cache are regenerated each round. Search stays V7;
the original loop, local method and global frozen builder code are preserved.

The context belongs to one invocation of `run_method_local`, is matched by model
object identity, and is cleared in `finally`. Different models/initial states,
methods and attempts cannot share it. FULL and DEP-D retain the V7 build path.
Only the bound static CMR models with pure action callbacks are in scope; this
does not add a cache to dynamic ROS transition-system updates. Failed full-TS
construction stores no partial cache. Metrics record actual construction/hit
counts, including failures; `T_full_ts` measures construction or lookup time.

V7's old binding promises a full rebuild every round, so it is unchanged.
This comparison has its own policy and binding:

- `CMR_AP_TS_REUSE_V1-b4c2588536755eb8`
- Binding SHA256: `ab54aec5040871f827df41363cc555f3985269fa3d1f1f392705b818427e7e1a`
- V8 backend SHA256: `279d27caa719b0fc0d0987556f50625486f5b3faced12a2aa42e5d81e193e5c9`

## One C3-T4/AP-D attempt per backend

The fixed regression uses the previously observed six-round AP case, outside
the formal ledger. It makes no population or outcome-blind selection claim.

| Backend | Exact objective | Full TS time, all rounds | Measured full TS builds / hits | Complete `T_total` | Independent replay |
| --- | ---: | ---: | --- | ---: | --- |
| Original solver | 12 | 0.048433800 s | Not instrumented | 1.166676500 s | PASS |
| Unchanged V7 | 12 | 0.042379100 s | 6 / 0 | 1.051325999 s | PASS |
| Candidate V8 | 12 | 0.011731300 s | 1 / 5 | 1.325302000 s | PASS |

All six refinements, initial precision `[3]`, final precision `[0,1,2,3,4,5]`,
the complete V7/V8 scientific round/search traces and concrete lasso agree.
The full source has **64 reachable states / 384 edges**. All three persisted
certificates pass additional independent replay. Three worker-internal
certificate checks are identified from the frozen P2f code and the three raw
certified rows; the readback does not invoke a verifier again.

The repeated-build problem is removed: **6 builds become 1**, and observed
full-TS time decreases **72.32%**. Complete runtime instead **increases 26.06%**
in this observation. The phase differences V8 minus V7 include `T_other`
`+149.27 ms`, certification `+50.86 ms`, preprocessing `+46.17 ms`, and search
`+42.44 ms`, against `T_full_ts -30.65 ms`. These timings identify where the
observed difference was charged; a single run cannot establish its cause or
stability. This candidate is **not adopted as an overall speedup or default**.
There was no rerun to seek a better timing result.

## Entry timing diagnosis and bounded optimization (2026-10-13)

The historical increase is mostly outside the core method: old V8's core
`T_other` is **6.2912 ms**, while result delivery adds **489.4769 ms**, producing
final `T_other = 495.7746 ms`. Old V7 delivery is 339.1702 ms. The old entry calls
`describe -> load_binding -> source_closure / implementations` repeatedly and
constructs a schema once in the worker and twice in the parent. It also reloads
the complete plan after worker publication. A read-only mirror of one parent
path measures 58.44 ms for `describe`, 117.25 ms for two schema constructions,
and about 178 ms overall. This probe runs no solver; its nested cumulative
times must not be added, and it does not explain every historical delivery ms.

The new entry keeps one verified binding/descriptor snapshot and one schema
per backend within **one parent or worker attempt**. All result validations
still run: one in the worker and two in the parent. Source closure, binding
bytes and authority receipt are checked again before publication. The new
parent check completes **before** the terminal timestamp is sampled, so its
cost is included in `T_total`, `T_other` and the original deadline decision.
The original 180/195 s predicates and process cleanup remain. Preflight,
instance loading, payload construction, certificate persistence/fsync/hash and
independent verification are executed, not cached. Diagnostics are separate
sidecars; the scientific row schema stays unchanged.

The frozen preprocessing and certificate functions were instrumented by
cloning their original bytecode. In final V8, preprocessing is 402.16 ms:
preflight 383.64 ms, instance loading 12.36 ms, payload 6.15 ms. A separate
read-only preflight probe takes 248.23 ms, with 14 `Path.resolve` calls consuming
210.93 ms inclusive and eight top-level `sha256_file` calls consuming 36.46 ms
inclusive. Hash-file/read-bytes/hash-bytes are nested; the raw profile's
24-call aggregate is not an independent 72.90 ms cost. Loading authority also
performs a preflight; this probe measures one additional explicit preflight.
These frozen path/source checks are a remaining hotspot, not a V8 TS operation.
One observation cannot establish why their latency differs between backends.

Final V8's certificate phase takes 124.58 ms: canonical record construction
67.24 ms, independent bound verification 53.23 ms, fsync 3.54 ms, certificate
hash 0.063 ms, payload 0.067 ms. Each executes once in the method's measured
scope. The additional persisted-certificate replay runs after delivery and is
outside row `T_total`; its time is retained separately. No certificate check,
source check or refinement was skipped or moved outside the method budget.

The final fresh C3-T4/AP-D comparison executes the original solver and unchanged
V7/V8 algorithms through this same new entry, once each:

| Backend | `T_total` | `T_other` | Preprocessing | Certification | Full TS | Builds / hits | Verdict / objective / replay |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Original solver | 1.054115593 s | 0.189287998 s | 0.262851898 s | 0.099672600 s | 0.043523400 s | Not instrumented | Certified / 12 / PASS |
| Unchanged V7 solver | 0.922065695 s | 0.235965099 s | 0.267243198 s | 0.104307899 s | 0.045298500 s | 6 / 0 | Certified / 12 / PASS |
| V8 TS reuse | 1.147387796 s | 0.297873699 s | 0.402160898 s | 0.124583900 s | 0.009999200 s | 1 / 5 | Certified / 12 / PASS |

Old V8 to final V8 is 1.325302000 -> 1.147387796 s (**13.42% lower observed
total**), with delivery 489.48 -> 291.39 ms. Final V8 is still **24.44% slower
than concurrent V7**. The 225.32 ms difference includes preprocessing
`+134.92 ms`, `T_other +61.91 ms`, certification `+20.28 ms`, and search
`+26.11 ms`, despite full TS `-35.30 ms`. The complete V7/V8 round/search traces
and concrete lasso agree, with all six rounds and precision `[3]` ->
`[0,1,2,3,4,5]`. These single observations qualify the implementation and locate
remaining costs; they do not establish stable total speedup or default readiness.

- Final source: `eb5e6896c763559def6ac65641bb902592dd9eda`
- Binding: `CMR_AP_TS_REUSE_V1-69b63b12cd3b9632`
- Binding SHA256: `93c5c241046df1d02b92381b9c471deb447068bc87e5e2e462b21a9be643defb`
- V8 backend SHA256: `5207a536472ad501184513c50c7b80641c186af36e24edd8fbd4f7f5576a2e34`

The [entry-timing evidence](evidence/20261013_entry_timing/index.json) retains
both fresh three-worker namespaces: intermediate `111ae6c` and final `eb5e689`.
Intermediate rows pass semantic/certificate checks, but their new parent
release check occurred after the recorded timestamp and is excluded from
those reported totals; they are not the final timing claim. No dispatched
worker was repeated within its namespace. Across this task there are **6 real
workers, 6 original `run_one` calls, 6 observed method certificate checks and
6 additional independent replays**, plus nine offline entry checks and three
synthetic delivery/deadline checks. The latter show a release check crossing
180 s becomes a right-censored timeout with null objective, without a real wait.
Final standard-library readback verifies 60 sources, 56 frozen input bindings,
row/certificate hashes, complete traces, reuse counts and inclusion of the
release check in all three terminal timestamps. The available reader-helper
failure log and scripts are retained; earlier helper failures without saved
stderr are identified in the evidence's `helper_failures.json`. Readback
starts no solver or verifier.
The initial V8 evidence, preserved V7, and `00fc5a9` remain intact. There is
no default switch, PR merge, new DDS/provider run or formal campaign.

## Validation and evidence

Five native fixture groups pass: real two-precision projection, all full-edge
witness identities, independent mutable labels, fresh contexts, model/initial
isolation, exact Fraction/zero costs, rejected labels, failed construction and
failed-reduction accounting. A builder-only fake method check shows both AP
invocations start cold and FULL/DEP-D rebuild each round; it invokes no solver.
Its initial missing-kernel and two incomplete-helper failures are retained.

The [evidence index](evidence/20261013/index.json) records **3 real process
workers / 3 original `run_one` calls / 3 additional optimal-certificate replays**.
The standard-library readback checks 60 frozen/live source files, unchanged
56 input bindings, exact row/request identities, result and certificate hashes,
complete round/search equivalence and actual reuse counters. It starts no
worker, solver or verifier. The original persisted result rows have no peak
memory field, so no memory improvement is claimed.

The exact objective `prefix + 10*suffix`, nonempty accepting suffix,
INITIAL_LABEL_V1, tracemalloc, complete refinement and **180 s method / 195 s
watchdog** acceptance remain. The first full TS is constructed inside the method
budget; no preprocessing is moved outside it. Default selection, original V7
bindings/results, `00fc5a9`, PRs and the formal batch remain unchanged. This phase
does not qualify V8 DDS or the complete formal Campaign chain.

## Reproduce the bounded comparison

Use the existing WSL Humble/message overlay and the qualified source import
paths. Prepend this checkout's packages to the sourced `PYTHONPATH`; retain ROS
paths. Choose a fresh output directory; dispatch markers prevent repetition.

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/ltl_automaton_execution:$PWD/ltl_automaton_planner:$PWD/ltl_automaton_planner_core:$PWD:$PYTHONPATH"
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_v8_ap_ts_reuse_fresh
python3 -B experiments/cmr_ros2_ap_ts_reuse/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_ap_ts_reuse/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```
