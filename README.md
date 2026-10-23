# LTL Automaton Core for ROS 2

ROS 2 migration of KTH-SML's `ltl_automaton_core`. The planning core
constructs transition systems, Buchi and product automata, and searches for
prefix/suffix accepting runs. ROS communication and symbolic execution are
separate packages.

## Scope and package boundaries

| Package | Responsibility |
| --- | --- |
| `ltl_automaton_planner_core` | ROS-independent YAML/guard parsing, automata, planning and replanning |
| `ltl_automaton_msgs` | Generated ROS messages, services and actions |
| `ltl_automaton_planner` | ROS node, planning services, state feedback and graph snapshots |
| `ltl_automaton_execution` | Optional accepted-run resolution and replaceable execution backend |
| `ltl_automaton_std_transition_systems` | 2D pose / 6D joint-space monitors and TS generation |
| `ltl_automaton_hil_mic` | Bool/velocity mixed-initiative controllers and read-only trap diagnostics |

The core does not import `rclpy`. The planner does not depend on the optional
execution package, whose current `FakeBackend` is symbolic: it does not provide
Gazebo, Isaac Sim or robot control.

Core is the general LTL planning/execution baseline. CMR algorithms, experiment
datasets, benchmark campaigns and provider integrations belong in independently
versioned research projects, outside Core's mainline dependency graph. Adapters
must use explicit interfaces without importing experiment internals into the
planner core. No CMR implementation is included in this cleanup.

