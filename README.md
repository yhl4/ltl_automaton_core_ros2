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
- 标准 2D pose 与 6D joint-space TS 状态监控及 2D TS 生成工具；
- Bool 与 Velocity mixed-initiative HIL 控制器；
- 只读 `TrapDetectionPlugin` 诊断服务。

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

### 1.6 HIL mixed-initiative 控制器

ROS 2 HIL 控制器位于：

```text
ltl_automaton_hil_mic/
```

当前支持：

- Bool 命令仲裁：规划器命令直接通过，人工命令仅在 TS 连通且非 trap 时通过；
- Velocity 命令仲裁：依据 trap 距离平滑混合人工与导航速度；
- trap 服务不可用、TS 未连通或状态超时时安全回退到导航命令；
- 通过异步 ROS 2 service client 查询 `check_for_trap`，避免阻塞控制回调；
- 可选 IRL 插件从示范 Product 轨迹学习软任务权重 β，并事务式提交重规划结果。

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

两个行为参数支持通过 `ros2 param set` 动态修改。新 consumer 使用 `/plan_ltl`
Action 切换任务并取得结构化结果；旧 `/replanning` 服务继续兼容。
两者均保证新任务成功规划后才替换当前计划。

`hard_task`、`soft_task`、`beta` 与 `gamma` 参数表示启动配置；Action 或 IRL
提交后的活动计划以当前 generation 的快照和执行观测为准，参数查询不会随之更新。

### 7.1 TS 输入约束

Planner 接受的 TS YAML 必须满足以下结构约束：

- `state_dim` 必须是非空列表，维度名必须是唯一、非空字符串；
- 每个维度的状态名、动作名以及 `connected_to` 中的目标状态和动作引用都必须是字符串；
- 每条边的目标状态必须出现在同一维度的 `nodes` 中，动作必须出现在顶层 `actions` 中；初始状态也必须已定义；
- 动作代价 `weight`、Planner 参数 `beta` 与 `gamma` 必须是有限的非负数；
- 边 guard 仍按 source-label 语义求值：使用边源状态的标签检查动作 guard，不能把目标状态标签替代源状态标签。

输入违反这些约束时，加载或规划请求应失败并保留此前有效的运行状态。

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

ROS 1 插件若仍直接导入 `rospy`，必须先把通信接口迁移到 `rclpy`；加载契约兼容
不代表 ROS 1 插件源码可不经修改直接运行。

### 9.1 可选 IRL 示范学习

原项目的 β 学习模块已恢复，默认插件配置仍只启用 trap 查询。显式启用 IRL：

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
  --packages-up-to ltl_automaton_core

