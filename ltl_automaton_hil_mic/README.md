# ltl_automaton_hil_mic

ROS 2 Humble migration of the KTH human-in-the-loop mixed-initiative
controllers.

## Boolean command controller

`bool_cmd_hil_mic` keeps planner Boolean commands unchanged. A `True` human
command is published only when its configured TS action leads to a connected,
non-trap state according to `check_for_trap`.

```bash
ros2 launch ltl_automaton_hil_mic bool_cmd_hil_mic.launch.py \
  transition_system_path:=/path/to/transition_system.yaml
```

The ROS 1 topic and service names are preserved: `ts_state`, `key_cmd`,
`planner_cmd`, `mix_cmd`, and `check_for_trap`.

Pending decisions track changes of symbolic TS state, so leaving and returning
to the same state does not revive an old response. Repeated identical state
messages keep a current query valid. Failed requests release the query without
publishing a human command; another human command can then start a fresh query.

## Velocity command controller

`vel_cmd_hil_mic` passes navigation commands through when human input is stale,
below the deadband, the TS state is unavailable, or either safety service is
unavailable. Otherwise it queries `closest_region` and `check_for_trap`:

- no connected trap: bounded human command;
- trap inside `ds`: navigation command;
- trap beyond `ds + epsilon`: bounded human command;
- trap inside the buffer: smooth blend of both commands.

```bash
ros2 launch ltl_automaton_hil_mic vel_cmd_hil_mic.launch.py
```

The ROS 1 topics remain `ts_state`, `key_vel`, `nav_vel`, and `cmd_vel`.

Async results use the latest accepted navigation and current human commands, with human-input
freshness checked again when each response arrives. An expired human input,
changed TS state, or failed service falls back to the latest valid navigation command.

Human-input age uses the node's ROS clock and must satisfy `0 <= age < timeout`.
When a check finds a negative age after clock reversal or an expired sample, it
clears that human input. Returning ROS time to the old window cannot revive the
sample; another human input is required. Receipt at ROS time zero remains valid
for a positive timeout, and `timeout=0` disables human input. The safety-query
deadline continues to use steady time.

All six `Twist` components must be finite. Invalid human input clears the manual
input and cancels its pending query; invalid navigation input leaves the last
valid navigation cache intact. Both reject the sample, log a warning and publish
the latest valid navigation command, or a zero `Twist` before any valid navigation
has arrived. A non-finite `closest_region` metric also releases the query and
falls back to valid navigation. Subsequent valid input can start another query.

`ds`, `epsilon`, `deadband`, human-input `timeout` and all axis limits must be
finite. `epsilon` must be positive; the other values are non-negative. Policy API
`max_linear` and `max_angular` each contain exactly three values; zero disables
that manual axis. These limits apply to human input; valid navigation commands
keep their existing passthrough behavior. Magnitude and smooth gain use stable
calculations to handle large finite components and tiny positive `epsilon`
without changing the mathematical deadband, safety-zone or blending rules.

Both launch files accept `safety_check_timeout` (default `1.0` seconds, finite
and positive). It bounds the complete safety query; the velocity controller's
closest-region and trap requests share that deadline. A 0.1-second steady-clock
timer expires pending queries and cancels their futures at its next callback;
response callbacks also reject expired queries. Bool drops the pending
human command; velocity publishes the latest valid navigation command. Late replies
cannot affect a newer query or publish after node teardown. The existing velocity
`timeout` remains the human-input freshness window, separate from this query limit.

The three safety-response callbacks retrieve completed Future exceptions before
checking node teardown, request identity and the deadline. An already queued
callback can then be discarded without an unread-exception diagnostic. Current
request failures retain their error logging, query release and navigation fallback.
Real Future/executor regressions and the local 90-test result are recorded in
[validation section 11.91](../ltl_automaton_planner/docs/validation.md).

Both controllers require TS state values and dimension names to have equal
length, the configured dimension to be present, and all dimension names to be
unique. Invalid TS messages log a warning and are dropped without replacing the
last valid state or invalidating its pending query. Before a valid state arrives,
they cannot start a safety query; a later valid state can restore normal control.

Both controllers' configuration parameters are startup-only and read-only.
Set limits, deadlines, the monitored action and model/dimension selection when
starting the node; runtime parameter writes are rejected instead of reporting
values that the existing policy does not use. ROS 2's inherited `use_sim_time`
parameter remains dynamic. For example:

```bash
ros2 run ltl_automaton_hil_mic vel_cmd_hil_mic --ros-args -p max_linear_x_vel:=1.0
```

```bash
ros2 launch ltl_automaton_hil_mic vel_cmd_hil_mic.launch.py \
  safety_check_timeout:=1.0
```

The controller package consumes the `check_for_trap` service. The read-only
ROS 2 `TrapDetectionPlugin` provides it when the planner loads:

