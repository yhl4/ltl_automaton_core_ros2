# KTH LTL 规划器 ROS2 闭环迁移演示

本演示复用 KTH ROS1 基线中的 `example_ts.yaml` 和
`example_ltl_formula.yaml`，集中验证 ROS2 迁移后的规划、状态反馈和重规划闭环。
不包含 Gazebo、Nav2、真实机器人、LLM 或图像到 TS。

## 1. 演示内容

演示依次覆盖：

1. 使用 KTH 原版 TS 和任务进行初始最优规划；
2. 根据 `/ts_state` 更新 Product belief 并推进计划；
3. 通过 `/replanning` 从当前状态切换 LTL 任务；
4. 收到合法但非预期状态后自动重规划。

ROS2 主链路为：

```text
KTH TS + LTL task
        ↓
Büchi + Product Automaton
        ↓
optimal prefix-suffix plan
        ↓
/next_move_cmd
        ↓
demo driver → /ts_state
        ↓
plan progression or replanning
```

## 2. KTH 原版输入

演示 TS 位于：

```text
config/kth_example_ts.yaml
```

它保留 KTH 原版的两个状态维度、节点、动作和权重：

```text
2d_pose_region: r1 ↔ r2, r1 ↔ r3
turtlebot_load: unloaded ↔ loaded
```

`pick` 和 `drop` 只能在 `r2` 执行。

任务位于：

```text
config/kth_demo_tasks.yaml
```

初始任务保持 KTH 原版：

```text
hard: ([]<> (r1 && loaded)) && ([]<> (r1 && unloaded))
soft: []!r3
```

在线切换任务只使用原 TS 中存在的 AP：

```text
hard: <> r3
soft: (r3 || ! r3)
```

## 3. 构建

```bash
cd ~/ltl_ros2_ws
source /opt/ros/humble/setup.bash

colcon build \
  --symlink-install \
  --packages-up-to ltl_automaton_planner

source install/setup.bash
```

## 4. 一条命令运行完整演示

```bash
ros2 launch \
  ltl_automaton_planner \
  kth_demo.launch.py \
  start_driver:=true \
  scenario:=full
```

`full` 场景的固定过程为：

```text
(r1, unloaded)
  --goto_r2--> (r2, unloaded)
  --pick-----> (r2, loaded)
  --goto_r1--> (r1, loaded)

调用 /replanning，将任务切换为 <> r3

Planner 期望 goto_r3
Demo Driver 合法偏离到 (r2, loaded)
Planner 从 (r2, loaded) 自动重规划
  --goto_r1--> (r1, loaded)
  --goto_r3--> (r3, loaded)
```

Driver 是确定性的演示节点，不是机器人执行器。它只订阅
`/next_move_cmd`、发布 `/ts_state`，并在指定阶段调用 `/replanning`。

## 5. 分阶段现场演示

### 5.1 启动 Planner

终端 1：

```bash
source /opt/ros/humble/setup.bash
source ~/ltl_ros2_ws/install/setup.bash

ros2 launch \
  ltl_automaton_planner \
  kth_demo.launch.py
```

启动成功后重点展示：

```text
Initial LTL planning succeeded.
Prefix actions: [...]
Suffix actions: [...]
Publishing possible LTL states: [...]
Published next move: goto_r2
```

### 5.2 正常状态反馈

终端 2：

```bash
source /opt/ros/humble/setup.bash
source ~/ltl_ros2_ws/install/setup.bash

ros2 run \
  ltl_automaton_planner \
  kth_demo_driver \
  --ros-args \
  -p scenario:=normal \
  -p max_steps:=3
```

前三次状态更新为：

```text
goto_r2 → (r2, unloaded)
pick    → (r2, loaded)
goto_r1 → (r1, loaded)
```

Planner 日志中的 `possible_ltl_states`、当前状态和下一动作应同步改变。

### 5.3 在线任务重规划

