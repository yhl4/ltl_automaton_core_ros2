# V10: solve-local suffix acceptance graph reuse

This optional experiment starts from V9 publication
`d3f12e932f5eb6ceda1dc42686d6fffdb2bd144e`. V9's precision projection,
witness-key normalization and one full reachable TS per AP-D invocation remain
enabled in both candidate and control. No default backend is changed.

## Reuse boundary

Each exact solve owns one `SuffixGraphContext`, bound to that solve's original
compact graph object and accepting-state set. It scans the source edge iterator
once per requested SCC, storing component edges in their original order. The
acceptance lift is materialized at most once per SCC and layer mode:
one layer for an accepting entry; two layers for a nonaccepting entry.

Later entries with the same SCC/mode reuse that graph and replace only the
dummy source's outgoing edges, in original successor order. Its incoming edges
must stay empty. Separate modes preserve the original node, successor and
predecessor order, graph sizes and exact edge weights. Failed construction
does not publish a partial graph. All context references are cleared at solve
exit, including exceptions; no graph is shared across refinements or attempts.

Each entry selected for exact suffix search still runs its own target-settled
Dijkstra and path restoration. Distances and solutions are not cached. Nonaccepting loop entries,
nonempty accepting closed suffixes, canonical parallel-edge selection, original
witness objects, exact integer/Fraction costs and `prefix + 10*suffix` remain.
INITIAL_LABEL_V1, full refinement, tracemalloc, **180 s method / 195 s watchdog**
and the original certificate persistence/fsync/hash/independent verification
are preserved. The existing guarded entry charges release checks before the
terminal timestamp and deadline decision.

## Fixed small comparison

The scope is exactly three AP-D cells, one original-solver, V9 and V10 worker
per cell, executed sequentially outside the formal ledger:

- C3-T4 is the existing six-round anchor. Its prior trace has one exact suffix
  search per round, so it checks overhead when graph reuse has no opportunity.
- D3-1 is an already observed multi-entry case. The historical V6 archive
  `experiments/cmr_ros2_product_perf/evidence/20261012/raw_attempts.zip`
  (SHA256 `fe4b6759890a4a6f8175792e8d5dab13c8d60dd37a7e56e5efe5769f01333f44`)
  records accepting entries 1 and 3, then nonaccepting entry 0 in one SCC.
- D3-2 was fixed before V10 results as the minimum `(Cartesian size, ID)`
  feasible D3/T4 metadata sibling excluding D3-1. This rule selects a two-state
  instance; it did not assume or filter on a candidate result.

V9 uses the original fresh lift builder with observation counters; V10 enables
the solve-local graph/index cache. Both retain the exact V9 witness machinery
and projection context. The independent binding hashes all new source files as
well as the unchanged V9 closure. Counters distinguish lift requests, full
materializations, graph reuses, dummy rebindings, complete source-edge scan
passes, and individual source edges actually yielded. Dummy updates are not
counted as full graph materializations.

## Qualification results

Executed source: `7a3ddc1d0b8ed22fb75c069085b8ffa3ff357ffc`, based on the
unchanged V9 publication above. Independent binding:
`CMR_SUFFIX_GRAPH_REUSE_V1-15f39035342797bd`, SHA256
`269b0487c156d2775ba76d978866dc7e3fb121aafcfdab2118c2e1acc935d392`.
The V10 backend SHA256 is
`336d2bec6b66d179a3b03eb3d68e2dc2c88304a846655a486c8c41494533dbe5`.
The binding includes 69 source files and 57 frozen inputs. All 65 V9 source
files match the previous frozen V9 archive; only four V10 files were added.

The following are single, sequential observations per cell/backend, with
tracemalloc enabled. Times are the original charged method `T_total`, including
preprocessing, certificate acceptance and release checks, rather than just the
suffix search. V9 is the counter-equipped control, not a new measurement of its
unmodified historical timing path.

