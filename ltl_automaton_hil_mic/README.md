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

The controller package consumes the `check_for_trap` service but does not
provide it. The ROS 2 TrapDetection planner plugin is delivered separately.
