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

## Generator

The output path is explicit so an installed package is never modified:

```bash
ros2 run ltl_automaton_std_transition_systems \
  region_2d_pose_definition /tmp/generated_ts.yaml
```

Generated actions include planner guards and the initial grid cell is derived
from the entered initial position.
