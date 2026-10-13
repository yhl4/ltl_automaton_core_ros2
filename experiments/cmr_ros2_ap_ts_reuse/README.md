# AP full reachable TS reuse prototype

This opt-in V8 experiment removes repeated construction of the full reachable
transition system within **one AP-D method invocation**. It starts from preserved
V7 commit `5ac80ee5f8e622a7f929eb848627c9a5ebf6cf01`; the implementation executed
for qualification is `db8236614c8ce4c876844127c8ce9df01c5d8507`.

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
