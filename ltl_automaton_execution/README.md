# LTL Automaton Execution

`ltl_automaton_execution` resolves Core's retained formal execution authority
and keeps command execution separate from observed transition-system truth.

The public input authority is
`/planning_execution_observation` plus the identity-matched
`/get_planning_graph_snapshot` response. The generation-bearing observation is
preferred over the legacy identity-less `/next_move_cmd` topic. The resolver
uses only Product nodes, Product edges, and the retained prefix/suffix accepted
run in those ROS contracts; it never imports planner internals or searches for a
different route.

The resolver indexes only one immutable snapshot at a time and reuses its
node and retained-action lookup for subsequent commands. A replacement snapshot
rebuilds the index. Missing accepted-run nodes are rejected as resolution errors.

If the snapshot service has not been discovered yet, the node retains the
latest current-authority observation and retries discovery. A newer observation
replaces the pending one, including while a snapshot request is in flight. On
response, dispatch uses that latest observation after checking its authority;
a newer observation without a next action suppresses the old command. Only one
accepted snapshot is cached, and dispatch deduplication records are cleared when
planning authority advances.

Within one generation, dispatch is deduplicated by Product state set and action.
An accepting cycle that revisits the same fingerprint stops dispatching at that
point. The V0.1 observation has no execution-step sequence to distinguish a
retransmission from a new visit; continuous cyclic execution remains unresolved.
Planning an accepted prefix/suffix alone does not verify continuous execution.

An `ExecutionBackend` receives an `ExecutionStep` containing an action and exact
symbolic source/target states. It completes asynchronously with an
`ExecutionCompletion` containing only execution success and a message. Backend
completion is not state truth and never publishes `/ts_state`.

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
control, and this package does not claim Gazebo or Isaac Sim support.