At the 2026-10-23 audit, main was `2624458c`; open
[PR #10](https://github.com/yhl4/ltl_automaton_core_ros2/pull/10)
(`10b3d632`) combines further ROS migration and CMR experiments.
Draft [PR #11](https://github.com/yhl4/ltl_automaton_core_ros2/pull/11)
(`32803381`) is stacked on the #10 branch. Those are separate, unmerged
baselines. This branch neither adopts their execution identity/API changes nor
claims their validation results. Selecting and separating a broader migration
baseline requires a dedicated architecture decision.

## Environment

The existing ROS acceptance baseline is Ubuntu 22.04, ROS 2 Humble and Python
3.10. Ubuntu 24.04 / Jazzy and other ROS/Python/OS combinations have not received
equivalent acceptance validation. The offline CI jobs use Ubuntu 22.04 / Python
3.10; they do not establish ROS or hardware acceptance.

Python dependencies are NetworkX, PLY and PyYAML. They are declared both in
planner-core's Python distribution metadata and its ROS `package.xml`.
The external `ltl2ba` executable is required for real formula translation and
end-to-end planning; it is not a Python dependency and is not bundled.

## Install the planning core without ROS

From a clone of this repository:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -c ci/constraints.txt setuptools wheel
python -m pip install --no-build-isolation -c ci/constraints.txt './ltl_automaton_planner_core[test]'
```

`ci/constraints.txt` records the dependency versions exercised by offline CI.
A normal `pip install ./ltl_automaton_planner_core` also installs its runtime
Python dependencies. This installs only the core, not generated ROS interfaces,
ROS nodes or the translator executable.

A minimal parsing smoke check is:

```bash
python - <<'PY'
from ltl_automaton_planner_core.boolean_formulas.parser import parse
from ltl_automaton_planner_core.configuration.transition_system import import_ts_from_file

assert parse('cargo').check({'cargo'})
assert import_ts_from_file('state_dim: [region]')['state_dim'] == ['region']
PY
```

### External translator

Obtain `ltl2ba` from the
[authors' project/download page](https://lsv.ens-paris-saclay.fr/~gastin/ltl2ba/),
build it following its supplied instructions, and place the executable on
`PATH`. Record the source version and checksum with your experiment results.
This repository does not currently pin or automate a translator source build.

```bash
command -v ltl2ba
ltl2ba -f '<> cargo'
```

The second command must produce a Promela `never` claim. A missing executable,
OS launch failure, timeout, nonzero exit or empty output raises
`LTL2BAError`; an empty input formula raises `ValueError`.
Offline subprocess tests simulate those cases and do not validate a real
translator.

## Build the ROS workspace

Install ROS 2 Humble and `rosdep` first. Use a workspace path of your choice:

```bash
export LTL_WS="$HOME/ltl_ws"
mkdir -p "$LTL_WS/src"
git clone https://github.com/yhl4/ltl_automaton_core_ros2.git "$LTL_WS/src/ltl_automaton_core_ros2"
cd "$LTL_WS"
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-up-to ltl_automaton_planner
source install/setup.bash
```

Install and check `ltl2ba` separately as above. To build every package, omit
`--packages-up-to`. An independently maintained ROS environment is required;
the Python-only virtual environment above does not supply ROS.

## Quick start

```bash
source /opt/ros/humble/setup.bash
source "$LTL_WS/install/setup.bash"
ros2 launch ltl_automaton_planner planner.launch.py
```

The default launch uses
[`minimal_ts.yaml`](ltl_automaton_planner/config/minimal_ts.yaml),
hard task `<> r2` and a tautological soft task. Successful startup logs the
initial plan, prefix/suffix actions, possible LTL states and next move. The node
then waits for state observations and remains running.

The [planning API](ltl_automaton_planner/docs/planning_api.md) defines the
mainline V0.1 consumer contract. The
[KTH demo guide](ltl_automaton_planner/docs/KTH_ROS2_DEMO.md) contains the larger
worked example; these existing examples and interfaces remain unchanged.

### Configuration

| Parameter | Meaning |
| --- | --- |
| `transition_system_path` | TS YAML file |
| `hard_task`, `soft_task` | Hard specification and optional soft preference |
| `beta` | Soft-task distance multiplier in product-edge cost |
| `gamma` | Suffix cost multiplier in accepting-run search |
| `initial_ts_state_from_agent` | Wait for a valid first observation before planning |
| `replan_on_unplanned_move` | Replan from unexpected TS feedback |
| `check_timestamp` | Discard feedback with the same timestamp as the last observation |
| `plugin_config_path` | Optional plugin YAML file |

Hard guards determine feasible product edges. Their satisfaction is not encoded
as a large penalty. Product-edge cost is transition cost plus `beta` times
soft-task distance; `gamma` weights the suffix in accepting-run search.

Inspect parameters with `ros2 param get /ltl_planner <parameter>`.
The `replan_on_unplanned_move` and `check_timestamp` behavior flags can change
through `ros2 param set`. Use the replanning service to change hard/soft tasks
transactionally, so a failed new plan retains the active plan.

To use observed initial states:

```bash
ros2 launch ltl_automaton_planner planner.launch.py initial_ts_state_from_agent:=true
```

The node maps `state_dimension_names` to TS dimensions; invalid or mismatched
observations do not start planning.

### Topics and services

| Endpoint | Type | Direction / purpose |
| --- | --- | --- |
| `/ts_state` | `ltl_automaton_msgs/msg/TransitionSystemStateStamped` | Input state observation |
| `/next_move_cmd` | `std_msgs/msg/String` | Output next action |
| `/prefix_plan`, `/suffix_plan` | `ltl_automaton_msgs/msg/LTLPlan` | Output complete accepting-run segments |
| `/possible_ltl_states` | `ltl_automaton_msgs/msg/LTLStateArray` | Output current possible product states |
| `/replanning` | `ltl_automaton_msgs/srv/TaskPlanning` | Replace the task after successful planning |

For example, observe retained plan output and request a new task:

```bash
ros2 topic echo /prefix_plan ltl_automaton_msgs/msg/LTLPlan \
  --qos-reliability reliable --qos-durability transient_local --once
ros2 service call /replanning ltl_automaton_msgs/srv/TaskPlanning \
  "{hard_task: '<> r2', soft_task: '(r2 || ! r2)'}"
```

A successful service response has `success: true` and republishes state/plan/action
outputs. An infeasible task, unknown state or planning exception retains the
previous task, TS initial state, product, accepting run and execution cursor.

For the symbolic minimal example, state feedback can be published manually:

```bash
ros2 topic pub --once /ts_state \
  ltl_automaton_msgs/msg/TransitionSystemStateStamped \
  "{ts_state: {states: ['r2'], state_dimension_names: ['region']}}"
```

Expected observations advance the cursor. Repeated unexpected states are ignored;
other unexpected states trigger replanning when enabled. The possible-product-state
update precedes cursor advancement and next-action publication.

### Plugins and optional packages

Plugin configuration preserves the class/module/argument contract:

```yaml
plugins:
  ExamplePlugin:
    path: example_package.example_plugin
    args:
      threshold: 3
```

Plugins implement `__init__(ltl_planner, args)`, `init()`,
`set_sub_and_pub()` and `run_at_ts_update(ts_state)`. ROS 2 plugins use
`set_node(node)` to obtain the host node. A plugin failure is logged without
terminating the planner or preventing other plugins from running. ROS 1 plugins
that import `rospy` still require a ROS 2 communication-layer migration.

Standard TS tools map pose messages to 2D regions and the first six joint
positions to 6D regions, and can generate compatible grid/station YAML.
Bool/velocity HIL controllers use asynchronous trap service requests; unavailable
services, disconnected states and stale observations fall back to navigation
commands. `TrapDetectionPlugin` is read-only and does not replace an active plan.

## Validation and contribution workflow

Create a focused branch from main, keep public interfaces and scientific
semantics stable, and include a regression for a reproducible bug. Describe the
baseline, actual commands and unrun acceptance surfaces in an English PR.
Keep credentials and machine-specific absolute paths out of examples.

Run the same offline checks as CI from the repository root:

```bash
python -m pip install -c ci/constraints.txt flake8
python -m compileall -q ltl_automaton_planner_core/ltl_automaton_planner_core
python -m flake8 --select=E9,F63,F7,F82 \
  ltl_automaton_planner_core/ltl_automaton_planner_core \
  ltl_automaton_planner_core/test/test_ltl2ba.py \
  ltl_automaton_planner_core/test/test_distribution.py
python -m pytest -q ltl_automaton_planner_core/test \
  --ignore=ltl_automaton_planner_core/test/test_copyright.py \
  --ignore=ltl_automaton_planner_core/test/test_flake8.py \
  --ignore=ltl_automaton_planner_core/test/test_pep257.py \
  --ignore=ltl_automaton_planner_core/test/test_ltl2ba_integration.py \
  --ignore=ltl_automaton_planner_core/test/test_buchi_integration.py \
  --ignore=ltl_automaton_planner_core/test/test_ltl_planner.py
git diff --check
```

The workflow also builds a wheel, installs it into a clean environment using
only wheel-declared runtime dependencies, and runs parsing/error smoke checks
outside the source checkout. It does not collect ROS tests or report missing
external tools as successful integration coverage.

With a real translator on `PATH`, run the complete core functional suite
(including planner/translator integration) by removing the last three ignores.
The ament lint files require their ROS tools. For ROS acceptance, build the
workspace, source ROS and its install overlay, then run:

```bash
cd "$LTL_WS"
colcon test --packages-up-to ltl_automaton_planner
colcon test-result --verbose
```

Execution, HIL and standard TS packages have separate tests; include the relevant
packages when changing them. ROS build, generated interfaces, launch/DDS services,
real translator behavior, optional controllers and hardware are outside the
offline CI jobs. A green offline run must not be presented as those checks passing.

## Known limitations

IRL has not been integrated into the transactional mainline ROS 2 planner
contract; the old in-place mutation implementation remains in Git history.
Further migration needs explicit state isolation and execution identity design.

Fast DDS can emit `RTPS_TRANSPORT_SHM Error: Failed init_port ...`.
If discovery or communication fails, inspect leftover nodes, duplicate publishers
and shared-memory locks rather than assuming a warning is harmless. Broader
ROS migration and experimental branch selection remain separate work.
