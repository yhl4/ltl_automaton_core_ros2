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

## Optional IRL beta learning

`IRLPlugin` restores the original scope: learn the soft-task weight beta from
demonstrated Product paths. It is available only when explicitly configured;
the default plugin configuration continues to enable trap diagnosis alone.

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

This is a bounded heuristic, without a convergence, inverse-optimality, or
exact demonstration-reproduction guarantee. Hard/soft tasks and gamma remain
the same. Learning and replanning operate on an isolated candidate, and the
host commits only while the captured instance, generation, execution sequence,
and accepted-state revision are current. A successful commit starts a new
generation at execution sequence zero; failure or a stale result preserves the
active beta and plan. Deferred recovery from unexpected feedback may separately
replace the old plan using its existing beta.

Startup ROS parameters are not rewritten by learning. The committed graph
contains canonical weights `transition_cost + beta * soft_task_dist`, without
the temporary learning margin, and the commit log reports the learned beta.
