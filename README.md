# LTL Automaton Core — ROS 2 Migration

本仓库是对 KTH-SML `ltl_automaton_core` 的 ROS 2 迁移版本，目标是在保留原有 LTL 规划语义的基础上，将消息接口、规划核心与 Planner 节点迁移到 ROS 2。

当前版本重点完成了：

- Transition System、Büchi Automaton 与 Product Automaton 的 ROS 无关核心；
- 基于 `ltl2ba` 的 LTL 到 Büchi 自动机转换；
- prefix–suffix 接受运行搜索；
- ROS 2 Planner 节点；
- TS 状态反馈、计划推进和意外状态重规划；
- 计划、下一动作与候选 Product 状态发布；
- 运行时任务重规划服务；
- 标准 2D pose 与 6D joint-space TS 状态监控及 2D TS 生成工具；
- Bool 与 Velocity mixed-initiative HIL 控制器；
- `TrapDetectionPlugin` 与 `IRLPlugin` Planner 插件。

> 当前迁移保持 Product Automaton 与离散规划算法的核心语义，不将 ROS 2 通信逻辑写入规划核心。

---

## 1. 当前支持范围

### 1.1 规划核心

当前已迁移并验证的核心模块包括：

- Transition System 解析与组合；
- Boolean guard 解析；
- Promela 生成；
- `ltl2ba` 调用与输出解析；
- Büchi Automaton 构建；
- TS × Büchi Product Automaton 构建；
- prefix–suffix 接受运行搜索；
- 静态 LTL 规划；
- 基于当前 TS 状态的重规划；
- 基于新 hard/soft task 的任务重规划。

规划核心位于：

```text
ltl_automaton_planner_core/
```

该包不依赖 `rclpy`，可独立进行单元测试。

### 1.2 ROS 2 接口

当前 ROS 2 接口包：

```text
ltl_automaton_msgs/
```

已包含 Planner 使用的消息与服务定义，包括：

- `TransitionSystemState`
- `TransitionSystemStateStamped`
- `LTLState`
- `LTLStateArray`
- `LTLPlan`
- `TaskPlanning`

### 1.3 ROS 2 Planner 节点

Planner 节点位于：

```text
ltl_automaton_planner/
```

当前支持：

- 从 YAML 文件加载 Transition System；
- 根据 hard task 和 soft task 构建 LTL 计划；
- 可选等待机器人发布真实初始 TS 状态后再构建计划；
- 发布完整 prefix 与 suffix；
- 发布当前下一动作；
- 接收 TS 状态反馈；
- 正常推进执行游标；
- 意外状态下从新状态重新规划；
- 发布当前可能的 Product 状态；
- 通过服务请求切换任务并重新规划。

### 1.4 标准 Transition System 工具

标准状态监控与 TS 生成工具位于：

```text
ltl_automaton_std_transition_systems/
```

当前支持：

- 将 `Pose`、`PoseStamped`、`PoseWithCovariance` 或
  `PoseWithCovarianceStamped` 映射为 2D square/station region；
- 保留 `current_region`、`station_access_request` 和 `closest_region`
  ROS 1 通信契约；
- 将 `JointState` 的前六个关节位置映射为 6D joint-space region；
- 交互生成可被当前 planner core 直接加载的 2D grid/station TS YAML。

### 1.5 HIL mixed-initiative 控制器

ROS 2 HIL 控制器位于：

```text
ltl_automaton_hil_mic/
```

当前支持：

- Bool 命令仲裁：规划器命令直接通过，人工命令仅在 TS 连通且非 trap 时通过；
- Velocity 命令仲裁：依据 trap 距离平滑混合人工与导航速度；
- trap 服务不可用、TS 未连通或状态超时时安全回退到导航命令；
- 通过异步 ROS 2 service client 查询 `check_for_trap`，避免阻塞控制回调。

---

## 2. 软件环境

当前版本主要在以下环境中验证：

- Ubuntu 22.04
- ROS 2 Humble
- Python 3.10
- NetworkX
- PLY
- PyYAML
- `ltl2ba`

Ubuntu 24.04 与 ROS 2 Jazzy 仍需完成独立兼容性验证。

---

## 3. 仓库结构

