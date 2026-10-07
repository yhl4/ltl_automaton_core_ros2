# ROS 2 Planning API

This document defines the Studio-facing ROS Planning Contract V0.2. Interface
definitions are owned by `ltl_automaton_msgs`, their implementation is owned by
`ltl_automaton_planner`, and the ROS-independent algorithm is owned by
`ltl_automaton_planner_core`. Consumers must not depend on planner Python
attributes, `LTLPlanner`, `TSModel`, NetworkX graphs, or private helpers.

## Planner Lifecycle

`/planner_status` publishes `ltl_automaton_msgs/msg/PlannerStatus` with reliable,
transient-local, depth-1 QoS. A late subscriber receives the latest state.

| State | Meaning |
|---|---|
| `UNINITIALIZED` | No validated transition system is active. |
| `READY` | A transition system is active, but no accepted plan is active. |
| `PLANNING` | One planning operation is in progress. |
| `ACTIVE` | An accepted prefix-suffix run is available for execution. |

The topic is the authoritative lifecycle signal. Action feedback text is only
informational.

## Loading a Transition System

`/load_transition_system` uses
`ltl_automaton_msgs/srv/LoadTransitionSystem`. The request contains complete
UTF-8 YAML content, not a file path.

- Loading is allowed in `UNINITIALIZED` and `READY`.
- A valid request atomically replaces the current transition system and leaves
  the planner in `READY`.
- Invalid input preserves the previous validated transition system.
- Referenced action weights must be finite and nonnegative. Numeric overflow
  during this validation is reported as an invalid action weight.
- Loading is rejected in `PLANNING` and `ACTIVE`.
- `active_ts_sha256` is the lowercase SHA-256 digest of the exact UTF-8 YAML
  payload that is active. It identifies the payload; it is not a semantic TS
  equivalence hash.

## Planning

`/plan_ltl` uses `ltl_automaton_msgs/action/PlanLTL`.

The goal supplies a hard task, soft task, multidimensional initial TS state,
`beta`, and `gamma`. State values are matched by dimension name and reordered
to the active TS definition, so message dimension order is not significant.
Both tasks must be non-empty for compatibility with existing wrapper behavior.
`beta` and `gamma` must be finite and nonnegative. Invalid weights abort with
`ERROR_INVALID_GOAL` before a candidate worker starts. Product edge weight is
`transition_cost + beta * soft_task_dist`; run cost is
`prefix_cost + gamma * suffix_cost`.

Atomic proposition identifiers start with a lowercase ASCII letter, followed
by ASCII letters, digits or underscores. Names remain case-sensitive:
`cargoReady1` and `cargoready1` are distinct propositions.

- Goals are accepted in `READY` and `ACTIVE`.
- Goals are rejected at the action transport level in `UNINITIALIZED` and
  `PLANNING`; rejected goals have no `PlanLTL.Result`.
- Only one planning transaction can exist at a time.
- Cancel requests are rejected and do not stop the search.

A successful accepted goal reaches the ROS action `SUCCEEDED` state and returns
`success=true`, `ERROR_NONE`, prefix and suffix plans, total cost, and planning
time. Any accepted-goal failure reaches `ABORTED` with `success=false`.

| Error | Meaning |
|---|---|
| `ERROR_INVALID_GOAL` | Task or initial-state input is invalid. |
| `ERROR_NOT_READY` | The accepted request no longer matches current execution state or transaction state. |
| `ERROR_NO_ACCEPTING_PLAN` | Valid input was searched normally, but no accepting run exists. |
| `ERROR_INTERNAL` | An unexpected implementation or runtime failure occurred. |

Translator startup failures, timeouts and termination by a signal return
`ERROR_INTERNAL`; signal diagnostics include the signal number. A positive
translator error exit retains `ERROR_INVALID_GOAL` and its captured diagnostic.
These failures preserve the active plan when a replacement is attempted.

After candidate search, prefix, suffix and total costs must convert to finite
float64 values. Finite input weights can still overflow during multiplication
or path accumulation; this computed-cost failure returns `ERROR_INTERNAL` before
the PlanLTL or IRL transaction can commit, preserving the active authority.
Diagnostics name the first invalid cost in prefix/suffix/total order. Large
finite results remain accepted. This ROS candidate check does not clamp weights,
change the Core objective, or change the ordinary snapshot-conversion fallback.