| AP-D instance | Recorded rounds per backend | Exact objective, all backends | Reference total (s) | V9 total (s) | V10 total (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| C3-T4 | 6 | 12 | 1.207577 | 1.069617 | 1.193454 |
| D3-1 | 1 | 20 | 0.708499 | 0.699923 | 0.706193 |
| D3-2 | 1 | 20 | 0.606325 | 0.807970 | 0.717547 |

| AP-D instance | Exact suffix requests V9 / V10 | Lift materializations V9 / V10 | Full source-edge scan passes V9 / V10 | Source edges examined V9 / V10 | V10 graph reuses |
| --- | ---: | ---: | ---: | ---: | ---: |
| C3-T4 | 6 / 6 | 6 / 6 | 6 / 6 | 3025 / 3025 | 0 |
| D3-1 | 3 / 3 | 3 / 2 | 3 / 1 | 42 / 14 | 1 |
| D3-2 | 3 / 3 | 3 / 2 | 3 / 1 | 18 / 6 | 1 |

Both multi-entry cells therefore save one full lift construction and two
complete source-edge scan passes. Their search times change from
0.006311 to 0.002845 s and from 0.002400 to 0.001816 s, respectively.
C3-T4 has one exact entry in each separate refinement solve, so the cache cannot
reuse a lift across those six rounds. Its search time increases from 0.155018
to 0.163405 s. V10 total time increases on C3-T4 and slightly on D3-1, and falls
on D3-2. These small observations establish reduced repeated construction;
they do not establish an overall speedup. In particular, C3-T4 preprocessing
also varies from 0.381711 to 0.585655 s; this single comparison does not isolate
that variation as an effect of suffix reuse.

All nine results are `OPTIMALITY_CERTIFIED`, uncensored, and agree with the
original solver's exact objective. All nine additional independent replays of
persisted certificates pass. V9 and V10 retain identical concrete lassos,
refinement decisions, projection/witness work, and search work after excluding
the new graph-construction counters. Each retains one full TS build per AP-D
invocation: C3-T4 has one build plus five hits; each D3 cell has one build and
zero hits. All nine workers exit with code 0 and leave no live worker after
cleanup. There are 24 recorded rounds in total, not 24 independent attempts.

Directed fixtures compare complete lift node/adjacency/predecessor ordering and
weights with the fresh builder, and cover accepting/nonaccepting entries,
multiple SCCs, zero costs, Fraction and large integer costs, tied parallel
witnesses, fresh-solve isolation and invalid context/dummy rejection. Entry
checks reject changed budgets and cross-cell reuse. The root's read-only
readback verifies source/input hashes, exact result and certificate bytes,
deadline accounting, counters, and preserved V9 search/build work without
starting another solver or certificate verifier.

Raw results, all dispatches, per-worker logs, timings, certificates, replay
records, source snapshots and the readback are retained in the
[evidence index](evidence/20261022/index.json). Early failed development fixture
records are also retained; their exact precommit source revisions were not
archived. Synthetic fixtures do execute small solvers, and the aggregate
development call count is unknown. There was one real qualification namespace,
nine real CMR workers, and no real DDS/provider calls or formal campaign.
This AP-D prototype remains optional: no default switch, PR merge, or broader
backend qualification is implied.

## Reproduction

Use the existing WSL Humble/message overlay, preserve ROS `PYTHONPATH`, and
choose a fresh `/tmp` output namespace. Dispatch markers prohibit repeating
already dispatched cells in that namespace. The runner always uses all three
fixed cells and all three backends, with unchanged budgets and acceptance.

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_combo_bd75495/install/setup.bash
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/ltl_automaton_execution:$PWD/ltl_automaton_planner:$PWD/ltl_automaton_planner_core:$PWD:$PYTHONPATH"
receipt=/mnt/d/Robotics/Robotics4LLM/ltl_planning_studio/analysis/cmr_experiment_a_missing_data_repair_20261004/final_campaign_receipt.json
kernel=/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel
out=/tmp/cmr_v10_suffix_reuse_fresh
python3 -B experiments/cmr_ros2_suffix_reuse/runner.py --prepare --binding "$receipt" --kernel-root "$kernel" --output "$out"
python3 -B experiments/cmr_ros2_suffix_reuse/runner.py --binding "$receipt" --kernel-root "$kernel" --output "$out"
```