```text
.
├── ltl_automaton_msgs/
│   ├── msg/
│   └── srv/
├── ltl_automaton_planner_core/
│   ├── ltl_automaton_planner_core/
│   │   ├── boolean_formulas/
│   │   ├── configuration/
│   │   └── ltl_tools/
│   └── test/
├── ltl_automaton_planner/
│   ├── config/
│   ├── launch/
│   ├── ltl_automaton_planner/
│   │   └── planner_node.py
│   └── test/
├── ltl_automaton_std_transition_systems/
│   ├── config/
│   ├── launch/
│   ├── ltl_automaton_std_transition_systems/
│   └── test/
├── ltl_automaton_hil_mic/
│   ├── config/
│   ├── launch/
│   ├── ltl_automaton_hil_mic/
│   └── test/
└── README.md
```

---

## 4. 依赖准备

### 4.1 ROS 2 环境

```bash
source /opt/ros/humble/setup.bash
```

### 4.2 Python 依赖

建议通过系统包、`rosdep` 或虚拟环境安装：

```bash
python3 -m pip install networkx ply pyyaml
```

### 4.3 ltl2ba

确保 `ltl2ba` 可执行文件位于 `PATH` 中：

```bash
which ltl2ba
ltl2ba -h
```

若 `which ltl2ba` 没有输出，Planner 将无法把 LTL 公式转换为 Büchi 自动机。

---

## 5. 构建

假设仓库位于 ROS 2 工作空间的 `src` 下：

```text
<workspace>/src/ltl_automaton_core_ros2
```

执行：

```bash
cd <workspace>
source /opt/ros/humble/setup.bash

rosdep install \
  --from-paths src \
  --ignore-src \
  -r \
  -y

colcon build --symlink-install
source install/setup.bash
```

仅构建 Planner 及其依赖：

```bash
colcon build \
  --symlink-install \
  --packages-up-to ltl_automaton_planner
```

---

## 6. 运行 Planner

```bash
source /opt/ros/humble/setup.bash
source <workspace>/install/setup.bash

ros2 launch \
  ltl_automaton_planner \
  planner.launch.py
```

默认 Launch 使用示例 Transition System 和 LTL 任务。启动成功后，日志应包含类似信息：

```text
Initial LTL planning succeeded.
Prefix actions: [...]
Suffix actions: [...]
Published ... possible LTL states.
Published prefix and suffix plans.
Published next move: ...
```

节点会持续运行并等待 `/ts_state`，因此启动终端不会自动返回命令提示符。

---

## 7. 参数

当前 Planner 使用以下参数：

| 参数 | 类型 | 说明 |
|---|---:|---|
| `transition_system_path` | string | Transition System YAML 文件路径 |
| `hard_task` | string | 必须满足的 LTL 任务 |
| `soft_task` | string | 用于软约束或偏好的 LTL 任务 |
| `beta` | double | hard-task 相关代价权重 |
| `gamma` | double | soft-task 相关代价权重 |
| `initial_ts_state_from_agent` | bool | 是否等待首个 `/ts_state` 作为规划初始状态 |
| `replan_on_unplanned_move` | bool | 收到非计划下一状态时是否自动重规划 |
| `check_timestamp` | bool | 是否丢弃时间戳与上一条相同的状态反馈 |
| `plugin_config_path` | string | ROS 2 Planner 插件 YAML 配置文件路径 |

查看运行参数：

```bash
ros2 param get /ltl_planner transition_system_path
ros2 param get /ltl_planner hard_task
ros2 param get /ltl_planner soft_task
ros2 param get /ltl_planner beta
ros2 param get /ltl_planner gamma
ros2 param get /ltl_planner initial_ts_state_from_agent
ros2 param get /ltl_planner replan_on_unplanned_move
ros2 param get /ltl_planner check_timestamp
ros2 param get /ltl_planner plugin_config_path
```

两个行为参数支持通过 `ros2 param set` 动态修改。hard/soft task 的运行时切换
仍使用 `/replanning` 服务，以保证新任务先成功规划再替换当前计划。

---

## 8. Topics

### 8.1 `/ts_state`

- 类型：`ltl_automaton_msgs/msg/TransitionSystemStateStamped`
- 方向：订阅
- 作用：接收机器人或执行器反馈的当前 TS 状态。

示例：

```bash
ros2 topic pub --once \
  /ts_state \
  ltl_automaton_msgs/msg/TransitionSystemStateStamped \
  "{ts_state: {states: ['r2'], state_dimension_names: ['region']}}"
```

Planner 会比较反馈状态与计划中的期望状态：

