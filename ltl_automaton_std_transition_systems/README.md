# ltl_automaton_std_transition_systems

ROS 2 Humble migration of the standard KTH transition-system tools.

The package provides:

- `region_2d_pose_monitor`: maps one of the four standard
  `geometry_msgs` pose types to a square or station region.
- `region_6d_jointspace_monitor`: maps the first six positions of a
  `sensor_msgs/JointState` message to a spherical joint-space region.
- `region_2d_pose_definition`: interactively generates a planner-compatible
  grid and station transition-system YAML file.

## 2D pose monitor

```bash
ros2 launch ltl_automaton_std_transition_systems \
  region_2d_pose_monitor.launch.py
```

Parameters:

- `transition_system_path`: TS YAML path.
- `pose_message_type`: `geometry_msgs/msg/Pose`, `PoseStamped`,
  `PoseWithCovariance`, or `PoseWithCovarianceStamped`.

Topics and service retain the ROS 1 names:

- subscribes `agent_2d_region_pose` and `station_access_request`
- publishes transient-local `current_region`
- serves `closest_region` using `ltl_automaton_msgs/srv/ClosestState`

Input x/y coordinates and all quaternion components must be finite; a zero
quaternion is rejected. Supply a unit quaternion following the
[ROS 2 convention](https://github.com/ros2/ros2_documentation/blob/humble/source/Tutorials/Intermediate/Tf2/Quaternion-Fundamentals.rst);
the monitor keeps the existing yaw formula without normalizing the input.
Rejected feedback is logged and does not publish a region or replace the last
valid pose used by `closest_region`. That service reports the last valid pose;
it does not certify observation freshness.
Programmatic model calls also report overflow in the x/y or quaternion
finite-value check as the existing `ValueError`, retaining the original cause.
The planar model continues to ignore the position z coordinate.

## 6D joint-space monitor

```bash
ros2 launch ltl_automaton_std_transition_systems \
  region_6d_jointspace_monitor.launch.py \
  transition_system_path:="$(ros2 pkg prefix --share ltl_automaton_std_transition_systems)/config/example_6d_jointspace_ts.yaml"
```

`transition_system_path` is required and selects the TS YAML. The monitor subscribes to
`feedback/joint_state` and publishes transient-local `current_region`.
The first six joint positions must be present and finite; later positions remain
ignored. Invalid feedback is logged without changing or publishing the last
valid region. Region membership retains the strict distance `< radius` rule.
Programmatic model calls report invalid first-six coordinates as `ValueError`,
including numeric overflow during their finite-value check.

The monitors' `transition_system_path` and the 2D monitor's `pose_message_type`
are startup-only, read-only parameters. Configure them through launch arguments
or startup ROS parameters. Runtime writes are rejected because the running
model and subscription are not reloaded. The inherited `use_sim_time` parameter
retains ROS 2's dynamic clock behavior.

## Generator

The output path is explicit so an installed package is never modified:

```bash
ros2 run ltl_automaton_std_transition_systems \
  region_2d_pose_definition /tmp/generated_ts.yaml
```

Generated actions include planner guards and the initial grid cell is derived
from the entered initial position.
Cell side length must be positive. Grid/station geometry, the initial x/y
position and derived cell centers must be finite. Violations of these geometry
checks raise `ValueError` before a TS file is written.
