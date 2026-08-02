# ltl_automaton_core_ros2

A work-in-progress ROS 2 port and architectural refactor of
[`KTH-SML/ltl_automaton_core`](https://github.com/KTH-SML/ltl_automaton_core).

The project provides building blocks for planning robot tasks expressed in
Linear Temporal Logic (LTL). The ROS 2 refactor separates the planning
algorithms from the ROS communication layer so that the core logic can be
tested and reused as ordinary Python code.

> **Development status:** This repository is under active migration. The ROS 2
> interfaces and part of the ROS-independent transition-system core are
> available. A complete ROS 2 planner node and end-to-end runtime are not
> available yet.

## Design goals

- Preserve the planning semantics of the original ROS 1 implementation.
- Separate ROS-independent algorithms from ROS 2 nodes and message handling.
- Support unit testing without starting ROS.
- Maintain one source tree for:
  - Ubuntu 22.04 with ROS 2 Humble;
  - Ubuntu 24.04 with ROS 2 Jazzy.
- Introduce ROS 2 functionality incrementally, with each migrated component
  covered by tests.

## Current architecture

```text
Transition-system YAML
          |
          v
configuration.transition_system
          |
          v
NetworkX state models
          |
          v
TSModel composition
          |
          v
Composed transition system

Büchi automaton, product automaton, planner node, execution monitoring
and replanning are planned migration stages.
```

The ROS-independent core must not import `rclpy` or depend on a running ROS
graph. ROS 2 nodes will be implemented later as adapters around this core.

## Repository layout

```text
ltl_automaton_core_ros2/
├── ltl_automaton_msgs/
│   ├── msg/                         # ROS 2 message definitions
│   ├── srv/                         # ROS 2 service definitions
│   ├── CMakeLists.txt
│   └── package.xml
│
├── ltl_automaton_planner_core/
│   ├── ltl_automaton_planner_core/
│   │   ├── boolean_formulas/        # Boolean guard lexer and parser
│   │   ├── configuration/           # YAML-to-state-model conversion
│   │   └── ltl_tools/               # Transition-system composition
│   ├── test/
│   ├── package.xml
│   └── setup.py
│
├── LICENSE
└── README.md
```

## Implemented components

### `ltl_automaton_msgs`

ROS 2 interface package implemented with `ament_cmake` and
`rosidl_default_generators`.

Messages:

- `LTLPlan`
- `LTLState`
- `LTLStateArray`
- `LTLStateRuns`
- `TransitionSystemState`
- `TransitionSystemStateStamped`

Services:

- `ClosestState`
- `TaskPlanning`
- `TrapCheck`

### `ltl_automaton_planner_core`

ROS-independent Python package containing:

- Boolean guard tokenization and parsing;
- Boolean guard satisfaction checks;
- Boolean violation-distance calculations;
- Composition of multiple state dimensions into a transition system;
- Guard-controlled transition generation;
- Transition-system initial-state updates;
- YAML transition-system loading;
- Conversion from transition-system dictionaries to NetworkX state models;
- Unit and code-style tests.

## Supported environments

| Platform | Status |
|---|---|
| Ubuntu 22.04 + ROS 2 Humble | Primary development environment |
| Ubuntu 24.04 + ROS 2 Jazzy | Compatibility target; full validation pending |

Python 3.10 or newer is required by the planner core.

## Dependencies

The principal runtime dependencies are:

- ROS 2;
- Python 3;
- PLY;
- NetworkX;
- PyYAML.

Testing uses:

- `pytest`;
- `ament_flake8`;
- `ament_pep257`;
- `ament_copyright`.

Dependencies should be installed through `rosdep` from the package manifests.

## Build

Create a ROS 2 workspace and clone the repository into its `src` directory:

```bash
mkdir -p ~/ltl_ros2_ws/src
cd ~/ltl_ros2_ws/src

git clone git@github.com:yhl4/ltl_automaton_core_ros2.git
```

Source the ROS 2 environment:

```bash
source /opt/ros/$ROS_DISTRO/setup.bash
```

Install dependencies:

```bash
cd ~/ltl_ros2_ws

rosdep install \
  --from-paths src \
  --ignore-src \
  --rosdistro "$ROS_DISTRO" \
  -r -y
```

Build the current packages:

```bash
colcon build \
  --symlink-install \
  --packages-select \
  ltl_automaton_msgs \
  ltl_automaton_planner_core
```

Source the workspace:

```bash
source ~/ltl_ros2_ws/install/setup.bash
```

## Test

Run the package tests:

```bash
cd ~/ltl_ros2_ws

colcon test \
  --packages-select \
  ltl_automaton_msgs \
  ltl_automaton_planner_core \
  --event-handlers console_direct+
```

Display the result summary:

```bash
colcon test-result --verbose
```

For fast development feedback, individual Python tests may also be run from the
planner-core package directory:

```bash
cd ~/ltl_ros2_ws/src/ltl_automaton_core_ros2/ltl_automaton_planner_core

python3 -m pytest test -v
```

## Minimal transition-system example

The following example loads a one-dimensional transition system from YAML,
converts it into a NetworkX state model, and builds the full transition system.

```python
from io import StringIO

from ltl_automaton_planner_core.configuration.transition_system import (
    import_ts_from_file,
    state_models_from_ts,
)
from ltl_automaton_planner_core.ltl_tools.ts import TSModel


ts_yaml = """
state_dim:
  - region

state_models:
  region:
    initial: r1
    nodes:
      r1:
        connected_to:
          r2: goto_r2
      r2:
        connected_to: {}

actions:
  goto_r2:
    guard: "1"
    weight: 2.0
"""

ts_dict = import_ts_from_file(StringIO(ts_yaml))
state_models = state_models_from_ts(ts_dict)

transition_system = TSModel(state_models)
transition_system.build_full()

print("States:", list(transition_system.nodes))
print("Initial:", transition_system.graph["initial"])
print("Transitions:", list(transition_system.edges(data=True)))
```

Expected state structure:

```text
States: [('r1',), ('r2',)]
Initial: {('r1',)}
```

## Development workflow

Development should be performed on a feature branch rather than directly on
`main`.

```bash
git switch main
git pull --ff-only origin main
git switch -c <feature-branch>
```

After implementing and testing one coherent change:

```bash
git add <changed-files>
git commit -m "<clear commit message>"
git push -u origin <feature-branch>
```

Create one pull request from the feature branch into `main`. Additional commits
pushed to the same source branch are automatically added to that open pull
request.

Generated files must not be committed. In particular, keep the following out of
Git:

```text
.idea/
.vscode/
build/
install/
log/
__pycache__/
.pytest_cache/
*.egg-info/
```

## Roadmap

- [x] Create ROS 2 message and service interface package.
- [x] Separate a ROS-independent Python planner-core package.
- [x] Port Boolean guard parsing and evaluation.
- [x] Port transition-system composition.
- [x] Add YAML-to-state-model conversion.
- [ ] Port Büchi-automaton construction.
- [ ] Port product-automaton construction and search.
- [ ] Add the ROS 2 planner adapter and `rclpy` node.
- [ ] Port state monitoring, execution feedback, and replanning.
- [ ] Add ROS 2 launch and example configurations.
- [ ] Validate the complete stack on Humble and Jazzy.
- [ ] Add continuous integration.

## Relationship to the upstream project

This repository is derived from the original ROS 1 project:

- [`KTH-SML/ltl_automaton_core`](https://github.com/KTH-SML/ltl_automaton_core)

The ROS 2 migration aims to preserve the original planning behavior while
modernizing the package structure, interface generation, build system, testing,
and separation of concerns.

## Publication

The original project is associated with:

> R. Baran, X. Tan, P. Varnai, P. Yu, S. Ahlberg, M. Guo, W. Shaw Cortez,
> and D. V. Dimarogonas, “A ROS Package for Human-In-the-Loop Planning and
> Control under Linear Temporal Logic Tasks,” 2021 IEEE 17th International
> Conference on Automation Science and Engineering (CASE), pp. 2182–2187,
> 2021.

```bibtex
@INPROCEEDINGS{9551648,
  author={Baran, Robin and Tan, Xiao and Varnai, Peter and Yu, Pian and
          Ahlberg, Sofie and Guo, Meng and Cortez, Wenceslao Shaw and
          Dimarogonas, Dimos V.},
  booktitle={2021 IEEE 17th International Conference on Automation Science
             and Engineering (CASE)},
  title={A ROS Package for Human-In-the-Loop Planning and Control under
         Linear Temporal Logic Tasks},
  year={2021},
  pages={2182--2187},
  doi={10.1109/CASE49439.2021.9551648}
}
```

## License

This project is distributed under the MIT License. See [`LICENSE`](LICENSE).
