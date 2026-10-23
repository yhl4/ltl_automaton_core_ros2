# V12: scalar compact weights before parallel-arc comparison

This optional AP-D experiment starts from V11 publication
`8cfb6bdf28496b3bc242402f973a17d258781543`. It retains V11 exact Fraction reuse,
V10 suffix acceptance graph reuse, V9 projection/witness reuse and one full
reachable TS build per AP-D invocation. No default backend is changed.

## Change

V7 originally builds its compact graph using exact Fraction costs, selects the
minimum parallel arc, then converts denominator-one selected graph weights to
Python integers. V12 moves that conversion before graph insertion and parallel
arc comparison. Nonintegral costs stay Fraction values, integers retain arbitrary
precision, and original abstract edges and witness objects are untouched.

Row order, node/adjacency/predecessor order, strict `<` replacement and first-edge
tie selection remain. Final graph weights and the original integer/fractional
edge counters match V11. New counters record rows, early scalarizations and
actual duplicate-arc comparisons. The V11 control uses the same observed loop
with conversion after graph construction; it is a counter-equipped control.

The original exact search, pruning, accepting/nonaccepting loop entries,
nonempty closed suffix, complete refinement, INITIAL_LABEL_V1,
`prefix_cost + 10*suffix_cost`, tracemalloc, **180 s method / 195 s watchdog**
and certificate persistence/fsync/hash/independent acceptance remain unchanged.

## Preflight diagnosis

A separate cProfile run of one original loaded V11 `preflight` measured
1.484309 s. Its 14 fresh `Path.resolve` calls accumulated 1.320704 s, including
154 `lstat` calls accumulating 1.110682 s; the eight SHA256 file checks
accumulated 0.161771 s. These nested times overlap. This is one diagnostic
observation on WSL-mounted authority paths, not an AP-D timing or a speedup.

V12 leaves preflight unchanged: all eight source hashes and all fresh module,
path and function identity checks still run. No resolved-path result is cached
across those checks or between attempts. The profile identifies remaining
filesystem overhead; this search change does not claim to fix it.

## Directed validation

A direct graph comparison covers parallel minima, equal ties, zero, values
above `2**80` and nonintegral Fraction costs. It checks graph order, weights,
selected original edge identities and the existing edge-type counters.
Nine compact search cases compare V11, observed control and V12 result paths,
exact costs, witness identities and all work except `compact_cost_*` counters.

The real comparison keeps the same C3-T4, D3-1 and D3-2 AP-D cells as V11,
with one fresh worker per original solver/V11/V12 combination. Selection,
budgets and certificate acceptance are fixed before candidate outcomes.

## Results and retained interruption

Executed source: `3cd0d168a8a93f441cd195e6fa9743cb6d213218`. Binding:
`CMR_COMPACT_COST_V1-067a6c2cae141886`, SHA256
`f276393f9d9ed39439b1ab693d14f304a3af300fc8f20aba4ebaf0f5312986e7`.
V12 backend SHA256:
`10f0c455ab1088e6ac702268489b96c5f26ffd84308987a7eef69555f7a190ee`.
All previous 73 source files and the V11 identity remain unchanged; the new
binding covers 77 source files and 57 frozen inputs.

| AP-D instance | Exact objective, all backends | Rows per ROS2 solve sequence | V12 early scalarizations | Duplicate-arc comparisons, both ROS2 arms |
| --- | ---: | ---: | ---: | ---: |
| C3-T4 | 12 | 3531 | 3531 | 506 |
| D3-1 | 20 | 14 | 8 | 0 |
| D3-2 | 20 | 6 | 6 | 0 |

The completed qualification is one sequential observation per cell/backend:

| AP-D instance | Reference total (s) | V11 total (s) | V12 total (s) | V11 search (s) | V12 search (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| C3-T4 | 1.531525 | 0.909437 | 0.877666 | 0.105577 | 0.096945 |
| D3-1 | 0.587272 | 0.725102 | 0.616009 | 0.002967 | 0.002237 |
| D3-2 | 0.933349 | 0.791255 | 0.645804 | 0.002520 | 0.001520 |

These are original charged method totals, with preprocessing, certificate
acceptance and final release checks included. The D3 controls have no duplicate
arcs; their timing changes do not establish a benefit from cheaper parallel-arc
comparison. C3's 506 comparisons use integer-valued weights after scalarization.
No general search or end-to-end speedup is established by these small timings.

The first namespace was interrupted after six workers had delivered results
and five additional replays had returned PASS. No matching qualification
process remained and no overall exit code had been written; the exact cause
was not established. Its sixth additional replay is incomplete, not a PASS.
The original `RUNNING` report and all six rows are retained unchanged. That
wave's C3-T4 V11/V12 search times were **0.105599/0.111312 s**, and totals were
**1.569238/1.615033 s**, including the unfavorable V12 observation.

The recovery used the identical source, cells, budgets and acceptance rules in
a fresh `_r2` namespace, with a detached supervisor. It did not resume or repeat
dispatches inside the interrupted namespace. All nine recovery workers exit 0,
leave no live workers, return uncensored `OPTIMALITY_CERTIFIED` results and pass
all nine additional independent persisted-certificate replays. Recovery has
24 recorded rounds; the interrupted wave has 21 rounds across six results.
Across both waves, 15 workers delivered results and 14 additional replays have
recorded PASS, with one interrupted replay left unclassified.

V11 and V12 recovery lassos, normalized rounds and all work except the new
compact-cost counters are identical. V11 exact-cost reuses stay 5852/23/14.
Full TS construction remains one build plus five hits for C3, and one build
for each D3 method. Suffix materializations/scans remain 6/6 across C3's six
solves and 2/1 in each D3 solve. D3-1 retains its nonintegral Fraction weights.

The [evidence index](evidence/20261023/index.json) binds both namespaces,
certificates/replay records, source snapshots, profile, scripts/logs and the
root readback. Early shell setup and incorrect-working-directory import guards
failed before prepare/worker dispatch and were corrected without changing
source identities. A directed fixture initially exposed a wrong integer-edge
counter classification; its failed result is retained. Exact failed script and
fixture revisions were not all retained. Synthetic fixture call totals are
unknown; the separate preflight profile ran no solver. No DDS/provider calls,
default switch, PR merge or formal batch occurred.

## Reproduction

Use a clean checkout, the existing WSL Humble/message overlay and a fresh output
namespace. Do not repeat a dispatched namespace.

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/ltl_automaton_execution:$PWD/ltl_automaton_planner:$PWD/ltl_automaton_planner_core:$PWD:$PYTHONPATH"
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_v12_compact_cost_fresh
python3 -B experiments/cmr_ros2_compact_cost/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_compact_cost/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```
