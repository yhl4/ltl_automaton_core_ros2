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

Action/IRL 提交前会准备计划消息、成功结果与快照；准备失败释放事务并保留
当前计划及执行身份。计划消息在成功提交后发布，提交后的发布或进程故障
不属于该准备回滚边界。可选 IRL 的失效示范丢弃与重新开始约定也见该接口说明。

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
- TS 状态必须包含控制维度且维度名唯一；无效消息丢弃并保留最后合法状态及其查询；
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

ROS 2 工作空间的 Python 依赖已在 `package.xml` 中声明，推荐按第 5 节
使用 `rosdep` 安装。单独使用 Planner core 时，可在虚拟环境中准备依赖：

```bash
python3 -m pip install networkx ply pyyaml
```

### 4.3 ltl2ba

`ltl2ba` 是外部原生程序，需单独准备。可从
[原作者下载页](https://lsv.ens-paris-saclay.fr/~gastin/ltl2ba/download.php)
获取源码，按随源码的说明编译。将编译出的可执行文件加入用户目录，
把下面的 `/path/to/built/ltl2ba` 替换为实际文件路径：

```bash
mkdir -p "$HOME/.local/bin"
install -m 755 /path/to/built/ltl2ba "$HOME/.local/bin/ltl2ba"
export PATH="$HOME/.local/bin:$PATH"
```

在启动 Planner 或运行测试的同一终端检查：

```bash
command -v ltl2ba
ltl2ba -f '[]<> p'
```

翻译检查应以状态 0 退出并输出 `never {` 开头的 Promela claim。
`command -v` 没有输出时，Planner 无法找到程序；启动其他终端时也需设置
上述 `PATH`。这里使用实际公式翻译检查安装，避免把帮助输出当作成功检查。

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
初始规划、PlanLTL、IRL、旧 `/replanning` 或意外状态恢复候选计算出的
prefix/suffix/total 代价必须
能表示为有限 float64；结果溢出或出现 NaN 时，Action/IRL 返回内部失败，
旧服务返回 `success: false`，自动恢复返回失败，保留活动计划与代际。
初始规划的结果溢出或提交准备失败时返回 READY，保留有效 TS，且不提交计划或增加代际。
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

自动恢复先在隔离候选上计算并准备有限代价、快照和计划消息，再提交新计划。
准备失败时保留原计划、generation 和 step；已接收的观测状态、修订号及时间戳
仍保持最新值。此时旧计划保留并不表示机器人回到了旧状态。

若启动时设置：

```bash
ros2 launch ltl_automaton_planner planner.launch.py \
  initial_ts_state_from_agent:=true
```

Planner 会先等待首个合法 `/ts_state`，按消息中的
`state_dimension_names` 将状态覆盖到对应 TS 维度，然后才构建并发布初始计划。
无效或维度不匹配的消息不会触发规划，节点会继续等待下一条状态。
初始候选的代价检查、快照或计划消息准备失败时，节点保持 READY 和等待初态；
下一条合法反馈可以重新尝试初始化，成功只提交一次新 generation。

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
服务或客户端。其余三个生命周期钩子保留原有名称与宿主调用方式。单个插件加载或运行失败会被记录，
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

若反馈无法一致地延伸记录中的候选 Product 路径，IRL 会停止记录并清空
示范缓存，不请求学习。随后再次发送 `True` 会从当前有效 Product belief
重新开始；空缓存状态下单独发送 `False` 不会请求学习。

`/possible_runs` 发布与示范一致的 Product 路径。Python 构造的消息中，各轨迹点
独立持有状态值和维度名列表，修改一个点不会影响其他点或后续发布。
`max_run_buffer_size` 默认 100，
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

候选计划、有限代价、计划消息和快照准备成功后才替换活动计划。
搜索或准备失败返回 `success: false`，旧计划、快照和执行身份保持；
成功后更新 generation 并从 step=0 开始。

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

### 最近局部验证（2026-10-10）

| 范围 | 实际结果 | 记录 |
|---|---|---|
| TS 后继坐标复用（源码 `e6e22c3`；原始对照基线 `5aeea47`） | 17/17 passed；0 skip/error/failure；9案例、10阶段等价；`list(node)` 12→6、48→24、40→20、重建4→2，false/空后继为0 | [11.121](ltl_automaton_planner/docs/validation.md) |
| Execution resolver 来源 ID 收集（源码 `5aeea47`） | 31/31 passed；0 skip/error/failure | [11.120](ltl_automaton_planner/docs/validation.md) |
| Boolean OR 距离零下界短路（对照基线 `fc6fdba`） | 108/108 passed；0 skip/error/failure；768 个公式/标签/容器组合与旧实现、候选及手算值一致 | [11.123](ltl_automaton_planner/docs/validation.md) |
| Büchi membership 局部索引（对照基线 `f84c939`） | 97/97 passed；0 skip/error/failure；初始/接受 membership 与重建 metadata 语义保持 | [11.124](ltl_automaton_planner/docs/validation.md) |
| 长 Boolean guard 与 Promela 分支合并（对照基线 `7717e76`） | 122/122 passed；0 skip/error/failure；2048项原递归错误修复，1280组旧/新/手算对照一致 | [11.126](ltl_automaton_planner/docs/validation.md) |
| 一维 TS 同来源 guard 求值复用（对照基线 `310adda`） | 124/124 passed；0 skip/error/failure；9场景/12阶段完整图等价；示例求值8→4，常量8→2 | [11.127](ltl_automaton_planner/docs/validation.md) |
| 历史重规划后继复用（对照基线 `3ba0374`） | 52/52 passed；0 skip/error/failure；完整候选状态及 γ=1/10 的路径、动作、成本一致；循环邻接读取5→2 | [11.129](ltl_automaton_planner/docs/validation.md) |
| 完整搜索邻接属性读取（对照基线 `7db6c74`） | 81/81 passed；0 skip/error/failure；6路径/6完整Run对照一致；示例额外EdgeView查找3→0、7→0 | [11.130](ltl_automaton_planner/docs/validation.md) |
| guard lexer 模板复用（对照基线 `c3a74d1`） | 104/104 passed；0 skip/error/failure；192对真值/距离、18类无效输入和26组token序列对照一致；KTH三阶段路径、动作与成本保持 | [11.132](ltl_automaton_planner/docs/validation.md) |
| 重规划复制中的不可变状态 key 复用（对照基线 `989bb8e`） | 83/83 passed；0 skip/error/failure；完整复制与内部别名一致、可变数据隔离；7类custom key及精确异常对照；KTH路径/动作/成本保持 | [11.133](ltl_automaton_planner/docs/validation.md) |
| 重规划复制中的基础标量 memo（对照基线 `a9f0207`） | 84/84 passed；0 skip/error/failure；完整复制、边属性别名、hook顺序及可变隔离保持；KTH atomic dispatch 1695→854、1718→865，dict/list复制次数保持 | [11.135](ltl_automaton_planner/docs/validation.md) |
| 可达 SCC 拓扑物化（对照基线 `3df6e23`） | 85/85 passed；0 skip/error/failure；96节点/96边 probe 的过滤 view 调用 2111→0；完整 Run、None 隐藏边与输入图保持 | [11.136](ltl_automaton_planner/docs/validation.md) |
| 重规划邻接目标 tuple memo（对照基线 `f8d367c`） | 85/85 passed；0 skip/error/failure；完整复制、别名及hook顺序保持；KTH tuple复制286→74、294→88，dict/list次数保持 | [11.137](ltl_automaton_planner/docs/validation.md) |
| IRL 路径软距离的边视图复用（对照基线 `84c159a`） | 85/85 passed；完整20步 margin 与 β 序列保持；128边路径的 EdgeView 访问128→1，空路径零访问；短路径存在额外开销 | [11.141](ltl_automaton_planner/docs/validation.md) |
| 完整 Product 构图的 TS 来源邻接复用（对照基线 `7321c75`） | 62/62 passed；有序图、动作引用、重建刷新及异常状态保持；128分支往返图的 TS 邻接查询256→129 | [11.142](ltl_automaton_planner/docs/validation.md) |
| 重规划嵌套 tuple 的直接类型检查（对照基线 `2f327a1`） | 85/85 passed；24类边界输入与原检查一致，完整复制/custom key/hook及20步IRL margin回归保持；16项嵌套 tuple 的 cProfile genexpr调用96→0 | [11.145](ltl_automaton_planner/docs/validation.md) |
| Run 输出的 TS 邻接复用（对照基线 `3c278b1`） | 四模块119/119 passed；完整20步IRL与复制/hook回归保持；128步Run的TS `__getitem__`调用128→0，六组每50次构造中位数6.939/2.592 ms | [11.149](ltl_automaton_planner/docs/validation.md) |
| suffix 单源 distance-only Dijkstra 内联（对照基线 `bcdd2b2`） | 120/120 passed；DP/testDP compile、flake8、pep257通过；ring64 callback 4096→0、bounded callback 65→0；N64 ring、N64 bounded、KTH 中位数门槛通过 | [11.150](ltl_automaton_planner/docs/validation.md) |
| suffix 松弛复用弹出距离（基线 `e4156ca`，DP `56f8c6c4`） | 四模块120/120 passed，完整20步IRL保持；34组对照通过；N64 ring/bounded/KTH每20次中位数分别降低约7.1%/5.4%/2.3%，仅本轮局部结果 | [11.152](ltl_automaton_planner/docs/validation.md) |
| prefix 原生权重查询内联（基线 `635e9fd`，DP `f1403027`） | 四模块123/123 passed，完整20步IRL保持；13项额外资格与37组控制通过；每200次完整搜索的dense/bounded/KTH中位数本轮约降4.3%/2.6%/0.8% | [11.156](ltl_automaton_planner/docs/validation.md) |
| 可达 SCC 来源邻接直接迭代（基线 `e1126ce`，DP `06c485fd`） | 四模块123/123 passed，完整20步IRL保持；32组控制通过；本轮ring/bounded/dense/KTH完整搜索中位数约降2.1%/10.5%/1.8%/3.0% | [11.159](ltl_automaton_planner/docs/validation.md) |

二十一项均为局部验证；局部结果与整包组合分别计数，不相加，也不作整体速度、内存、IRL 科学效果或实机声明。

同级 AND/OR 现在构造平衡语法树，保留叶顺序、优先级和原输入 formula 文本；
Promela 同目标分支一次性按原顺序 OR 合并。单分支和 `skip` 文本保持，三条及以上
重复分支的 `guard_formula`（含快照字段）会减少冗余括号，语义与距离保持。
任意深度的手写括号或连续否定仍受递归限制。

一维 TS 构建也按来源节点复用相同 guard 的求值结果，每次重建重新检查；
适用于构建期间稳定的标签。公开 `is_action_allowed` 仍逐次求值。

历史重规划在单次查询内按 Product 来源保存有序后继，重复历史仍逐步过滤，
下一次查询重新读取图。适用于查询期间固定的 Product；临时 tuple 会增加存储，
短或不重复的历史可能增加分配开销。小规模耗时对照波动明显，不据此声称稳定加速。

接受环闭合边及紧路径恢复直接从标准 DiGraph 的 `pred` / `adj` 读取边属性，
减少额外 EdgeView 查找；仍按相同顺序遍历边、处理默认权重与 `None` 隐藏边。

完整搜索 SCC 带权图复用候选未纳入：N64 每20次完整搜索中位数由 **73.26925 ms**
变为 **77.38565 ms**，KTH 由 **5.93420 ms** 变为 **7.53670 ms**，两项均为六组全部更慢。
15个语义控制通过，但预设性能门槛未通过。该轮没有新增测试资格，当时累计采用16项。
详见 [validation.md 11.146](ltl_automaton_planner/docs/validation.md)。

闭合 SCC 的原生权重复用候选也未纳入：17个语义场景通过；固定六组、每20次完整搜索的
N64 中位数为 **87.67675 / 86.74320 ms**（旧/候选），保存 KTH 图为
**7.07275 / 7.12160 ms**。KTH 未通过预设时间门槛，未补采样或修改生产代码；
该轮仅更新文档，当时累计采用16项。详见
[validation.md 11.147](ltl_automaton_planner/docs/validation.md)。

闭环代价界裁剪 suffix 的候选未纳入：27类场景与跨调用修改通过，固定六组、每20次
完整搜索的 N64 ring 中位数旧/候选为 **78.58747 / 101.12983 ms**，可裁剪场景为
**8.67445 / 8.81595 ms**，保存 KTH 图为 **6.75525 / 7.31040 ms**，均未通过预设性能门槛。
裁剪场景返回节点64→1仍不等于完整搜索加速；未补采样或应用候选，当时累计采用16项。
首次14次辅助 Fraction 检查失败与修正后1022次对照独立保留；该轮没有新增测试/组合资格。
详见 [validation.md 11.148](ltl_automaton_planner/docs/validation.md)。

Run 输出现在在单次调用内惰性复用标准 TSModel/DiGraph 的邻接，下次调用重新读取，
包括整个 TS 对象被替换；自定义 TS/metadata 保留原查询，路径、动作引用与异常保持。
固定六组每50次128步完整 Run 构造中位数旧/新为 **6.93865 / 2.59190 ms**；
每20次完整搜索 N64 为 **92.36821 / 91.03056 ms**，保存 KTH 图为
**7.43939 / 6.98364 ms**，后两项仍有3/6、2/6组更慢。通过预设门槛后采用，
四个相关模块119项、两文件 compile/flake8/pep257通过，保留完整20步 IRL margin。
该修改尚无新七包组合资格，不作稳定或整体加速声明。详见
[validation.md 11.149](ltl_automaton_planner/docs/validation.md)。

suffix 单源 distance-only Dijkstra 本轮按真实 NetworkX 2.4 的堆、counter、默认/None
权重、seen 等值比较和异常顺序内联 component 过滤，省去固定为 None 的分支判断与
仅用于 distance-only 路径的 wrapper；prefix、SCC、accept 目标次序、tight restore、
Run、source/action identity 和 gamma/IRL 范围保持。fix3 完成 66 semantic、4 profile、
960 timed 和一次历史 snapshot 加载；ring64 callback 4096→0、bounded 65→0，但 suffix
搜索节点数不变。N64 ring、N64 bounded、KTH 中位数均不慢，N1 仅作报告；这仍是局部
探针结果，不作稳定或整体加速声明。详见 [validation.md 11.150](ltl_automaton_planner/docs/validation.md)。

suffix 松弛现在复用刚弹出的 distance 对象，省去刚赋值的 distances[current] 查询；
适用于搜索期间图与节点 hash/equality 稳定的场景，数值对象、事件、堆次序和目标函数保持。
34组控制、4次profile和唯一960次完整kernel计时通过预设门槛；每20次搜索的六组中位数
N64 ring为 **48.323/44.891 ms**、单接受目标为 **7.301/6.907 ms**、保存KTH图为
**5.011/4.896 ms**，分别有0/1/3组候选更慢，N1略慢且只报告。应用后四模块一次
**120 passed**，含完整20步IRL，改变的DP文件compile/flake8/pep257通过。没有补采样，
结果只表示本轮局部对照；详见 [validation.md 11.152](ltl_automaton_planner/docs/validation.md)。

### 最近七包组合记录（源码 `803f28e`，2026-10-08）

本次覆盖第11.137节及此前十三项局部修改，包括基础标量 memo、可达 SCC 拓扑和
邻接目标 tuple 复用。在全新 `/tmp/ltl_ros2_combo_803f28e` 七包构建和默认并行测试
各执行一次，均 exit 0：

| 包 | tests / passed / skipped |
|---|---:|
| `ltl_automaton_msgs` | 11 / 11 / 0 |
| `ltl_automaton_planner_core` | 222 / 221 / 1 |
| `ltl_automaton_planner` | 188 / 187 / 1 |
| `ltl_automaton_execution` | 143 / 143 / 0 |
| `ltl_automaton_hil_mic` | 131 / 130 / 1 |
| `ltl_automaton_std_transition_systems` | 51 / 50 / 1 |

合计 **746 tests = 742 passed / 4 skipped**，0 errors/failures；四项跳过均为既有 copyright。
CTest wrapper 另1项通过，查询为747。此前744项加恰好新增2项的完整身份与 skip flags
和执行前冻结清单逐一一致；新增hook顺序及None结构边回归均通过。
138份源码/IDL/包构建文件与Git资格源码绑定，23模块实际导入字节匹配，消息来自本次新构建。
四个真实DDS符号场景、Studio、完整20步IRL及提交、HIL偏好提交、启动准备8项及
payload准备6项通过；历史规划热点及lexer/复制回归明确核对通过。
5份stderr共4615字节保留既有依赖警告，53文件证据副本已冻结并回读。
此前组合53文件及标量/SCC/目标memo局部46/61/44文件闭包在执行前后保持。
详见 [validation.md 11.138](ltl_automaton_planner/docs/validation.md)。

该记录是Humble符号级组合资格，不证明稳定加速、内存收益、IRL科学效果或实机能力。
本次未重跑性能profile；原局部操作计数和单次耗时分别保留，不把它们当作组合性能。
lexer首次完整校验固定规则，每次clone隔离输入、行号和状态栈；重规划仍完整deepcopy，
本次memo只复用符合原类型限制的不可变状态tuple、邻接目标key和基础标量，全部可变
状态与内部别名保持，失败回滚边界保持。额外扫描、memo和SCC临时拓扑均有成本。
此前ab45b9b的744项组合保留在第11.134节，与本次及各局部范围独立计数。

后续前驱 key memo 候选未纳入：固定 KTH 复制探针中 tuple/deepcopy 调用从
74/2649 降到 50/2601，但六组对照五组更慢，中位数旧/候选为 2.353/3.191 ms。
额外前驱扫描抵消了本探针的复制收益；生产字节保持，上述组合资格不变。
失败辅助检查、修正后的对照及限制见 [validation.md 11.139](ltl_automaton_planner/docs/validation.md)。

节点属性标量 memo 候选暂不纳入：评估在标准 deepcopy 的完整 pickle 检查处停止，
额外诊断未复现，首次失败副本未保存，原因未确定。尚无候选调用数或耗时结果；
该节点 memo 候选未改变生产代码，上述旧组合资格保持。准备、失败及诊断记录见
[validation.md 11.140](ltl_automaton_planner/docs/validation.md)。

后续 IRL 路径评分只在单次调用内惰性复用边视图，下次调用重新读取图，保持浮点
累加顺序、异常及输入图。三份核心测试一次 **85 passed**，包含完整20步 margin；
compile、flake8、pep257 通过。普通 DiGraph 的128边局部探针中，每200次调用的
六组批次中位数旧/新为 **38.161/9.685 ms**；单边为 **0.448/0.451 ms**。
这是局部合成路径结果，新 IRL 字节尚未进行新的七包组合验证，不代表端到端加速。
全部计时、首次探针失败与复制失败的独立续查见
[validation.md 11.141](ltl_automaton_planner/docs/validation.md)。

完整 Product 构图现在为每个 TS 来源惰性读取一次邻接，保留有序 tuple 边快照与原
边属性引用；空邻接仍不读取，下次重建重新取值。Product 与 Planner 定向测试一次
**62 passed**，compile、flake8、pep257 通过。128分支往返图的20次完整构图批次
中位数旧/新为 **38.472/37.457 ms**，六组中仍有一组候选更慢，双分支中位数略慢。
适用于构图期间邻接稳定的标准 TSModel/DiGraph；该局部结果不证明稳定或整套加速。
旧七包组合未包含本修改及后续 IRL 修改，辅助失败、缺失和最终证据见
[validation.md 11.142](ltl_automaton_planner/docs/validation.md)。

可达 SCC 邻接视图绑定候选（对照基线 `d49fedd`）未纳入：128分支完整搜索的邻接
读取129→1，但每20次搜索批次中位数旧/新为 **37.770/39.987 ms**，六组中四组更慢。
9个语义案例的20次调用与720次普通 DiGraph 计时调用仅执行一轮，时间门槛未通过。
生产代码未修改，用于三份既有核心测试的 runner 未执行；全部结果保留在
[validation.md 11.143](ltl_automaton_planner/docs/validation.md)。

节点属性标量遍历融合的后续候选（基线 `bf32f29`）也暂未纳入：现有生产方法只完成
一次复制，最后字节检查之前的别名与可变对象隔离断言通过，但严格 pickle 相等门槛
因一个 set 的四项引用顺序旋转失败。候选、控制与计时调用均为0，生产和测试字节未改；
本次完整失败副本及只读归因见 [validation.md 11.144](ltl_automaton_planner/docs/validation.md)。

后续只将既有不可变节点检查中的内层 `all(generator)` 改为等价直接循环，精确类型、
两级限制、短路顺序、memo 和完整 deepcopy 保持。每批16000次纯嵌套 tuple 检查的六组
中位数旧/新为 **17.172/9.854 ms**，平坦 tuple 为 **3.657/3.697 ms**；这不是完整
复制或端到端重规划耗时。既有三份核心测试85项通过，旧七包组合不包含本修改，
此前节点 memo 候选的失败门槛和状态保持，详见 [validation.md 11.145](ltl_automaton_planner/docs/validation.md)。

此前源码 `ce014f7` 的740项、`683c333` 的737项与 `62b94b3` 的724项组合记录分别保留在
第11.131、11.128、11.125节，各版本计数不相加。

可达 SCC 临时拓扑直接建边候选（基线 9681280）未纳入：原生精确字典工厂条件下，
临时拓扑的 add_edges_from 调用由1降为0，但 N64 ring 完整搜索中位数由
49.378451 ms 变为 50.457350 ms（3/6 组候选更慢），预设性能门槛未通过。
34个语义控制组、4次资源 profile 与960次完整计时调用均保留；生产代码与测试字节未修改。
详见 [validation.md 11.151](ltl_automaton_planner/docs/validation.md)。

### 历史验证索引

历史命令、局部失败、日志、XML 与冻结哈希的位置见
[`validation.md`](ltl_automaton_planner/docs/validation.md)，各版本按源码和范围分别计数，不相加。

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


tight 路径恢复的原生 AtlasView 候选（基线 dd56790）未纳入：37组语义控制及完整Run、
源图、custom view/inner dict读取事件保持，恢复的边视图查询63→0。唯一六组每20次完整
搜索中位数旧/候选：N64 ring50.562/49.475 ms，单接受目标7.657/7.651 ms，KTH保存图
5.045/5.060 ms；KTH未通过既定门槛，未补采样或改门槛。首runner因错误恢复计数停止，
保留76次语义/4次profile原件；复核后只继续尚未执行的960次计时，各阶段不重复。
本轮只更新文档，十九项优化及既有120项回归资格保持；
详见 [validation.md 11.153](ltl_automaton_planner/docs/validation.md)。


纯有向环的线性后缀距离候选（af9c605 基线）未纳入：严格限制为整图每节点单后继、
原生节点/字典与非负整数权重，其他输入回退原 heap 搜索。37组控制、16项额外资格控制、
完整Run/源图/成本次序保持；ring64 heap push/pop 各4160→64。唯一六组每20次完整搜索
中位数旧/候选：ring49.206/19.639 ms，带分支图7.408/7.515 ms，KTH5.243/5.219 ms。
带分支图约慢1.442%，未通过原定门槛，未补采样或应用。首轮资源计数误将128写成129，
保留失败后只继续未执行的960次计时；生产、十九项优化及既有120项资格保持。
详见 [validation.md 11.154](ltl_automaton_planner/docs/validation.md)。


### 可达接受目标阈值的 cycle-dispatch 候选（未采用）

679f834 基线上的候选，只对至少四个可达接受目标且同一 SCC 包含至少四个目标的
原生闭环启用本次调用的 cycle map；prefix 可达节点须覆盖整图，其余输入保留原搜索。
ring64 的 heap push/pop 各4160→64，bounded64 各128保持。固定六组每20次完整搜索的
中位数旧/候选为 ring46.788/19.131 ms、bounded6.811/6.724 ms、KTH6.161/6.650 ms。
KTH 门槛未通过，候选未采用，未补采样；生产、十九项优化及既有120项资格保持。
详见 [validation.md 11.155](ltl_automaton_planner/docs/validation.md)。


prefix 搜索在 exact DiGraph/ProdAut 上内联原生权重查询，自定义图与实例覆写仍走原
NetworkX 接口；source 顺序、tie、默认/None 权重、代价类型和动作引用保持。
固定六组每200次完整 kernel 的中位数旧/新为：N64 ring **466.175/465.913 ms**，
bounded **69.374/67.540 ms**，dense **1047.820/1003.129 ms**，保存 KTH 图
**51.963/51.524 ms**；四项既定门槛通过，ring 差异很小，不作稳定或整套加速声明。
权重回调减少，逻辑搜索/返回节点数保持；唯一12084次混合调用及额外26次 prefix
资格检查完整保留。应用后一次四模块 **123 passed**，完整20步IRL与复制/hook回归通过；
两文件相同字节的 compile/flake8/pep257在应用前通过。首测试runner因环境变量转义
未启动pytest，修正后只运行一次；失败记录保留。累计采用二十项，七包资格仍为旧版本。
详见 [validation.md 11.156](ltl_automaton_planner/docs/validation.md)。


prefix 松弛复用弹出距离的候选（84a0cd1基线）未采用：一行字典查询改为同一弹出对象，
13项额外资格与38组公共控制通过，四节点路径hash调用26→23，完整Run与源图保持。
固定六组每200次完整搜索中位数旧/候选为ring **459.443/467.648 ms**，bounded
**66.518/65.865 ms**，dense **992.973/988.669 ms**，KTH **49.791/48.267 ms**。
ring约慢1.79%，未通过既定门槛，未补采样或修改生产代码；唯一12086次混合调用和
独立26次资格控制完整保留。二十项已采用优化及既有123项回归资格保持，本轮只更新文档。
详见 [validation.md 11.157](ltl_automaton_planner/docs/validation.md)。


history TS 状态索引候选本轮未采用：64 分支、129 个观测的完整重规划
中位耗时约降10.3%，但单后继图和保存的 KTH 图分别约增11.1%与37.0%，
未通过执行前固定的三项门槛，未补采样。26次独立资格、36次历史语义、
6次profile及9600次完整重规划计时保留；首轮构图异常与仅续跑未执行阶段的记录
一并归档。二十项已采用优化、既有123项回归和完整20步可选IRL资格保持；
本轮只更新文档。详见 [validation.md 11.158](ltl_automaton_planner/docs/validation.md)。


SCC 拓扑扫描现在对标准 DiGraph/ProdAut 直接迭代来源邻接，省去每个可达节点的
邻接视图包装；自定义图保持原 getter 路径。四项预设中位数门槛本轮通过，
完整 Run、拓扑次序、代价类型、动作引用及 outer/inner/getter 回调保持。
应用后一次四模块 **123 passed**，含完整20步IRL；compile/flake8/ament_pep257通过。
累计采用二十一项，详见 [validation.md 11.159](ltl_automaton_planner/docs/validation.md)。


可达临时图的 SCC 遍历现在直接读取邻接字典，保留 NetworkX 2.4 的分量与节点顺序。
本轮固定批次中位数在 ring/bounded/dense/KTH 上分别下降约9.6%/32.0%/3.8%/11.2%，
四项预设门槛通过；这是局部测量结果。完整 Run、代价类型、回调和输入图保持。
应用后一次四模块 **126 passed**，新增分量顺序/回退定向测试，含完整20步可选IRL；
compile/flake8/ament_pep257通过。累计采用二十二项，
详见 [validation.md 11.160](ltl_automaton_planner/docs/validation.md)。


SCC lowlink 的 min 两参数候选本轮未采用：完整Run与回调检查通过，但受限图固定批次
中位耗时约增1.13%，未通过四项预设门槛，未补采样。现有二十二项优化与4c5ab12的
126项回归资格保持，生产源码和测试未改。本轮证据见
[validation.md 11.161](ltl_automaton_planner/docs/validation.md)。


### 最新七包组合验证（源码 bd75495，2026-10-10）

包含目前二十二项已采用优化的源码，在全新构建/安装目录完成 ROS 2 Humble 七包
构建和默认并行测试：**754 个 JUnit 用例，750 passed / 4 skipped，0 errors/failures**。
四项跳过均为既有 copyright；另有一个通过的 CTest 包装用例，colcon 汇总为755项。
全部旧用例身份与跳过状态保持，新增8项规划定向检查；23个模块从新安装环境导入，
实际路径及哈希与当前源码一致。四个真实DDS场景、Studio consumer、历史重规划、
完整20轮可选IRL学习与提交、规划失败后的恢复均通过。

本次刷新第11.138节之后的七包组合验证记录；前文各局部/历史记录仍绑定各自提交。
ROS2 V0.2接口及默认关闭、从示范轨迹学习软任务权重β的IRL范围保持。
本轮验证结果不构成新的性能测量或实机资格。详见
[validation.md 11.162](ltl_automaton_planner/docs/validation.md)。


SCC 首次 DFS 的邻居迭代器缓存候选本轮未采用：分量顺序、完整 Run、代价类型、
动作引用及自定义节点/映射回调检查通过，但固定批次在 ring/bounded/KTH 上的
中位耗时分别约增1.45%/6.50%/5.27%，未达到四项预设性能门槛，未补采样。
生产源码和测试保持；累计采用仍为二十二项，第11.162节七包组合资格继续绑定
原源码 bd75495，可选IRL范围保持。详见
[validation.md 11.163](ltl_automaton_planner/docs/validation.md)。


路径恢复现在对标准 DiGraph/ProdAut 逐节点读取原生后继映射，减少邻接视图包装；
自定义图保留原 getter，恢复中替换的映射仍会被读取，tie、代价类型和动作引用保持。
固定六对、每侧200次完整搜索的批次中位耗时，本轮 ring 约降3.3%、保存的 KTH 图约降8.6%；
bounded/dense差异很小，单节点N1约慢2.1%（预设仅报告），不作整套或稳定加速声明。
四项预设门槛通过，应用后一次四模块 **130 passed**，含原126项及4项新增定向检查、
完整20轮可选IRL；compile/flake8/ament_pep257通过。累计采用二十三项。
七包754项组合资格仍绑定第11.162节源码bd75495，本轮新增资格为上述四模块130项，
没有将两者相加。ROS2 V0.2接口和默认关闭的示范轨迹软权重β学习范围保持。
详见 [validation.md 11.164](ltl_automaton_planner/docs/validation.md)。


前驱外层视图候选已完成固定采样：语义、源图和回调检查通过，但 bounded/dense
批次中位耗时约增3.00%/0.20%，未通过四项预设性能门槛，因此未采用、未重采样。
源码和测试保持第11.164节字节，累计采用仍为二十三项；四模块130项资格仍适用，
七包754项资格继续绑定第11.162节原源码bd75495，本轮没有重跑或合并这两组计数。
ROS2 V0.2接口及默认关闭的示范轨迹软权重β学习范围保持。固定结果和首次夹具失败
均保留，详见 [validation.md 11.165](ltl_automaton_planner/docs/validation.md)。


可达拓扑构建优化已采用，累计二十四项：原生字典路径减少建图重复操作，
自定义图和字典工厂保留原回退路径。固定6对×每侧200次完整kernel采样中，
ring/bounded/dense/KTH批次中位耗时分别下降约2.63%/10.55%/30.75%/9.07%。
本轮四模块136项全部通过，保留原130项及IRL完整20次更新检查；ROS2 V0.2接口与
默认关闭的示范轨迹软任务权重β学习范围保持。七包754项历史资格仍绑定bd75495，
没有重跑或与本轮计数合并。测量范围与准备阶段证据缺口详见
[validation.md 11.166](ltl_automaton_planner/docs/validation.md)。


SCC lowlink 的局部 min/list 消除候选未采用：语义、完整 Run、代价类型、动作引用、hash 顺序、原始输入和自定义回退检查均通过，但固定批次的 ring 与 KTH 中位耗时分别上升约4.742%和0.953%，未达到预设门槛；未补采样。累计采用仍为二十四项，四模块136项资格与 2bfbd81 当前源码绑定，详见 [validation.md 11.167](ltl_automaton_planner/docs/validation.md)。


搜索循环的 `next` 局部绑定候选未采用：完整路径、代价类型、hash/回调、原始输入和资源检查保持，但固定批次的带分支图与 KTH 中位耗时分别上升约0.495%和3.761%，未通过四项门槛；未补采样。累计采用仍为二十四项，源码与四模块136项资格保持，详见 [validation.md 11.168](ltl_automaton_planner/docs/validation.md)。


重规划复制的节点类型检查现在在单次复制内复用 `(str, int)`，累计采用二十五项局部优化。
本轮只测类型检查：固定六对交替、每侧每批16000次，平坦 tuple 的中位耗时
3.718400→2.988800 ms，嵌套 tuple 为8.447800→6.559000 ms，分别约降19.6%/22.4%；
不代表完整复制或重规划的加速比例。24类边界输入保持；应用后现有四模块 **136 passed**，
完整20次可选IRL更新、自定义key、hook顺序和可变对象隔离回归通过，修改文件compile/lint通过。
ROS2 V0.2接口与默认关闭的示范轨迹软任务权重β学习范围保持；七包754项仍为bd75495历史资格。
详见 [validation.md 11.169](ltl_automaton_planner/docs/validation.md)。


SCC 的 `min([a, b])` 改为 `min(a, b)` 候选未采用：完整搜索的语义、Run、hash/回调和源图检查通过，
但固定采样中 KTH 批次中位耗时约升0.106%，未通过四项预设门槛；未补采样。
当前仍为二十五项已采用优化，源码与四模块136项资格保持d5ca7d9版本；本轮没有重跑pytest或lint。
详见 [validation.md 11.170](ltl_automaton_planner/docs/validation.md)。