- 到达期望状态：更新 Product 候选状态并推进计划；
- 收到重复但非期望状态：忽略；
- 收到意外状态：尝试从该状态重新规划。

若启动时设置：

```bash
ros2 launch ltl_automaton_planner planner.launch.py \
  initial_ts_state_from_agent:=true
```

Planner 会先等待首个合法 `/ts_state`，按消息中的
`state_dimension_names` 将状态覆盖到对应 TS 维度，然后才构建并发布初始计划。
无效或维度不匹配的消息不会触发规划，节点会继续等待下一条状态。

### 8.2 `/next_move_cmd`

- 类型：`std_msgs/msg/String`
- 方向：发布
- 作用：发布当前需要执行的下一动作。

```bash
ros2 topic echo \
  /next_move_cmd \
  std_msgs/msg/String \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --once
```

### 8.3 `/prefix_plan`

- 类型：`ltl_automaton_msgs/msg/LTLPlan`
- 方向：发布
- 作用：发布完整 prefix 计划，而不是仅发布尚未执行的剩余部分。

```bash
ros2 topic echo \
  /prefix_plan \
  ltl_automaton_msgs/msg/LTLPlan \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --once
```

### 8.4 `/suffix_plan`

- 类型：`ltl_automaton_msgs/msg/LTLPlan`
- 方向：发布
- 作用：发布接受运行的循环 suffix。

```bash
ros2 topic echo \
  /suffix_plan \
  ltl_automaton_msgs/msg/LTLPlan \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --once
```

### 8.5 `/possible_ltl_states`

- 类型：`ltl_automaton_msgs/msg/LTLStateArray`
- 方向：发布
- 作用：发布当前 TS 观测下仍可能对应的 Product 状态。

每个元素包含：

```text
TransitionSystemState + Büchi state
```

查看初始或最新缓存状态：

```bash
ros2 topic echo \
  /possible_ltl_states \
  ltl_automaton_msgs/msg/LTLStateArray \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --once
```

实时观察后续状态更新：

```bash
ros2 topic echo \
  /possible_ltl_states \
  ltl_automaton_msgs/msg/LTLStateArray \
  --qos-reliability reliable \
  --qos-durability volatile
```

Product 候选状态的更新顺序为：

```text
接收新的 TS 状态
→ 更新 possible Product states
→ 推进计划执行游标
→ 发布下一动作
```

该顺序用于避免 Product 状态与计划游标之间出现一步时序错位。

---

## 9. Planner 插件

通过 `plugin_config_path` 可以加载与 KTH ROS 1 版本同样采用
“类名 + Python 模块路径 + 参数字典”契约的插件：

```yaml
plugins:
  ExamplePlugin:
    path: example_package.example_plugin
    args:
      threshold: 3
```

插件类构造函数及生命周期方法为：

```python
class ExamplePlugin:
    def __init__(self, ltl_planner, args): ...
    def set_node(self, node): ...          # ROS 2 通信插件需要
    def init(self): ...
    def set_sub_and_pub(self): ...
    def run_at_ts_update(self, ts_state): ...
```

`set_node()` 是 ROS 2 适配点，插件通过传入的 Planner Node 创建订阅、发布器、
服务或客户端。其余三个生命周期钩子保持原版语义。单个插件加载或运行失败会被记录，
不会终止 Planner 或阻止其他插件运行。

当前已迁移两个 KTH Planner 插件：

- `TrapDetectionPlugin`：提供 `check_for_trap` 服务，验证 TS 维度并判断候选
  Product 状态是否仍可到达接受环；
- `IRLPlugin`：记录与 TS 反馈一致的 Product 运行，通过 `irl_trigger` 控制学习，
  更新非负 `beta` 后以事务方式重规划，失败时恢复原权重。

可直接使用随 HIL 包安装的配置：

```bash
ros2 run ltl_automaton_planner ltl_automaton_planner \
  --ros-args \
  -p plugin_config_path:=$(ros2 pkg prefix ltl_automaton_hil_mic)/share/ltl_automaton_hil_mic/config/trap_detection_plugin.yaml
```

## 10. Services

### 10.1 `/replanning`

- 类型：`ltl_automaton_msgs/srv/TaskPlanning`
- 作用：从当前 TS 状态出发，使用新的 hard task 和 soft task 重新规划。

服务定义：

```text
string hard_task
string soft_task
---
bool success
```

调用示例：

