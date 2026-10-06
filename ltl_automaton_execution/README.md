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
rebuilds the index. Missing accepted-run nodes are rejected as resolution errors.

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

An `ExecutionBackend` receives an `ExecutionStep` containing the command identity,
action, and exact symbolic source/target states. It completes asynchronously with
an `ExecutionCompletion` containing only execution success and a message.
Backend completion is not state truth and never publishes `/ts_state`.

A dispatch exception is reported as a backend failure and releases the busy
state. It does not fabricate observed state or automatically retry that command.

A generic `StateObserver[T]` reports raw plant, simulator, or robot observations
independently of command execution. A matching `StateAbstraction[T]` converts a
safe observation to ordered `SymbolicState`; only that pipeline may publish
`/ts_state`. Invalid abstractions fail closed. Core remains authoritative for
whether the observation is expected and how planning state advances.

P4 fake execution composes `FakeBackend` and `FakeStateObserver` around one
in-memory `FakePlant`. The backend mutates the plant after its configured delay;
the observer emits `FakePlantObservation`; `FakeStateAbstraction` revalidates the
ordered symbolic state. The plant contains no task route or Demo-D1 logic.

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