正常推进到 `(r1, loaded)` 后执行：

```bash
ros2 service call \
  /replanning \
  ltl_automaton_msgs/srv/TaskPlanning \
  "{hard_task: '<> r3', soft_task: '(r3 || ! r3)'}"
```

应看到：

```text
Received task replanning request.
Replanning from TS state: ('r1', 'loaded')
Task replanning succeeded.
Published next move: goto_r3
```

### 5.4 合法状态偏离与自动重规划

此时 Planner 期望 `(r3, loaded)`。发布原 TS 中合法的另一个后继：

```bash
ros2 topic pub --once \
  /ts_state \
  ltl_automaton_msgs/msg/TransitionSystemStateStamped \
  "{ts_state: {states: ['r2', 'loaded'], \
  state_dimension_names: ['2d_pose_region', 'turtlebot_load']}}"
```

应看到：

```text
Unexpected TS state. Expected ('r3', 'loaded'),
received ('r2', 'loaded'). Replanning from the received state.
Publishing possible LTL states: [(['r2', 'loaded'], ...)]
Replanning succeeded from ('r2', 'loaded').
Published next move: goto_r1
```

## 6. Driver 场景

| `scenario` | 行为 |
|---|---|
| `normal` | 按 Planner 动作正常发布状态 |
| `task_replanning` | 正常推进三步后切换到 `<> r3` |
| `deviation` | 第一条 `goto_r2` 改为合法分支 `r3` |
| `full` | 正常推进、任务切换、合法偏离和恢复 |

可调参数：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `scenario` | `normal` | 演示场景 |
| `step_delay` | `1.0` | 每次状态反馈间隔，单位秒 |
| `max_steps` | `8` | 最多发布的状态数 |
| `replanning_after_steps` | `3` | 切换任务前的正常反馈数 |

## 7. 3–5 分钟现场讲解脚本

| 时间 | 操作与讲解重点 |
|---|---|
| 0:00–0:40 | 指出输入来自 KTH 原版 TS/LTL，核心规划语义未改变 |
| 0:40–1:30 | 启动 Planner，解释 prefix、suffix、possible states 和第一动作 |
| 1:30–2:20 | 运行前三步正常反馈，指出 Product belief 和执行游标同步更新 |
| 2:20–3:10 | 切换任务为 `<> r3`，对比新旧计划和下一动作 |
| 3:10–4:10 | 注入合法偏离状态，展示从实际状态自动重规划并恢复 |
| 4:10–4:40 | 总结 ROS2 通信闭环与在线重规划已经完成 |

推荐讲解：

```text
这是 KTH 原版的 Transition System 和 LTL 任务。
当前工作没有修改 Product Automaton 的规划语义，
主要完成了 ROS1 到 ROS2 的接口迁移和闭环执行。

状态反馈不只是界面显示，它会更新 Product belief 和执行游标。
任务变化时从当前实际状态重建计划；出现合法偏离时也会自动恢复。
```

## 8. 建议的导师展示布局

左侧显示 KTH TS：节点、动作、初始状态、当前状态和 `r3` 目标。

中间持续显示：

```text
Hard task
Soft task
Current TS state
Current possible Product states
Prefix plan
Suffix plan
Next move
```

右侧保留 ROS2 日志，依次指出初始规划、正常推进、任务重规划和偏离重规划。
主画面不展示完整 Product 图，除非需要回答算法细节。

## 9. 验收检查

```bash
ros2 node list
ros2 topic list
ros2 service type /replanning
ros2 topic info /possible_ltl_states --verbose
```

需要确认：

- 只有一个 `/ltl_planner`；
- `/possible_ltl_states` 的 Publisher count 为 1；
- `/prefix_plan`、`/suffix_plan`、`/next_move_cmd` 均存在；
- `/replanning` 类型为 `ltl_automaton_msgs/srv/TaskPlanning`；
- 正常反馈、任务切换和偏离恢复期间 possible states 均非空。
