# ROS 2 Planning API

This document defines the Studio-facing ROS Planning Contract V0.1. Interface
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

- Goals are accepted in `READY` and `ACTIVE`.
- Goals are rejected at the action transport level in `UNINITIALIZED` and
  `PLANNING`; rejected goals have no `PlanLTL.Result`.
- Only one planning transaction can exist at a time.
- V0.1 cancel requests are rejected and do not stop the search.

A successful accepted goal reaches the ROS action `SUCCEEDED` state and returns
`success=true`, `ERROR_NONE`, prefix and suffix plans, total cost, and planning
time. Any accepted-goal failure reaches `ABORTED` with `success=false`.

| Error | Meaning |
|---|---|
| `ERROR_INVALID_GOAL` | Task or initial-state input is invalid. |
| `ERROR_NOT_READY` | The accepted request no longer matches current execution state or transaction state. |
| `ERROR_NO_ACCEPTING_PLAN` | Valid input was searched normally, but no accepting run exists. |
| `ERROR_INTERNAL` | An unexpected implementation or runtime failure occurred. |

## Execution During Planning

Planning uses transactional replacement semantics. When a new goal starts from
`ACTIVE`, the existing plan remains the execution authority while an isolated
candidate is built in a worker thread.

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

`planning_generation` starts at zero and increments once when startup planning,
`PlanLTL`, legacy task replanning, or state-based replanning successfully
replaces the accepted run. Planning attempts, failures, stale candidates,
transition-system loading, service requests, and ordinary execution-cursor
progress do not increment it.

During candidate planning from `ACTIVE`, the service continues to return the
old active generation; an uncommitted candidate is never visible. If graph
conversion is unavailable for a successful planning generation, planning still
succeeds, the new generation is retained with `metadata.available=false`, and
the service returns `success=false` with an empty graph payload and explanatory
metadata. This does not restore or expose an older generation.

## Known V0.1 Limitations

V0.1 does not provide:

- cooperative `PlanLTL` cancellation;
- a planning time limit;
- explored-node or percentage feedback;
- detailed planning stages;
- runtime transition-system replacement while `ACTIVE`;
- queued or concurrent planning goals.

These are contract limitations, not indications that a request is malfunctioning.

## Compatibility

This contract is tested on Ubuntu 22.04, ROS 2 Humble, and Python 3.10. No ROS 2
Jazzy compatibility claim is made.
