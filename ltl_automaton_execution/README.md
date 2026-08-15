# LTL Automaton Execution

`ltl_automaton_execution` turns Core's retained formal execution authority into
symbolic transition-system observations through a simulator-independent backend
boundary.

The public input authority is
`/planning_execution_observation` plus the identity-matched
`/get_planning_graph_snapshot` response. The generation-bearing observation is
preferred over the legacy identity-less `/next_move_cmd` topic. The resolver
uses only Product nodes, Product edges, and the retained prefix/suffix accepted
run in those ROS contracts; it never imports planner internals or searches for a
different route.

An `ExecutionBackend` receives an `ExecutionStep` containing an action and exact
symbolic source/target states. It completes asynchronously with an
`ExecutionResult`. P3 supplies a `FakeBackend`; future Gazebo, Isaac Sim, or
real-robot backends can map the same step to controller commands and report the
resulting symbolic observation without changing `/ts_state` publication or Core.

Fake execution is symbolic execution, not physics simulation. It provides no
kinematics, trajectory generation, collision checking, perception, or hardware
control, and this package does not claim Gazebo or Isaac Sim support.