```yaml
plugins:
  TrapDetectionPlugin:
    path: ltl_automaton_hil_mic.trap_detection
    args: {}
```

Trap diagnosis reads the host's currently committed planner, so a successful
`PlanLTL` replacement immediately changes the graph used by the existing
service. An uncommitted candidate is never used; without an active planner,
the service returns `is_connected=false` and `is_trap=false`.

For a connected query, a state is non-trap when any candidate Product node can
reach any node in `accept_with_cycle`, including a candidate already in that set.
Normal directed Product graphs use one reverse reachability traversal per query.
The search keeps no graph cache between requests, so later edge or accepting-set
changes are read again. Empty candidate sets remain disconnected; an empty
accepting-cycle set makes a connected query a trap.

## Optional IRL beta learning

`IRLPlugin` restores the original scope: learn the soft-task weight beta from
demonstrated Product paths. It is available only when explicitly configured;
the default planner launch leaves `plugin_config_path` empty and loads no plugins.
The `trap_detection_plugin.yaml` example enables trap diagnosis alone; pass
`irl_plugin.yaml` to enable IRL.

```bash
ros2 launch ltl_automaton_planner planner.launch.py \
  transition_system_path:=/path/to/transition_system.yaml \
  plugin_config_path:="$(ros2 pkg prefix ltl_automaton_hil_mic)/share/ltl_automaton_hil_mic/config/irl_plugin.yaml" \
  replan_on_unplanned_move:=false
```

With an active plan, publish `std_msgs/msg/Bool` on `/irl_trigger`: `True`
starts recording from the current Product belief, and `False` stops recording
and requests learning. Supply actual, freshly timestamped `/ts_state` feedback
between those messages. `/possible_runs` publishes diagnostic Product paths.

Within a Python-built diagnostic message, each path occurrence owns its TS
state-value and dimension-name lists. Editing one occurrence does not change
another occurrence, the source TS format, or the next publication.

`max_run_buffer_size` defaults to 100 and counts nodes across all candidate
paths; exceeding it stops recording and requests learning once. A generation
change clears the teaching buffer. Repeated trigger values do not repeat a
learning request.

For a demonstration that departs from the planned next state, disable the
existing `replan_on_unplanned_move` behavior. Observations must still match
actual Product successors and hard guards. Automatic replanning or task
replacement otherwise starts a new generation and ends the old teaching
session. To use both IRL and trap diagnosis, list both plugin classes in your
own plugin YAML.

When distinct teaching histories converge at one Product state, each feedback
update enumerates that state's successors once and reuses the matching targets.
All distinct history paths remain in the run set. This lookup is local to one
update, so the next update reads changed Product edges; buffer limits and
learning triggers retain their existing behavior.

Diagnostic run publication reuses flattened TS values within one publication.
Every state's `states` field still receives a separate list; the ordered runs,
dimension names and Buchi fields retain their existing payloads. The next
publication rebuilds the conversion lookup.

The learner follows the legacy ROS 2 port's margin heuristic:

- select the demonstrated path with the least adjacent-edge soft distance;
- search with `transition_cost + beta * soft_task_dist`, plus a margin of 1
  on each edge absent from that demonstration;
- subtract the searched run's raw suffix adjacent-edge soft distance from the
  demonstration's soft distance to obtain the gradient; the suffix closing
  edge is excluded, following the original heuristic;
- project beta onto nonnegative values, using step 1 for the first ten
  iterations and `1 / (iteration + 1)` thereafter;
- stop after at most 20 iterations or a beta change of at most 0.3, and return
  the latest beta.

Once per learning call, the learner records the private Product's ordered edge
attribute references and whether each edge is absent from the demonstration.
Every iteration traverses this local table to reset all canonical weights and
apply the margin, reading the referenced attributes each time. The margin does
not accumulate; multiplication, base-weight addition and margin addition keep
their original order. The table uses space proportional to the edge count and
is rebuilt on the next learning call.

This is a bounded heuristic, without a convergence, inverse-optimality, or
exact demonstration-reproduction guarantee. Hard/soft tasks and gamma remain
the same. Learning and replanning operate on an isolated candidate, and the
host commits only while the captured instance, generation, execution sequence,
and accepted-state revision are current. A successful commit starts a new
generation at execution sequence zero; failure or a stale result preserves the
active beta and plan. Deferred recovery from unexpected feedback may separately
replace the old plan using its existing beta.

Before an IRL candidate can commit, its prefix, suffix and total costs must
convert to finite float64 values. Computed overflow fails the transaction
internally and preserves the active authority, without clamping the learned
beta or changing the learning rules.

Startup ROS parameters are not rewritten by learning. The committed graph
contains canonical weights `transition_cost + beta * soft_task_dist`, without
the temporary learning margin, and the commit log reports the learned beta.
