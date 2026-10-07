# LTL Automaton Core — ROS 2 Migration

本仓库是对 KTH-SML `ltl_automaton_core` 的 ROS 2 迁移版本，目标是在保留原有 LTL 规划语义的基础上，将消息接口、规划核心与 Planner 节点迁移到 ROS 2。

`ltl_automaton_core` 是 ROS 2 aggregate 包，统一组织下面六个功能包并提供
`colcon build/test --packages-up-to ltl_automaton_core` 入口。

当前版本重点完成了：

- Transition System、Büchi Automaton 与 Product Automaton 的 ROS 无关核心；
- 基于 `ltl2ba` 的 LTL 到 Büchi 自动机转换；
- prefix–suffix 接受运行搜索；
- ROS 2 Planner 节点；
- TS 状态反馈、计划推进和意外状态重规划；
- 计划、下一动作与候选 Product 状态发布；
- 运行时任务重规划服务；
- `PlanLTL` Action、只读规划快照与 V0.2 执行步骤接口；
- 可选符号执行包，区分动作完成与实际 TS 状态反馈；
- 标准 2D pose 与 6D joint-space TS 状态监控及 2D TS 生成工具；
- Bool 与 Velocity mixed-initiative HIL 控制器；
- 只读 `TrapDetectionPlugin` 诊断服务；
- 默认关闭、从示范轨迹学习软任务权重 β 的可选 IRL 模块。

> 当前迁移保持 Product Automaton 与离散规划算法的核心语义，不将 ROS 2 通信逻辑写入规划核心。