If candidate computation raises an unexpected exception, the PlanLTL worker
completes its executor-bound Future with `ERROR_INTERNAL` and the exception's
message. The action aborts and releases the transaction, preserving the current
authority. A later valid request can proceed. This does not add a planning
deadline, cooperative cancellation, or an automatic retry.

## Execution During Planning

Planning uses transactional replacement semantics. When a new goal starts from
`ACTIVE`, the existing plan remains the execution authority while an isolated
candidate is built in a worker thread.

At commit, the retained snapshot copy, new metadata and immutable Product ID
mapping are prepared before replacing authority. A preparation exception returns
`ERROR_INTERNAL` and releases the PlanLTL or IRL transaction, preserving the
current planner, TS, snapshot, IDs, generation and execution step. This covers
snapshot preparation; it does not roll back a later publisher or process failure.

Expected `/ts_state` feedback continues to advance the old plan, update possible
states, and publish the old plan's next command. The candidate publishes nothing
before commit. Commit requires the current canonical TS state to still equal the
candidate initial state. Otherwise the action aborts with `ERROR_NOT_READY`, and
the latest state and cursor of the old plan are preserved.

Unexpected feedback during candidate planning records the latest observed state
without starting a concurrent recovery search. If the candidate cannot commit,
the existing state-based recovery path runs serially after the transaction ends.

## Existing Execution Topics

| Name | Type | Direction from planner | Purpose |
|---|---|---|---|
| `/ts_state` | `ltl_automaton_msgs/msg/TransitionSystemStateStamped` | Subscribe | Observe the current executor/robot TS state. |
| `/next_move_cmd` | `std_msgs/msg/String` | Publish | Current execution command. |
| `/prefix_plan` | `ltl_automaton_msgs/msg/LTLPlan` | Publish | Current accepting-run prefix. |
| `/suffix_plan` | `ltl_automaton_msgs/msg/LTLPlan` | Publish | Current accepting-run suffix. |
| `/possible_ltl_states` | `ltl_automaton_msgs/msg/LTLStateArray` | Publish | Current possible Product states. |

The four planner output topics use reliable, transient-local, depth-1 QoS.
`/ts_state` uses the existing reliable, volatile subscription behavior.

## Legacy API

`/replanning` (`ltl_automaton_msgs/srv/TaskPlanning`) remains available for
backward compatibility. It replaces the task on the active planner and returns
only `bool success`. New consumers should use `/plan_ltl` for structured results
and errors. `/replanning` is rejected with `success=false` while another planning
operation is active.

## Formal Planning Graph Snapshot

`/get_planning_graph_snapshot` uses
`ltl_automaton_msgs/srv/GetPlanningGraphSnapshot`. It is an on-demand,
read-only view of the latest successfully committed accepted planning
generation. The retained payload contains the full Büchi graph, full Product
graph, and complete accepted prefix-suffix run with snapshot-local IDs.

The accepted suffix omits the repeated start node at the end; its final node
closes back to its first through a Product edge. A one-node suffix represents a
self-loop. The execution resolver rejects a multi-node suffix whose final node
duplicates its first.

The exporter also requires a nonempty prefix whose last node is the first
suffix node, and checks every adjacent prefix/suffix Product edge. A broken
run uses the unavailable empty-payload conversion result described below;
it is never marked as an available execution snapshot.

Each request atomically captures the current snapshot or its absence. A snapshot
response remains tied to that complete captured generation even if a newer one
commits during copying. The returned copy can be modified without changing the
planner's retained snapshot.

`planning_generation` starts at zero and increments once when startup planning,
`PlanLTL`, legacy task replanning, or state-based replanning successfully
replaces the accepted run. A successful optional IRL beta-learning commit also
replaces the run and increments the generation. Planning attempts, failures,
stale candidates, transition-system loading, service requests, and ordinary
execution-cursor progress do not increment it.

`metadata.planner_instance_id` is a non-empty opaque UUID created once for a
`PlannerNode` lifetime. Snapshot identity is the pair
`(planner_instance_id, planning_generation)`: the generation counter resets
when the node restarts, so consumers must never compare generations across
different instance IDs. Transition-system loading keeps the same instance ID
and counter, but clears all active plan authority until a later successful plan
commit.

During candidate planning from `ACTIVE`, the service continues to return the
old active generation; an uncommitted candidate is never visible. If graph
conversion is unavailable for a successful planning generation, planning still
succeeds, the new generation is retained with `metadata.available=false`, and
the service returns `success=false` with an empty graph payload and explanatory
metadata. This does not restore or expose an older generation.

