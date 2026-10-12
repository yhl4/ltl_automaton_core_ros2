# Local CMR integration

This independent ROS 2 package uses the frozen exact CMR kernel. The existing
ltl_automaton_planner and its ROS behavior remain unchanged. This local branch
uses PR10 fixed snapshot 989bb8effc41226b4d3e478a0e760f2f5998eb0d;
main was 2624458c15799aa7784d3ca6ee75da02ca785204 when checked.

No code was pushed, uploaded, shared, or published. Publishing remains pending
explicit authorization from the parent task.

## Unified entry point

Python >= 3.10:

    from ltl_automaton_cmr.engine import plan
    from ltl_automaton_cmr.office import load_office_query
    query = load_office_query("D2")
    result = plan(query.model, arm="AP", family_prior=query.family_prior)
    record = result.to_dict()

FULL uses all dimension IDs. AP uses the explicit task AP support Sphi.
FAMILY uses Sphi union the fixed RF supplied once at request creation.
All three use the same model, action oracles, exact solver, concretizer,
certificate, deterministic refinement, and gamma=10 objective.
The prior is copied once and does not change during recovery. This package
does not learn a prior, translate arbitrary LTL, or claim a family benchmark.

The formal model boundary requires explicit AP names and support mappings,
stable unique action names, atomic multidimensional effects, and separate
read/write/cost_support. Costs are int/Fraction; floats and booleans are rejected.
Guards, effects, labels and costs must be pure deterministic functions.

    export PYTHONPATH=$PWD/ltl_automaton_cmr:$PWD/ltl_automaton_execution
    python3 -m ltl_automaton_cmr.cli --office-query D2 --arm AP --output /tmp/cmr-d2.json
    python3 -m ltl_automaton_cmr.cli --model-factory my_model:build --arm FULL --output /tmp/cmr-model.json

The JSON retains each round's dimensions, action occurrences, exact rational
LB/UB, recovery scores/reasons, sizes, phase times, total elapsed time, and
complete concrete lasso. The original closed suffix remains in this artifact.
Finite exact LB=UB is required. Exact emptiness of the optimistic Product is
a sound negative proof (every concrete lasso projects into it). Infeasible
results carry no lasso. Uncertified full precision raises CertificationError
and is never passed to execution. CLI exit codes: 0 certified, 1 exact-empty,
2 model/certification error.

## ROS and symbolic execution

Build in a local ROS Humble workspace:

    source /opt/ros/humble/setup.bash
    colcon build --packages-up-to ltl_automaton_cmr
    source install/setup.bash
    ros2 launch ltl_automaton_cmr cmr_experiment.launch.py
    ros2 service call /cmr/replanning ltl_automaton_msgs/srv/TaskPlanning "{hard_task: D2, soft_task: ''}"

The launch uses the isolated /cmr namespace. No planning begins until the
TaskPlanning service is called. The request accepts original Office D1-D8 IDs
or their exact manifest formula text; unsupported formulas and soft tasks fail
explicitly. A full observed ten-dimensional state is used for subsequent
service replanning. The synchronous experimental service can block callbacks
during planning; this version does not support cancellation/deadlines,
dynamic TS loading, IRL or a general LTL parser.

The adapter reuses TaskPlanning, GetPlanningGraphSnapshot,
PlanningExecutionObservation, next_move_cmd, ts_state and the existing
ltl_automaton_execution resolver/backend. Only a validated, certified concrete
lasso crosses this boundary. Each finite occurrence receives a distinct
snapshot node ID, even when its formal Product state repeats. Prefix/suffix
share their boundary occurrence; only the final suffix closure node is removed.
The closing edge and every repeated action remain. This avoids DiGraph/action
collapse and avoids importing the old source-label Product/accepting-state
split solver or the one-dimension TSModel.

CMR snapshots have metadata.buchi_type=cmr_retained_occurrences. They contain
the retained occurrence graph, not a complete searched Product/BA graph.
The exact JSON preserves the original formal Product states, all edges and
costs. Legacy execution consumers use the retained node/action contract;
visualizers assuming complete Product/BA graphs must inspect this type.

CMR certification never passes through float64. The certified_execution_snapshot(result, model, ...) helper revalidates the
witness against its original formal model. The lower-level lasso conversion
requires a previously validated witness. The Python execution contract
has no cost fields and can execute any certified exact rational result.
Existing ROS snapshot cost fields are float64: export first checks every edge,
prefix/suffix cost and objective is exactly representable. Non-dyadic values
such as 1/3, integers such as 2**53+1, or overflow fail with CapabilityError.
No rounded ROS plan is committed. Exact JSON remains available. This version
does not extend the public message schema with rational cost or edge-ID fields.

The execution cursor advances only on strictly newer expected timestamped TS
feedback. Completion is not state truth. Unexpected valid state revokes command
authority until explicit replanning. For self-loops, a new same-state stamp is
an execution observation under the existing PR10 convention. The state observer
must emit an action-caused observation per dispatch; periodic unchanged-state
messages alone cannot prove a self-loop was physically executed.

## Office8 input and scope

Office8 means the original eight queries D1-D8 over ten dimensions:
r,p,d,b,f,l,c,w,j,s. b is the temporary badge/pass. The frozen RF is {0,1,2,3}
(r,p,d,b), from code_v4/design_new_local.py. D2 is F(p=E), Sphi={1}.
Input JSON and monitor compiler are copied unchanged. The adapter compiles
the official guard/assignment/support metadata into the formal kernel model.
It preserves print_job (j,s) and wash_floor (f,w) atomic effects.

Only representative D2/AP is measured here. The full Office FULL arm has a
large source-state scan in the frozen abstraction; it was not run. No experiment
data, historical metrics, manifest queries, or full benchmark were changed.

## Provenance and license

Authoritative source: yhl4/CMR-LTL commit
dad230c2f54d9d5eb85d5e8dfd01e2d6c229afbc, core path
reproducibility/paper_20261005_r2/core/qualified_p1/ecc_p1_formal_kernel/ecc_p1/.
All eight source blobs are unchanged. Office input/monitor source is under
cmr_repro/oct6/office_v4/code_v4/. Its older exact_backend and ecc_p1 copy are
not used. Source Git blob IDs and SHA-256 hashes are in provenance.json.

The kernel/monitor code uses MIT, Copyright (c) 2026 yhl4; the original complete
LICENSE is retained. Benchmark content follows the source repository's
CC BY 4.0 attribution. No KTH-derived source is relicensed by this package.
Selected upstream mechanism tests retain their behavior with imports redirected
to the authoritative vendor. No historical successor-only semantic freeze is used.

    python3 ltl_automaton_cmr/scripts/verify_vendor.py
    python3 -m pytest -q ltl_automaton_cmr/test

See docs/VALIDATION.md for actual executed checks, evidence and unrun scope.
