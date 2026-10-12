# Executed validation, 2026-10-08

This local integration is based on PR10 fixed snapshot
989bb8effc41226b4d3e478a0e760f2f5998eb0d, with main
2624458c15799aa7784d3ca6ee75da02ca785204. Final read-only GitHub verification
found PR10 still open/unmerged, now at ab45b9b7333ead2e371211a3ccb932dfb254fdad
(its parent is the fixed snapshot). That later immutable-state-copy optimization
is not part of this tested baseline.

The source checkout at D:\Robotics\Robotics4LLM\ltl_automaton_core-ros2 initially
had two uncommitted files. Its HEAD later advanced to ab45b9b... independently.
Both files' SHA-256 hashes remained identical between our entry and exit checks.
This task did not change that checkout, its branch, or its working files.
The independent clone has only the new ltl_automaton_cmr package as a change.

No repository AGENTS.md or .agents/skills directory was present in the source
or independent clones. The existing ROS README's colcon build/test guidance was
read. Relevant local Codex memory was read solely to locate/verify sources;
no memory file was modified.

## Actual checks

- ROS Humble / local WSL Ubuntu-22.04-D: clean independent build of five
  dependency packages succeeded (4 min 6 s). Final new-package rebuild succeeded.
- colcon test --packages-select ltl_automaton_cmr: 97 tests, zero errors,
  zero failures, zero skips. Includes initial/X semantics, nonaccepting SCC entry,
  exact nonempty accepting closed walks, multidimensional atomic effects,
  parallel action identity, projected hidden self-loops, exact rational bounds,
  recovery occurrence frequency/ties/all-zero, hidden transient and multicycle
  concretization, all three S0 arms, source fidelity, float64 capability,
  repeated occurrence export and invalid encodings.
- Generated-message tests include actual DDS TaskPlanning services/results and
  real CMR engine -> existing ExecutionManagerNode/FakeBackend -> stamped state
  feedback, with at least four cursor advances. Small deterministic models only.
- Old planner core package: 217 passed, 1 skipped (see legacy-core.xml).
- Old symbolic resolver/backend package: 72 passed. No legacy source file changed.
- verify_vendor.py verified twelve exact upstream blobs, including all eight
  required qualified_p1 core files, Office model/task JSON, monitor compiler and
  original MIT LICENSE.
- Representative Office D2/AP: OPTIMALITY_CERTIFIED, exact objective 20,
  98.7413 seconds on existing Windows Python 3.12. Precision sequence
  [1], [0,1], [0,1,2], [0,1,2,3]; lower bounds 14,18,19,20; final LB=UB20.
  Prefix cost10, suffix cost1, gamma10. All nine serialized concrete edges were
  independently replayed against the original formal model and acceptance.
  See validation/office_d2_ap.json.

The first regression harness invocation had incorrect source PATH/PYTHONPATH
and ran linters from the workspace root (scanning generated/frozen code).
The corrected package-local harness uses the already installed
/home/yuhling/.local/bin/ltl2ba and passes. No dependency installation was needed.
These were harness/environment corrections; no old algorithm was edited.

The Office solve was run once. Offline parser/metadata checks for D1-D8 do
not constitute solving those queries. No Office FULL/FAMILY large solve,
eight-query sweep, full benchmark, historical-data update, hardware experiment,
arbitrary LTL translation, ROS action cancellation or timing deadline was run.
The node currently provides a synchronous experimental service and the known
Office8 manifest interface. Its snapshots contain retained concrete occurrences,
not the full explored Product/BA graph. See README.md for float64 and feedback
capabilities.

## Reproduce

Run from the independent repository using the existing local ROS Humble setup:

    bash ltl_automaton_cmr/scripts/run_cmr_checks.sh
    bash ltl_automaton_cmr/scripts/run_legacy_checks.sh
    python3 ltl_automaton_cmr/scripts/verify_vendor.py

For the single representative solve:

    export PYTHONPATH=$PWD/ltl_automaton_cmr:$PWD/ltl_automaton_execution
    python3 -m ltl_automaton_cmr.cli --office-query D2 --arm AP --output /tmp/cmr-d2.json

On this Windows host the checks are invoked as:

    wsl -d Ubuntu-22.04-D -- bash /mnt/c/Users/Yuhling/Documents/Codex/2026-10-08/task-2/cmr-ros2/ltl_automaton_cmr/scripts/run_cmr_checks.sh

Raw local build/pytest/XML logs are retained in validation/ and ignored by Git.
Machine-readable source and result evidence is retained in provenance.json,
validation/summary.json and validation/office_d2_ap.json.

Publishing is pending explicit authorization. No push, remote branch creation,
PR creation, code upload or sharing was performed by this task.

The proposed benchmark v2 remains an external design draft. This implementation
keeps one plan call and one machine-readable record per query/request. Query budgets,
controlled cold-start/cache consistency and cancellation isolation are unimplemented
or unvalidated. Engine total_seconds measures the plan call and excludes input/monitor
loading; it is not a whole-request deadline. No new dataset was built or run.