## Formal Execution Observation

`/planning_execution_observation` publishes
`ltl_automaton_msgs/msg/PlanningExecutionObservation` with reliable,
transient-local, depth-1 QoS. Each message is a compact view of the active
execution authority and carries the same `(planner_instance_id,
planning_generation)` identity as its retained graph snapshot.

`execution_step_seq` is a `uint64` sequence within that planning generation.
Every successfully committed generation starts at sequence `0`. The planner
increments it only after accepting the expected, timestamped TS feedback and
advancing the execution cursor. A new timestamp for the same symbolic TS state
can advance a self-loop; repeated publication does not increment the sequence.
With the default `check_timestamp=true`, repeated or older TS timestamps are
rejected. TS feedback must use the planner's configured clock consistently.
The command identity is the triple
`(planner_instance_id, planning_generation, execution_step_seq)`, while the
snapshot identity remains the pair
`(planner_instance_id, planning_generation)`.

- `possible_product_node_ids` is the sorted, unique set of snapshot-local
  Product IDs currently possible for execution. It may contain zero, one, or
  many IDs.
- `has_next_action` is authoritative. When false, `next_action` is empty; when
  true, `next_action` is the selected current planner action.
- `execution_step_seq` distinguishes a later execution step from a repeated
  publication of the same observation. Consumers must reject duplicate or older
  sequences. A later sequence may carry the same Product IDs and action and is
  still a new command.
- Product IDs refer only to the graph returned by
  `/get_planning_graph_snapshot` for the same identity. Consumers should cache
  snapshots by the identity pair and discard an observation whose matching
  snapshot has not been obtained yet.

The planner publishes an observation only when the active snapshot is
available and every current internal Product node has a retained mapping into
that exact snapshot. Graph-conversion failure or a mapping mismatch suppresses
the formal observation without changing planning success or legacy execution
topics. During `PLANNING` from `ACTIVE`, observations can continue to describe
the previous active generation while its execution remains authoritative; an
uncommitted candidate never publishes observations.

While one backend command is in flight, consumers retain the newest observation
and may coalesce intermediate commands. A failed or rejected step is not
automatically retried at the same sequence. Backend completion contains only
`success` and `message`; it does not establish TS state truth. Expected TS
feedback remains the source of execution-state advancement. A delayed snapshot
request may have captured an older sequence, but a response with the matching
snapshot identity is resolved against the latest observation for that identity.

All consumers must regenerate and rebuild the `ltl_automaton_msgs` interfaces
before use. V0.2 provides no compatibility layer for the old observation
message.

## Optional IRL Transactions

The HIL package can explicitly enable `IRLPlugin` through `plugin_config_path`.
It records demonstrations using `/irl_trigger` and `/possible_runs`, then asks
the planner host to learn beta and replan on an isolated candidate. It uses the
same single planning transaction as `PlanLTL`; concurrent requests are rejected.
The previous plan remains authoritative while learning runs.

IRL commit requires the captured instance, generation, execution sequence, and
accepted TS-feedback revision to remain current, in addition to the source hash
and canonical-state checks. Even an observed departure and return to the same
state invalidates the learning candidate. Successful commit publishes a new
snapshot and resets execution sequence to zero. Failure or stale input leaves
the active beta and plan unchanged; deferred unexpected-state recovery can
subsequently replace the run using the old beta.

The original beta-only learning heuristic is retained, without convergence or
inverse-optimality guarantees. See the [HIL documentation](../../ltl_automaton_hil_mic/README.md#optional-irl-beta-learning)
for recording settings and the learning rule. Startup task and weight ROS
parameters do not track subsequent Action or IRL commits.

## Known V0.2 Limitations

V0.2 does not provide:

- cooperative `PlanLTL` cancellation;
- a planning time limit;
- explored-node or percentage feedback;
- detailed planning stages;
- runtime transition-system replacement while `ACTIVE`;
- queued or concurrent planning goals.

The execution package remains a symbolic execution boundary. It does not provide
Gazebo, Isaac Sim, kinematics, trajectory generation, collision checking,
perception, hardware control, or physical-simulation validation.

These are contract limitations, not indications that a request is malfunctioning.

## Compatibility

This contract is tested on Ubuntu 22.04, ROS 2 Humble, and Python 3.10. No ROS 2
Jazzy compatibility claim is made.
