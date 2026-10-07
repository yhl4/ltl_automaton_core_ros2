# LTL Automaton Execution

`ltl_automaton_execution` resolves Core's retained formal execution authority
and keeps command execution separate from observed transition-system truth.

The public input authority is
`/planning_execution_observation` plus the identity-matched
`/get_planning_graph_snapshot` response. The observation carries
`planner_instance_id`, `planning_generation`, and the V0.2
`execution_step_seq`. The command identity is this full triple; the graph
snapshot identity remains the pair `(planner_instance_id, planning_generation)`.
The resolver uses only Product nodes, Product edges, and the retained
prefix/suffix accepted run in those ROS contracts. It never imports planner
internals or searches for a different route.

For every successfully committed planning generation, the execution sequence
starts at `0`. The planner increments it only after accepting the expected,
timestamped TS feedback and advancing the execution cursor. A new timestamp
may advance a same-state self-loop; repeated publication does not increment the
sequence. Backend completion reports only `success` and `message`; it is never
TS-state truth. Consumers must regenerate and rebuild `ltl_automaton_msgs` for
this V0.2 field; there is no compatibility layer for the old message.

The resolver indexes only one immutable snapshot at a time and reuses its
node and retained-action lookup for subsequent commands. A replacement snapshot
rebuilds the index with one full Product-edge scan, retaining only edges used by
the accepted run. Missing run edges are reported before missing run nodes; a
failed rebuild leaves the prior valid index intact.

When converting a ROS snapshot, nodes with equal ordinary string dimensions and
values share one immutable `SymbolicState` within that conversion. Product node
IDs and order remain distinct. Each new message is converted independently;
string subclasses and malformed inputs retain the original validation path.

Command resolution visits every retained edge matching the current Product IDs
and action, accumulating the complete source and target ID sets directly. IDs
are still returned sorted, current nodes with no matching edge are omitted,
and all target IDs must represent one symbolic TS state. This avoids a temporary
list of candidate pairs without pruning the matches or changing ambiguity rules.

The suffix omits the repeated start node at the end and closes through an implicit
final edge.
A multi-node suffix that repeats its start at the end is rejected before
dispatch. A one-node suffix remains valid and uses its explicit Product self-loop.

Duplicate or older execution sequences are not dispatched. A later sequence may
dispatch even when its Product IDs and action match the previous step. While a
backend call is in flight, the node retains the newest current-authority
observation and retries it with the existing retry timer after the backend is
idle. A failed or rejected step is not automatically retried at that sequence.
An observation with no next action clears a pending command. A delayed snapshot
response validates only the graph identity and then uses the latest observation
for that identity, so a newer sequence is not rejected because the request
captured an older sequence.

Snapshot service discovery and failed requests use the same 0.1-second retry
timer. A request exception, missing response, or unsuccessful response retains
only the latest actionable observation for the same current graph identity.
A newer authority or no-action observation suppresses retries of the old command.
Successful responses still require valid identity and schema before dispatch.
Node teardown cancels pending retries and ignores late snapshot completions.

`snapshot_request_timeout` sets a finite positive request deadline in seconds at
startup (default `5.0`). The existing 0.1-second retry timer uses a steady clock, so a
paused simulated ROS clock does not prevent an unanswered request from expiring.
Each request retains its original monotonic deadline; repeated observations do
not extend it. The timer, new observations, and response callbacks check that
deadline. An expired request is detached before cancelling its Future, then the
latest actionable observation may request a new snapshot. A late reply cannot
clear the replacement request or dispatch an old command. Changed graph authority,
no-action observations, and teardown cancel requests that are no longer needed.
The deadline is checked when a callback runs, not a hard real-time guarantee.

The fake launch exposes the same parameter:

```bash
ros2 launch ltl_automaton_execution fake_execution.launch.py snapshot_request_timeout:=5.0
```

`snapshot_request_timeout` and the fake backend's `execution_delay_sec` are
read-only startup parameters. Startup overrides are applied before constructing
requests and the backend; runtime writes are rejected instead of reporting
values that were not applied. The inherited `use_sim_time` remains dynamic.

`FakeBackend` requires a finite, non-negative numeric execution delay. The default
ROS-backed node also rejects delays outside the native timer range at startup.
Zero delay keeps the existing asynchronous 1-millisecond minimum and ROS clock.
Each one-shot timer is destroyed after its callback, including when that callback
raises. Teardown clears pending execution timers and ignores already queued
callbacks, so they cannot mutate the fake plant after shutdown. A supplied backend
retains its own scheduling contract.

`ExecutionManagerNode` selects defaults only for `None` arguments. Explicitly
supplied backends, observers, abstractions and fake plants are used regardless of
their Boolean value. The default fake backend and observer share the supplied
plant; fake execution-delay validation applies when the default backend is used.

An `ExecutionBackend` receives an `ExecutionStep` containing the command identity,
action, and exact symbolic source/target states. It completes asynchronously with
an `ExecutionCompletion` containing only execution success and a message.
Backend completion is not state truth and never publishes `/ts_state`.

A dispatch exception is reported as a backend failure and releases the busy
state. It does not fabricate observed state or automatically retry that command.

If the fake backend's asynchronous plant update or observation delivery raises,
it reports a failed completion before re-raising the error. The manager releases
its busy state; an already applied plant update is preserved. The same command
is not automatically retried, and failed delivery does not fabricate TS feedback.

A generic `StateObserver[T]` reports raw plant, simulator, or robot observations
independently of command execution. A matching `StateAbstraction[T]` converts a
safe observation to ordered `SymbolicState`; only that pipeline may publish
`/ts_state`. Invalid abstractions fail closed. Core remains authoritative for
whether the observation is expected and how planning state advances.

`SymbolicState` requires aligned, nonempty string dimension names and values,
with unique dimensions. Non-string entries, including nonempty bytes, raise the
existing `ValueError` at construction; valid strings are kept without trimming
or coercion. An abstraction construction failure follows the node's existing
rejection path, and later valid observations can still publish.

Node teardown stops the observer and ignores previously queued observation
callbacks before abstraction or publication, protecting destroyed ROS entities.

P4 fake execution composes `FakeBackend` and `FakeStateObserver` around one
in-memory `FakePlant`. The backend mutates the plant after its configured delay;
the observer emits `FakePlantObservation`; `FakeStateAbstraction` accepts the
constructed `SymbolicState`. The plant contains no task route or Demo-D1 logic.

Future integrations are independent extension points. A Gazebo integration
would use `ExecutionStep -> GazeboExecutionBackend -> simulator command` and
`Gazebo topics/state -> GazeboStateObserver -> HouseholdStateAbstraction ->
SymbolicState -> /ts_state`. Isaac and physical-robot integrations likewise use
separate execution backends and observers. A future backend must not fabricate
TS-state success from its command target. No simulator integration exists yet.

Fake execution is symbolic execution, not physics simulation. It provides no
kinematics, trajectory generation, collision checking, perception, or hardware
control, and this package does not claim Gazebo or Isaac Sim support or physical
simulation validation.
