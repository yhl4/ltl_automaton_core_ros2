# V11: solve-local exact Fraction reuse

This optional AP-D prototype starts from V10 publication
`f4a31b1b85d2efdb6a86d3df4fa9f21fa2b22640`. It retains V10 suffix acceptance
graph reuse, V9 projection and witness-key reuse, and one full reachable TS
construction per AP-D invocation. The default backend is unchanged.

## Measured motivation and change

A directed profile of the frozen V10 source
`7a3ddc1d0b8ed22fb75c069085b8ffa3ff357ffc` built C3-T4 at full precision and
ran one abstract solve. With cProfile and tracemalloc enabled, that solve took
0.130671 s, processed 1792 Product transitions and called `_base._exact` 2179
times. The edge-row builder accumulated 0.048252 s; `_exact` accumulated
0.024723 s. These nested profile times overlap and must not be added. This
diagnostic is not a complete AP-D run, a certificate validation, or a timing
comparison with V11.

The original converter imports the qualified `exact_cost` and constructs a
Fraction even when its input is already an exact built-in Fraction. V11 returns
that existing value only when `type(value) is Fraction`. All other values use
the unchanged converter, including integers, Fraction/int subclasses, bools,
floats, Decimal and None. This is a value fast path, not an edge-identity cache;
there is no stale cost lookup and no global monkeypatch.

Private function clones apply the same converter to edge costs, normalized
witness keys and decoded prefix/suffix checks. Negative edge rejection remains
in place. Canonical ordering, original witness objects, integer/Fraction exact
arithmetic, nonaccepting loop entries and nonempty accepting closed suffixes
are preserved. Distances, entries and solutions are not cached.

INITIAL_LABEL_V1, `prefix_cost + 10*suffix_cost`, complete refinement,
tracemalloc, **180 s method / 195 s watchdog**, original certificate
persistence/fsync/hash/independent verification, and the charged final release
check remain unchanged. The V10 control uses the same observation wrapper but
delegates every conversion to its original converter; it is a counter-equipped
control rather than the historical uninstrumented timing path.

## Directed validation

Nine compact cases compare V10 and V11 results, exact objectives, original
witness/edge identities and all search work except the new `exact_cost_*`
counters. Cases cover nonaccepting entries, zero self-loops/cycles, parallel
witnesses and ties, multiple SCCs/initial states, a loose first bound and
accepting entries without self-loops. Converter checks cover zero, rational and
large values, subclass fallback, invalid-type rejection, negative edge costs
and malformed float witness costs. Separate counters distinguish conversion
requests, exact Fraction reuses and original-converter fallbacks.

The real comparison keeps the same preselected C3-T4, D3-1 and D3-2 AP-D cells
as V10, with one fresh worker per original solver/V10/V11 combination. No
instance is selected or removed based on a candidate outcome. No DDS/provider
calls or formal campaign are part of this experiment.

## Qualification results

Executed source: `e5ff91294b373a1f33e7ae9458641e4a2200ab56`. Independent binding:
`CMR_EXACT_COST_REUSE_V1-d7ddeec3931b21e0`, SHA256
`c68af7a505b584e645025581428ac10619680069b2ddda1ea2f900c87271eebd`.
V11 backend SHA256:
`35838cf764a85cd04e3376825d1f807bbb458bb2c39418046bd2f2624abb9cd4`.
The binding includes 73 source files and 57 frozen inputs. All previous 69
source files and the V10 component identity are unchanged; four V11 files
were added.
Counters cover the substituted search conversion sites only; Fraction
construction in other arithmetic, model loading and verification still runs.

| AP-D instance | Exact objective, all backends | Conversion requests per ROS2 backend | Original conversions V10 / V11 | V11 exact Fraction reuses |
| --- | ---: | ---: | ---: | ---: |
| C3-T4 | 12 | 5852 | 5852 / 0 | 5852 |
| D3-1 | 20 | 23 | 23 / 0 | 23 |
| D3-2 | 20 | 14 | 14 / 0 | 14 |

| AP-D instance | Reference total (s) | V10 total (s) | V11 total (s) | V10 search (s) | V11 search (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| C3-T4 | 1.820352 | 1.477440 | 1.617667 | 0.136800 | 0.111782 |
| D3-1 | 1.166937 | 1.131895 | 1.174660 | 0.002612 | 0.002353 |
| D3-2 | 1.013304 | 1.277144 | 1.177149 | 0.002534 | 0.003069 |

These are single sequential observations per cell/backend, with the original
charged method `T_total` including preprocessing, acceptance and release checks.
C3-T4 search falls 18.29%, while its total increases 9.49%. Its preprocessing
changes from 0.702039 to 0.789250 s, certification from 0.201803 to 0.217745 s,
and `T_other` from 0.338375 to 0.380322 s. D3-1 total also increases; D3-2 total
decreases even though its search increases. The supported result is removal of
redundant exact-cost reconstruction, not a general search or total speedup.
No unfavorable observation was discarded or rerun.

All nine workers return uncensored `OPTIMALITY_CERTIFIED` results with objectives
matching the original solver. All nine additional independent certificate
replays pass. There are six recorded rounds per C3-T4 backend and one per D3
backend, 24 rounds across nine attempts. V10 and V11 have identical concrete
lassos, normalized rounds and all build/search work except the new cost counters.
The C3-T4 full TS remains one build plus five hits. Each D3 method builds it
once. Suffix construction remains six materializations/scans across C3's six
solves, and two materializations plus one reuse and one source-edge scan in
each D3 solve. All workers exit with code 0 and leave no live worker after cleanup.

The [evidence index](evidence/20261023/index.json) retains the complete namespace,
source snapshots, original certificates, replay records, input hashes, diagnostic
profile, scripts/logs, and the root's independent readback. Failed development
preparations are retained with their limits: the first profile failed before
solving because its kernel path was missing; an early fixture assertion selected
an integer-only case; a native Windows entry check rejected its WSL-shaped source
map before dispatch. WSL is the qualified entry environment. The exact precommit
failed fixture source was not retained. Aggregate synthetic fixture calls are
unknown, separate from one successful directed profile solve and nine real CMR
workers. Readback runs no solver or verifier. No default switch, PR merge, DDS
test, provider call or formal batch was performed.

## Reproduction

Use a clean source checkout with the existing WSL Humble/message overlay and
choose a new output namespace. A dispatched namespace must not be reused.

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/ltl_automaton_execution:$PWD/ltl_automaton_planner:$PWD/ltl_automaton_planner_core:$PWD:$PYTHONPATH"
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_v11_exact_cost_fresh
python3 -B experiments/cmr_ros2_exact_cost_reuse/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_exact_cost_reuse/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```