```bash
ros2 service call \
  /replanning \
  ltl_automaton_msgs/srv/TaskPlanning \
  "{hard_task: '<> r2', soft_task: '(r2 || ! r2)'}"
```

成功时返回：

```text
success: true
```

服务成功后会重新发布：

- `/possible_ltl_states`
- `/prefix_plan`
- `/suffix_plan`
- `/next_move_cmd`

任务不可行、初始 TS 状态未知或规划内部抛出异常时，Planner 会保留调用前的
hard/soft task、TS 初始状态、Product、run 和执行游标；失败请求不会留下半更新状态。

---

## 11. 测试

执行全部相关测试：

```bash
cd <workspace>
source /opt/ros/humble/setup.bash
source install/setup.bash

colcon test

colcon test-result --verbose
```

当前已验证的内容包括：

- TS 构建；
- Boolean guard 解析；
- Promela 生成；
- `ltl2ba` 集成；
- Büchi 构建；
- Product 构建；
- prefix–suffix 规划；
- `LTLPlanner` 静态规划与重规划；
- Planner 节点的初始 ROS 2 输出；
- TS 状态反馈后的计划推进；
- `/replanning` 服务调用；
- 不可行任务、未知状态与内部异常下的事务式重规划回滚；
- 2D pose 与 6D joint-space 状态监控及 TS 生成；
- Bool 与 Velocity HIL 控制器策略和真实 Launch；
- trap service 的安全、trap、断连与错误维度路径；
- IRL 运行记录、beta 学习、事务式重规划与真实插件联调；
- Launch 测试结束时的干净退出。

提交前建议额外执行：

```bash
git diff --check
```

---

## 12. ROS 1 到 ROS 2 迁移对照

| KTH ROS 1 | 当前 ROS 2 | 说明 |
|---|---|---|
| catkin 包内规划算法 | `ltl_automaton_planner_core` | 与 ROS 通信解耦，可独立 pytest |
| `transition_system_textfile` | `transition_system_path` | 传入 YAML 文件路径 |
| `initial_beta` | `beta` | 权重含义不变 |
| `~initial_ts_state_from_agent` | `initial_ts_state_from_agent` | 改为非阻塞等待首个 `/ts_state` |
| dynamic_reconfigure | ROS 2 参数回调 | 使用 `ros2 param set` 修改两个行为参数 |
| `~plugin/<name>/...` 参数树 | `plugin_config_path` YAML | 保留类名、模块路径、args 契约 |
| `rospy` Publisher/Service | `rclpy` Node API | 插件通过 `set_node(node)` 获取宿主节点 |
| `region_2d_pose_monitor.py` | `region_2d_pose_monitor` | 四种 pose 消息通过参数选择，保留 station 与 closest-region 行为 |
| `region_6d_jointspace_monitor.py` | `region_6d_jointspace_monitor` | 迁移旧仓库中未安装的 6D monitor |
| `region_2d_pose_definition.py` | `region_2d_pose_definition` | 显式输出路径，生成 planner-compatible TS |
| `BoolCmdMixer` | `bool_cmd_hil_mic` | 保留 Bool 仲裁语义，trap 查询改为异步 ROS 2 service client |
| `VelCmdMixer` | `vel_cmd_hil_mic` | 保留速度混合语义，增加服务不可用与状态超时的安全回退 |
| `TrapDetectionPlugin` | `ltl_automaton_hil_mic.trap_detection` | 提供 ROS 2 `check_for_trap` 服务并检查接受环可达性 |
| `IRLPlugin` | `ltl_automaton_hil_mic.inverse_reinforcement_learning` | 保留示教运行与 beta 学习语义，重规划失败时回滚 |
| `catkin_make` | `colcon build --symlink-install` | 构建与测试命令见第 5、11 节 |

## 13. 已知限制

Ubuntu 24.04 / ROS 2 Jazzy 尚未执行独立兼容性验证；当前验证基线仍为
Ubuntu 22.04 / ROS 2 Humble。

此外，使用 Fast DDS 时可能出现共享内存端口警告：

```text
RTPS_TRANSPORT_SHM Error: Failed init_port ...
```

在当前验证中，该警告未阻止节点、Topic 或 Service 正常工作。若遇到 ROS 2 发现异常，应优先检查是否存在残留节点、重复 Publisher 或 DDS 共享内存锁冲突。

---

## 14. 后续计划

在需要时执行 Ubuntu 24.04 / ROS 2 Jazzy 独立验证。该项不属于当前 Humble
迁移验收范围。