导航：[构建](#5-构建) · [运行 Planner](#6-运行-planner) ·
[V0.2 Planning API](ltl_automaton_planner/docs/planning_api.md) ·
[可选 IRL](#91-可选-irl-示范学习) · [验证记录](ltl_automaton_planner/docs/validation.md)

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

已包含 Planner、执行器和 Studio consumer 使用的 ROS 2 消息、服务与 Action，当前公开接口包括：

- `TransitionSystemState`
- `TransitionSystemStateStamped`
- `LTLState`
- `LTLStateArray`
- `LTLPlan`
- `PlannerStatus`
- `PlanningExecutionObservation`
- `PlanningGraphMetadata`
- `PlanningGraphSnapshot`
- `BuchiGraphNode`、`BuchiGraphEdge`
- `ProductGraphNode`、`ProductGraphEdge`
- `AcceptedRunSnapshot`
- `LoadTransitionSystem`
- `GetPlanningGraphSnapshot`
- `ClosestState`、`TrapCheck`
- `PlanLTL`
- `TaskPlanning`

面向新 ROS 2 consumer 的正式 V0.2 contract 见
[`ltl_automaton_planner/docs/planning_api.md`](ltl_automaton_planner/docs/planning_api.md)。

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

### 1.4 可选符号执行包

可选执行包位于：

```text
ltl_automaton_execution/
```

它通过带 planning identity 的正式 execution observation 和只读 planning
graph snapshot 解析当前接受运行步骤，再由可替换的 `ExecutionBackend` 完成动作。
独立的 `StateObserver` 与 `StateAbstraction` 将实际观测映射为符号状态并发布
`/ts_state`；后端完成回调仅报告执行结果。当前仅提供符号级 `FakeBackend`，不包含物理仿真、Gazebo、
Isaac Sim 或机器人控制依赖；Planner 与 planner core 均不依赖该包。
Python 构造接口仅在参数为 `None` 时选择默认组件；显式注入的执行后端、观测器、
抽象器与 fake plant 保留所提供的对象，自定义后端采用自己的调度契约。
V0.2 的命令身份为
`(planner_instance_id, planning_generation, execution_step_seq)`；快照身份仍为
`(planner_instance_id, planning_generation)`。每个成功提交的 generation 从序号 0
开始，只有接受预期 TS 状态反馈并推进执行游标时才递增，包括带新时间戳的同状态自环；
重复发布不递增，后端 completion 不代表 TS 状态真值。使用者必须重新生成并构建
`ltl_automaton_msgs` 接口，当前不提供旧消息的兼容层。

### 1.5 标准 Transition System 工具

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

监控拒绝非有限坐标和零四元数，保留最后有效反馈；生成器拒绝零边长和非有限几何。
初始位置必须严格位于某个网格单元内部，恰在共享边、外边或角点时拒绝生成。
运动过程中的正滞回仍可保留当前区域。
输入约束与 6D 启动参数见
[标准 TS README](ltl_automaton_std_transition_systems/README.md)。

### 1.6 HIL mixed-initiative 控制器

ROS 2 HIL 控制器位于：

```text
ltl_automaton_hil_mic/
```

当前支持：

- Bool 命令仲裁：规划器命令直接通过，人工命令仅在 TS 连通且非 trap 时通过；
- Velocity 命令仲裁：依据 trap 距离平滑混合人工与导航速度；
- trap 服务不可用、TS 未连通或人工输入超时时安全回退到导航命令；
- 通过异步 ROS 2 service client 查询 `check_for_trap`，避免阻塞控制回调；
- 安全查询用 `safety_check_timeout` 限时，过期响应不覆盖新状态或命令；
- TrapDetection 对当前 Product 的候选状态到接受环的可达性进行一次反向搜索；
- Velocity 人工输入的 ROS 时间年龄必须非负且小于 `timeout`；已失效输入清除后须重新接收；
- 非有限速度/服务距离回退到最后有效导航命令，无有效缓存时输出零速度；
- 可选 IRL 插件从示范 Product 轨迹学习软任务权重 β，并事务式提交重规划结果。

控制器启动参数和仲裁规则见 [HIL README](ltl_automaton_hil_mic/README.md)。

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
├── ltl_automaton_core/
│   ├── CMakeLists.txt
│   └── package.xml
├── ltl_automaton_msgs/
│   ├── action/
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
│   ├── docs/
│   │   ├── planning_api.md
│   │   └── validation.md
│   ├── launch/
│   ├── ltl_automaton_planner/
│   │   └── planner_node.py
│   └── test/
├── ltl_automaton_execution/
│   ├── launch/
│   ├── ltl_automaton_execution/
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

colcon build \
  --symlink-install \
  --packages-up-to ltl_automaton_core
source install/setup.bash
```

`ltl_automaton_core` 是六个功能包的 ROS 2 aggregate 入口；使用
`--packages-up-to ltl_automaton_core` 会一并构建并安装接口、Planner core、
Planner、execution、标准 TS 和 HIL 包。

仅构建 Planner 及其依赖：

```bash
colcon build \
  --symlink-install \
  --packages-up-to ltl_automaton_planner
```

要同时构建执行器、标准 TS 工具和 HIL 控制器，可使用：

```bash
colcon build \
  --symlink-install \
  --packages-up-to \
  ltl_automaton_execution \
  ltl_automaton_std_transition_systems \
  ltl_automaton_hil_mic
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
| `beta` | double | soft-task 边惩罚权重 |
| `gamma` | double | suffix 代价乘数 |
| `initial_ts_state_from_agent` | bool | 只读启动配置：是否等待首个 `/ts_state` 作为规划初始状态 |
| `replan_on_unplanned_move` | bool | 收到非计划下一状态时是否自动重规划 |
| `check_timestamp` | bool | 是否丢弃重复或倒序时间戳的状态反馈 |
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

`initial_ts_state_from_agent` 通过 launch 或启动 ROS 参数设定，运行时写入会被拒绝。
`replan_on_unplanned_move` 与 `check_timestamp` 支持通过 `ros2 param set`
动态修改，继承的 `use_sim_time` 也保持动态。新 consumer 使用 `/plan_ltl`
Action 切换任务并取得结构化结果；旧 `/replanning` 服务继续兼容。
两者均保证新任务成功规划后才替换当前计划。

`hard_task`、`soft_task`、`beta` 与 `gamma` 参数表示启动配置；Action 或 IRL
提交后的活动计划以当前 generation 的快照和执行观测为准，参数查询不会随之更新。

执行节点的延迟/快照超时、标准 TS monitor 的模型路径/消息类型及 HIL 控制器
配置均为只读启动参数。通过 launch 或启动 ROS 参数设定，运行时修改会返回拒绝，
避免参数查询显示新值但实际对象继续使用旧值。继承的 `use_sim_time` 仍可动态修改。

KTH 演示驱动的六个场景、延迟、步数和任务配置参数也为只读启动参数，
运行时写入会被拒绝，`use_sim_time` 仍可动态修改。
`step_delay` 必须为有限正数，并在 ROS 定时器范围内；
无效延迟会在创建驱动通信接口前拒绝。启动方式与场景见
[KTH 演示说明](ltl_automaton_planner/docs/KTH_ROS2_DEMO.md#6-driver-场景)。

### 7.1 TS 输入约束

Planner 接受的 TS YAML 必须满足以下结构约束：

- `state_dim` 必须是非空列表，维度名必须是唯一、非空字符串；
- 每个维度的状态名、动作名以及 `connected_to` 中的目标状态和动作引用都必须是字符串；
- 每条边的目标状态必须出现在同一维度的 `nodes` 中，动作必须出现在顶层 `actions` 中；初始状态也必须已定义；
- 动作代价 `weight`、Planner 参数 `beta` 与 `gamma` 必须是有限的非负数；
- LTL/guard 命题名以小写 ASCII 字母开头，后续允许 ASCII 字母、数字和下划线；区分大小写，如 `cargoReady1` 与 `cargoready1` 是不同命题；
- 边 guard 仍按 source-label 语义求值：使用边源状态的标签检查动作 guard，不能把目标状态标签替代源状态标签。

输入违反这些约束时，加载或规划请求应失败并保留此前有效的运行状态。
直接调用 Python 核心 Planner 或 IRL 时，超出浮点表示范围的 β/γ 也返回
各自既有的无效权重 `ValueError`，并保留转换溢出的异常原因。
PlanLTL 或 IRL 事务候选计算出的 prefix/suffix/total 代价必须能表示为
有限 float64；结果溢出或出现 NaN 时返回内部失败，保留活动计划与代际。
这是候选结果检查，不改变核心代价定义或为有限 β/γ 设置额外上限。

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

默认 `planner.launch.py` 的 `plugin_config_path` 为空，不加载插件。
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

ROS 1 插件若仍直接导入 `rospy`，必须先把通信接口迁移到 `rclpy`；加载契约兼容
不代表 ROS 1 插件源码可不经修改直接运行。

### 9.1 可选 IRL 示范学习

原项目的 β 学习模块已恢复，IRL 默认关闭。`trap_detection_plugin.yaml` 示例
只配置 trap 诊断；显式传入 `irl_plugin.yaml` 才启用 IRL：

```bash
ros2 launch ltl_automaton_planner planner.launch.py \
  transition_system_path:=/path/to/transition_system.yaml \
  plugin_config_path:="$(ros2 pkg prefix ltl_automaton_hil_mic)/share/ltl_automaton_hil_mic/config/irl_plugin.yaml" \
  replan_on_unplanned_move:=false
```

在已有活动计划时发布 `True` 开始记录，提供带新时间戳的 `/ts_state` 示范反馈，
再发布 `False` 结束并学习：

```bash
ros2 topic pub --once /irl_trigger std_msgs/msg/Bool '{data: true}'
# 提供真实示范状态反馈后结束记录
ros2 topic pub --once /irl_trigger std_msgs/msg/Bool '{data: false}'
```

`/possible_runs` 发布与示范一致的 Product 路径。`max_run_buffer_size` 默认 100，
所有候选路径的节点总数超过该值时自动结束并提交一次学习请求。
替代路线示范需要关闭 `replan_on_unplanned_move`，其状态仍须匹配实际 Product
后继；切换任务或自动重规划产生新 generation 时，旧示范会清空。
可在自己的插件 YAML 中同时配置 `IRLPlugin` 和 `TrapDetectionPlugin`。

学习只修改 β，保留 hard/soft task 与 γ。宿主在隔离副本上学习并从当前 TS 状态
重新规划，校验身份、执行序号与状态反馈版本后才提交新 generation，序号重置为 0。
失败或过期学习不改写活动 β 与计划。该模块沿用原项目的 margin 学习启发式，
不保证收敛、逆最优性或新计划完全复现示范；具体规则见
[HIL README](ltl_automaton_hil_mic/README.md#optional-irl-beta-learning)。

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
Core 在隔离副本中重规划，失败时原 TS、Product 和 run 的对象引用也保持不变。
成功后安装候选图；直接使用 Core API 的调用方应从当前 planner 获取 TS/Product，
ROS consumer 则按新的 generation 获取正式快照。

---

## 11. 测试

执行全部相关测试：

```bash
cd <workspace>
source /opt/ros/humble/setup.bash
source install/setup.bash

colcon test \
  --packages-up-to ltl_automaton_core \
  --return-code-on-test-failure

colcon test-result --verbose
```

现有测试覆盖：

- TS、Boolean guard、Promela、原生 `ltl2ba`、Büchi 与 Product 构建；
- prefix–suffix 代价、接受环、自环、零代价循环与历史重规划；
- Planner 状态反馈、任务替换、`PlanLTL` Action 和失败时的活动计划保留；
- 正式快照与执行观测身份、步骤序号、缓存更新及异常/超时恢复；
- 符号执行闭环、四个真实 ROS 2 DDS 场景及 Studio consumer；
- 标准 2D/6D TS monitor、HIL 仲裁、trap 查询与无效输入恢复；
- 可选 IRL 的示范选择、完整二十步学习、隔离候选与事务式提交；
- 启动参数、运行时参数服务、launch、节点销毁与 lint。

提交前建议额外执行：

```bash
git diff --check
```

### 最新七包组合验证（源码 e5a663c，2026-10-07）

将最近 IRL 示范评分复用与执行索引键复用一起纳入完整组合。
干净源码 `e5a663c` 的七包构建和默认并行整包测试各执行一次，
均 exit 0；后续文档更新没有改变该资格版本的源码或测试。

| 包 | tests | passed | skipped |
| --- | ---: | ---: | ---: |
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 191 | 190 | 1 |
| ltl_automaton_planner | 159 | 158 | 1 |
| ltl_automaton_execution | 143 | 143 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 49 | 48 | 1 |

合计 **656 tests = 652 passed / 4 skipped**，0 errors、0 failures。
四项跳过均为既有 copyright；接口 CTest wrapper 另有一项通过，
对实际隔离 build 的 colcon 查询为 657 tests。保留 np.int/
SelectableGroups 依赖弃用警告，五包 stderr 非空；历史 XML
按测试开始时间排除。完整记录见
[validation.md 第 11.86 节](ltl_automaton_planner/docs/validation.md)。

IRL 示范评分与执行索引的局部对照、旧版本资格、原始失败，以及
命令、日志和冻结哈希清单的位置见同一验证记录，按源码版本分别计数。
符号级组合通过不证明整体加速、IRL 科学效果或实机效果。

---

## 12. ROS 1 到 ROS 2 迁移对照

| KTH ROS 1 | 当前 ROS 2 | 说明 |
|---|---|---|
| catkin 包内规划算法 | `ltl_automaton_planner_core` | 与 ROS 通信解耦，可独立 pytest |
| `transition_system_textfile` | `transition_system_path` | 传入 YAML 文件路径 |
| `initial_beta` | `beta` | soft-task 边惩罚权重 |
| `gamma` | `gamma` | suffix 代价乘数 |
| `~initial_ts_state_from_agent` | `initial_ts_state_from_agent` | 改为非阻塞等待首个 `/ts_state` |
| dynamic_reconfigure | ROS 2 参数回调 | 使用 `ros2 param set` 修改两个行为参数 |
| `~plugin/<name>/...` 参数树 | `plugin_config_path` YAML | 保留类名、模块路径、args 契约 |
| `rospy` Publisher/Service | `rclpy` Node API | 插件通过 `set_node(node)` 获取宿主节点 |
| `region_2d_pose_monitor.py` | `region_2d_pose_monitor` | 四种 pose 消息通过参数选择，保留 station 与 closest-region 行为 |
| `region_6d_jointspace_monitor.py` | `region_6d_jointspace_monitor` | 迁移旧仓库中未安装的 6D monitor |
| `region_2d_pose_definition.py` | `region_2d_pose_definition` | 显式输出路径，生成 planner-compatible TS |
| `BoolCmdMixer` | `bool_cmd_hil_mic` | 保留 Bool 仲裁语义，trap 查询改为异步 ROS 2 service client |
| `VelCmdMixer` | `vel_cmd_hil_mic` | 保留速度混合语义，服务失败、查询过期或人工输入超时时回退到最新导航命令 |
| `TrapDetectionPlugin` | `ltl_automaton_hil_mic.trap_detection` | 只读查询，不修改 active plan、generation 或 execution state |
| `IRLPlugin` | `ltl_automaton_hil_mic.inverse_reinforcement_learning` | 可选 β 学习；隔离候选并由宿主事务式重规划提交 |
| `catkin_make` | `colcon build --symlink-install` | 构建与测试命令见第 5、11 节 |

ROS 1 的插件源码若直接依赖 `rospy`，仍需逐个迁移通信层。

## 13. 已知限制

当前版本的主要未完成项与限制：

- 可选 IRL 沿用原项目 β 学习启发式，尚无收敛或逆最优性保证，也未进行机器人示范实验；
- `ltl_automaton_execution` 仍是符号级执行包，尚未提供 Gazebo、Isaac Sim、运动学、轨迹、碰撞检查、感知或真实机器人控制，也没有物理仿真验证；
- Ubuntu 24.04 / ROS 2 Jazzy 独立验证；

此外，使用 Fast DDS 时可能出现共享内存端口警告：

```text
RTPS_TRANSPORT_SHM Error: Failed init_port ...
```

在当前验证中，该警告未阻止节点、Topic 或 Service 正常工作。若遇到 ROS 2 发现异常，应优先检查是否存在残留节点、重复 Publisher 或 DDS 共享内存锁冲突。

---

## 14. 后续计划

在需要时执行 Ubuntu 24.04 / ROS 2 Jazzy 独立验证；真实机器人示范与物理执行验证
需使用对应环境另行开展。