colcon test-result --verbose
```

仓库包含以下定向测试：

- TS 构建；
- Boolean guard 解析；
- Promela 生成；
- `ltl2ba` 集成；
- Büchi 构建；
- Product 构建；
- 接受状态所在 SCC、自环与更便宜接受环的比较、零代价循环；
- 非法 TS/guard/代价拒绝、单维 TS guard 与显式初始状态保留；
- prefix–suffix 规划；
- `LTLPlanner` 静态规划与重规划；
- Planner 节点的初始 ROS 2 输出；
- TS 状态反馈后的计划推进；
- `/replanning` 服务调用；
- `PlanLTL` Action 的接受、失败和事务式替换；
- planning graph snapshot 与 execution observation 的 identity contract；
- FakeBackend/FakeStateObserver 执行闭环及真实 ROS 2 DDS 通信边界；
- 快照服务延迟发现后的命令恢复、执行后端异常后的忙碌状态释放；
- 快照请求失败后的最新命令恢复，以及节点销毁后晚到响应的抑制；
- 标准 2D/6D TS monitor、HIL controller 与 TrapDetectionPlugin 的 launch 通信；
- Launch 测试结束时的干净退出。
- 不可行任务、未知状态与内部异常下的事务式重规划回滚。
- 完整 Product 上的历史重规划、最新到达状态、代价参数与新任务历史隔离。

提交前建议额外执行：

```bash
git diff --check
```

### 11.1 本次重构补全验证（2026-10-06）

在 Ubuntu 22.04 / ROS 2 Humble / Python 3.10 下，七个包完成
`colcon build --symlink-install` 与 `colcon test`。`colcon test-result`
汇总为 **227 tests, 0 errors, 0 failures, 4 skipped**；四项跳过均为仓库
原有的版权头检查标记，功能与通信测试没有跳过。

本轮恢复统一包入口并补齐依赖；修正接受环识别、自环与其他循环的代价比较、
零代价路径、单维动作 guard 和非法输入处理。优化包含 guard 复用、Product
guard 检查复用、一次 SCC 遍历、已构建 TS 复用、反馈状态直接对已加载图校验，
以及仅缓存当前执行 generation。目标函数与 source-label 约定保持不变；
受上述缺陷影响的旧计划可能被拒绝或得到更低代价的正确计划。
这些是定向正确性与通信验证结果，未开展性能 benchmark 或物理仿真实验。

### 11.2 后续优化验证（2026-10-06）

组合 TS 与 hard/soft Büchi 的构造改为直接枚举实际后继，减少无效节点扫描。
以修改前实现为参考，对 KTH、Demo-D1 和自环/guard 小图比较全部节点、边、
属性与初始集合；另对三组真实 `ltl2ba` 公式比较 Büchi 图及 guard 判定，均一致。
这些检查证明本轮图构造等价，未测量端到端加速比。

陷阱检测改为读取宿主当前提交的 planner，避免 `PlanLTL` 替换任务后继续使用旧图。
相关三个包（planner core、planner、HIL）的 `colcon test` 通过，包括真实 Action
重新规划后陷阱判定改变的 Launch 回归；未扩大到仿真或 benchmark。

### 11.3 执行观测与解析优化（2026-10-06）

修复快照请求期间收到新观测后仍派发旧动作的问题：响应返回时读取最新观测，
再次检查 identity；新观测无下一动作时抑制旧派发。只保留最新一条观测。
动作解析为当前不可变快照建立一次节点与接受路径索引，后续命令复用；
缺失接受路径目标节点时返回解析错误，避免未处理的 `KeyError`。

本轮重跑 execution 包 `colcon test`，包括三个可控延迟响应节点回归、
解析与 generation 切换、已有真实 DDS/FakeBackend 场景和 lint，全部通过。
该轮 V0.1 验证时，接受环的重复状态/动作仍会抑制派发；这一限制由
第 11.5 节的接口升级解决。

### 11.4 重规划隔离与搜索优化（2026-10-06）

重规划改为在候选 planner 副本中计算，成功才提交；未知状态在复制前拒绝。
回归覆盖不可行任务、Büchi 构造异常和隔离状态重规划失败，检查原 TS、Product、
run 引用以及初始集、possible states、游标均保持不变。

完整 Product 的 Dijkstra 搜索复用已计算的 SCC 接受环集合，跳过不在环上的接受
节点；没有接受环时直接返回无解。小图中总代价仍为手算的 13，且不再对只能
到达非接受环的接受节点启动搜索。该结果不代表端到端加速比。
本轮重跑 Core 与 ROS planner 两包的 `colcon test`，包括重规划、Action、
快照 generation 和 lint 回归，全部通过。

### 11.5 执行步骤接口升级（2026-10-06）

Planning Contract 升级为 V0.2，新增 `uint64 execution_step_seq`。
规划成功提交时序号归零，预期 TS 反馈推进游标后递增；失败的规划请求保留原序号。
执行器按 instance、generation 和步骤序号去重，使接受环与同状态自环可持续派发。
后端忙碌时保留最新命令，空闲后复用已有快照；快照服务离线不影响已缓存图的派发。
默认 `check_timestamp=true` 时拒绝重复或倒序 TS 时间戳。

七个包重新完成 `colcon build --symlink-install`，并运行七包 `colcon test`；
更新旧接口字段断言后重跑消息包，最终汇总为
**246 tests, 0 errors, 0 failures, 4 skipped**，跳过项仍为原有版权头检查。
真实 DDS/FakeBackend 四项闭环回归覆盖 Demo-D1 导航与任务替换、取放动作、
两状态接受环至少推进 10 步，以及同状态自环至少推进 8 步。
另检查重复/倒序命令、忙碌期间最新命令保留、重复后端回调、失败规划保留序号、
新 generation 归零及 `uint64` 消息序列化。验证范围为符号执行与 ROS 通信；
未运行性能 benchmark 或物理仿真实验。

V0.1 消费者需重新生成并构建 `ltl_automaton_msgs` 及其依赖包；
当前不提供旧消息兼容层。

### 11.6 历史重规划补全（2026-10-06）

Core 的 `LTLPlanner.replan()` 改为复用已构建的完整 Product 和当前 Dijkstra 搜索，
不再调用依赖旧 `region/fly_predecessors` 接口的动态搜索。
搜索历史包含已完成动作的源状态与游标当前到达状态，使用配置的 `gamma`；
候选起点不改写图的 initial 集。计划比较使用 Product 路径，避免同名动作掩盖
不同目标状态。成功规划新任务时清空旧任务历史，同任务历史重规划保留原执行记录。
该路径以已接受反馈、已推进游标的当前执行状态为起点；异常偏离后的恢复仍使用
`replan_from_ts_state()`。

原问题在小图中复现为缺失动态 TS 接口异常、重规划起点落后以及旧任务历史残留。
修复后的手算代价检查、未知/非法历史、任务替换和八次连续执行/重规划均通过。
本轮重跑 Core、ROS planner 与 execution 三包 `colcon test`（含 Action、真实 DDS
闭环与 lint），全部通过；与其他包保留结果合计为
**253 tests, 0 errors, 0 failures, 4 skipped**。Product source-label 与代价公式保持不变，
未运行性能 benchmark。

### 11.7 多源 prefix 搜索优化（2026-10-06）

Dijkstra 将多个 Product 起点的 prefix 搜索合并为一次多源搜索，
只对可达且属于接受环的节点计算 suffix，并只保留最佳候选。
对固定接受节点，suffix 代价与初始点无关，因此先取最小 prefix 代价再计算
`prefix_cost + gamma * suffix_cost`，保持原目标函数；并列最优时可能返回另一条合法路径。

以提交 `fbce25d` 的搜索实现为对照，KTH、Demo-D1 导航与取放 Product 分别验证
默认起点和三起点查询、`gamma=0/1/10`，共 18 组；总代价差均为 0，
路径边与接受环有效，initial 与 possible states 均未改写。
定向检查确认一次多源 prefix 搜索、不可达接受环不触发 suffix 搜索、
零代价多源路径有限。Core、ROS planner 与 execution 三包 `colcon test` 通过，
与其他包保留结果合计为 **256 tests, 0 errors, 0 failures, 4 skipped**。
本轮验证搜索等价性与调用次数，未测量端到端加速比。

### 11.8 搜索路径缓存内存优化（2026-10-06）

prefix 与 suffix 搜索只计算最短距离，选出最佳接受环后再恢复两条路径，
避免为每个可达节点缓存完整路径。路径恢复严格使用 Dijkstra 距离等式，
以已访问节点阻止零代价环重复进入；浮点代价不使用容差放宽最短路条件。

以提交 `e00cacc` 的搜索实现为对照，重复上述三个 Product、两种起点设置与
`gamma=0/1/10` 的 18 组检查，总代价差均为 0，路径合法且图状态不变。
在预先构建的 1,000 状态链式 TS、2,000 节点 Product 定向用例中，
仅搜索阶段的 Python 分配峰值由 **4,283,854 bytes** 降至 **179,656 bytes**，
两者总代价均为 1,010、prefix 均含 1,001 个节点。该测量使用 `tracemalloc`，
不包含图构造，也不表示进程总内存或端到端加速比。

浮点最短路、零代价环与多源搜索定向检查通过。Core、ROS planner 与 execution
三包 `colcon test` 通过，与其他包保留结果合计为
**257 tests, 0 errors, 0 failures, 4 skipped**。

### 11.9 执行快照请求失败恢复（2026-10-06）

修复快照请求失败后动作命令被丢弃、执行停住的问题。客户端同步异常、
Future 异常、空响应与 `success=False` 均通过现有 0.1 秒 timer 重试，
只保留同一当前 instance/generation 下最新且有下一动作的观测。
旧 generation/instance 的失败不会覆盖新命令，新的无动作观测会抑制重试。
节点销毁时清空等待并取消 timer，晚到的快照完成回调直接返回。
成功响应仍需通过图身份与 schema 校验；执行后端拒绝或失败不自动重派同一步。

旧实现已复现为请求失败后 pending 命令为空。修复后的节点定向检查为
**16 passed**，覆盖失败类型、最新序号、无动作、过期身份及销毁边界。
真实 DDS 定向检查仅发布一次命令，让服务先失败再成功；后端接受和拒绝两种
情况均为两次快照请求、一次动作派发，未生成 TS 状态反馈。
本轮 `ltl_automaton_execution` 包 `colcon test` 通过（含原有四项执行闭环与 lint），
与其他包保留结果合计为 **267 tests, 0 errors, 0 failures, 4 skipped**。

### 11.10 可选 IRL 恢复（2026-10-06）

恢复原项目从示范轨迹学习 β 的范围，保持原 margin 启发式、步长与停止条件。
默认关闭；示范记录、隔离学习与接受计划提交由 ROS 2 插件和宿主分别承担。
增加反馈版本校验，学习期间离开再返回同一状态也会拒绝过期结果。
关闭非计划状态自动重规划后，Product belief 按实际后继更新，避免旧计划的接受
边界误删合法替代路线；默认计划反馈的接受边界检查保持原行为。

Core 的 11 项学习检查与两项替代路线检查通过；宿主六项 IRL 事务检查覆盖提交、
失败隔离、过期执行序号、旧 generation、离开再返回、销毁后晚到结果。
真实 ROS 2 Action、Bool trigger 与 DDS 状态反馈验证了 β 从 1 增大、新 generation
序号归零、旧 planner 未被学习改写及快照边权恢复为规范代价；不将该小图结果作为
收敛或机器人示范效果证明。另验证 buffer 超限仅学习一次及任务替换后的插件身份。
本轮构建 core、planner 与 HIL 三包，重跑 core、planner、HIL 与 execution 四包测试；
与其他包保留结果合计为 **288 tests, 0 errors, 0 failures, 4 skipped**。

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
| `VelCmdMixer` | `vel_cmd_hil_mic` | 保留速度混合语义，增加服务不可用与状态超时的安全回退 |
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
