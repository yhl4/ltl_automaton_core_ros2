# 历史验证记录

本文件保留根 README 第 11 节的逐轮验证正文，作为历史记录。aggregate 结果可能包含未修改包沿用的既有验证结果；每一轮的范围、数值、fixture 与限制按原记录保留。

返回根 README 测试章节：[README.md 第 11 节](../../README.md#11-测试)。

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

### 11.11 接受环搜索范围优化（2026-10-06）

prefix 仍在完整 Product 上搜索；suffix 只搜索接受点所属的强连通分量。
离开该分量的路径无法返回接受点，因此不可能参与接受循环。分量在本次搜索内
计算，不写入 Product 缓存；目标函数、闭环边计费、严格浮点路径恢复与零代价环
处理保持不变。所有接受点均不可达时不执行额外 SCC 遍历。

以 `b1b97ce` 为旧实现，KTH、Demo-D1 导航及取放三个真实 Product，默认与三起点、
γ=0/1/10 共 18 组总代价差均为 0，路径合法且 initial/possible states 未变。
固定 1,003 节点 Product 包含两节点接受环与 1,000 节点单向尾，suffix 搜索得到有限
距离的节点从 **1,002 个降至 2 个**；前后总代价均为 51，输入边权和状态集合不变。
这是定向搜索范围检查，不表示端到端加速比。

本轮重跑 core、planner、HIL 与 execution 四包，覆盖可选 IRL 示范学习及真实执行
闭环回归；与其他包保留结果合计为 **288 tests, 0 errors, 0 failures, 4 skipped**。

### 11.12 Product guard 求值复用（2026-10-06）

组合 Büchi 的不同层可能共享同一组 hard/soft guard 对象。构造 Product 时，
对同一个 TS 源标签复用这些 guard 的 truth/distance 结果，避免重复求值。
缓存只在当前源节点的构造中使用，切换源节点或重建 Product 都会重新计算，
不保存到 Product、TS 或 Büchi 图中；source-label 语义、动作与加权代价保持不变。

以 `906388b` 为旧实现，对照三个真实 Product 的完整节点、边属性、initial、accept、
accept-with-cycle 与 possible states，结果一致，原 TS/Büchi 未变：

| Product | 节点 / 边 | 旧 guard 求值次数 | 新 guard 求值次数 |
|---|---:|---:|---:|
| KTH | 36 / 72 | 96 | 48 |
| Demo-D1 导航 | 120 / 388 | 180 | 90 |
| Demo-D1 取放 | 180 / 736 | 360 | 180 |

上述三个 Product 的默认与三起点、γ=0/1/10 共 18 组计划总代价差均为 0，
prefix 与闭合 suffix 合法，初始与 possible states 保持不变。这里测量的是 guard
求值次数，不表示端到端加速比。定向检查另验证共享 hard guard、不同 soft guard
不会错误合并，以及修改源标签或 guard 后重建会重新求值。

本轮重跑 core、planner、HIL 与 execution 四包，含 IRL 示范学习与真实执行闭环；
与其他包保留结果合计为 **289 tests, 0 errors, 0 failures, 4 skipped**。

### 11.13 完整命题名与不可满足任务解析（2026-10-06）

修复 `cargo_ready1`、`danger_zone2` 等命题被符号提取正则拆分的问题，
hard/soft 原始 Büchi 与组合图现在记录完整名称；`true`、`false` 作为原生 LTL
常量，不列入原子命题清单，`true_value0`、`false_alarm1` 等普通名称仍保留。

原生 ltl2ba 对不可满足任务生成带 `false;` 的无出边初始状态。解析器现在接受
该输出并保留声明节点，Büchi 工厂使用这些节点构图，不添加虚构转移。
`parse_ltl` 仍返回 transition dictionary；缺失 never header 会明确报解析错误。
真实 `false` hard-task Action 在 READY 与 ACTIVE 下均返回
`ERROR_NO_ACCEPTING_PLAN`，ACTIVE 的 planner/run、快照及执行序号保持不变。
命题 guard、source-label 与代价语义保持不变。

定向检查覆盖完整名称、常量清单、死端状态与缺失 header，并使用原生 ltl2ba
验证原始/组合 Büchi 图与 `parse_ltl` 返回接口。本轮重跑 core、planner、HIL 与
execution 四包；与其他包保留结果合计为 **297 tests, 0 errors, 0 failures, 4 skipped**。

### 11.14 不完整 Promela 输出校验（2026-10-06）

修复解析器静默接受不完整输出的问题。缺少 `fi;` 或 claim 闭合 `}`、未声明的
目标状态、重复状态声明、空 if 块与未声明状态的空 claim 均明确报 `ParseException`。
合法前向引用保持支持，原生 `false;` 的无边初始状态仍可正常解析。

六类错误 fixture 在修复前均被接受，修复后均被拒绝；12 项解析检查与七项原生
ltl2ba/Büchi 集成检查通过。受控故障测试将截断的工具输出注入真实 ROS 2 Action，
返回 `ERROR_INTERNAL` 并保留 ACTIVE planner/run、快照与执行序号；该故障输入是
测试 fixture，不表示观察到了原生 ltl2ba 的输出损坏。

本轮重跑 core 与 planner 两包；与其他包保留结果合计为
**304 tests, 0 errors, 0 failures, 4 skipped**。

### 11.15 同目标 Promela 分支保留（2026-10-06）

同一源/目标的多个 `:: guard -> goto target` 现在将条件合并为带括号的逻辑或，
避免被最后一条分支覆盖。[Promela 的 if 语义](https://spinroot.com/spin/Man/if.html)
允许选择任意可执行分支，因此合并保留同一转移的可执行条件。唯一分支文本、
transition-dictionary 与 DiGraph 接口不变；soft distance 仍沿用现有 OR 的最小值规则。

受控双分支 fixture 的单状态 TS 仅含 `cargo` 标签，边代价为 2、β=5、γ=10。
修复前 hard Product 丢失接受路径，soft 计划总代价为 27；修复后两者均得到
手算总代价 **2 + 10 × 2 = 22**。另用三分支的六种标签核对真值与软距离，
并反转分支顺序，确保较早分支和嵌套条件都保留。

独立原生 ltl2ba 探测的 20 个固定公式均翻译成功，未观察到重复源/目标分支。
以上复现采用受控 fixture，不据此声称当前原生输出发生了该缺陷。

本轮重跑 core 与 planner 两包；与其他包保留结果合计为
**313 tests, 0 errors, 0 failures, 4 skipped**。

### 11.16 组合 TS 节点逐项构造（2026-10-06）

组合 TS 节点与初始状态现在用 `itertools.product` 逐项枚举，避免先物化完整组合
列表；初始状态直接加入已有集合，避免额外的临时集合。公共 `node_product()`
仍返回原顺序的扁平 tuple 列表，零维输入为 `[()]`，空因子返回 `[]`。
节点 label/marker、guard、边覆盖规则与单维分支保持不变。

以 `9b4466a` 为旧实现对照，KTH、Demo-D1 导航与取放的 TS 节点/边顺序及属性、
初始集合和对应 Product 完整值一致，输入因子未被修改。默认及三起点、γ=0/1/10
共 18 组规划总代价差均为 0，prefix 与闭合 suffix 合法，initial/possible states 不变。

固定 64×64×4 无边因子、各因子所有状态均为初始的 fixture 共生成 16,384 个
TS 节点与初始状态。构造期间的 tracemalloc Python 分配峰值为
**11,590,949 → 10,294,820 bytes**，图值与顺序一致；该结果不代表进程总内存
或端到端规划加速。七项 TS 检查覆盖原有 guard 行为、三因子顺序、多个初始状态
及公共列表接口。

本轮重跑 core 与 planner 两包；与其他包保留结果合计为
**316 tests, 0 errors, 0 failures, 4 skipped**。

### 11.17 HIL 异步安全查询（2026-10-06）

受控回调复现了两个控制器的过期结果问题：状态从 A 离开后回到 A，旧 trap
响应仍可能放行人工命令；Velocity 的响应使用查询开始时捕获的输入，可能覆盖
最新导航或人工输入。请求同步抛错会留下 busy 标记，服务不返回也没有查询截止时间。

现在按有效符号 TS 内容变化递增版本，重复相同状态消息不使当前查询失效。
查询保存独立上下文与 Future 身份；异常、缺失响应和超时均释放查询，先脱离上下文
再取消 Future，晚到响应不能影响新查询。新增 `safety_check_timeout`（默认 1 秒，
有限正值），Velocity 的 closest/trap 两阶段共享截止时间。0.1 秒 steady-clock
timer 在下一次回调清理过期请求，响应回调也检查截止时间；不作为严格实时调度保证。
Bool 丢弃过期人工命令，Velocity 回退到最新导航；正常响应也重新检查人工输入
时效并读取最新输入。仲裁公式与速度边界保持不变，销毁节点后抑制晚到服务回调。

新增 22 项检查通过：20 项使用真实 Node 与受控 Future 检查 A→B→A、重复状态、
请求/响应失败、晚到回调、新查询身份、销毁边界、最新输入、人工输入过期和共享
截止时间；另两项通过真实 `monotonic`、steady timer 与 `rclpy.spin_once` 验证未返回
请求的取消和重试。故障用例采用受控服务替身，不声称其为真实 DDS 故障测量。
两个已安装 launch 入口的 `--show-args` 均暴露新参数及默认值。

本轮仅重跑 HIL 包 `colcon test`，含原有 controller、TrapDetection 和 IRL Launch
通信回归及 lint，pytest 为 **45 tests, 0 errors, 0 failures, 1 skipped**；
与其他包保留结果合计为
**338 tests, 0 errors, 0 failures, 4 skipped**。
这些检查不构成硬件安全、机器人示范效果或多线程执行器的验证。

### 11.18 标准 TS 几何与反馈输入（2026-10-06）

以 `3377669` 为基线，零边长的 2×1 网格会生成中心均为 `[0, 0]` 的两个区域，
planner 仍能加载；NaN station 坐标会直接写入节点和动作位姿。生成器现在检查
正边长、有限的输入几何与派生中心，拒绝这些定义，正常 grid/station 输出结构不变。

2D 基线把零四元数当作 yaw=0，在 station 请求下可错误进入该区域；NaN 位姿
会替换 `closest_region` 使用的缓存。现在 `update`/`closest_region` 在计算前
验证 x/y 与四个 quaternion 分量有限，拒绝零四元数。Node 记录并丢弃无效反馈，
保留最后有效 pose 和符号状态，不发布新区域。单位四元数仍是输入假设；本轮没有
归一化或新增 norm 容差。服务使用最后有效 pose，不据此保证观测新鲜度。

6D 验证至少六个位置及前六个分量有限，后续关节仍忽略；无效反馈保留最后有效
区域并记录错误。基线的六个 `1e200` 位置触发 `OverflowError`，距离计算改为
`math.hypot` 后，可按同一欧氏范数正确判定。手算 fixture 中
`sqrt(6) * 1e200 < 1e201`，新实现位于半径 `1e201` 的区域内；另验证严格
`distance < radius` 边界及额外 NaN 关节的原有忽略规则。区域切换、连通性和
hysteresis 规则保持不变，浮点范数的末位舍入可能不同。

模型与真实 Node 回调定向检查为 **30 passed**，包含 18 项新增生成/模型检查和
四项新增回调检查；回调用记录型 publisher，未将其称为 DDS 故障测试。
本轮仅重跑标准 TS 包 `colcon test`，含原有 2D/6D monitor Launch 通信及 lint，
pytest 为 **34 tests, 0 errors, 0 failures, 1 skipped**；
与其他包保留结果合计为 **360 tests, 0 errors, 0 failures, 4 skipped**。
未进行硬件、仿真或机器人示范验证。

### 11.19 HIL 速度数值边界（2026-10-06）

以 `970df4c` 为基线，NaN 人工速度被限幅成默认正向最大速度 `0.5`，Inf 输入
也被直接饱和；NaN 导航分量会污染混合输出，单轴 `1e200` 人工速度的平方触发
`OverflowError`。正值小 `epsilon` 的两个指数均下溢为零，使增益计算除零；
NaN/Inf 参数、负限幅和不足三轴的限幅配置也没有被拒绝。

现在策略入口验证六个速度分量、距离和参数的有限性，三轴限幅必须恰好三个
非负值，零限幅保留为禁用该人工轴。Node 丢弃并记录非有限速度，保留最后有效
导航缓存；无有效缓存时发布零 `Twist`。无效人工输入同时清除人工输入时效。
无效速度或服务距离取消并释放当前查询，旧回调不能影响新查询；有效输入可重试。
混合结果先成功计算才结束查询，节点销毁后不再处理输入回调。

幅值使用 `math.hypot` 保留原欧氏范数定义。单轴 `1e200` 不再平方溢出；三个
`1.5e308` 分量各自有限，但 `sqrt(3) * 1.5e308` 超出浮点范围，内部幅值可为
Inf，之后仍按人工限幅输出三个有限的 `0.5`，不把这个内部标量当作无效命令。
平滑增益仍为 `rho(a)/(rho(a)+rho(b))`，其中 `a=d-ds`、`b=epsilon-a`；
改用等价的稳定指数比值，避免两个指数同时下溢。精确二进制对称中点的 gain
为 `0.5`，非对称小安全区仍按原曲线趋向 `0`/`1`，没有用常数代替平滑区。
五个普通区间点与 60 位 Decimal 原式对照通过；浮点末位舍入可能不同。
导航不额外限幅，deadband、安全区和混合的数学定义保持不变。

新增 36 项检查；策略与真实 Node/受控 Future 两文件合计 **66 passed**，覆盖
参数、命令、服务距离、限幅、指数下溢、缓存、取消与重试，以及销毁边界。
本轮仅重跑 HIL 包 `colcon test`，含原有 controller、TrapDetection、IRL Launch
通信及 lint，pytest 为 **81 tests, 0 errors, 0 failures, 1 skipped**；
与其他包保留结果合计为 **396 tests, 0 errors, 0 failures, 4 skipped**。
故障用例使用受控客户端与记录型 publisher，不声称真实 DDS 故障或硬件安全验证。

### 11.20 执行端快照请求截止时间（2026-10-06）

以 `fe9dd86` 为基线，真实 ExecutionManagerNode 配合永不完成的 Future 复现了
执行停滞：首次快照请求保留 identity；收到同代际的新 step 后仍只有一次请求，
没有 pending observation，retry timer 无法恢复命令。原有异常、空响应和失败
响应回归不覆盖这个未返回请求场景。

新增 `snapshot_request_timeout`（默认 5 秒，有限正值），并在 fake launch 中
暴露为 float 参数。每个请求保存独立上下文、Future 和 monotonic 截止时间；
现有 0.1 秒 retry timer 改用 steady clock。timer、观测和响应回调均检查截止时间，
重复观测不延长请求或不断重置 timer。超时先脱离上下文再取消 Future，保留同一
当前 graph authority 的最新可执行观测以重试。旧响应不能清除新请求或派发命令；
新 instance/generation、no-action 和销毁取消不再需要的请求。

正常响应仍要求 identity、schema 和 retained run 有效，再解析最新 step。
新参数仅限制快照读取，不给已派发 backend 设置超时，也不重试已经尝试的 step；
backend completion 与真实符号状态的独立观测边界保持不变。检查发生在回调调度时，
不声称严格实时截止保证。

新增 **17 项检查**；新旧 Node 两文件合计 **33 passed**，覆盖永不返回请求、
最新 step、达到截止时间但 timer 尚未调度的成功响应、同步 cancel 回调与晚到
成功/异常、重复观测、新 authority/no-action、缺失 Future/回调注册异常及参数。
其中两项运行真实 steady timer 和 SingleThreadedExecutor，在 `use_sim_time=True`
且 ROS 时钟保持零的情况下，分别验证没有新观测和持续重复观测时的取消及重试。
另验证新 instance 的 no-action 观测仍清除旧维度 schema，不阻断独立状态反馈。
故障由受控客户端注入，不声称真实 DDS 丢包测量。

已安装 fake launch 的 `--show-args` 显示新参数和默认值，安装入口解析到当前源码。
首次包级命令遗漏 `--install-base`，误选仓库内旧安装目录，在接口导入阶段失败；
显式选择当前隔离 build/install 后重跑执行包，含原有四项真实 DDS 符号执行闭环
及 lint，结果为 **71 tests, 0 errors, 0 failures, 0 skipped**。
与其他包保留结果合计 **413 tests, 0 errors, 0 failures, 4 skipped**。
未进行仿真物理、实机、机器人示范或多线程执行器验证。

### 11.21 启动参数与运行对象一致性（2026-10-06）

以 `adcb955` 为基线，真实 Node 参数写入复现了配置显示与实际对象不一致：
HIL `max_linear_x_vel` 设置为 `1.2` 返回成功，查询显示 `1.2`，实际限幅仍为
`0.5`；执行节点参数显示 timeout `7.0` / delay `2.0`，缓存仍为 `5.0` / `0.5`。
2D/6D monitor 的模型路径及 2D 消息类型同样可成功写入，却没有重载模型或订阅。

五个节点中这些初始化后缓存的参数现在以 `ParameterDescriptor(read_only=True)`
声明：HIL 两个 controller 的全部配置、执行节点的 delay/快照 timeout、标准
monitor 的路径及 2D 消息类型。运行时写入明确拒绝，参数显示与缓存保持一致；
启动 CLI/parameter overrides 仍先应用再构造对象，`use_sim_time` 保持动态。
三个包补齐直接 `rcl_interfaces` 依赖声明，无新增配置框架或运行时重载逻辑。
区域、仲裁公式、任务、执行身份和既有计时语义保持不变。

新增 **5 passed**：HIL 两个 Node 验证配置只读、启动覆盖、动态 ROS 时钟参数
及混合原子写入的全体拒绝；两个 monitor 验证路径/类型写入拒绝、原模型反馈
继续工作及动态时钟参数；执行 Node 通过真实 DescribeParameters、SetParameters
和 SetParametersAtomically 服务检查公开 descriptor、拒绝结果、启动 timeout/delay
缓存以及原子失败不修改 `use_sim_time`。修复后的同一 HIL probe 返回失败，
查询值、策略限幅和输出均保留 `0.5`。

仅重新构建并串行重跑三个受影响包：执行 **72 tests / 0 skipped**、HIL
**83 tests / 1 skipped**、标准 TS **36 tests / 1 skipped**，合计
**191 tests, 0 errors, 0 failures, 2 skipped**；包含原有 controller、IRL、
TrapDetection、monitor Launch、真实 DDS 符号执行闭环及 lint。
与其他包保留结果合计 **418 tests, 0 errors, 0 failures, 4 skipped**。
这些检查不构成实机、物理仿真或机器人示范验证。

### 11.22 fake 执行延迟与 timer 生命周期（2026-10-06）

以 `bd13d7f` 为基线，默认执行 Node 启动时接受 NaN、Inf 和 `1e10` 秒延迟，
却在首次调度时分别触发浮点转换或原生 timer 范围异常。真实 ROS probe 同时
复现三个 one-shot 完成后 `Node.timers` 仍为 4（初始为 1），节点销毁后
`_execution_timers` 仍保留一个已销毁的 timer 引用。

`FakeBackend` 现在构造时拒绝非数值、非有限和负延迟；默认 ROS Node 额外
使用 `Duration` 检查与原生 timer 相同的纳秒表示范围，错误提前发生在启动时。
通用 scheduler 和自定义 backend 不额外受 ROS 范围约束。零延迟仍使用原有
1 毫秒异步 timer，执行延迟仍使用 ROS clock；快照重试的 steady clock 不变。

one-shot 回调结束后通过 `finally` 销毁 timer，保留回调异常的传播。销毁节点
时先清空执行 timer 集合，再取消并释放资源；已排队回调与后续调度均受关闭
状态保护，不能再修改 fake plant。修复后的真实 probe 显示三个步骤完成后
timer 数量从 4 回到 1，销毁后 Node timer 与执行 timer 集合均为 0。

两个定向测试文件共 **38 passed**，较基线新增 **19** 项检查，覆盖纯 backend
延迟、默认 Node 启动拒绝、原生 timer 释放、回调异常后的释放与继续调度、
销毁后已排队回调、零延迟及自定义 backend 的独立调度契约。
仅重跑受影响的执行包，含原有四项真实 DDS 符号执行闭环、快照恢复与 lint：
**91 tests, 0 errors, 0 failures, 0 skipped**。与其他包保留结果合计
**437 tests, 0 errors, 0 failures, 4 skipped**。
timer 数量检查不构成 RSS 或性能测量；未进行物理仿真、实机或多线程执行器验证。

### 11.23 fake 异步反馈异常后的忙碌状态（2026-10-06）

以 `1cf767c` 为基线，注入一个抛异常的 plant listener 后，异步步骤已经将
plant 从 `r1` 改为 `r2`，但没有调用 completion，manager 一直保持
`in_flight=True`，下一序号被判为 busy。通过真实 ROS timer 和受控 TS publisher
复现相同故障：timer 已释放，执行器仍忙碌。新增三个回归均在基线上失败；
原有两项选中的故障检查通过。

`FakeBackend` 仅在异步 `plant.set_state` 抛普通 `Exception` 时先报告一次失败
completion，再重新抛出原错误，manager 因而释放忙碌状态并记录失败原因。
已发生的 plant 更新保留，未成功交付的 TS 反馈不补造；不修改 listener fanout、
执行身份、去重或观察管线。相同序号不自动重派；调用方处理异常、恢复观察端并
接收新的有效步骤后可以继续派发。异常仍从 executor 抛出，本轮不增加顶层自动恢复。

两个定向测试文件共 **41 passed**，含新增三项：一次失败 completion 与原错误、
实际 plant 状态保留、manager 释放、旧步骤去重和新步骤执行；真实 Node 检查还
验证 timer 资源已释放。故障 publisher 和快照 Future 为受控 fixture，并非真实
DDS 网络故障测量。
仅重跑受影响的执行包，含原有四项真实 DDS 符号执行闭环、快照恢复与 lint：
**94 tests, 0 errors, 0 failures, 0 skipped**。与其他包保留结果合计
**440 tests, 0 errors, 0 failures, 4 skipped**。
未进行物理仿真、实机或多线程执行器验证。

### 11.24 观测管线销毁后的晚到回调（2026-10-06）

以 `cf0cb71` 为基线，保存 observer 回调模拟已排队观测后销毁真实 ROS Node：
`stop()` 虽然已清空 observer 当前回调，保存的旧回调仍进入 abstraction 和
TS publisher，触发 `InvalidHandle: cannot use Destroyable because destruction
was requested`。同一新增回归在基线上失败。

观测回调入口现在检查已有的 `_shutting_down` 状态；关闭后直接丢弃晚到观测，
在 abstraction、日志与发布之前返回。活动节点的观察、schema 校验和 TS 状态
权威保持不变，不新增 observer 框架或更改原有 `start/stop` 生命周期。

新增 **1 passed**：活动时有效观测正常进入 abstraction；销毁后 observer 已
停止，保存的回调对有效及不支持的输入均不再调用 abstraction，也不访问已
销毁 publisher。该检查直接交付保存的 callback，不作为多线程竞争测量。
仅重跑受影响的执行包，含原有四项真实 DDS 符号执行闭环、快照恢复与 lint：
**95 tests, 0 errors, 0 failures, 0 skipped**。与其他包保留结果合计
**441 tests, 0 errors, 0 failures, 4 skipped**。
未进行物理仿真、实机或多线程执行器验证。

### 11.25 快照构造内的重复转换（2026-10-06）

以 `b1aa31e` 为基线，快照服务已经保留提交时的完整消息并返回防御性副本；
重复开销位于一次构造内部。Büchi 排序及消息填充重复计算 identity，Product
排序和消息填充重复转换 TS 值，并在多个 Product 节点中重复计算同一 Büchi
对象的 identity。本轮保留服务防御性复制，只在一次转换中复用不可变 tuple。
Product 属性持有 TS/Büchi 对象，局部缓存以对象身份为键，结束构造后释放；
每个 Product 消息的 `states` 仍创建新 list，不跨图或 generation 保留缓存。
结构化排序、公开 ID、边/接受运行验证及 flatten 规则保持不变。

同一批三个既有小图上加载旧版 serializer，与新版完整消息、Product ID 映射
以及实际 `serialize_message` / `deserialize_message` 结果对照，均相同。
下表计数每次构造的 helper 调用，采用相同 planner 对象和 active TS hash：

| fixture | B/P 节点数 | Büchi identity 旧→新 | TS 值转换旧→新 | 新旧 CDR 长度 |
|---|---:|---:|---:|---:|
| MINIMAL，hard `<> r2`，soft 空 | 2/4 | 8→5 | 8→2 | 836/836 |
| MINIMAL，soft `(r2 || ! r2)` | 4/8 | 16→11 | 16→3 | 1588/1588 |
| KTH，hard `<> r3`，同一 soft | 4/24 | 32→11 | 48→10 | 4868/4868 |

本机对相等旧版消息的重复序列化曾出现原始 CDR 字节差异；本轮报告完整字段、
ID 映射和实际编解码结果相等，不宣称原始字节逐一相同。helper 调用数不作为
整体规划耗时、吞吐或 RSS 测量。

两个定向文件共 **12 passed**，新增三项检查覆盖 single/safe Büchi 的状态值
列表独立性、重新构造不受先前消息修改影响，以及 Büchi 属性改变后新构造
读取新 identity、ID 映射正确且旧消息保持不变。既有 shape mismatch 仍拒绝。
仅重跑受影响的 planner 包：**102 tests, 0 errors, 0 failures, 1 skipped**，
含 Action、Launch、事务与 lint；另重跑执行包原有四项真实 DDS 闭环，**4 passed**。
与其他包保留的 colcon 结果合计 **444 tests, 0 errors, 0 failures, 4 skipped**；
额外直接运行的 DDS 检查不再次累计到这一总数。
未进行物理仿真、实机或 Jazzy 独立验证。

### 11.26 服务快照副本与状态锁（2026-10-06）

以 `6c17694` 为基线，服务在 `_state_lock` 内 deepcopy 整个保留快照。
受控 Event 暂停复制时，另一线程无法获得此锁；释放复制后才可以获得锁。
ROS 默认 callback group 仍互斥，实际共享此锁的并发参与者包括 PlanLTL 和
IRL 的独立 worker。本轮仅减少服务复制的锁占用，不改变 callback group。

所有权检查确认保留消息只在初始化/TS 替换时清空，或在提交时被新的独立副本
替换；metadata 在安装为 active 之前赋值，随后不原地修改。服务仍返回防御性
副本。现在仅在锁内捕获 snapshot 引用与 active TS hash，再在锁外复制。
局部引用保留捕获对象；复制期间新代际提交不会混合旧响应的身份、图或运行。
API 文档明确一次响应对应捕获时的完整代际，复制期间可能已有更新提交。

新增 **3 passed**，三项均在基线上因复制持锁而失败。使用真实 ROS 消息、
实际服务/commit helper 与 RLock/Event/Thread 受控 fixture，覆盖可用快照、
转换不可用及尚无快照：复制被暂停时另一线程获得锁并提交 generation 8；
响应仍为捕获的 generation 7 或旧的无快照/hash 结果，旧消息保持不变，
修改响应也不影响当前保留副本；候选输入不被 commit 原地修改，执行序号归零。
这些 helper 检查不调用 planner，不作为 ROS 多线程 executor 压力或实时性验证。

重跑受影响的 planner 包：**105 tests, 0 errors, 0 failures, 1 skipped**，
含既有只读服务、候选可见性、事务、Action、Launch 与 lint；另重跑原有四项
真实 DDS 符号执行闭环，**4 passed**。与其他包保留的 colcon 结果合计
**447 tests, 0 errors, 0 failures, 4 skipped**，额外 DDS 检查不重复累计。
未测量整体耗时、吞吐或 RSS；未进行物理仿真、实机或 Jazzy 独立验证。

### 11.27 接受运行索引的单次边扫描（2026-10-06）

以 `c0b6bd8` 为基线，执行器首次索引快照时，先构造全部 Product 边的
端点集合检查接受运行，再扫描全部边构造动作查询。现在仅完整扫描一次，
记录命中的运行端点与边引用；先按原有运行顺序报告缺边，再检查缺节点，
最后只对命中的边构造动作查询。运行结构校验、错误优先级、执行身份、
符号状态/动作歧义规则与缓存原子替换保持不变。

新旧 resolver 外部对照共 **11 个 case**：prefix、suffix、closing、自环的
完整 `ExecutionStep`，以及缺边、缺节点、两者同时缺失、重复节点 ID、
边界不匹配、目标歧义和缺边与不可哈希动作并存时的异常类型/精确消息，
全部相同。仓库 resolver 定向检查 **15 passed**；新增两项缺 closing edge
检查，并加强缺节点时保留原缓存的检查。这些检查在基线上也通过，用于
确认优化保持原有拒绝规则，不作为修复原有错误的 RED 证据。

另以预先构造的固定 **128 nodes / 16,384 edges / 4 retained pairs** 图对照：
首次索引的完整边遍历从 **2 次 / 32,768 项** 降为 **1 次 / 16,384 项**；
完整执行步骤相同。同一快照第二次解析时，新旧版本的边、节点及运行序列
遍历增量均为零。在同一次新旧 probe 中，首次解析的 `tracemalloc` 峰值为
**1,446,060 → 15,204 bytes**。此数值仅为该预构造 fixture 下首次解析的
Python 分配峰值，未包括图构造，不代表 RSS、一般规划规模或端到端性能。

仅重跑受影响的 execution 包，包含原有四项真实 DDS 符号执行闭环及 lint：
**97 tests, 0 errors, 0 failures, 0 skipped**。结合其他包保留结果，合计
**449 tests, 0 errors, 0 failures, 4 skipped**。
未进行物理仿真、实机或 Jazzy 独立验证。

### 11.28 HIL 人工输入的 ROS 时间年龄（2026-10-06）

以 `65792ae` 为基线，Velocity 控制器只检查 `age < timeout`。人工输入于
ROS 时间 10 接收、时间回退到 5 后，负年龄仍被判为新鲜；closest 与 trap
两阶段的晚到响应均输出旧人工速度 0.3，而非最新导航速度 0.8。另一个问题
是已观察到过期的样本仍留在缓存，时间返回原窗口后可以重新成为人工输入。

现在 freshness 仅接受 `0 <= age < timeout`；检测到负年龄或过期时清空人工
命令与接收时间，之后必须接收新输入。保持 ROS 时间口径、严格上界、ROS
零时刻的有效接收、零 timeout 禁用人工输入，以及独立 steady 查询截止时间。
混合曲线、限幅、TS 状态版本与异步请求身份规则不变。

新增六项定向检查，在旧源码上为 **4 failed / 2 passed**，修复后均通过：
两阶段异步回复在负年龄时回退导航并释放查询；负年龄与 timeout 边界失效后
不能随时间返回而复活，新人工输入可恢复正常查询；零时刻接收在正 timeout
下有效，零 timeout 下只通过导航。受控 fixture 使用真实 Node 与消息、记录型
publisher 和 Future，ROS 时间与 steady 请求时间分开控制；不作为真实 DDS
`/clock` 分发、机器人安全或实机测量。

重跑受影响的 HIL 包，含既有控制器、TrapDetection/IRL 通信与 lint：
**89 tests, 0 errors, 0 failures, 1 skipped**，其中 async 文件 **43 passed**。
结合其他包保留结果，合计 **455 tests, 0 errors, 0 failures, 4 skipped**。
未进行物理仿真、实机或 Jazzy 独立验证。

### 11.29 显式执行组件的选择（2026-10-06）

以 `90c4e57` 为基线，执行节点用 `or` 选择默认 backend、observer、abstraction
及 fake plant，并以 `if not backend` 决定 fake 延迟校验。符合既有接口、但
布尔值为 False 的显式组件被默认对象替换：后端收不到正式步骤，观测器没有
注册回调，合法独立状态被默认 abstraction 丢弃，所提供的 plant 未被更新。

现在仅对 `None` 参数创建默认组件；默认 backend 与 observer 共享所提供的
plant，自定义 backend 保留其既有调度契约。默认 fake 延迟的有限性、非负性
与 ROS timer 范围检查保持不变。执行身份、步序去重、completion 与 TS 状态
权威、快照请求及 timer 逻辑不变。

新增五项在旧源码上均失败，修复后通过：显式后端收到正式 `move` 步骤且
不创建 fake timer；自定义后端未使用的 fake 延迟构造覆盖不再被错误校验；
observer 注册/停止与 abstraction 的独立观测转换正常；默认 fake 执行确实
更新所提供的 plant 并通过其 observer 报告状态。检查使用真实 Node、受控
快照 Future、调度回调与发布记录，不作为新增真实 DDS 故障或实机测量。

重跑受影响的 execution 包，包含原有四项真实 DDS 符号执行闭环及 lint：
**102 tests, 0 errors, 0 failures, 0 skipped**，node 文件 **23 passed**。
结合其他包保留结果，合计 **460 tests, 0 errors, 0 failures, 4 skipped**。
未进行物理仿真、实机或 Jazzy 独立验证。

### 11.30 TrapDetection 单次反向可达搜索（2026-10-06）

以 `84b1399` 为基线，TrapDetection 对每个候选 Product 状态和接受环节点逐对
调用 `has_path`，只要任一候选能到达 `accept_with_cycle` 中的任一节点便为
非 trap。现在对端点完整的正常 directed Product/set 输入，从接受节点进行
一次反向多源 BFS，遇到候选便短路；仅使用本次查询的 visited/deque。
其它输入保留原始逐对查询，以保持列表/迭代器顺序、缺失节点的异常及成功
短路行为。连通性判定、接受环集合定义、边权与只读服务权威不变。

新增十四项语义保持检查，含搜索方向、多候选/多接受节点、混合 safe/trap、
自身可达、空集合、缺失端点的精确诊断、较早成功路径避开后续缺失节点，
以及同一 Product 对象的边/接受集合变化。旧实现与新实现的 trap 文件均为
**20 passed**，不作为原有算法出错的 RED 证据。

外部新旧对照使用固定 **5 nodes / 5 self-loop edges / 3 candidates /
2 accepting nodes** 图：判定均为 trap；旧实现调用 `has_path` **6 次**，
新实现一次反向遍历，仅两个接受节点各展开 **1 次**，其余三个节点未展开。
添加可达边后两版均为非 trap，移除该边并清空接受集合后均为 trap；空集合、
缺失端点及有序短路的返回值或异常类型/精确消息相同。此计数不是整体耗时、
吞吐或 RSS 测量；不进行跨请求图缓存，也不增加服务的并发锁保证。

重跑受影响的 HIL 包，含既有控制器、TrapDetection 任务替换/只读身份检查、
IRL 通信及 lint：**103 tests, 0 errors, 0 failures, 1 skipped**。
结合其他包保留结果，合计 **474 tests, 0 errors, 0 failures, 4 skipped**。
未进行物理仿真、实机或 Jazzy 独立验证。

### 11.31 IRL 每轮权重的单次边扫描（2026-10-06）

以 `5f47362` 为基线，IRL 每轮先通过 `update_beta` 重算全部 Product 边权，
再完整扫描边添加非示范 margin。现在在私有学习 Product 的一次边遍历内
设置 β、重置 `transition_cost + beta * soft_task_dist` 并按原顺序加 `1.0`。
仅合并两次扫描；示范选择、梯度、步长、20 次上限、0.3 停止条件、接受性
与隔离副本不变，公开的 `ProdAut.update_beta` 也未修改。

新增四项权重保持检查，覆盖零/正 β、普通小数、`1e16` 运算顺序、连续修改 β
及同一 β 重复迭代。每轮重新计算基础权重，margin 不累加；示范边无 margin，
其它边属性不变。旧 helper 运行 **4 passed**，新 core 学习文件 **15 passed**，
用于保持既有行为，不作为旧算法错误的 RED 证据。

外部计数型 Product double 的四条边，在 β=0 与 β=2.5 时旧/新精确权重一致。
旧 helper 调用实际仓库 `ProdAut.update_beta` 后再加 margin，共 **2 次遍历 /
8 个 edge items**；新 helper 为 **1 次 / 4 项**。另在既有真实 `ProdAut`
小图上，新旧完整 `IRLLearningResult` 字段相同，β 序列为 `(1, 2, 3, 3)`；
两份源图的 β、initial、possible states 与边属性不变。计数 double 与完整
学习对照分别验证，不作为整体耗时、吞吐、RSS 或学习效果测量。

重跑受影响的 core 与 HIL 包：分别为 **120 tests / 1 skipped** 与
**103 tests / 1 skipped**，均为 **0 errors / 0 failures**；包含真实 ROS 2
IRL 通信、规划核心与 lint。结合其它未改包保留结果，合计
**478 tests, 0 errors, 0 failures, 4 skipped**。
未进行物理仿真、实机示范或 Jazzy 独立验证。

### 11.32 执行快照 suffix 结构检查（2026-10-06）

以 `660e2c7` 为基线，执行 resolver 会接受末尾重复起点的 suffix；若起点
还有自环，该自环会被额外计为闭合边。既有 `AcceptedRunSnapshot.msg` 规定
首节点不在末尾重复，planner serializer 也已拒绝此形态。现在 resolver 在
边界校验后拒绝长度大于 1 且首末相同的 suffix，使用明确 `ResolutionError`。
合法单节点 suffix 仍通过 Product 自环闭合，无接口消息或规划语义变更。

新增四项定向检查：两项纯 resolver 坏 suffix `(3, 3)` 与 `(3, 4, 5, 3)`
在旧实现均因未抛错失败；额外 `3 -> 3` 边存在，排除原缺边校验导致的拒绝。
合法 `(3,)` suffix 检查在旧实现即通过。另用真实 ROS Node/消息与受控
snapshot Future，旧代码收到 `[2, 2]` suffix 后确实派发一次 `move`，因此
不分派断言失败。修复后坏快照拒绝、manager 不忙碌，并接受后续有效代际。
两项纯 resolver 检查还验证拒绝不替换原有效索引，原快照仍可正常解析。

重跑 execution 包：**106 tests, 0 errors, 0 failures, 0 skipped**，
resolver 文件 **18 passed**，node 文件 **24 passed**；含原有四项真实 DDS
符号执行闭环与 lint。新增坏快照场景不作为真实 DDS 网络故障或机器人测量。
结合其它未改包保留结果，合计 **482 tests, 0 errors, 0 failures, 4 skipped**。
未进行物理仿真、实机或 Jazzy 独立验证。

### 11.33 ltl2ba 进程失败诊断（2026-10-06）

以 `26af9a9` 为基线，translator 被找到但无法执行时会泄漏原始 `OSError`；
信号终止的负退出码被 Planner 当作 `ERROR_INVALID_GOAL`，空诊断还显示
`Unknown ltl2ba error`。现在启动异常统一为保留原 cause 的 `LTL2BAError`，
负退出码明确报告信号号并保留可用 stderr/stdout。Planner 仅把正退出码
映射为既有 `ERROR_INVALID_GOAL`，信号终止返回 `ERROR_INTERNAL`。
参数列表、默认 translator 超时、公式解析与事务式计划替换规则不变。

新增三项检查在旧实现为 **2 failed / 1 passed**：受控启动 `OSError`
没有包装，真实 ROS 2 Action 调用临时 POSIX 脚本自发 signal 9 后返回错误
输入分类。正退出码 1 的诊断/分类检查原本通过。修复后，启动异常 cause、
完整 subprocess 参数/调用者 timeout 均保留；两项 Action 检查确认 ABORTED
以及活动 planner/run、执行序号与完整快照不变。临时脚本由本次 fixture
创建并运行，不代表真实 translator 自身发生了崩溃。

外部临时可执行文件/脚本对照验证非零退出、空 stdout、超时、Exec format
error 和 signal 9 五条路径均为 `LTL2BAError`。Exec format 的 cause 为
`OSError`，signal cause 为 `CalledProcessError(returncode=-9)`；正退出码
保留 stderr 优先的原诊断。未测量崩溃率、进程树清理或总规划截止时间。

重跑受影响 core 与 planner：分别为 **121 tests / 1 skipped** 与
**107 tests / 1 skipped**，均为 **0 errors / 0 failures**；Action 文件
**32 passed**，含既有真实 translator、ROS 2 通信与 lint。结合其它未改包
保留结果，合计 **485 tests, 0 errors, 0 failures, 4 skipped**。
未进行物理仿真、实机或 Jazzy 独立验证。

### 11.34 hard/soft Büchi 后继复用（2026-10-06）

以 `7e9cdb4` 为基线，hard/soft Büchi 组合原先为每个组合状态和两个 level
重复枚举组件后继并读取 guard。现在仅在本次构建内，为每个组件节点保存
有序的 `(target, guard)` 元组；下一次构建重新读取组件。节点/边插入顺序、
全部节点属性、initial/accept/symbols/type、source 接受性驱动的 level 切换、
组件图引用和原 guard 对象引用均保持不变。公式翻译、软任务距离与代价不变。

新增四项检查在旧实现与新实现均通过，用于语义保持，不作为 RED 错误证据。
手工指定的 2 个 hard / 3 个 soft 状态覆盖全部 level 切换、12 个节点与
24 条边的顺序、属性及解析 guard 的引用身份；两个参数化场景分别覆盖无边
hard/soft 组件；更新同一组件 guard 后重新构建验证本次复用不跨调用保留。

外部临时 probe 分别加载旧提交与新源码，并使用计数型 DiGraph 执行实际
构建函数。固定 12 nodes / 24 edges 图的节点、边、属性及顺序一致，每版
均引用自己的输入组件 guard。后继枚举调用 hard 12→2、soft 12→3，合计
24→5；枚举项 hard 24→4、soft 12→3，合计 36→7。该计数使用受控组件，
不作为原生 translator 新旧对照、端到端耗时、吞吐或 RSS 测量。

重跑受影响 core 与 planner：分别为 **125 tests / 1 skipped** 与
**107 tests / 1 skipped**，均为 **0 errors / 0 failures**，合计
**230 passed / 2 skipped**。含新增四项、既有真实 translator、ROS 2 Action
通信与 lint；跳过项为原有版权头检查。结合其它未改包保留结果，合计
**489 tests, 0 errors, 0 failures, 4 skipped**，并非本轮重跑全部包。
未进行物理仿真、实机或 Jazzy 独立验证。

### 11.35 Product 的 TS 后继复用（2026-10-06）

以 `7e1bc97` 为基线，`ProdAut.build_full` 原先随每个 Büchi 源状态重复
枚举同一 TS 源状态的后继和边属性。现在只在每个 TS 源状态的局部范围内，
按原顺序保存 `(target, 原 edge dict)` 元组。Büchi 外层循环、composition
调用顺序、原位置的 weight/action 读取及 `cost + beta * dist` 运算不变。
保留 source-label、guard 求值复用、节点/边顺序与属性、initial/accept/
accept_with_cycle、possible_states 和 TS/Büchi 引用。每次重建重新读取输入；
局部表额外占用与当前 TS 源状态出度成比例的空间，无跨调用缓存。

新增四项检查在旧实现与新实现均通过，不作为 RED 错误证据。三个参数化
场景使用解析 guard，分别检查 hard/soft/safe Büchi 下分支、孤立状态与无边
Büchi 状态的手工指定节点/边顺序、属性、接受集合和源标签软任务代价；另
一项更新 TS 的后继、weight/action 和 initial 后重建，验证新值与旧边清除。

外部临时 probe 加载实际旧提交和新源码，以计数型 DiGraph 构建相同三个
9 nodes Product，边数分别为 4 / 6 / 4。新旧有序图属性与完整接受运行字段
一致（已消费的 zip 迭代器按其剩余元素序列比较），输入 TS 节点/边属性
保持不变；修改输入后的重建结果也一致。每图 TS 后继枚举调用及枚举项
均从 9 降到 3。该 probe 使用受控 TS/Büchi，不作为原生 translator 新旧
对照、端到端耗时、吞吐、RSS 或大图峰值内存测量。

重跑受影响 core 与 planner：分别为 **129 tests / 1 skipped** 与
**107 tests / 1 skipped**，均为 **0 errors / 0 failures**，合计
**234 passed / 2 skipped**；Product 文件 **13 passed**。含既有真实
translator、ROS 2 Action 通信与 lint；跳过项为原有版权头检查。结合其它
未改包保留结果，合计 **493 tests, 0 errors, 0 failures, 4 skipped**，
并非本轮重跑全部包。未进行物理仿真、实机或 Jazzy 独立验证。

### 11.36 TS 代价转换溢出诊断（2026-10-06）

以 `b01d08f` 为基线，动作代价 `±10**400` 在 `math.isfinite` 中触发
`OverflowError`，核心 helper 泄漏原异常，真实加载服务将其报告为
`Unexpected transition-system loading failure`。现在只在既有权重验证内
将该溢出视为无效，返回同一条 `ValueError` 权重诊断。bool/Real、有限性和
非负性规则、有效代价的原类型和值、guard 与图构造不变；服务的其它异常
分类及允许加载的生命周期状态不变。API 文档同步说明该无效权重诊断。

三项新增检查在旧实现均失败：两个核心参数分别覆盖正/负超大整数，另一项
通过真实 ROS 2 LoadTransitionSystem 服务加载含正超大整数代价的 YAML。
修复后，核心两项均为 `ValueError`；服务明确返回
`Action 'goto_r2' weight must be finite and nonnegative.`，保留已验证 TS
对象、active hash 和 READY 状态，随后加载有效 TS B 成功并更新 hash。
该场景在 READY 下没有活动计划，不作为 ACTIVE 计划替换、网络故障或
机器人安全测量；没有扩大已接受数值范围或钳制权重。

重跑受影响 core 与 planner：分别为 **131 tests / 1 skipped** 与
**108 tests / 1 skipped**，均为 **0 errors / 0 failures**，合计
**237 passed / 2 skipped**；TS 配置文件 **18 passed**，planner node 文件
**27 passed**。含既有真实 translator、ROS 2 Action/服务通信与 lint；
跳过项为原有版权头检查。结合其它未改包保留结果，合计
**496 tests, 0 errors, 0 failures, 4 skipped**，并非本轮重跑全部包。
未进行物理仿真、实机或 Jazzy 独立验证。

### 11.37 多维 TS 因子后继复用（2026-10-06）

以 `03c8cda` 为基线，`TSModel.compose_edges` 原先随其它维度的组合状态
重复枚举同一因子状态后继。现在在本次调用内，按维度维护局部表，只在首次
遇到因子状态时保存有序 `(successor, 原 edge dict)` 元组。guard 仍逐项对
完整源标签求值；维度/节点/边顺序、后维度覆盖相同端点的规则、全部属性、
初始集合、单维分支与 guard cache 保持不变。局部表不跨调用，额外空间随
实际遇到的因子状态及其出边增长；空组合不枚举，缺失状态保留 NetworkXError。

四项新增检查在旧实现与新实现均通过，不作为 RED 错误证据。手工指定的
4 nodes / 7 edges 小图检查跨维 guard、自环覆盖、顺序与完整属性；另三项
分别覆盖因子 guard/边/动作/代价/初始状态更新后的重建、空因子和缺失状态。

外部临时 probe 加载实际旧提交与新源码，以计数型 DiGraph 及原 guard 检查
构建固定小图和仓库 YAML。新旧完整有序 TS/图元数据一致，输入因子属性
不变，guard 调用的条件与源标签序列一致；修改固定小图后的重建结果也一致。

| TS | 节点 / 边 | 后继枚举调用（旧→新） | 枚举项（旧→新） | guard 检查调用（两版相同） |
|---|---:|---:|---:|---:|
| 固定小图 | 4 / 7 | 8→4 | 12→6 | 12 |
| KTH YAML | 6 / 10 | 12→5 | 14→6 | 14 |
| Demo-D1 YAML | 30 / 92 | 60→17 | 120→47 | 120 |
| minimal 单维 YAML | 3 / 3 | 0→0 | 0→0 | 3 |

单维构建直接复制因子邻接关系，本次未修改该分支。以上仅为实际构造函数的
操作计数，不作为端到端耗时、吞吐、RSS 或大图峰值内存测量。

重跑受影响 core 与 planner：分别为 **135 tests / 1 skipped** 与
**108 tests / 1 skipped**，均为 **0 errors / 0 failures**，合计
**241 passed / 2 skipped**；TS 文件 **11 passed**。含既有真实 translator、
ROS 2 Action/服务通信与 lint；跳过项为原有版权头检查。结合其它未改包
保留结果，合计 **500 tests, 0 errors, 0 failures, 4 skipped**，
并非本轮重跑全部包。未进行物理仿真、实机或 Jazzy 独立验证。

### 11.38 混合大小写命题名解析（2026-10-06）

以 `0135a03` 为基线，原生 `ltl2ba` 成功翻译 `cargoReady1` 和
`dangerZone2`，但 Boolean guard lexer 在 R/Z 抛出 ValueError，Promela
命题元数据也会拆分名称。两处正则现在统一为 `[a-z][a-zA-Z0-9_]*`，完整
保留小写起首的混合大小写名称；不 lower，不修改 guard truth/distance、
source-label、接受性或代价。true/false 过滤、排序去重与非法字符处理保持
不变。原生工具对首字母大写 `Cargo1` 和首字符下划线 `_cargo` 的拒绝已由
外部小 probe 确认，本次没有扩展这些范围；README/API 同步说明名称约束。

四项新增检查在实际旧 lexer/元数据源码上均失败：纯 guard 检查、命题元
数据、真实 translator 的 hard/soft/组合 Büchi 检查，以及真实 ROS Action。
修复后保留 `cargoReady1` / `dangerZone2` 完整名称，且与全小写变体区分；
解析 guard 的手算 truth/distance 和原生 Büchi guard symbol 均符合预期。

Action 经真实加载服务使用 r1→cargoReady1 与后者自环的 TS，硬任务
`<> cargoReady1`、软任务 `[] !dangerZone2`、beta=1000、gamma=10。
prefix 动作代价 2+1=3，组合 Büchi 接受 suffix 的两次自环代价为 2，
总代价 `3 + 10 * 2 = 23`。相同任务改为 `<> cargoready1` 后 ABORTED /
ERROR_NO_ACCEPTING_PLAN，原 planner 对象、generation、ACTIVE 状态和完整
快照保持不变。该符号小图不作为物理机器人或示范学习效果测量。

重跑受影响 core 与 planner：分别为 **138 tests / 1 skipped** 与
**109 tests / 1 skipped**，均为 **0 errors / 0 failures**，合计
**245 passed / 2 skipped**。Boolean 文件 **10 passed**，Promela 文件
**20 passed**，原生 Büchi 文件 **5 passed**，Action 文件 **33 passed**；
含既有真实 translator、ROS 2 通信与 lint，跳过项为原有版权头检查。
结合其它未改包保留结果，合计 **504 tests, 0 errors, 0 failures, 4 skipped**，
并非本轮重跑全部包。未进行物理仿真、实机或 Jazzy 独立验证。

### 11.39 守卫 token 队列消费（2026-10-06）

以 `b845369` 为基线，Boolean Parser 原先通过 `list.pop(0)` 消费 token，
每次搬移剩余元素。现在内部 token 集合使用 `collections.deque`，全部
消费位置改用 `popleft()`。首项查看与剩余符号查询仍保持原顺序，语法、
左结合构树、NNF、formula、truth/distance 及诊断不变。仓内没有调用方
依赖内部 tokens 的 list 专有操作；本次不修改递归算法或其深度限制。

三项新增检查在实际旧提交与新实现均通过，不作为 RED 错误证据。一项用
手算 NNF 检查四个命题的全部 16 个标签组合、优先级及解析前后 symbols；
另外两项检查 256 命题 AND/OR 的有序 AST、真值、距离与完整消费。

外部临时 probe 加载实际旧源码与当前源码，以计数型 list/deque 记录真实
解析方法的消费。10 个有效和 10 个错误守卫的新旧 AST/NNF、formula、
truth/distance、精确错误信息、token 类型/值/行号/位置消费序列、剩余
token 和 symbols 一致。256 命题 AND 与 OR 各消费 511 个 token，剩余
元素搬移数各由 130,305 降为 0；未测端到端耗时、吞吐、RSS 或深层守卫容量。

仅重跑受影响 core：**141 tests / 1 skipped**，**140 passed**，
**0 errors / 0 failures**，含真实 translator、图构造、代价/接受性、IRL
与 lint；Boolean 文件 **13 passed**，跳过项为原有版权头检查。结合
planner 等其它未改包保留结果，合计
**507 tests, 0 errors, 0 failures, 4 skipped**，并非本轮重跑全部包。
未进行本轮 ROS 通信重跑、物理仿真、实机或 Jazzy 独立验证。

### 11.40 可达 Product 的 SCC 搜索（2026-10-06）

以 `b7c400b` 为基线，prefix Dijkstra 已算出可达节点，搜索阶段的额外 SCC
遍历却仍处理完整 Product。现在只对 prefix 可达节点诱导的只读 DiGraph
view 遍历 SCC；合法接受环的每个节点必定从起点可达，因此不排除有效环。
显式选择 DiGraph view 避免调用需要 ts/buchi 参数的 ProdAut 构造器，
view 共享原属性而不复制完整 Product。prefix/suffix Dijkstra 仍使用原图，
候选顺序、目标函数、闭合边计费、tight 恢复、零代价、None 隐藏边及输入
状态不变。无跨调用缓存；Product 构建时的接受环预计算未改。

三项新增检查在实际旧提交与新实现均通过，不作为 RED 错误证据。覆盖
不可达接受环和添加/移除连接后的重新搜索、显式断开起点、None 隐藏边；
手算代价分别为 5→0→5、0，以及默认/隐藏起点下的 32/30。输入 TS 边、
Product 边、initial/accept/accept_with_cycle/possible_states 保持不变。

外部临时 probe 加载实际旧/新搜索源码，计数型只读 DiGraph view 在真正的
NetworkX SCC 算法入口记录邻接读取。九组查询的完整接受运行字段（已消费
zip 按剩余序列比较）和输入 TS/Product 一致，覆盖固定断开密图、切换
起点、连接再断开、隐藏边、空起点及真实 translator 的 KTH Product。

| 查询 | SCC 处理节点（旧→新） | 邻接读取调用（旧→新） | 邻接项扫描（旧→新） | 两版总代价 |
|---|---:|---:|---:|---:|
| 固定图：3 可达节点 + 32 节点断开完全有向图 | 35→3 | 103→8 | 2,586→11 | 32 |
| 固定图：显式断开起点 | 35→32 | 103→95 | 2,586→2,575 | 0 |
| 固定图：新增连接 | 35→35 | 104→104 | 2,590→2,590 | 0 |
| 原生 KTH，gamma=0 / 10 | 24→14 | 67→41 | 155→91 | 10 / 210 |

移除连接后恢复第一行计数；空起点两版均不调用 SCC。以上仅涵盖搜索阶段
SCC 的处理节点和邻接操作，view 过滤仍有成本；不作为端到端耗时、吞吐、
RSS 或整个 Product 构建加速测量。

仅重跑受影响 core：**144 tests / 1 skipped**，**143 passed**，
**0 errors / 0 failures**；离散规划文件 **16 passed**，含真实 translator、
图构造、代价/接受性、IRL 与 lint，跳过项为原有版权头检查。结合 planner
等其它未改包保留结果，合计
**510 tests, 0 errors, 0 failures, 4 skipped**，并非本轮重跑全部包。
未进行本轮 ROS 通信重跑、物理仿真、实机或 Jazzy 独立验证。

### 11.41 核心 β/γ 转换溢出诊断（2026-10-06）

以 `24d95ea` 为基线，直接调用 Python 核心接口并传入 β/γ=`±10**400`
时，`LTLPlanner.__init__` 的 isfinite 与 IRL 的 float 转换均泄漏
`OverflowError`。现在 Planner 只捕获原验证表达式的 OverflowError，
IRL 将该类型加入原 float 转换的捕获范围；各自返回既有精确 ValueError
诊断，并以 cause 保留原溢出。bool/有限性/非负规则不变，Planner 保留
有效输入的原对象，IRL 保留 float 归一化及数值字符串接受行为。
目标函数、示范选择、margin、梯度、步长、20 次上限和停止条件未改。

八项新增检查在实际旧提交源码上全部失败，修复后全部通过：两个入口各
覆盖 β/γ 与正/负超大整数。Planner 诊断为
`{name} must be finite and nonnegative.`，IRL 为
`{name} must be finite and non-negative.`。IRL 在 deepcopy 和 margin
规划前拒绝无效输入，源边属性、β、initial 与 possible_states 保持不变。
外部小对照确认 int 0/1000、float 2.5、Fraction 1/3 和 Decimal 2.5 五类
有效输入的 Planner 对象与 IRL float 结果保持一致；IRL 的字符串 2.5
接受行为与 Planner 对字符串权重的 TypeError 保持原状，未扩大输入范围。

仅重跑相关 `test_ltl_planner.py` 与 `test_irl.py`：分别 **26 passed** 和
**19 passed**，合计 **45 passed**，含既有真实 translator 规划检查。
两个源码 py_compile/ament_flake8 与两个测试文件 ament_flake8/pep257 均
通过；文档链接、40 节历史验证记录保留及 diff 检查通过。本轮没有重跑整包、
ROS 通信、物理仿真、实机或 Jazzy，也不作为学习收敛/效果测量；超大整数
是 Python 接口的触发输入，没有通过 ROS double 字段传输该数值。

### 11.42 IRL 合流示范后继复用（2026-10-06）

以 `224120b` 为基线，可选 IRL 记录器原先对每条历史分别枚举 Product
末尾状态的相同后继。现在在单次 `update_possible_runs` 内按末尾状态
保存匹配本次 TS 反馈的有序后继元组，仍对每条历史分别追加并返回完整
路径集合。实际已构建 Product 边保持权威；不从 TS/Büchi 推测，不剪枝
或合并不同历史，不改 buffer 阈值、发布、触发、宿主身份或学习规则。
局部表不跨调用，额外空间随本次不同合法末尾状态及其匹配后继增长。

两项新增 fake-host 检查在实际旧提交与新实现均通过，不作为 RED 错误
证据。覆盖不同长度历史合流到同一状态、全部匹配后继、无匹配反馈、
后继删除/恢复后重新更新，以及空/缺失/不可哈希末尾、重复历史、迭代器
和同状态自环；输入历史、Product 边和 possible_states 保持不变。

外部临时 probe 加载实际旧/新源码并运行四项 fake-host 检查，两版各
**4 passed**。计数型 DiGraph 上 6 条有效合流历史、6 个后继（4 个匹配）
均输出同一完整 24 条路径：后继枚举调用 **6→1**，枚举项 **36→6**，
受控观测对象记录的状态比较 **36→6**。无匹配、删/恢复后继、无效及
重复历史的完整路径集也一致，源图不变，下一调用读取修改后的边。
计数不作为端到端耗时、吞吐、RSS 或示范学习效果测量。

只重跑相关 `test_irl_plugin.py` launch 文件：pytest **1 passed**，包含
真实 ROS 2 Action/Bool/DDS 示范记录与学习提交检查；保留 generation
更新、step 归零和启动 β/γ 参数不回写。源码 py_compile/ament_flake8、
测试文件 ament_flake8/pep257、文档链接/41 节历史正文保留及 diff 检查
通过。本轮未重跑整包、物理仿真、实机或 Jazzy，不作为 IRL 收敛证明。

### 11.43 IRL 诊断消息 TS 转换复用（2026-10-06）

以 `592c561` 为基线，`publish_possible_runs` 原先随每个 Product 状态
重复展开相同 TS 值。现在只在本次发布内按 TS 状态保存不可变值元组，
每条 ROS `states` 字段仍创建新列表。repr 排序、完整 run/state 数量、
维度名称、Büchi 字符串、发布及示范/学习规则不变。局部表不跨调用，
额外空间随本次不同 TS 状态及其展开值增长，不复用 ROS 消息对象。

一项新增 fake-host 检查在实际旧提交与新实现均通过，不作为 RED 错误
证据；覆盖组合两维 TS、有序 Büchi 字段、列表独立性及调用方修改后
重新发布。外部临时 probe 加载实际旧/新源码，两版各 **5 passed**，并
对照单维共享、组合两维共享、24 条合流路径和空消息四个小 fixture。
全部有序 ROS 字段、真实编解码结果和所有非填充序列化字节相同，输入
图与 run 集合不变；每个 states 列表独立，第二次发布重新执行转换。

单维 3 条路径 / 6 状态记录的顶层展开调用为 **6→1**；组合两维相同
记录也为 **6→1**。24 条两维路径 / 72 状态记录共 8 个不同 TS 状态，
顶层调用 **72→8**，包括递归在内调用 **360→40**。空消息两版均为 0。
这是函数操作计数，不作为端到端耗时、吞吐、RSS 或消息压缩测量。

初始原始字节全等检查在旧版同一消息重复序列化时也失败；根据当前
string-only 消息定义逐字段检查，差异仅位于 CDR 对齐填充位，有效负载
字节及真实 deserialize 结果一致。因此不声称原始字节串完全相同，也
没有修改 ROS 序列化器或通过删除消息字段解决该差异。

相关 `test_irl_plugin.py` launch 文件 pytest **1 passed**，含既有真实
Action/Bool/DDS 示范记录与提交检查。源码 py_compile/ament_flake8、
测试文件 ament_flake8/pep257、文档链接/42 节历史正文保留及 diff 检查
通过。本轮未重跑整包、物理仿真、实机或 Jazzy，不作为 IRL 收敛证明。

### 11.44 tight 路径恢复在目标发现时停止（2026-10-06）

以 `da1e449` 为基线，距离搜索后的 `_restore_tight_path` 原先在发现
目标后仍扫描当前节点其余后继及此前排队的兄弟节点，直到弹出目标。
现在在首次设置目标的 parent 后结束 BFS；首次发现已经确定完整父节点
链，后续访问不会覆盖它。保留起点顺序、邻接顺序、严格浮点 tight-edge
判断、None 隐藏边、零代价环处理、缺失目标诊断和原始路径重建。
距离搜索、接受性、目标函数及 IRL 学习规则不变；不改并列路径选择。

三项新增检查在实际旧提交和新实现均通过，不作为 RED 错误证据。
覆盖目标位于邻接首位/末位、零代价并列父节点与环、目标本身作为显式
起点；手算路径分别为 source→target、source→a→target 和单节点 target。
图边属性及距离表不变。外部临时 probe 加载实际旧/新源码，七组 helper
调用的完整路径或精确 RuntimeError 诊断一致；含缺失/不一致距离和
严格浮点距离及 None 隐藏边。两个真实 translator KTH Product 查询
（gamma=0/10）的全部接受运行字段与输入图一致，总代价仍为 10/210。

计数型 DiGraph 使用 32 个兄弟分支及各自尾节点。目标在 source 邻接
首位时，恢复后继枚举调用 **1→1**、枚举项 **33→1**；目标在末位时，
调用 **33→1**、枚举项 **65→33**。零代价并列图为调用 **3→2**、项
**6→4**。显式目标起点、缺失目标和不可恢复距离的计数保持原样。
计数仅覆盖路径恢复 helper，不包括 Dijkstra、SCC 或 Product 构建，
不作为端到端耗时、吞吐、RSS、规划或学习效果测量。

仅重跑相关 `test_discrete_plan.py`、`test_ltl_planner.py` 和 `test_irl.py`，
分别 **19 passed**、**26 passed**、**19 passed**，合计 **64 passed**，
含既有真实 translator 与 IRL 检查。源码 py_compile/ament_flake8、
测试文件 ament_flake8/pep257、文档链接/43 节历史正文保留及 diff 检查
通过。本轮未重跑整包、ROS 通信、物理仿真、实机或 Jazzy。

### 11.45 IRL 学习内 margin 边表复用（2026-10-06）

以 `5a28cba` 为基线，`learn_beta` 原先在每轮 margin 更新时重新枚举
Product 边，并判断各边是否属于选定示范。一次学习的私有 Product 拓扑
和示范边集合固定；现在在 deepcopy 后按原边顺序构造本次调用内的
`(edge 属性引用, 非示范标志)` 元组表。每轮仍按原顺序更新全部边，
从引用属性读取 transition_cost/soft_task_dist，先重置 canonical weight
再按需加 1.0 margin；不复制属性字典或跨调用缓存。额外空间随边数增长，
单轮学习未减少边枚举数量，并增加该临时表的构造成本。

示范选择与并列时的首个选择、只读源图和私有 deepcopy 边界、距离搜索、
浮点运算顺序、gradient、step、20 次上限及 0.3 停止阈值保持原样。
公开 ProdAut.update_beta 和 learn_beta 接口未改变；仅内部 margin helper
接收边表。原四项 margin 检查改用该内部签名，保留独立计算的期望权重。

两项新增检查在实际旧提交和新实现均通过，不作为 RED 错误证据：
固定大梯度/受控 suffix 运行完整 20 轮，核对前十次 +10、其后逐次
+10/(iteration+1)、全部 match scores 和每轮四条边的重置权重；同一
私有 Product 被复用，源图不变。另一项在真实 margin 搜索后修改源边
属性，再次学习得到 beta=0 的单轮结果，确认下一调用重新读取输入。

外部临时 probe 加载实际旧/新源码，十组学习调用的完整结果、全部 β
序列、逐轮边权重、完整规划运行字段或精确异常诊断一致；输入 Product、
TS/Büchi 属性、initial/accept 集合和 possible_states 保持不变。覆盖
beta=0/2.5、gamma=0、并列示范的两种顺序、源边修改后再调用、受控
20 轮、反向梯度非负投影、无接受运行和未知示范节点。

计数型边 view 与示范集合执行实际 margin 代码。固定四边图的四轮真实
搜索，边枚举调用 **4→1**、枚举项 **16→4**、示范成员判断 **16→4**，
两版 β 序列均为 (1, 2, 3, 3)。受控 20 轮为调用 **20→1**、项与成员
判断各 **80→4**，两版最终 β=106.68771403175428；该场景的 planner
返回固定 suffix，用于检验迭代规则，不作为真实 planner 的 20 轮测量。
单轮场景两版调用 1、项和判断各 4；无效示范两版均为 0。每轮权重
赋值没有减少。计数仅涵盖 margin 边枚举与成员判断，不作为端到端耗时、
吞吐、RSS、学习收敛或机器人示范效果测量。

相关 `test_discrete_plan.py`、`test_ltl_planner.py` 和 `test_irl.py` 分别
**19 passed**、**26 passed**、**21 passed**，合计 **66 passed**；含
既有真实 translator 检查。IRL `test_irl_plugin.py` launch 文件另为
pytest **1 passed**，含真实 Action/Bool/DDS 示范记录和学习提交检查。
源码 py_compile/ament_flake8、测试文件 ament_flake8/pep257、README/HIL
说明/文档链接、44 节历史正文保留及 diff 检查通过。本轮没有重跑整包、
物理仿真、实机或 Jazzy。

### 11.46 执行 resolver 流式汇总候选 ID（2026-10-06）

以 `31246f9` 为基线，`AcceptedRunResolver.resolve` 原先先保存所有
匹配的 `(source_id, target_id)` 候选，再分别提取目标 TS 状态与源/目标
ID。现在遍历相同有序 current_ids 和 retained target set，直接汇总这
三个集合，省去候选边对列表；没有跳过匹配或提前结束。返回的源/目标
ID 仍分别去重排序，只包含确有匹配边的节点；目标仍须对应唯一 TS 状态。
动作身份、instance/generation/step、结构及源 TS 校验、完整返回字段、
精确失败诊断、快照索引和提交边界不变，未改变 ROS 消息或规划规则。

两项新增检查在实际旧提交和新实现均通过，不作为 RED 错误证据：
两种含重复/重排/无匹配当前节点的输入，对照完整 ExecutionStep；三个
匹配边对汇总为源 IDs (1, 2)、目标 IDs (3, 4)，无匹配的当前节点 5
未进入返回源集合，两个目标共享同一 TS 状态。重复解析同一快照仍使用
原索引，输入顺序变化不影响结果。

外部临时 probe 加载实际旧/新源码，十三组调用的全部步骤字段或精确
ResolutionError 诊断及缓存状态一致。覆盖 prefix、closing suffix、
单节点自环、多 ID 完整汇总、目标歧义、源 TS 歧义、缺失观测节点、
无匹配动作、空当前集合、无 action、身份不一致、缺边优先于缺节点和
显式重复首节点 suffix。另验证失败索引保留先前快照，下一有效 generation
可正常替换并解析新目标状态。

在预构造并已索引的有向二分匹配 fixture 上，仅测量后续单次 resolve
的 tracemalloc Python 分配峰值。128 nodes / 8,256 edges / 4,096
匹配边对：旧版三次均 **267,320 bytes**，新版三次均 **7,728 bytes**；
256 nodes / 32,896 edges / 16,384 匹配边对：旧版三次均
**1,067,736 bytes**，新版三次均 **21,776 bytes**。完整 ExecutionStep
相同，返回全部 64/128 个源与 64/128 个目标 ID，nodes/edges/接受运行
完整序列的重复遍历增量均为零。fixture 的保留 prefix 遍历全部匹配边，
不是 planner 生成的最优路径样本；未包含构图或首次索引，不作为 RSS、
端到端耗时、吞吐或机器人效果测量。

仅重跑相关 `test_accepted_run_resolver.py`、`test_execution_node.py` 和
`test_snapshot_timeout.py`，合计 **61 passed**；`test_real_dds_execution.py`
另为 **4 passed**，包含真实 ROS 2 Action/服务/观察消息与符号 FakeBackend
执行闭环。源码 py_compile/ament_flake8、测试文件 ament_flake8/pep257、
README/执行说明/文档链接、45 节历史正文保留及 diff 检查通过。本轮
未重跑整包、物理仿真、实机或 Jazzy。

### 11.47 ROS 事务候选代价溢出拒绝（2026-10-06）

以 `3476a0a` 为基线，有限输入的数学代价可能在浮点乘法或路径累加中
溢出。真实 translator 的只读 probe 复现原 worker 返回 ERROR_NONE，
且可用快照含 (prefix=3, suffix=2, total=inf)；循环 TS 每条边 1e308、
gamma=0 时得到 (inf, inf, nan)。现在 PlanLTL 和 IRL worker 在确认
可执行接受运行之后、设置当前状态或序列化成功候选之前，按 prefix、
suffix、total 顺序检查 float 转换与有限性。非有限值或转换错误返回
ERROR_INTERNAL，精确说明首个无效字段；转换异常保留原 cause。

检查只作用于 ROS 事务候选，未修改 Core Dijkstra、source-label、数学
代价、示范选择、IRL 更新/步长/停止规则或普通快照转换失败的 fallback。
不钳制计算结果或权重，不设置 β/γ 的额外有限上限；直接 Core/legacy
路径和所有 Product 边的序列化数值检查没有在本轮扩展。

三个新增真实 ROS Action/反馈/快照检查在实际旧提交均失败：γ=1e308
导致 total=inf 的 PlanLTL 仍 SUCCEEDED；β=1e308、soft=(missing1 &&
missing2)、gamma=0 导致 prefix=inf 的 PlanLTL 仍 SUCCEEDED；受控
学习返回 beta=1e308 后的真实 IRL 重规划替换了活动 planner。修复后
两个 Action 为 ABORTED/ERROR_INTERNAL，精确报告 total_cost 或
prefix_cost；IRL 失败保留活动 planner、β 和源边权重。三个场景都保留
generation、execution_step_seq、ACTIVE 状态与完整服务快照。PlanLTL
随后将对应参数降为 1e307，有限结果正常提交并只增加一个 generation。
IRL 场景注入 learned beta 来验证候选边界，不作为原算法的实测学习结果。

外部临时 probe 加载实际旧/新 worker 源码，六组有限候选的完整 ROS
快照和 Product ID 映射相同：gamma=0、普通参数、beta=2.5/gamma=3、
gamma=1e307、beta=1e307/gamma=0、beta=1e308 且软距离为零。
对应 (prefix,suffix,total) 为 (3,2,3)、(3,2,23)、(8,2,14)、
(3,2,2e307)、(2e307,2,2e307)、(3,2,3)。三个原有非有限结果
(3,2,inf)、(inf,2,inf)、(inf,inf,nan) 现在都返回内部失败，outcome
不携带 planner、TS 或快照，未替换为其它路径或放宽接受条件。

另有十八项 helper 检查覆盖三个成本字段的 ±inf、nan、10**400、None
和非法字符串，精确诊断/转换 cause 及源属性保持通过。五组有限值
（int、float、Fraction、Decimal、数值字符串）保持原对象，不原地转换。
超大整数是 Python 内部字段检查，不声称通过 ROS float64 传输该整数。

仅重跑 `test_plan_ltl_action.py` 和 `test_planner_node.py`，合计
**63 passed**，其中 Action 文件含三个新增检查和既有真实 translator /
ROS 2 事务、IRL 提交、快照及转换失败 fallback 检查。源码 py_compile /
ament_flake8、测试文件 ament_flake8/pep257、README/API/HIL 说明、
文档链接/46 节历史正文保留及 diff 检查通过。本轮没有重跑整包、物理
仿真、实机或 Jazzy，不作为性能、收敛或机器人示范效果测量。

### 11.48 PlanLTL worker 意外异常完成 Future（2026-10-06）

以 `61e88c4` 为基线，PlanLTL worker 直接将计算返回值写入 Future；
计算若在内部已分类异常之外失败，worker 线程退出而 Future 保持未完成，
Action 和规划事务无法结束。现在只在 worker 的候选计算调用周围捕获
普通 Exception，转换为带原异常文字的 ERROR_INTERNAL outcome，并通过
原有单次 set_result 交回 executor。已有输入/translator 错误分类、
候选成本检查、提交身份/状态检查、IRL worker 与快照 fallback 保持不变。

四个新增检查在实际旧提交均失败。两个直接使用真实 rclpy Future，分别
注入 RuntimeError 和 ValueError；旧版异常逃出，修复后 Future 完成、
错误码/文字精确且 outcome 不携带可提交的 planner、TS 或快照。另两个
从 READY 和 ACTIVE 发起真实 ROS 2 Action，在真实 translator 和搜索
完成后向候选序列化注入 RuntimeError；旧版两个 Action 在测试观察窗口
内均未完成，并出现 worker 线程异常。失败断言之后仅为旧基线 teardown
完成悬置 Future，不将该清理算作通过，也不在生产代码增加超时或重试。

修复后两个 Action 为 ABORTED/ERROR_INTERNAL，保留精确异常文字，
释放规划 token，保持原 planner、generation、execution_step_seq、
READY/ACTIVE 状态和完整服务快照。恢复序列化后下一有效请求均正常
SUCCEEDED，开始一个新 generation。故障为受控注入，不声称真实 DDS
故障、线程终止、BaseException 或通用进程崩溃恢复。

仅重跑 `test_plan_ltl_action.py` 和 `test_planner_node.py`，合计
**67 passed**，包含四个新增检查，以及既有事务、IRL、候选代价检查和
普通快照转换失败不阻断规划的检查。源码 py_compile/ament_flake8、
测试文件 ament_flake8/pep257、README/API、文档链接/47 节历史正文
保留及 diff 检查通过。本轮未重跑整包、物理仿真、实机或 Jazzy，
未修改目标、规划时限、接受性、IRL 更新/步长/停止规则。

### 11.49 事务提交前准备保留快照和 ID 映射（2026-10-06）

以 `931fbcf` 为基线，候选提交先替换活动 TS/planner/canonical state，
然后才 deepcopy 保留快照；快照 helper 又在构造不可变 ID 映射之前
更新 generation、step 和保留消息。准备若抛出异常，就可能保留混合
代际且未释放规划事务。现在 helper 先在局部完成复制、新元数据和
ID 映射构造，成功后才赋值保留字段；事务候选先调用该 helper，成功
后才替换 planner/TS 和其余执行权威。普通准备异常在锁外转为带原文字
的 ERROR_INTERNAL，经既有失败出口释放事务，不发布候选计划。

六个新增检查在实际旧提交均失败：READY/ACTIVE 下各发起两个真实
ROS 2 Action，分别受控注入保留快照复制和 MappingProxyType 构造
异常；另两个在真实 IRL 候选重规划之后注入同样异常。旧 Action 场景
明确观察到原 planner 已被候选替换；IRL 检查也未能完成既有失败出口。
故障是普通 RuntimeError 的受控注入，不是实测内存耗尽或 DDS 故障。
IRL 学习返回 beta+7 为受控 fixture，用于检查提交隔离，不作为学习效果。

修复后四个 Action 均 ABORTED/ERROR_INTERNAL，错误文字精确，保持
原 planner、TS、快照、IDs 对象以及 canonical/waiting 状态，generation
和 execution_step_seq 不变，token/worker 被清除，状态恢复 READY 或
ACTIVE；完整服务快照一致。两个 IRL 场景保留原 β、Product 权重、
TS/快照/IDs、generation 和 step。移除故障后，PlanLTL 和 IRL 的下一
有效请求均正常提交一个新 generation；IRL 新 β 为注入值且 step 归零。

仅重跑 `test_plan_ltl_action.py` 和 `test_planner_node.py`，合计
**73 passed**；源码 py_compile/ament_flake8、测试文件 ament_flake8 /
pep257、README/API、文档链接/48 节历史正文保留和 diff 检查通过。
helper 的其它调用也采用准备后赋值的次序，但本轮仅给事务候选补充
结构化准备失败出口，不扩展 legacy 重规划或初始规划的恢复范围。
已提交后的 publisher 失败和进程崩溃不在回滚范围；普通快照转换失败
fallback、freshness/锁边界、目标/接受性及 IRL 算法保持不变。本轮未
重跑整包、物理仿真、实机或 Jazzy，不作为性能或收敛测量。

### 11.50 当前七包构建与整包组合验证（2026-10-06）

在实际代码提交 `58481a2b93876a5b4b34eb3a45bc5c799ce181ed` 上重新
构建并测试 aggregate 及六个功能包，补充多轮定向修改之后的组合证据。
`colcon list` 和 aggregate 的六个 exec_depend 确认入口覆盖全部功能包；
aggregate 自身仅提供 ament 入口，没有独立测试。环境为 WSL
Ubuntu-22.04-D、ROS 2 Humble、Python 3.10；保留真实 ltl2ba，未调用
LLM、硬件、物理仿真或 benchmark，未修改代码、测试及判断条件。

使用现有隔离目录 `/tmp/ltl_ros2_completion_20261006`，build/install/log
均显式绑定该目录，build 启用 symlink-install 和 BUILD_TESTING=ON，
选择 `--packages-up-to ltl_automaton_core`。七包全部构建成功。source
隔离 install 后确认 planner 与 core 实际导入解析到本 checkout，msgs
解析到隔离 build 的 rosidl_generator_py。测试同样显式指定 build/install，
选择 aggregate、`--executor sequential --return-code-on-test-failure`，
ROS_DOMAIN_ID=230；七包测试命令正常结束。

按本轮开始时间核对六份独立 JUnit 文件，全部为新结果，不沿用先前
未修改包的结果。每份 XML 的 testcase 数与 tests 属性一致，errors 和
failures 均为零。当前统计如下；“收集”包含 skipped。

| 功能包 | 收集 | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 157 | 156 | 1 |
| ltl_automaton_planner | 122 | 121 | 1 |
| ltl_automaton_execution | 108 | 108 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 36 | 35 | 1 |
| 合计 | 537 | 533 | 4 |

四个 skipped 均为既有 copyright 检查，原生 translator 集成及 POSIX
故障检查未跳过。msgs 的本轮 CTest wrapper 也为 passed；标准
`colcon test-result --test-result-base .../build --verbose` 返回
**538 tests, 0 errors, 0 failures, 4 skipped**，其中多一项是该接口
wrapper，不作为额外独立 pytest 检查。临时副本仅保留本轮六份 JUnit
及当前 CTest XML，四份历史 CTest XML 未用于本轮统计；没有删除或
改写历史结果。源码树保持干净。既有 NumPy/NetworkX 与 lint 插件的
弃用警告仍存在，未作为失败，也未为本轮更换依赖。

检查范围包含当前核心单元/原生 translator、ROS Action/服务/快照/DDS、
符号 FakeBackend 执行、IRL、HIL、标准 2D/6D monitor、已有 lint 与
launch 通信及退出检查。IRL plugin 的 pytest launch wrapper 内包含
其受控 helper/真实通信检查，不将内部 unittest 数另加到上述统计。
本轮为当前版本组合验证，不推出 IRL 收敛、整体加速、真实网络故障、
物理仿真、硬件/机器人示范效果或 Jazzy 兼容性。

### 11.51 多维 TS 每源状态复用 guard 求值（2026-10-06）

以 `8eeeb5e` 为基线，多维 compose_edges 对每条因子后继边调用
is_action_allowed；同一完整源标签的相同 guard 会重复求值。现在
每个组合源节点使用局部 guard_checks 表，只求值第一次遇到的 guard，
包括 False 结果。原因子后继表、全部后继枚举、source-label、维度/
节点/边顺序、action/guard/weight 读取及后维度属性覆盖规则保持不变。
表不跨源节点、compose 调用或 build_full；一维分支、AST parse cache
和公开 is_action_allowed 保持不变。临时表大小随本源不同 guard 数增长，
没有常驻图级缓存；不改变搜索、接受性、目标或 IRL 规则。

两个新增检查在旧提交的求值次数条件均失败：四状态共享跨维度 guard
原调用 16 次，而局部复用后为 4 次。新检查包含 source-dependent 的
True/False、手工九条边/属性/插入次序与自环后维度覆盖，以及重复构图、
修改 guard 后重建和公开 checker 的独立调用。首次新版本相关回归为
91 passed / 2 failed，因为新 fixture 的预期边序忽略了输入图已有边；
按旧输入实际插入次序修正期望，未改构图行为以适配测试，最终通过。

外部临时 probe 加载实际旧/新 ts.py，八个小图/故障案例的完整节点、
边顺序/属性和图元数据相同，原因子图不被修改。共享真假 guard 的
四节点九边图求值 16→4；不同 guard/覆盖 fixture 为 12→9；一维
分支为 4→4，空因子为 0→0；非法 guard 的异常类型及精确文字相同。
guard 修改后的第二次构图也保持完整图一致。

合成全连接因子图的计数：8×8 tautology TS 有 64 节点/960 边，
求值 1024→64；8×8 混合真/假 guard 有 64 节点/496 边，求值
1024→128；4×4×4 tautology TS 有 64 节点/640 边，求值 768→64。
这些是确定性构图操作计数，不包含耗时、RSS 或端到端加速测量。

真实 translator 的 KTH γ=0/10 和 Demo-D1 的 <> kc0 查询，完整 TS、
Product 节点/边及 Run 字段/路径/动作一致，总代价分别为 10、210、6.6。
KTH 构图 guard 求值 14→12；Demo-D1 为 120→60。该查询是规划对照，
不是完整 Demo-D1 机器人示范或物理执行实验。

仅重跑 test_ts.py、test_transition_system.py、test_ltl_planner.py、
test_irl.py 和 test_temporal_capability_regressions.py，合计
**93 passed**。源码 py_compile/ament_flake8、测试文件 ament_flake8 /
pep257、README/文档链接、50 节历史正文保留及 diff 检查通过。
本轮未重跑整包、物理仿真、实机或 Jazzy；11.50 的整包结果仍属于
其原代码基线，不作为本轮整包证据。

### 11.52 6D Python 输入坐标溢出诊断（2026-10-06）

以 `d081611` 为基线，Region6DJointspaceModel 的前六坐标有限性检查
对 ±10**400 的 Python 整数抛出 OverflowError，未转为已约定的
ValueError；Node 的现有失败出口只捕获 ValueError。现在仅给
math.isfinite 的既有捕获增加 OverflowError，保留原精确诊断
`JointState positions must be finite numbers.` 和 raise-from cause。
不转换或钳制输入，不扩展配置 center/radius 校验，不修改区域顺序、
六维截取、严格半径、math.hypot、ROS 参数或规划/IRL 规则。

四个新增检查在实际旧提交均失败，均由 OverflowError 逃出。
两个 model 检查分别使用正/负超大整数，覆盖第一个和第六个坐标，
update 与 is_in_region 均精确返回 ValueError，并保留 OverflowError
cause、输入列表及最后有效区域。第七个同类整数继续被忽略，后续有效
位置正常处理。另两个使用真实 ROS Node 和记录型 publisher，向回调
注入受控 SimpleNamespace Python 消息；无效输入不发布或改变 q1，
随后有效生成 JointState 反馈继续发布 q2。

超大整数不能作为正常的 ROS float64 坐标传输；本轮是 Python 接口
边界检查，不声称真实 DDS 传输此整数，也不是配置几何或物理反馈测试。
现有 nan/±inf、缺少关节、额外关节忽略、严格半径和 1e200 级别有限
坐标的距离检查仍通过。

仅重跑标准 TS 包的 colcon test，明确指定既有隔离 build/install、
ROS_DOMAIN_ID=230 及 --return-code-on-test-failure。结果为
**40 tests, 0 errors, 0 failures, 1 skipped**，即 **39 passed**；
单一 skipped 为既有 copyright 检查。JUnit 确认四个新增 case 均通过。
包含原有 2D/6D monitor launch 通信/干净退出及 package lint。
源码 py_compile/ament_flake8、根与包 README、文档链接/51 节历史正文
保留及 diff 检查通过。本轮没有重跑其它包、物理仿真、实机或 Jazzy，
既有 NumPy/NetworkX 和 lint 插件弃用警告保留。

### 11.53 Planner 批次内复用状态维度名（2026-10-06）

以 `c2cdc7a` 为基线，prefix/suffix 和 possible-state 消息对每个
TS 状态重复展开相同维度名。现在本次构造的第一个状态先按既有顺序
序列化 states、读取维度名，成功后保留不可变 tuple；后续消息仍各自
用新列表写入维度字段。prefix 与 suffix 共用本次局部值，possible-state
捕获本次 planner。无跨调用缓存，不复用可变 states，不新增锁或改变
QoS、公开接口、执行身份、快照、规划目标、接受性或 IRL 规则。

原 prefix 构造与迭代仍先于 suffix；possible-state 仍按 str 排序，
状态、动作、stamp、Büchi 字符串及日志/发布顺序保持不变。空计划或
空候选集合不访问 TS graph；首个状态转换失败仍先于维度元数据访问。
ROS 生成 setter 直接保留传入列表，因此缓存 tuple 后每个消息创建
独立列表，修改一个消息不能影响其它消息；后续调用读取更新后的维度。

十个新增参数化检查覆盖 compound/空维度、prefix+suffix/suffix-only、
相同 TS 状态的多个 Büchi 状态、完整消息字段/顺序与日志、列表独立性、
跨调用刷新、输入保持、空批次缺少 graph/非法 metadata 和错误优先级。
在独立进程执行实际旧提交完整 planner_node.py 后，该文件为
**9 passed / 5 failed**，五个失败均仅为维度复用计数条件：plan 为
5→1 或 3→1，possible-state 为 3→1；旧字段行为没有被判为功能故障。

外部临时 probe 分别加载实际旧完整模块与当前 checkout 模块，使用
真实生成 ROS 消息直接比较完整 LTLPlan、LTLStateArray 和日志。
五个批次对照均相同：compound prefix+suffix 调用 5→1，suffix-only
2→1，三个 Product 候选为 3→1；空计划和不可访问 graph 的空候选
均为 0→0。输入、列表独立性、跨调用刷新与首个转换错误顺序通过。
这是确定性操作计数，未测量耗时、RSS、DDS 传输或端到端加速。

仅运行 test_transition_state_serialization.py、test_plan_ltl_action.py
及 test_planner_node.py，合计 **87 passed**；包含真实 ROS Action
交互与事务回归。加强输入快照断言后，序列化文件的 **14 passed**
再次通过。源码 py_compile/ament_flake8、测试 ament_flake8/pep257、
README/文档链接、52 节历史正文保留及 diff 检查通过。使用既有
Ubuntu 22.04 / ROS 2 Humble / Python 3.10.12 隔离 overlay；本轮
未重跑整包、物理仿真、实机或 Jazzy。11.50 整包证据仍属于原代码
基线，NumPy/NetworkX 的既有弃用警告保留。

### 11.54 遗留 margin 构图示范边成员查询（2026-10-06）

以 `211dca9` 为基线，ProdAut.build_full_margin 将 opt_path 的交替
source/target 配对保存为一次性 zip，随后对每条 Product 候选执行
成员查询。前面的未命中会消耗所有后续项，导致实际示范边未减去 1，
错误保留 margin；即使第一个示范命中，后续未命中也会耗尽余下示范。
现在只将该 zip 固化为 tuple，并补充输入格式 docstring。可重复查询
不新增 hashability 要求，保留原 [0::2]/[1::2] 配对、重复项与奇数
尾项忽略，不改为相邻轨迹边。len<2 的 None 路径、guard/source-label、
cost + beta*dist + 1 - k 运算顺序、节点/边属性与接受循环构造不变。
tuple 仅存在于本次调用；没有跨调用缓存或新增输入校验。

仓内 rg 确认该 helper 只有定义和本次直接测试，没有运行调用点。
当前可选 IRL 的 learn_beta 使用独立 _apply_margin；活跃 build_full、
搜索、β 更新、IRL 学习与 ROS 接口不变。本轮修复遗留公开 helper，
不把该缺陷描述为当前 IRL 的学习故障，也不声称学习效果或加速。

八个新增参数化检查：六项组合 hard/soft/safe Büchi 和示范分支前/后
两种插入顺序，以手算八条边检查两个示范、非示范和跨两个 flat pair
的桥接边；重复示范仅减一次，奇数尾项不参与。验证 transition_cost、
soft_task_dist、initial/accept/accept_with_cycle、输入对象/守卫属性保持，
并以新示范再次调用，确认旧优惠恢复、margin 不累积、节点/边顺序不变。
另两项空/单节点输入保持所有边的 margin。

实际旧提交完整 product.py 在独立进程的八项新检查为
**6 failed / 2 passed**，六项均只因示范边额外加 1 的权重不符失败，
分别为 3 vs 2、7 vs 6、4 vs 3、8 vs 7；没有使用 mocked margin。
初次新版本相关回归为 **62 passed / 6 failed**：边权均正确，但新
输入保留断言直接比较深拷贝后的守卫对象，而它们没有值相等实现。
改为原对象身份与独立属性快照比较，未改生产代码适配测试，随后通过。

仅重跑 test_product.py、test_irl.py 与 test_ltl_planner.py，结果
**68 passed**。源码 py_compile/ament_flake8、测试 ament_flake8/pep257、
README/文档链接、53 节历史正文保留与 diff 检查通过。环境仍为既有
Ubuntu 22.04 / ROS 2 Humble / Python 3.10.12 隔离 overlay；本轮未
重跑整包、物理仿真、实机、Jazzy 或真实示范学习实验。11.50 的整包
证据属于原基线，既有 NumPy/NetworkX 弃用警告保留。

### 11.55 执行 SymbolicState 字符串类型边界（2026-10-07）

以 `7366267` 为基线，SymbolicState 构造只检查空值和 .strip()。
整数/list 会逃出 AttributeError；非空 bytes 有 .strip()，会被误接收，
随后进入生成 ROS 消息 setter 触发断言。现在在维度名和值的既有
短路条件最先检查 isinstance(..., str)，继续返回各自原精确 ValueError。
alignment、维度非空、唯一性、值非空的校验次序保持；合法字符串子类
与含首尾空格的原值及 tuple 身份不变，不转换/裁剪/解码输入。
不扩展 container、其它模型字段或身份校验，不改变 resolver、执行调度、
backend、observer、规划或 IRL。包 README 补充构造要求，并将 fake
abstraction 的说明改为接受已构造 SymbolicState，与实际代码一致。

六个新增 model 参数化检查将非空 int/bytes/list 放在第二个维度或值，
验证每个元素均检查、精确 ValueError 文案及 list 输入保持。一个合法
字符串子类/空格检查确认 tuple 对象和原字符串保持，无额外归一化。
另两个使用真实 ExecutionManagerNode、受控 ConstructingAbstraction 与
记录型 publisher：先记录一条有效生成消息，再输入维度/值 bytes，
拒绝时消息数不变、无 backend 调用，随后有效观察继续记录第二条消息，
第一条的值不变。此处没有发送非法 bytes ROS 消息，不作为 DDS 或
硬件反馈边界验证；生成类型的标准字符串字段未修改。

在独立进程执行实际旧提交完整 models.py 后，九项新增检查为
**8 failed / 1 passed**：四次 int/list 的 AttributeError 逃出、两次
bytes 未抛 ValueError、两个 Node 案例在 state_dimension_names/states
setter 抛 AssertionError；合法子类/原值检查通过。基线不是对模型
行为的 mock；Node 案例的 abstraction 和 publisher 为受控测试组件。

仅重跑 test_backend.py、test_accepted_run_resolver.py 与
test_execution_node.py，合计 **83 passed**。包含已有身份/重复步骤、
resolver、backend 失败恢复、Node 快照重试与观测管线回归。源码
py_compile/ament_flake8、两个测试文件 ament_flake8/pep257、根/包 README、
文档链接、54 节历史正文保留与 diff 检查通过。实际模型 import 的
resolve 路径绑定当前 checkout，使用既有 Ubuntu 22.04 / ROS 2 Humble /
Python 3.10.12 隔离 overlay。本轮未重跑整包、物理仿真、实机、Jazzy
或示范学习实验；11.50 整包证据仍属于其原基线。

### 11.56 2D Python pose 有限性溢出诊断（2026-10-07）

以 `46169bb` 为基线，Region2DPoseModel._validate_pose 在 x/y 与
四个 quaternion 分量的 math.isfinite 检查中只捕获 TypeError。
±10**400 的 Python 整数会逃出 OverflowError。现在仅给既有捕获
增加 OverflowError，保留原 ValueError 精确文字
`Pose position and orientation must be finite numbers.` 和 raise-from cause。
不转换/钳制输入，不增加 z 校验，不改变零 quaternion 拒绝、yaw 公式、
station request、区域次序/严格边界/hysteresis、closest 查询、配置几何、
ROS 字段、消息提取、Node callback、规划或 IRL 规则。

两个新增参数化 model 检查使用正/负超大整数，分别放入第一个受检查
分量 position.x 和最后一个 orientation.w；update 与 closest_region
均返回原 ValueError 并保留 OverflowError cause。输入字段、r1 区域与
s0 station request 不变；随后有效 x/y/quaternion 输入正常进入 r2，
同一输入的超大 position.z 仍被忽略。已有 nan/inf、零 quaternion、
支持的四种消息提取、station/closest 与 6D 边界检查仍执行。

独立进程执行实际旧提交完整 region_2d_pose_monitor.py 后，两个新
检查均因 math.isfinite 的 OverflowError 逃出失败。另一次旧源码
直接 probe 也复现 position.x 正整数、position.y 负整数和 orientation.w
的相同错误。超大整数不能通过正常 ROS float64 pose 字段传输；新
fixture 是受控 SimpleNamespace Python model 输入，没有以 Node 注入、
非法 DDS 传输或物理反馈作为验证。未新增 quaternion 归一化或几何校验。

仅重跑标准 TS 包 colcon test，指定既有隔离 build/install、
ROS_DOMAIN_ID=230 与 --return-code-on-test-failure。标准结果为
**42 tests, 0 errors, 0 failures, 1 skipped**，即 **41 passed**；
JUnit 确认唯一 skipped 是既有 copyright，两个新增 case 均通过。
包含原有 monitor launch 通信/干净退出与包 lint。实际模型 import
resolve 到当前 checkout。源码 py_compile/ament_flake8、测试
ament_flake8/pep257、根/包 README、链接/55 节历史正文保留及 diff
检查通过。环境为既有 Ubuntu 22.04 / ROS 2 Humble / Python 3.10.12；
本轮未重跑其它包、物理仿真、实机、Jazzy 或示范学习，11.50 整包
证据仍属原基线。NumPy/NetworkX 与 lint 插件的既有弃用警告保留。

### 11.57 当前代码七包组合验证刷新（2026-10-07）

在实际代码提交 `c70d38deee51319f109d3f3b5018af1f861be31e` 上构建
并测试 aggregate 与其六个功能包，补充 11.51–11.56 修改后的组合证据。
原 11.50 结果继续保留为其原代码基线的历史记录。本轮不修改源码、
测试、目标函数、学习规则或验收条件，只更新 README 和本记录。
`colcon list` 与 aggregate 的六个 exec_depend 覆盖当前全部包；
aggregate 本身仅提供 ament 入口，没有独立测试。

环境仍为 WSL Ubuntu-22.04-D、ROS 2 Humble、Python 3.10.12、
NetworkX 2.4，使用 `/home/yuhling/.local/bin/ltl2ba`。构建前与测试前
均核对 exact HEAD 和干净源码树；source 隔离 install 后确认 TS/core
planner、ROS planner、execution models 和 2D model 实际导入 resolve
到本 checkout，msgs resolve 到隔离 build 的 rosidl_generator_py。
没有更换依赖、调用 LLM、运行 benchmark、硬件或物理仿真。

使用既有隔离目录 `/tmp/ltl_ros2_completion_20261006`，build/install/log
均显式绑定该目录。构建使用 symlink-install、BUILD_TESTING=ON、
`--packages-up-to ltl_automaton_core` 和 sequential executor，七包
全部成功。测试同样选择 aggregate 并指定隔离 build/install，使用
ROS_DOMAIN_ID=230、`--executor sequential --return-code-on-test-failure`
和 pytest -q，七包命令正常结束，退出码为 0。

按本轮测试开始时间核对六份独立 JUnit，全部为新结果，各 XML 的
testcase 数与 tests 属性一致，errors/failures 均为零。“收集”含 skipped。

| 功能包 | 收集 | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 167 | 166 | 1 |
| ltl_automaton_planner | 132 | 131 | 1 |
| ltl_automaton_execution | 117 | 117 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 42 | 41 | 1 |
| 合计 | 572 | 568 | 4 |

四个 skipped 均为已有 copyright 检查。逐项确认近期 guard 求值复用、
legacy margin、批量维度序列化、SymbolicState 字符串边界及 2D/6D
溢出回归都在新 JUnit 中通过；真实 translator/Büchi 集成与两个 POSIX
故障 case 也通过，未因 PATH 或平台条件跳过。范围还包含既有 ROS
Action/服务/快照/DDS、符号 FakeBackend、可选 IRL、HIL、monitor、
launch 通信/干净退出与 lint。IRL launch wrapper 的内部 unittest 数
不另外加到独立 JUnit 统计，受控学习检查不作为机器人示范实验。

msgs 的本轮 CTest wrapper 为 passed；标准
`colcon test-result --test-result-base .../build --verbose` 返回
**573 tests, 0 errors, 0 failures, 4 skipped**，比独立 JUnit 多一项
接口 wrapper。五份历史 CTest XML 按时间排除，未删除或改写；本轮
六份 JUnit 与当前 CTest XML 另复制到 `verified_results_c70d38d`，
原 `verified_results_58481a2` 保留。`verification_c70d38d.json` 与
`verified_summary_c70d38d.json` 在上述隔离目录记录 HEAD、环境、
导入路径、开始时间、结果数量、必需回归及排除的历史路径。

本轮保留 NumPy/NetworkX 和 lint 插件的既有弃用警告，不改变依赖
绕过它们。结果只证明当前基线的组合检查通过；不推出整体加速、IRL
收敛/逆最优性、真实网络故障、物理仿真、实机/机器人示范效果或
Jazzy 兼容性。全部 56 节历史正文保持，文档链接和 diff 检查通过。

### 11.58 接受环闭合边流式选择（2026-10-07）

以 `d804f78` 为基线，dijkstra_plan_networkX 在每个接受目标的 suffix
距离计算后，将全部可用 predecessor 的闭合环成本保存在 cycle_costs
字典，再用 min 选一个。现在按原 predecessor 次序只保存当前最佳
节点与成本，首个可行候选直接保留，后续仅 candidate_cost < suffix_cost
时替换。省去每个目标随可用入边数增长的临时成本表；prefix/loop
距离表、SCC 与其它搜索空间不变，不宣称整体加速或总内存下降。

仍先读取边的 weight（缺失时为 1），再检查 predecessor 在 loop_dist
且 weight 不是 None，按原 loop_dist[pred] + edge_weight 顺序计算。
并列成本保持首候选，无可行闭合边时继续跳过目标；接受目标的最终
比较、prefix_cost + gamma * suffix_cost、tight 路径恢复、闭合边输出、
显式起点、Product/TS 图与执行身份、ROS 字段及 IRL 学习规则均未改。

五个新增手算 case 包含两种 predecessor 次序的并列成本 5，确认
prefix 成本 2、suffix 成本 5、总成本 52 与首候选动作/闭合边；修改
另一条闭合边后下一次读取新值，suffix 成本 1、总成本 12。记录图边、
initial/accept/accept_with_cycle/possible_states 保持。另两个 gamma=0/10
case 确认缺失 weight 使用 1、None 隐藏闭合边与 SCC 外入边被排除，
suffix 成本 2、总成本为 2/22。最后一个只有隐藏自环，结构上接受但
没有可用闭合候选，正确返回 (None, None)。

独立进程用 git show 导出的完整旧 discrete_plan.py 替换测试进程中的
模块，逐字核对导出内容；上述五个新增 case 在旧模块上也是
**5 passed**，旧/新均符合相同手算结果。另一个普通非负 finite
Product 星形样例有 256 个可用闭合 predecessor：旧函数的局部
cycle_costs 最大为 **256 项**，新函数没有创建该表；两版全部 Run
字段一致（已消费的 zip 字段转为 tuple 比较）。该计数只证明此临时
表被省去，不是计时 benchmark，也不作为整体内存测量。

初次外部对照探针有部分场景名与输入配置不一致，补充脚本尾部还
包含对无计划结果属性的访问；这些部分不作为缺失/隐藏权重、无解或
图属性保留的证据。采用上述精确旧模块的五个仓内 case 补齐这些
边界验证，保留初始临时脚本，没有用场景命名代替实际输入检查。

discrete-plan、ltl-planner、IRL 三个相关测试文件合计 **70 passed**；
随后补充的无可用闭合边 case 单独 **1 passed**，未重复跑三文件。
源码 py_compile/ament_flake8 与测试 py_compile/ament_flake8/pep257
通过。新测试初次 lint 有一行超过已有 99 字符限制，换行后通过，
未改变断言或生产逻辑。使用既有 WSL Ubuntu 22.04 / ROS 2 Humble /
Python 3.10.12 隔离 overlay，NumPy/NetworkX 弃用警告保留。

本轮没有重跑整包、ROS 通信、物理仿真、实机、Jazzy、benchmark
或机器人示范学习；11.57 整包证据仍属于原代码基线。README、
57 节历史正文保留、本地链接/锚点与 diff 检查通过。

### 11.59 运行结果转换复用单条 TS 边属性（2026-10-07）

以 `e2234e1` 为基线，ProdAut_Run.plan_output 的 prefix/suffix 循环
每条 TS 边分别为 action 和 weight 定位同一边属性。现在每次边处理
先读取一次原 edge dict，再先 append action、后 append weight。
引用只用于当前这次边处理，不提前读取 TS、不跨边/调用保存，没有
建立缓存表。prefix/suffix/TS 投影、重复与闭合边次序、zip 类型及
耗尽行为、日志与错误次序、原始数值类型、成本列表起始 0 均保持。
不修改 Dijkstra/SCC、代价公式、接受性、执行身份、ROS 字段或 IRL。

五个新增 case 使用真实 ProdAut 和 TS。一个重复 prefix/self-loop
case 的 prefix 成本 4、suffix 成本 1、总成本 14，确认动作、投影、
重复/闭合边和成本列表完整；四条输出边的真实 DiGraph.__getitem__
访问从旧版 8 次变为新版 4 次。更改 self-loop action/weight 后再次
转换会读取新值，输出列表重新创建，原列表与输入路径保持。原记录的
precost/sufcost/totalcost 按旧行为不在 plan_output 中自动重算，不能
把重新转换旧运行当作修改 TS 后的重新规划证据。

另两个空/单节点 prefix case 均没有 prefix 动作，单节点 suffix
输出一条自环，访问从 2 次变为 1 次；空 prefix 只属于 helper 允许的
输入，不声称 solver 会产生该运行。两个缺 action/weight case 保留
精确 KeyError，缺 action 不添加动作，缺 weight 时已添加该动作而
成本列表仍为 [0]；suffix 的既有输出在 prefix 失败后保持。

独立进程加载 git show 导出的完整旧 product.py 后，五个新增检查
为 **3 failed / 2 passed**，三项只在重复访问计数断言失败，分别是
8 vs 4、2 vs 1、2 vs 1；字段/成本断言在计数前通过，两项错误次序
检查通过。JUnit 原始结果保留在既有隔离目录的
`run_output_baseline_e2234e1.xml`，没有把旧版重复访问作为语义错误。

另用实际旧/当前完整模块对照一条连续四边 prefix 及其终点自环
suffix，手算 prefix 成本 10、suffix 成本 5、总成本 60；全部 Run
字段一致（已耗尽 zip 转 tuple），prefix 访问 8→4、suffix 访问 2→1。
单节点/空 prefix、TS 属性更新后的再转换、缺 action/weight 的异常
和部分输出也一致；各版本调用前后对 Product/TS 节点/边 dict-copy
及接受/初始集合 set-copy 的快照核对保持。旧文件逐字节匹配 git
导出，当前模块导入绑定本 checkout。首次外部探针将线性 prefix
误标为重复路径且与 suffix 不相连，审阅后在同一临时脚本修正为
上述连续路径再运行；原配置不作为可行接受运行的证据。

仅重跑 test_product.py、test_discrete_plan.py、test_irl.py 与
test_ltl_planner.py，合计 **97 passed**。源码 py_compile/ament_flake8、
测试 py_compile/ament_flake8/pep257 通过；环境仍为 WSL Ubuntu 22.04 /
ROS 2 Humble / Python 3.10.12 隔离 overlay，保留 NumPy/NetworkX
弃用警告。没有重跑整包、ROS 通信、物理仿真、实机、Jazzy、benchmark
或机器人示范学习；11.57 整包证据仍属于其原代码基线。README、
58 节历史正文保留、本地链接/锚点与 diff 检查通过。图访问计数只
证明这些边处理的重复定位被省去，不作为整体加速或总内存测量。

### 11.60 空接受集合跳过 SCC 遍历（2026-10-07）

以 `c749780` 为基线，ProdAut.build_accept_with_cycle 对空接受集合
仍遍历全部 Product SCC。现在与本次已创建的空 accepting_cycles
集合比较，确认空 set/frozenset 时将该新集合写入 accept_with_cycle
并返回。没有将任意 falsey 值或缺失键视为空接受集合；用 graph.get
保留原 missing-key 路径。非空分支的 SCC、结构环、自环与交集规则
逐字未变，没有跨调用缓存，不改变权重、Dijkstra、接受运行、执行
身份、ROS 字段或 IRL 规则。

四个新增 case：空图/空 set 与已构图/空 frozenset 均清除 stale
环标记，保留旧标记对象、原接受集合身份、节点/边、initial 与已有
possible_states；空集合时 SCC 调用为 0。已构图案例恢复非空接受
集合后调用 SCC 并标记自环，移除自环后再次调用并清除标记。另两个
受控 missing-accept 案例仍调用 SCC：无环时输出新空标记，有自环
时抛原精确 KeyError('accept') 并保持旧标记，不补造 accept 字段。

独立进程加载 git show 导出的完整旧 product.py 后，四个新增检查
为 **2 failed / 2 passed**，两项仅在 SCC 调用次数 1 vs 0 失败，
两项 missing-key 诊断通过。原始 JUnit 保留在既有隔离目录的
`empty_acceptance_baseline_c749780.xml`。旧行为的结果正确，只存在
这次省去的无用遍历，不将旧版计数失败作为接受性错误。

另用原生 `/home/yuhling/.local/bin/ltl2ba` 做旧/当前完整模块对照。
初始数字 `0` 被工具拒绝，诊断为 `expected predicate, saw '0'`，
没有计为通过，也未修改库代码使其自动替换公式。一个额外矛盾公式
`p && !p` 产生空接受集合；最终按主代理确认采用仓内已有的
`<> (false)` 常量 false fixture：Büchi 仅孤立 T0_init、0 边、空
accept/symbols；两状态循环 TS 生成 Product 2 节点/0 边，initial 与
possible_states 均为 {('s0', 'T0_init')}。两版节点/边/属性及集合快照
一致，TS/Büchi 输入快照保持，SCC 调用旧版 1 次、新版 0 次。
旧源逐字节匹配 git 导出，当前导入与 translator 路径核对。此样例
只有 2 个 Product 节点，不外推大图收益、整体加速或总内存变化。

仅重跑 test_product.py、test_discrete_plan.py、test_irl.py 与
test_ltl_planner.py，合计 **101 passed**。源码 py_compile/ament_flake8、
测试 py_compile/ament_flake8/pep257 通过。使用既有 WSL Ubuntu 22.04 /
ROS 2 Humble / Python 3.10.12 隔离 overlay，保留 NumPy/NetworkX
弃用警告。未重跑整包/ROS 通信、LLM、benchmark、物理仿真、实机、
Jazzy 或机器人示范；11.57 整包证据仍属于原代码基线。README、
59 节历史正文保留、本地链接/锚点与 diff 检查通过。

### 11.61 接受运行边对直接构造 tuple（2026-10-07）

以 `92a46bf` 为基线，AcceptedRunResolver._retained_pairs 原先先建立
prefix 边对列表，再 extend suffix 边对、append 隐式闭合边，最后
复制为 tuple。现在用 itertools.chain 直接构造同一 tuple，省去
中间列表。保留原 prefix/suffix 切片、边对次序与重复项、单节点
suffix 自环及唯一隐式闭合边；此前的结构校验和精确诊断逐字保持。
快照索引、动作解析、缓存提交与失败出口没有改动，不改变模型、
ROS 接口、执行身份、接受性、规划代价或可选 IRL 的 β 学习规则。

七个新增 case 覆盖三个合法路径的 tuple 类型/全部边对、三个结构
错误的精确消息与有效索引保留/恢复，以及缺边优先于缺节点的重复
缺边诊断次序。仅重跑 resolver、backend、execution-node 三个相关
文件，合计 **90 passed**。随后为三个 formatter fixture 补齐实际
Product 边并断言全部边对存在，这三个 case 再次通过；它们是前述
90 项的子集，不另计独立通过项。源码 py_compile/ament_flake8 与
测试 py_compile/ament_flake8/pep257 通过。

独立进程加载 git show 导出的完整旧 resolver 后，七个新增检查
**7 passed**，确认旧版原本具有相同语义。首次临时 harness 因包
初始化会提前导入 resolver 而在模块加载处失败，未执行测试；先
初始化包再加载旧模块后通过，旧源码字节校验保留，未修改生产代码。

另用实际旧/当前完整模块构造边齐全的重复 prefix/multi-node suffix
与 single-node suffix：全部边对 tuple、完整 ExecutionStep、缺闭合
边/显式重复 suffix 的精确诊断、原有效缓存保持及后续恢复一致。
两版调用前保存 deepcopy 并在调用后确认输入快照保持。1024 项
重复 prefix（1、3 交替）与三节点 suffix（3、4、5）产生相同的
1026 项边对，跟踪实际 helper 帧确认旧中间 pairs 列表最大 1026
项，新版无该列表。首次临时大样例只有一个重复自环，single/large
的 deepcopy 比较也未保存调用前状态；审阅后在同一脚本修正并重跑，
上述重复路径与输入保持结论来自修正后的实际断言。仍保留输入切片
和输出 tuple，未测时间、RSS 或总分配，不外推整体加速/总内存收益。

环境仍为既有 WSL Ubuntu 22.04 / ROS 2 Humble / Python 3.10.12
隔离 overlay。未重跑整包/ROS 通信、LLM、benchmark、物理仿真、
实机、Jazzy 或机器人示范；11.57 整包结果属于原代码基线。README、
60 节历史正文保留、本地链接/锚点与 diff 检查通过。

### 11.62 快照导出校验完整接受运行结构（2026-10-07）

以 `5efdada` 为基线，_serialize_run 原先只校验运行节点是否属于
Product、suffix 非空/末尾不重复起点及闭合边。空 prefix、边界不相接
或内部缺边仍可能被导出为 metadata.available=true，执行 resolver
随后拒绝。现在在原有校验之后补查 prefix 非空、prefix 最后节点与
suffix 首节点一致，以及 prefix/suffix 各自全部相邻 Product 边。
保持原有错误优先次序与消息；新的结构失败走既有转换 fallback，
输出 unavailable 元数据、空全部图/运行载荷及空 ID 映射。规划成功
语义、提交规则、ROS 字段、执行身份、搜索/接受性、代价与 IRL 不变。
该检查只证明这些运行结构满足导出契约，不证明接受性或最优性。

四个新增参数 case 分别损坏 prefix、边界、prefix 内部边和 suffix
内部边，健康控制图有三状态 TS、单节点恒真 Büchi 及匹配 Product，
边为 p0→p1→p2→p1。prefix 一边成本 1，suffix 两边各 1、成本 2，
gamma=10 的记录总成本 21。损坏运行的精确 ValueError、unavailable
原因和完整空载荷、Product/TS 与运行保持，以及修复后的完整快照
恢复均核对。初始控制 fixture 将 suffix 两边各写 2 却记录成本 2，
并使用不一致的接受标记；审阅后在同一 fixture 校正权重与恒真接受
标记，补断言记录成本，再重跑四个定向 case，均通过。

新增四个检查在旧源码均失败，因为导出没有抛出结构错误。fixture
校正后，独立进程再次加载逐字匹配 git show 的完整旧模块，仍为
**4 failed**；该失败不是规划无解或算法最优性结果。修复后仅重跑
test_planning_graph_snapshot.py 与 test_snapshot_service_copy.py，合计
**15 passed**；fixture 校正后的四个通过属于前述测试子集，不另计
独立项。保留原 NumPy/NetworkX 弃用警告。源码/测试 py_compile、
ament_flake8 与测试 pep257 通过。

另用原生 ltl2ba 与真实 Core 规划 `<> r2`：source-label 消费规则下
goto_r2 成本 2、再 stay_r2 成本 1 进入接受，prefix=3、suffix=1、
gamma=10、total=13。实际旧/新完整 ROS 快照与公开 ID 映射相同，
执行 consumer 解析 goto_r2 的完整源/目标符号状态为 r1→r2。仅将
运行 prefix 改为空，旧导出仍 available=true 而 consumer 精确拒绝；
新转换返回 unavailable 空载荷，保留运行字段，恢复原 prefix 后
完整快照和 ID 映射再次相同。旧文件字节、当前模块导入与原生
translator 路径核对。此探针不启动 ROS 节点或 DDS 通信。

环境仍为 WSL Ubuntu 22.04 / ROS 2 Humble / Python 3.10.12 隔离
overlay。未重跑整包、ROS 通信、LLM、benchmark、物理仿真、实机、
Jazzy 或机器人示范；11.57 整包结果属于原代码基线。README/API、
61 节历史正文保留、本地链接/锚点与 diff 检查通过。

### 11.63 并行测试 DDS 隔离与最新七包组合验证（2026-10-07）

最近几轮同时修改接受环搜索、运行结果转换、执行边对和快照导出，
本轮重新验证 aggregate 七包组合。初始干净基线为
`2c52c71385ba4c6c732eb199c4de6a60af53cd6b`，构建七包成功，实际
耗时 19.547 秒、exit 0；默认并行整包测试耗时 44.405 秒、exit 1。
六份新 JUnit 合计 **597 tests = 588 passed + 5 failed + 4 skipped**。
execution 为 121 passed/3 failed；HIL 为 100 passed/2 failed/1 skipped。
其它包未失败，四个 skipped 均为已有 copyright。

execution 的观测管线收到其它 TS 的 load/2d_pose_region 消息，两个
真实 DDS 加载请求被不同的 ACTIVE planner/hash 拒绝；HIL 两个 IRL
Action 得到 ABORTED，日志警告可能存在多个 /plan_ltl action server。
并行包的 Context 和 launch 节点此前均继承同一 ROS_DOMAIN_ID=229，
使用同名根 topic/service/action，存在跨包串扰。日志未单独标识每个
重复 server 的进程，不将其作为所有错误的唯一来源证明。未修改规划、
学习或接受判断，也未通过串行、缩短运行或过滤失败用例取得通过。

在 planner/execution/HIL/标准 TS 的 test/conftest.py 收集阶段分别
设置测试 domain 215/216/217/218；各包 in-process Context 和 launch
子进程继承同包设置。此约定适用于 colcon 每包独立 pytest 进程。
四个文件 py_compile 与 diff 检查通过，提交为
`6cbfd3940df2628a0c4ac8ff01c713cbed0a4648`。只有测试环境配置改变，
正式运行节点、ROS 字段、搜索/代价、执行规则及 IRL 算法保持。

修复后的干净基线重新执行相同七包构建与默认并行整包测试，均 exit 0，
实际耗时分别 22.698 秒和 69.542 秒。构建仍使用 packages-up-to
ltl_automaton_core、symlink-install、BUILD_TESTING=ON；测试明确选择
全部七包并启用 return-code-on-test-failure，没有 pytest 用例过滤。
build/install 仍是 `/tmp/ltl_ros2_completion_20261006` 下的隔离目录。
运行环境为 WSL Ubuntu 22.04 / ROS 2 Humble / Python 3.10.12 /
NetworkX 2.4，translator 为原 `/home/yuhling/.local/bin/ltl2ba`，
未升级依赖。构建/测试前后核对 HEAD 和清洁树；Core TS/planner/
Product/discrete-plan、ROS planner/snapshot、execution models/resolver
及 2D monitor 的实际导入来自当前 checkout，生成接口来自隔离 build。

独立核对测试开始时间之后的六份 JUnit，不计历史 XML 或 wrapper 重复项：

| package | tests | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 181 | 180 | 1 |
| ltl_automaton_planner | 136 | 135 | 1 |
| ltl_automaton_execution | 124 | 124 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 42 | 41 | 1 |

合计 **597 tests = 593 passed + 4 skipped，0 errors，0 failures**。
四个 skipped 仍均为已有 copyright。当前接口 CTest wrapper 一项通过，
标准 colcon 汇总为 598 tests；七份旧 CTest XML 按时间排除。近期
25 个接受环/结果转换/边对/导出结构新增 case，四个真实 DDS 场景、
Studio consumer、snapshot fallback、IRL commit/step reset，以及既有
native translator/POSIX 和核心回归均核对确实执行、参数数量正确且
没有跳过。其它完整包检查包括 HIL、2D/6D monitor、launch 与 lint。
保留 NumPy/NetworkX 和 SelectableGroups 的既有弃用警告。

首轮六份失败 JUnit/当前 CTest、完整 receipt 与 SHA256 manifest 保存于
`failed_results_2c52c71_run1`，原 log_combo_2c52c71 与 receipt 保留；
通过轮六份 JUnit/当前 CTest 保存于 `verified_results_6cbfd39`，并有
`verification_6cbfd39.json`、`verified_summary_6cbfd39.json` 与完整
log_combo_6cbfd39。均在上述隔离目录，未把首轮失败或历史通过混入
本次统计，也未覆盖旧 verified_results_c70d38d 的证据。

没有 LLM、benchmark、物理仿真、实机、机器人示范或 Jazzy 验证。
通过支持该基线的组合运行，不证明 IRL 收敛/逆最优性、机器人示范
效果或整体加速。README、62 节历史正文保留、本地链接与 diff 检查通过。

### 11.64 快照私有 Product ID 表省去返回副本（2026-10-07）

初始基线为 `c997347a81315170e9c62e903194d609139570de`。快照构造的
Product ID 表由本次调用新建，后续运行序列化仅查询该表；planner、
输入图及 ROS 消息没有保留该字典引用。返回处现在直接构造
MappingProxyType(product_ids)，省去原 MappingProxyType(dict(product_ids))
中的同大小副本。每次构造仍创建新表，公开映射保持只读。事务提交处
_commit_planning_graph_snapshot 的独立 dict 复制和消息 deepcopy 均保留。
排序、ID、全部消息字段、诊断/fallback、搜索/代价及 IRL 规则保持。

新增定向用例先保留完整快照和 ID，再插入排序靠前的孤立 Product
节点，检查新 ID 及 prefix/suffix 全部引用更新，原快照/映射不变，
两张表都拒绝写入；移除新节点后恢复原完整消息/ID，并仍得到新映射。
首次新用例直接比较 ROS array('I') 与 Python list 而失败，改为 list
后，test_planning_graph_snapshot.py 与 test_snapshot_service_copy.py
合计 **16 passed**，保留两项既有弃用警告。随后仅补齐 suffix ID
断言并单独重跑该用例，**1 passed / 12 deselected**，属于前述测试
子集，不另计独立项。源码/测试 py_compile、ament_flake8，以及测试
pep257 通过；没有为测试比较问题修改生产代码或接受条件。

另加载逐字匹配 git show c997347 的完整旧模块，与当前 checkout
实际导入对照。原生 ltl2ba 规划 <> r2，source-label 消费规则下
goto_r2 成本 2，再 stay_r2 成本 1 进入接受，prefix=3、suffix=1、
gamma=10、total=13。旧/新完整生成 ROS 快照与公开 ID 映射相同。
在两个模块内分别记录实际显式 dict 构造（代理仍调用 builtins.dict），
4 节点 Product 的旧路径复制长度为 [4]，新路径为 []；dict comprehension
未替换。旧/新公开映射均拒绝写入，后续新构造保持字段/值相同且
映射对象独立。证据仅支持本次私有 ID 表减少一个 N 项副本，不作为
总分配、峰值内存、RSS 或整体加速结果。

探针保留于 Windows Temp/probe_snapshot_id_map_c997347.py，旧源码位于
隔离目录 snapshot_baseline_c997347.py；实际当前模块路径与原
/home/yuhling/.local/bin/ltl2ba 均核对。环境仍为 WSL Ubuntu 22.04 /
ROS 2 Humble / Python 3.10.12 / NetworkX 2.4 隔离 overlay，未更换依赖。
本轮没有整包、ROS 节点/DDS、LLM、benchmark、物理仿真、实机、
机器人示范或 Jazzy 验证；11.63 七包结果属于原 6cbfd39 基线。
README、63 节历史正文保留、本地链接/锚点与 diff 检查通过。

### 11.65 IRL 相邻轨迹遍历省去尾部副本（2026-10-07）

初始基线为 `ab75d0fc01fe7a9272f3fe2269ddc095dd51e493`。pure IRL
在示范校验、软距离求和及示范边集合构造中使用 zip(path, path[1:])，
会复制轨迹尾部；软距离在示范选择及每轮学习中重复调用。三处现在
使用 itertools.islice 的流式相邻遍历，不增加 helper 或缓存。输入
仍为校验后的 tuple 和原生 ProdAut_Run.suffix list，不扩大为单次
generator path 接口。候选列表、validated tuple、min 示范选择及并列
规则、原顺序 sum、margin、私有 Product deepcopy、梯度/步长、20 次
上限和 0.3 停止条件保持；suffix 仍不额外计入隐式闭合边。

新增两个 list/tuple 参数化测试，共四个 case：覆盖空/单节点距离零、
重复边/自环逐项计数、不补闭合边、1e16+1+1 的原顺序求和及输入
图/路径保持。示范保留重复节点/边并转换为 tuple；当较早的
good→bad 边缺失而末尾节点 unknown 时，仍先报告 unknown node，
保持全部节点校验先于边校验。test_irl.py 与 test_discrete_plan.py
合计 **49 passed**。补强该错误优先级条件后，仅重跑对应 list/tuple
两个 case，**2 passed / 23 deselected**，属于前述测试子集，不另计独立项。
源码/测试 py_compile、ament_flake8、测试 pep257 与 diff 检查通过。

独立进程加载逐字匹配 git show ab75d0f 的完整旧 IRL 模块，执行
这四个新增语义 case，同为 **4 passed / 21 deselected**；这是行为
保持检查，不作为旧算法错误的 RED 证据。完整旧/新 learn_beta 在
真实 ProdAut 控制小图上返回相同 IRLLearningResult 字段，β 序列为
(1, 2, 3, 3)。在两侧以保留 tuple/list 行为的子类记录实际尾切片，
search 仍调用实际 NetworkX，并保留未计数调用的结果对照：旧版
六个长度 2 的 tuple 尾副本及四个长度 1 的 suffix list 尾副本，新版
均为零。该计数仅针对这些相邻遍历的轨迹副本，其它列表/tuple、
Product deepcopy 和 margin 边表仍保留，不作为总分配/RSS/加速测量。

另以原生 ltl2ba 构造 hard GF hub / soft GF good 的真实 Büchi/Product，
在 hub/good 观测词下获得 64 条示范路径；旧/新完整学习结果相同，
β=6。两组源 Product 的 metadata、节点、边、possible states 及所引用
TS/Büchi 内容，在学习前后的完整 pickle 序列化一致。这是原算法
保持检查，不证明收敛、逆最优性、示范效果或改进学习质量。

完整探针为 Windows Temp/probe_irl_adjacency_ab75d0f.py，旧模块重放
为 replay_irl_semantics_ab75d0f.py，旧源码保留在隔离目录
irl_baseline_ab75d0f.py。旧源码字节、当前 IRL 模块路径与原
/home/yuhling/.local/bin/ltl2ba 均核对。环境仍为 WSL Ubuntu 22.04 /
ROS 2 Humble / Python 3.10.12 / NetworkX 2.4 隔离 overlay，未更换依赖。
本轮没有整包、ROS 节点/DDS、LLM、benchmark、物理仿真、实机、
机器人示范或 Jazzy 验证；11.63 七包结果属于原 6cbfd39 基线。
README、64 节历史正文保留、本地链接/锚点与 diff 检查通过。

### 11.66 2D 生成器初始 cell 与严格区域规则一致（2026-10-07）

初始基线为 `9cc30324e924532efc52516c10dad60d3fb80a1e`。2D 生成器
用 <= half 选择初始 cell，Region2DPoseModel 初次观测则用 < half；
model 初始 state=None，不能用已有区域的滞回规则补偿。2×1 网格、
边长 1、无 station、初始位置 (1, 0.5) 会生成 initial=r1，但 fresh
monitor 在同一位置无法识别任何区域。仅将生成器初始 x/y 比较改为
严格内部规则，边界输入现在抛出既有精确 ValueError：
Initial position is outside the generated grid. 运行时 square/station
几何、正滞回、TS 边/动作/固定代价、搜索/接受性和 IRL 均未修改。

新增四个边界回归，分别为共享边 (1, 0.5)、外边 (0, 0.5)、水平外边
(0.5, 0)、角点 (0, 0)。旧源码在修复前实际 **4 failed / 33 deselected**，
均未抛出预期 ValueError。另两项用 math.nextafter(1, 0) 与
math.nextafter(1, 2) 检查边界两侧内点各自选择 r1/r2，并与 fresh
monitor 一致；一项检查先进入 r1 后，正滞回仍保留共享边状态。
修改后 test_region_models.py 与 test_monitor_inputs.py 合计
**45 passed**，保留两项既有警告。源码/测试 py_compile、ament_flake8、
测试 pep257 与 diff 检查通过，没有修改 monitor 或放宽边界验收。
RED 使用 -k test_generator_rejects_exact_grid_boundaries，只选择四个
新触发场景；PASS 未过滤这两个文件的既有用例。失败与通过输出
保留在本轮工具 stdout，未生成额外 JUnit 或独立日志文件。

独立探针加载逐字匹配 git show 9cc3032 的完整旧生成器，与当前实际
导入对照。四个边界输入的旧输出均为 r1，fresh monitor 返回 None；
新输出均为上述精确 ValueError。四个内点（两 cell 中心及 nextafter
两侧）的完整旧/新 TS 字典相同、initial 与 fresh monitor 相同，输入
定义前后 pickle 字节一致。以正滞回先进入 r1 后移动到共享边，仍
返回 r1；同点的 fresh model 仍返回 None，保持运行时严格规则。

普通内点生成的旧/新 TS 继续通过实际 Core YAML 入口、原生 ltl2ba
规划 <> r2；完整运行字段、生成 ROS 快照及公开 Product ID 均相同。
source-label 规则下 prefix=20、suffix=10、gamma=10、total=120，保留
原固定动作代价 10。此检查不启动 ROS Node 或 DDS，不作为实机/物理
观测证明。未更换边界为闭集，也未修改已有 YAML 或冻结实验数据。

探针为 Windows Temp/probe_initial_cell_boundary_9cc3032.py，完整旧源码
保留于隔离目录 generator_baseline_9cc3032.py。旧源码字节、当前生成器
及 monitor 实际导入的 resolve 路径、原 /home/yuhling/.local/bin/ltl2ba
均核对。环境仍为 WSL Ubuntu 22.04 / ROS 2 Humble / Python 3.10.12 /
NetworkX 2.4 隔离 overlay，build 路径经 symlink 绑定当前 checkout。
本轮没有整包、ROS 节点/DDS、LLM、benchmark、物理仿真、实机、
机器人示范或 Jazzy 验证；11.63 七包结果属于原 6cbfd39 基线。
两份 README、65 节历史正文保留、本地链接/锚点与 diff 检查通过。

### 11.67 Product 边必需字段集合在单次快照内复用（2026-10-07）

初始基线为 `9d4962df07f351026c740be9d2cc451e1f8c2197`。Product
快照导出每处理一条边都会新建相同的 action/transition_cost/
soft_task_dist/weight 四字段 set。现在将该局部 literal set 移到
循环前，边内仍只调用 difference，不外泄、不跨调用缓存。保持
set 类型、缺失字段按字母序诊断、字段读取/转换次序及边排序；
节点/运行校验、全部消息、只读 ID 和事务复制、搜索/代价/IRL 保持。
每条边的 missing 差集与消息仍单独构造。

新增两个参数 case，分别仅缺 weight 和四字段全缺：直接 builder
抛出原精确 ValueError，转换 fallback 保留原诊断并给出完全空载荷，
损坏边属性不被校验改写；恢复字段后完整快照和公开 ID 同原健康
结果。test_planning_graph_snapshot.py 与 test_snapshot_service_copy.py
合计 **18 passed**。补充 ID 恢复断言后仅重跑这两个 case，
**2 passed / 13 deselected**，属于前述测试子集，不另计独立项。
源码/测试 py_compile、ament_flake8、测试 pep257 与 diff 检查通过。
独立加载逐字匹配 git show 的完整旧模块，并核对旧 builder 确实被
planner_node 的 fallback 使用；新增两项同为 **2 passed / 13 deselected**，
用于保持既有行为，不作为算法 bug 的 RED 证据。

完整旧/新 builder 在原生 ltl2ba 的 single/safe/KTH 三个图上比较，
普通及 trace 调用的全部生成 ROS 快照与公开 ID 相同。在实际
missing 差集语句执行处保留真实 required set 引用，避免释放后
地址复用，所观察到的集合数量如下：

| native graph | Product edges | old distinct sets | new distinct sets |
|---|---:|---:|---:|
| single | 5 | 5 | 1 |
| safe | 10 | 10 | 1 |
| KTH | 44 | 44 | 1 |

后续新构造使用另一个新 set；两个缺字段场景的旧/新精确诊断相同，
恢复后完整消息相同。single 的原成本保持 prefix=3、suffix=1、
gamma=10、total=13。首次探针的整对象 pickle 比较失败，诊断再运行
确认唯一新增对象属性是 NetworkX 的 Buchi.nodes 懒 view 缓存；
比较前读取同一 view 后再运行通过，生产代码未因该探针问题改变。
图/运行输入内容保持。初始失败和诊断输出保留在工具 stdout；
此计数只证明这些有边图少了重复四字段集合，不作为总分配、RSS、
整体耗时或加速比测量。

完整探针为 Windows Temp/probe_product_required_fields_9d4962d.py，
旧模块重放为 replay_snapshot_fields_9d4962d.py，完整旧源码保留于
隔离目录 snapshot_baseline_9d4962d.py。旧字节、当前模块的 resolve
导入与原 /home/yuhling/.local/bin/ltl2ba 均核对；build symlink 绑定
当前 checkout。环境仍为 WSL Ubuntu 22.04 / ROS 2 Humble /
Python 3.10.12 / NetworkX 2.4 隔离 overlay，未更换依赖。
本轮没有整包、ROS 节点/DDS、LLM、benchmark、物理仿真、实机、
机器人示范或 Jazzy 验证；11.63 七包结果属于原 6cbfd39 基线。
README、66 节历史正文保留、本地链接/锚点与 diff 检查通过。

### 11.68 KTH 演示驱动延迟参数的有限性与 timer 范围（2026-10-07）

初始基线为 `ad0340847713acc82bd30529f5be545ce68242da`。KTH driver
此前仅检查 step_delay <= 0，NaN/+inf 和有限的 1e10 均会进入
ROS timer 创建。现在保留 scenario、非正延迟和 max_steps 的原
检查/诊断顺序，之后验证延迟有限，并使用当前 Humble Duration
检查纳秒表示范围；超范围统一返回 step_delay 的 ValueError，保留
原 OverflowError cause。检查位于演示 pub/sub/client/timer 创建前。
负值、零与 -inf 仍为原精确 Parameter 'step_delay' must be positive.
诊断；NaN/+inf 为 step_delay must be finite.；超范围为
step_delay is outside the ROS timer range.。没有新常量上限、最小
延迟或构造签名改动，实际传给 timer 的原 delay 保持。

test_kth_demo_driver.py 原有九项动作转换与新增九项参数 case 合计
**18 passed**，无 pytest warnings。验收后补强参数 case，仅重跑
该子集：**9 passed / 9 deselected**，不累计为 27。参数测试实际
构造独立 rclpy Node/Context，演示 pub/sub/client 使用 spy，timer
调用委托原生 Node.create_timer。无效值断言演示实体调用列表为空；
1e10 还核对 ValueError 的 OverflowError cause。有效 0.25 秒的
timer_period_ns 为 250000000，1e-12 秒保持原截断结果 0 ns。
NaN 与 max_steps=0 同时给定时，保留 max_steps 的原诊断优先级。
全部节点/Context 在正常及异常路径销毁/关闭，未做 DDS 通信集成。
源码/测试 py_compile、ament_flake8 --linelength 99、测试 pep257 与
diff 检查通过；补强后仅重新检查修改过的测试文件。

最初新增参数测试在生产修复前为 **3 failed / 6 passed / 9 deselected**，
当时 timer 使用 spy；输出保留在工具 stdout。补强后主代理另加载
逐字匹配 git show 的完整旧模块，收集时断言所有 case 的
KthDemoDriver 绑定该旧类；仍为 **3 failed / 6 passed / 9 deselected**，
实际 pytest exit 1。NaN 在原生 timer 整数转换处泄漏普通 ValueError，
+inf 泄漏 OverflowError，1e10 在 C timer 构造处泄漏 TypeError。
这三个失败均为参数拒绝 case；原非正值、max_steps 优先级及两个
有效原生 timer case 在旧版也通过。失败没有过滤或混入 PASS。
独立重放脚本为 Windows Temp/replay_kth_demo_delay_ad034084.py；
完整旧源码保留于隔离目录 kth_demo_baseline_ad034084.py，重放的
kth_delay_old_ad034084.xml 和 kth_delay_old_ad034084.log 也保留。
当前源码 resolve 路径绑定本 checkout，旧源码字节与基线一致。

使用既有 WSL Ubuntu-22.04-D、ROS 2 Humble 和隔离 overlay：
source /opt/ros/humble/setup.bash 与
source /tmp/ltl_ros2_completion_20261006/install/setup.bash。
测试命令为 python3 -m pytest -q ltl_automaton_planner/test/test_kth_demo_driver.py；
补强子集使用 -k 'step_delay or max_steps_error'。以上两次 PASS 为
工具 stdout，没有新增 PASS JUnit；旧模块重放有独立 JUnit/log。
范围转换依据当前已安装代码及
[rclpy Humble Duration](https://github.com/ros2/rclpy/blob/humble/rclpy/rclpy/duration.py)，
未更换依赖。launch、反馈间隔的有效值、max_steps、场景/阶段、
动作转换与规划/代价/IRL 代码保持。本轮没有整包、完整闭环场景、
LLM、benchmark、物理仿真、实机/机器人示范或 Jazzy 验证；七包
组合结果仍属于 11.63 的 6cbfd39 基线。README 与 KTH 演示说明
同步输入约束，前 67 节历史正文保持，本地链接/锚点与 diff 检查通过。

### 11.69 近期改动后的当前七包组合验证（2026-10-07）

资格基线为干净提交 `4817dd4939c04d14a479f3bb1ef1105eb5c478a1`。
自 6cbfd39 上次整包结果以来，代码已修改快照、IRL 相邻遍历、
2D 初始边界及 KTH driver 参数处理，因此本轮重新执行组合检查。
colcon list 的全部七包与 aggregate 的六个 exec_depend 一致。
使用既有 WSL Ubuntu-22.04-D / ROS 2 Humble / Python 3.10.12 /
NetworkX 2.4，build/install 仍为 /tmp/ltl_ros2_completion_20261006
隔离路径，translator 为原 /home/yuhling/.local/bin/ltl2ba。
构建显式使用 --executor sequential、--symlink-install、
--packages-up-to ltl_automaton_core 与 -DBUILD_TESTING=ON；
测试选择全部七包，默认并行并启用 --return-code-on-test-failure，
没有 pytest 筛选或修改条件/时限。包级测试 domain 215/216/217/218
保留，未更换依赖或修改运行代码。构建 exit 0、实际 35.729804081 秒；
测试 exit 0、实际 61.438237663 秒，各只执行一次。

独立核对测试开始时间之后的六份 JUnit 与当前接口 CTest wrapper：

| package | tests | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 185 | 184 | 1 |
| ltl_automaton_planner | 148 | 147 | 1 |
| ltl_automaton_execution | 124 | 124 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 49 | 48 | 1 |

合计 **620 tests = 616 passed + 4 skipped，0 errors，0 failures**。
四项跳过仍为已有 copyright。接口 CTest wrapper 一项通过，实际
colcon test-result --verbose 返回 **621 tests，0 errors，0 failures，4 skipped**。
八份历史 CTest XML 按时间排除，不与 JUnit 重复计数。aggregate
本身没有独立 pytest case，其七包依赖覆盖已核对。
自 6cbfd39 后新增 23 项逐包核对实际执行且未跳过：快照 3、IRL 4、
2D 生成器边界 7、KTH 参数 9。四个真实 DDS 执行场景、Studio
consumer、快照转换 fallback、IRL commit/step reset，以及既有
接受环/结果转换、native translator/POSIX、HIL、monitor、launch
与 lint 回归也核对。保留 NetworkX/NumPy np.int 及 SelectableGroups
的既有弃用警告；测试日志有五包 stderr，不作为零警告结果。

Core TS/planner/Product/discrete-plan、ROS planner/snapshot、execution
models/resolver 及 2D monitor 的实际导入绑定 checkout，消息为隔离
build 生成接口。主代理另以同一 overlay 核对 IRL、2D generator 与
KTH driver 三个当前模块的 resolve 路径和完整源字节，均与资格
提交相同。构建/测试前后的 HEAD 与清洁树核对，文档提交前源码/
测试保持该基线；本次仓库只改 README 和此验证记录。

本轮 verification_4817dd4.json、verified_summary_4817dd4.json、
verified_results_4817dd4 与 log_combo_4817dd4 均在隔离路径下。
collector 只执行一次，将六份新 JUnit/当前 CTest、receipt/summary、
三模块导入记录、旧证据哈希清单与完整 colcon 实体日志冻结为
83 个文件，sha256_manifest.json 清单逐项通过；日志便利 symlink
不复制，不影响实体日志内容。冻结副本与当前六份 JUnit 字节一致。
先前 verified_results_c70d38d、verified_results_6cbfd39 与
failed_results_2c52c71_run1/原 receipt 共 26 份冻结文件，在本轮前后
SHA256 保持；没有覆盖历史通过、最初五项失败或旧模块重放证据。
新增辅助脚本均使用 4817dd4 独立名字，旧执行脚本没有重跑。

本轮没有 LLM、benchmark、物理仿真、实机/机器人示范或 Jazzy
验证；该耗时是资格命令时间，不是规划性能/加速比，组合通过也不
证明 IRL 收敛或逆最优性。README 刷新为当前资格结果，前 68 节
正文完整保留，本地链接/锚点及 diff 检查通过。

### 11.70 KTH driver 缓存启动配置的只读参数契约（2026-10-07）

初始基线为干净 `a27c17de5ac20b95d232a33d62771a2857ff7a19`，
其源码与 4817dd4 组合资格相同。driver 仅在启动时缓存 scenario、
step_delay、max_steps、replanning_after_steps、replanning_hard_task、
replanning_soft_task，原先却允许运行时成功写入这六项。真实节点
复现六项 set_parameters 都返回 successful=True，但各缓存仍为原
值；例如 step_delay 写入后 self.step_delay 仍为 1.0、timer 仍为
1000000000 ns。该复现保留在工具 stdout，未生成额外 JUnit。

现在分别声明六个独立的 ParameterDescriptor(read_only=True)，
运行时写入拒绝，启动 override 仍应用于缓存和原生 timer。
不共享可变 descriptor，不增加动态重配置或自定义 callback。
继承的 use_sim_time 仍可动态写入；已有 rcl_interfaces 直接依赖
保持，无 package/launch/构造签名、延迟校验/异常优先级、反馈
阶段/步数或规划/代价/IRL 改动。ROS 参数服务的拒绝是本轮可见
接口变化，KTH 文档明确启动设置并补齐两个任务参数。

test_kth_demo_driver.py 初次完整运行 **20 passed**（原 18 项及
两个启动/本地 API case）。随后加入原生公开 SetParametersAtomically
服务 case，单独 **1 passed / 20 deselected**。验收补强两个原子场景，
仅重跑 **2 passed / 19 deselected**；这些属于同一文件的重叠子集，
未重跑最终 21 项整文件，不累计为 23。以上均无 pytest warnings。
完整启动覆盖核对全部六个缓存/参数/descriptor，并确认 0.25 秒
timer 保持 250000000 ns。本地 API 六项分别拒绝且参数/缓存/timer
保持；原子请求先给可写的 use_sim_time、再给只读项，整批拒绝
且 use_sim_time 保持 False，单独 use_sim_time 设置仍成功。

公开 case 使用真实 native Node.create_client 与同 Context 的
SingleThreadedExecutor，服务发现和 Future 等待各沿用 2 秒。
use_sim_time 在前、step_delay 在后的请求被拒绝，无部分写入；
随后独立 use_sim_time 请求成功。此 case 确实经过公开参数 RPC，
driver 演示 pub/sub/client 仍为 spy，timer 和基础参数服务为原生；
不作为完整演示、TS/规划执行闭环或 clock 反馈验证。正常及测试
异常路径清理 client/executor/node/context。源码/测试 py_compile、
ament_flake8 --linelength 99、测试 pep257 与 diff 检查通过，测试
补强后只重新检查已修改的测试文件。

生产修改前未执行两个新增测试，不补称前置 RED。主代理在最终
测试补强后独立加载逐字匹配 git show 的完整旧 driver，收集时
断言 KthDemoDriver 确实绑定旧类。三个新增 case 为
**3 failed / 18 deselected**，实际 pytest exit 1：启动 case 的只读
descriptor 缺失，本地 runtime 和公开 RPC 均实际返回错误的
successful=True，后两项不是被提前 descriptor 断言阻断。
失败 JUnit/log 单独保留，未混入 PASS。完整旧源码保留于隔离
目录 kth_demo_baseline_a27c17d.py，重放脚本为 Windows Temp/
replay_kth_params_a27c17d.py，产物为 kth_params_old_a27c17d.xml 与
kth_params_old_a27c17d.log。当前源码 resolve 与旧字节已核对。

环境仍为 WSL Ubuntu-22.04-D / ROS 2 Humble 及既有隔离 overlay，
未更换依赖。本轮没有七包组合重跑、完整场景、LLM、benchmark、
物理仿真、实机/机器人示范或 Jazzy 验证；11.69 的 620 项结果仍
属于 4817dd4 原资格基线。README/KTH 演示说明同步，前 69 节
历史正文完整保留，本地链接/锚点与 diff 检查通过。

### 11.71 快照运行相邻校验省去尾部副本（2026-10-07）

基线为干净 `86f915eae6dcbbc422b131f571466ec5a59ba89e`。
`_serialize_run` 在 prefix/suffix 相邻 Product 边校验时，以
`zip(nodes, islice(nodes, 1, None))` 替代 `zip(nodes, nodes[1:])`，
省去两个序列尾部副本。仅增加标准库导入与该表达式；保留全部
ID 转换、suffix 非空/重复起点/闭合边、prefix 非空/共享边界、
prefix 先于 suffix 的内部边检查和 any 短路、消息成本转换的顺序。
支持既有 list/tuple 运行，不扩展为单次 generator 输入契约，不改
搜索、接受性、目标函数、IRL、事务、消息或快照服务防御性副本。

复用控制 Product，新增 list/tuple 两种容器的重复访问与单节点
自环四项：重复 prefix 为 p0,p1,p2,p1,p2,p1，suffix 为
p1,p2,p1,p2，手算成本为 5/4/45；单节点 prefix/suffix 均为 p1，
零代价 Product 自环成本 0/0/0。断言完整 ID 顺序、重复项、成本
及输入图/run 未变。既有损坏参数化增加 prefix/suffix 同时缺边，
仍先报告 prefix missing。两个快照相关文件一次运行 **23 passed**，
保留两条既有 NetworkX/NumPy np.int 弃用警告；没有前置 RED，
新用例为语义保留检查。源码/测试 py_compile、ament_flake8
--linelength 99（两文件）、测试 pep257 与 diff 检查通过；实际
source realpath 指向本 checkout 的隔离 symlink overlay。

主代理独立加载逐字匹配 git show 的完整旧模块，对照三个原生
single/safe/KTH 小规划，成本分别为 3/1/13、3/2/23、20/20/220。
再对照上述四个 list/tuple 控制运行；完整 ROS 快照、Product ID
映射、图/run 输入 pickle 字节均相同。对支持序列的真实切片和
has_edge 调用做独立观察：每次尾部切片 2 -> 0，三个原生运行的
被复制元素数分别 2/3/3 -> 0，重复控制运行 8 -> 0；单节点原
尾部为空，也不再触发尾部切片。每个成功运行的 has_edge 次序
完全相同。两个损坏运行的精确 ValueError、短路调用和 unavailable
空载荷亦相同；同时缺边时仅检查闭合边 p2->p1 与缺边 p0->p2，
没有继续检查 suffix。该观察不测时间，不作为整体性能/加速比。

原生 translator 保持 /home/yuhling/.local/bin/ltl2ba，当前模块
resolve 与完整旧字节已核对。旧源码位于隔离目录
snapshot_baseline_86f915e.py；对照脚本为 Windows Temp/
probe_snapshot_run_slices_86f915e.py，成功 stdout 保留在工具记录。
环境仍为 WSL Ubuntu-22.04-D / ROS 2 Humble 及既有 overlay，
不更换依赖。本轮没有七包、完整演示、LLM、benchmark、物理仿真、
实机/机器人示范或 Jazzy 验证；11.69 的 620 项仍属于 4817dd4。
README 同步本轮局部结果，前 70 节历史正文保持，本地链接/锚点
及四文件范围/diff 检查通过。

### 11.72 Core 运行转为 Product 边列表省去临时切片（2026-10-07）

基线为干净 `f7795b33b9e057ff8237886da348dc7d9b5cddcf`。
ProdAut_Run.prod_run_to_prod_edges 在 prefix 与 closed_suffix 的
相邻 zip 中使用 islice，省去原四个切片。仍保留输出 list、空
suffix 分支和原 `self.suffix + [self.suffix[0]]` 拼接：tuple
suffix 继续在 prefix 输出更新后抛原 TypeError，不引入新兼容层。
全部边顺序、重复项、自环和唯一按原规则拼接的闭合边保持；
每次生成新边列表，读当前 prefix/suffix。plan_output、TS 投影/
切片、动作与成本读取/日志/zip 消费未改，搜索、接受性、目标
函数、IRL、ROS 消息/快照/事务和历史重规划调用点不变。

测试复用现有 Product，新增 list/tuple 重复 prefix + 空 suffix
两项和 tuple suffix 的 TypeError/部分更新一项。完整顺序与
重复边、空输出、旧输出独立性、输入值和其它计划/成本字段均
检查。Product 与 discrete-plan 两现有文件一次 **57 passed**。
审阅补强新 prefix list 与旧输出的对象独立性，并 deepcopy 旧
字段值以免活引用掩盖原地修改；仅三新增用例子集重跑
**3 passed / 30 deselected**，未重跑最终整组，不累计为 60。
两次均保留两条既有 NetworkX/NumPy np.int 弃用警告。源码/测试
py_compile、ament_flake8 --linelength 99（初次两文件/补强后仅
测试）、测试 pep257 与 diff 检查通过。新用例属于语义保持检查，
没有前置 RED；没有更换依赖。

主代理独立加载逐字匹配 git show 的完整旧 Product 模块，以
三个原生 single/safe/KTH 小规划的同一 Product/输入运行重建
旧/新 ProdAut_Run。全部 prefix/suffix、边列表、TS line/loop、
动作序列与分项成本、总体成本、info 调用及已耗尽 TS zip 相同；
完整 ROS 快照/ID 映射和图/run 输入 pickle 字节保持。原生成本
分别为 3/1/13、3/2/23、20/20/220。支持序列上的实际切片观察
仅针对 Product 边生成阶段，每次 4 -> 0，被复制元素分别
6/8/8 -> 0；闭合 suffix 拼接仍各发生一次，TS 转换切片仍保留。
这不是总分配或耗时/整体加速测量。旧/新直接 helper 对照亦
保留 list/tuple prefix 与空 suffix 的新列表，以及 tuple suffix
精确 TypeError args 和 prefix 先更新/suffix 原输出不变。

旧源码保留于隔离目录 product_baseline_f7795b3.py；独立脚本为
Windows Temp/probe_core_run_edges_f7795b3.py，成功 stdout 保留
于工具记录。实际 Core source resolve 来自本 checkout；原生
translator 仍为 /home/yuhling/.local/bin/ltl2ba。环境为既有 WSL
Ubuntu-22.04-D / ROS 2 Humble 隔离 overlay。本轮没有七包、完整
演示、LLM、benchmark、物理仿真、实机/机器人示范或 Jazzy 验证；
11.69 的 620 项仍为 4817dd4 原资格，不代表本轮整包通过。
README 同步，前 71 节历史正文保持，13 个本地链接/锚点、四文件
范围及 diff 检查通过。

### 11.73 近期接口及运行转换改动后的七包组合资格（2026-10-07）

资格基线为干净 `be23c757388568d6ffeeb890c37be2f4d6b27aec`。
自 4817dd4 后又修改 KTH 只读启动参数、快照相邻校验和 Core
运行转边列表，本轮重新执行完整组合。colcon 发现的七包与
aggregate 的六个 exec_depend 一致。环境为既有 WSL Ubuntu-22.04-D /
ROS 2 Humble / Python 3.10.12 / NetworkX 2.4，原生 translator
仍为 /home/yuhling/.local/bin/ltl2ba，隔离 build/install 路径保持。
一次 build 使用 --executor sequential、--symlink-install、
--packages-up-to ltl_automaton_core 和 -DBUILD_TESTING=ON，实际
exec session 81261 返回 exit 0，耗时 37.695947396 秒。一次 test
选择全部七包、默认并行并启用 --return-code-on-test-failure，
实际 exec session 89485 返回 exit 0，耗时 62.274619121 秒。
主代理也实际观察到同一 test wrapper PID355 与 colcon PID376
存活；工具 yield 时只等待原句柄，没有重启命令。包级 domain
215/216/217/218 保持，没有 pytest 筛选、缩短条件或更换依赖。

独立核对测试开始后的六份 JUnit：

| package | tests | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 188 | 187 | 1 |
| ltl_automaton_planner | 156 | 155 | 1 |
| ltl_automaton_execution | 124 | 124 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 49 | 48 | 1 |

合计 **631 tests = 627 passed + 4 skipped，0 errors，0 failures**。
四项跳过仍为已有 copyright。当前接口 CTest wrapper 一项通过；
实际 colcon test-result --verbose 汇总为 **632 tests，0 errors，
0 failures，4 skipped**。九份历史 CTest XML 按时间排除，不与
本轮 JUnit 混用/重复计数；aggregate 没有独立 pytest case。
自 4817dd4 后新增 11 项核对执行且不跳过：KTH 启动覆盖/本地
原子拒绝/公开参数 RPC 三项，快照重复运行/单节点自环四项及
同时缺边诊断一项，Core 空 suffix/tuple suffix 三项。此前新增
23 项、四个真实 DDS 场景、Studio consumer、快照 fallback、IRL
commit/step reset、接受环/结果转换、native translator/POSIX、
HIL、monitor、launch 与 lint 亦核对。保留 NetworkX/NumPy np.int
及 SelectableGroups 弃用警告；五包有 stderr，不作为零警告结果。

构建/测试前后 HEAD 和清洁树均核对，常用 Core、ROS planner/
snapshot、execution 及 monitor 实际导入来自本 checkout，消息
来自隔离生成接口。主代理另核对 Product、snapshot、IRL、2D
generator、KTH driver 五模块 resolve 和完整 git 源字节，均绑定
资格提交。collector 只执行一次，verification_be23c75.json、
verified_summary_be23c75.json、verified_changed_imports_be23c75.json、
historical_hashes_before_be23c75.json 与新 JUnit/当前 CTest、完整
构建/测试实体日志冻结于 verified_results_be23c75，清单 83 文件
逐项 SHA256 通过。log_combo_be23c75 的便利 symlink 不复制，
实体日志保留；后续 test-result 查询使用独立 log_query_be23c75。
旧 4817dd4 的 83 文件清单在本轮前先校验，旧资格/失败/近期旧
模块重放等 119 份历史证据前后哈希保持。没有覆盖最初五项失败、
KTH 旧模块三项失败或原生对照源码/证据，也没有重跑旧执行脚本。

本轮没有 LLM、benchmark、物理仿真、实机/机器人示范或 Jazzy
验证；资格命令耗时不作为规划速度，组合通过不证明 IRL 收敛或
逆最优性。本次仓库只更新 README 与此记录，源码/测试保持
be23c75。前 72 节历史正文完整保留，13 个本地链接/锚点及
doc-only diff 检查通过。

### 11.74 Planner 初始状态等待配置的只读启动契约（2026-10-07）

基线为干净 `81cc78afde35f3e03bf930a04df40073aabdfdb0`。
源码审阅确认 initial_ts_state_from_agent 仅在构造时读取为内部
_waiting_for_initial_state；后者随后由生命周期更新，不是动态
参数的回调。更改前用真实 Node/Context、空 TS 路径和独立 domain
229 观察：默认参数/等待缓存均 False，运行时写入 True 返回成功，
参数变为 True 但缓存仍 False。启动 True override 能应用。两个
行为开关和 use_sim_time 的原子更新成功，确认它们仍应保持动态。

生产修改仅为该声明添加独立 ParameterDescriptor(read_only=True)
及既有 rcl_interfaces.msg 的 import。启动 override 保留；运行时
单项及含该项的原子更新由 ROS 参数 API 拒绝。replan_on_unplanned_move、
check_timestamp 的已有回调和 use_sim_time 保持；任务、权重、TS/
插件配置在后续初始化时读取的路径不变。没有修改生命周期、规划、
代价、接受性、IRL 学习范围/启用配置、接口定义、依赖或 launch。

复用现有 test_planner_node.py，只新增两个函数、三个 case：
False/True 启动覆盖分别检查参数/缓存一致，直接反向写入被拒绝；
将三个可变参数置前、只读参数置后的 mixed atomic batch 拒绝后，
参数与缓存保持，随后 mutable-only 更新成功。第三项通过真实
SetParametersAtomically RPC 检查同样的拒绝、完整性及可变更新；
沿用 2 秒 discovery / 3 秒 future 上限，finally 清理 client。
节点/Context/executor 清理保留。最终整文件 **30 passed，exit 0**，
两条既有 NetworkX/NumPy np.int 弃用警告。此前拆分为四新增 case
的草稿整文件为 31 passed，不与最终结果累计。最终两文件
py_compile、ament_flake8 --linelength 99、测试 pep257 和 diff 通过。

主代理在修改后加载 git show 81cc78a 的完整旧 planner_node.py，
核对完整字节、当前 checkout import resolve 和所收集测试绑定
旧 PlannerNode。第一次 helper 的 collection hook 早于 pytest
筛选，断言 3 项时收到 30 项，实际 INTERNAL_ERROR，未运行测试；
原日志保留，不作为回归失败证据。修正为筛选完成后核对，使用
新 run2 XML/log，旧源码不覆盖。实际 pytest **exit 1：3 failed /
27 deselected**，无 errors/skips；两项 direct API 与一项公开 RPC
均先执行写入，再因旧 successful=True 失败，早于 descriptor 检查。
helper 核对预期失败后自身 exit 0；这不是更改前的新用例 RED。

旧源码为隔离目录 planner_node_baseline_81cc78a.py；结果为
planner_initial_param_old_81cc78a_run2.xml/.log，对照脚本为 Windows
Temp/replay_planner_initial_param_81cc78a_run2.py；第一次 .log 与
脚本亦保留。环境仍为既有 WSL Ubuntu-22.04-D / ROS 2 Humble /
Python 3.10.12 隔离 overlay，新测试与旧重放使用包测试 domain 215。
新增 case 使用真实节点及其原生通信实体、公开参数 RPC，空 TS
路径不创建 planner；不构成有效规划、执行/时钟反馈闭环或 IRL
效果验证。没有七包、LLM、benchmark、仿真、实机/机器人示范或
Jazzy 验证；11.73 的 631 项只属于 be23c75 历史资格。
README/API 同步；前 73 节正文完整保留，本地链接/锚点和五文件
范围/diff 检查通过。

### 11.75 TS 动作转换的稳定节点快照与切片缩减（2026-10-07）

基线为干净 `c559fd60dc65f82c95e1290cd418634194a78b02`。
先对动态参数做只读审计：当前 Planner 只注册一个参数回调，先
校验两个行为参数再更新缓存。安装的 Humble rclpy 在用户回调前
执行 descriptor/type/read-only 校验。真实空 TS Node/Context、
domain 230 的三种 mixed atomic probe（合法 behavior=False 在前，
其它参数错误 string、只读初始参数或另一个 behavior 错误 int 在后）
均返回拒绝，四参数与两个行为/等待缓存保持原值；随后合法两行为
更新成功且参数/缓存同步，probe exit 0。没有发现不一致，没有为
该审计修改回调、注册新插件机制或扩大参数兼容范围。

本轮生产修改仅在 ProdAut_Run.plan_output：保留 line/loop 两个
输出 list 和 loop 追加首节点，将原四次相邻节点尾部 list 切片换为
每段一次稳定 tuple 与 zip/islice。空/单节点 prefix 使用空 tuple；
suffix 仍读取原追加闭合节点的 loop。全部次序、重复项、自环、
动作后取 weight、成本字段、错误/部分更新、日志及公开 zip 类型/
消费保持。发生转换错误后，剩余 zip 仍读取本次原节点快照，即使
line/loop 随后原地修改也不受影响；没有跨调用缓存。Product 边列表
转换、历史重规划调用点、搜索、接受性、目标函数和可选 IRL 不变。

仅补强现有缺失 action/weight 的两个 case，不新增测试函数：有效
prefix 改为 start/goal/goal，手算成本 3/1/13；失败后原精确 KeyError、
partial action/cost、suffix 原输出保持，再改 line/loop 为单节点列表，
剩余 prefix 和未消费 suffix zip 均仍返回原 s1->s1。Product 与
discrete-plan 两现有文件一次 **57 passed**，两条既有 NetworkX/
NumPy np.int 弃用警告。最终两文件 py_compile、ament_flake8
--linelength 99、测试 pep257 与 diff 通过，没有更换依赖。

主代理独立加载逐字匹配 git show c559fd6 的完整旧 Product 模块，
使用原生 single/safe/KTH 小规划的同一 Product 与运行输入构造旧/新
ProdAut_Run。完整字段、line/loop、动作及分项成本、已耗尽 TS zip、
info 调用、完整 ROS 快照与 Product ID 映射一致；旧/新转换的 graph/run 输入
pickle 字节保持。成本分别 3/1/13、3/2/23、20/20/220。观察真实
plan_output 传给 zip 的节点容器类型、身份与长度：原四个临时尾部
list 变成两个 tuple，复制节点引用分别 6/8/8 -> 5/6/6。重复 prefix
控制为 4 -> 2 容器、8 -> 6 引用；空/单节点 prefix 为 4 -> 1 容器、
2 -> 2 引用。两种缺字段的精确错误、部分输出及原地修改 line/loop
后剩余 zip 的隔离亦与完整旧模块一致。不是总分配或耗时/加速测量。
属于语义保持对照，没有前置新用例 RED，也没有重跑旧执行脚本。

旧源码保留在隔离目录 product_baseline_c559fd6.py；独立脚本为
Windows Temp/probe_ts_output_snapshots_c559fd6.py，成功 stdout
保留于工具记录。实际 Product import resolve 来自本 checkout，
原生 translator 仍为 /home/yuhling/.local/bin/ltl2ba；环境为既有 WSL
Ubuntu-22.04-D / ROS 2 Humble / Python 3.10.12 隔离 overlay。
本轮没有七包、完整演示、LLM、benchmark、仿真、实机/机器人示范或
Jazzy 验证。11.73 的 631 项仍属于 be23c75，11.74 的 Planner 30 项
仍属于 c559fd6 局部资格；不作当前整包通过或 IRL 效果声明。
README 同步；前 74 节正文完整保留，本地链接/锚点及四文件范围/
diff 检查通过。

### 11.76 Planner 参数与 TS 转换改动后的七包组合资格（2026-10-07）

资格基线为干净 `b555100743fb348f60554c084da1f372273ef81d`。
前两轮改动 Planner 只读启动参数及 TS 动作转换的稳定节点快照，
本轮重新执行完整组合。colcon 发现的七包与 aggregate 的六个
exec_depend 一致。环境为既有 WSL Ubuntu-22.04-D / ROS 2 Humble /
Python 3.10.12 / NetworkX 2.4，原生 translator 仍为
/home/yuhling/.local/bin/ltl2ba，隔离 build/install 保持。
一次 build 使用 --executor sequential、--symlink-install、
--packages-up-to ltl_automaton_core 和 -DBUILD_TESTING=ON，实际
exec session 14031 terminal exit 0，耗时 28.073706513 秒。一次
test 选择全部七包、默认并行与 --return-code-on-test-failure，实际
exec session 81802 terminal exit 0，耗时 54.444397821 秒。主代理
实际确认同一 test wrapper PID345/colcon PID366 存活；工具 yield
只等待原句柄，未重启。新 helper 另有 exclusive run marker，
包级 domain 215/216/217/218 保持，无 pytest 筛选、缩时或改条件。

独立核对测试开始后的六份新 JUnit：

| package | tests | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 188 | 187 | 1 |
| ltl_automaton_planner | 159 | 158 | 1 |
| ltl_automaton_execution | 124 | 124 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 49 | 48 | 1 |

合计 **634 tests = 630 passed + 4 skipped，0 errors，0 failures**。
四项跳过仍为已有 copyright。当前接口 CTest wrapper 一项通过；
实际 colcon test-result --verbose 为 **635 tests，0 errors，0 failures，
4 skipped**。十份历史 CTest XML 按时间排除，不与当前 JUnit 混用/
重复计数；aggregate 没有独立 pytest case。相对 be23c75 增加的
三项 Planner False/True 启动覆盖/运行时拒绝及公开参数 RPC 均执行，
两个补强的 TS 缺 action/weight 与剩余 zip 隔离 case 亦执行、不新增
计数。此前 23+11 项新增回归、四个真实 DDS 场景、Studio consumer、
快照 fallback、IRL commit/step reset、native translator/POSIX、
HIL、monitor、launch 与 lint 亦核对。保留 NetworkX/NumPy np.int
与 SelectableGroups 弃用警告，五包有 stderr，不作为零警告结果。

构建/测试前后 HEAD 与清洁树核对，start gate 的常用 Core、ROS
planner/snapshot、execution、monitor 来自本 checkout，消息来自
隔离生成接口。主代理另核对 Planner、Product、snapshot、IRL、2D
generator、KTH driver 六模块 resolve 和完整 git 源字节，均绑定
资格提交。collector 只执行一次，verification_b555100.json、
verified_summary_b555100.json、verified_changed_imports_b555100.json、
historical_hashes_before_b555100.json 与新 JUnit/当前 CTest、完整
构建/测试实体日志冻结于 verified_results_b555100，清单 83 文件
逐项 SHA256 通过。log_combo_b555100 便利 symlink 排除，实体日志
保留；后续查询使用独立 log_query_b555100，不改冻结闭包。
旧 be23c75 的 83 文件清单在执行前先校验；五个旧资格/失败目录
与选定 standalone receipt、旧模块/失败日志等 213 份历史证据前后
哈希保持。原 be23c75/4817dd4/6cbfd39 统计、最初五项失败、KTH
与 Planner 旧模块失败、Planner 首次 helper INTERNAL_ERROR 以及
原生旧/新对照源码均保留，没有重跑原 helper 或覆盖原证据。

本轮没有 LLM、benchmark、物理仿真、实机/机器人示范或 Jazzy
验证；执行场景仍为符号级 FakeBackend。命令耗时不是规划性能，
组合通过不证明 IRL 收敛、逆最优性或机器人示范效果。本次仓库
只更新 README 与本记录，源码/测试保持 b555100。前 75 节历史
正文完整保留，13 个本地链接/锚点及 doc-only diff 检查通过。

### 11.77 执行快照中不可变符号状态的单次转换复用（2026-10-07）

基线为干净 `3484d801d0874c1c00be52d4a8a2bfa52ee5e3c8`。
先只读检查默认 FakeBackend 的延迟、异步失败及 busy 释放，并以
既有 Humble 空 Node、domain 231 验证非有限参数与 ROS timer 范围；
未发现新缺陷，没有为该审计改动后端或参数行为。随后三个原生
single/safe/KTH public snapshot 的投影分别有 4/8/24 个 Product 节点，
却只有 2/2/6 种不可变符号状态，为本轮局部复用提供输入证据。

生产修改仅在 ExecutionManagerNode._snapshot_from_message：嵌套
generator 的本地字典按 dimension/value tuple 复用已校验的普通
str SymbolicState。仍先 int(node.id)，再取两 tuple；子类/非字符串
继续执行原构造校验。缓存只存在于本次转换，全部节点 ID/顺序、
边、accepted-run、实例/代际和下游执行策略保持；未修改消息接口、
搜索、接受性、代价、后端完成/TS 观测权威或默认关闭的可选 IRL。

新增四个定向测试函数、六个 case：重复状态与节点顺序、原消息
保持、后续修改与先前投影隔离、有效不可哈希 str 子类类型/值保持，
以及三种 malformed 字段的原 ValueError/ID 转换优先次序。后两类
使用 SimpleNamespace 检查直接转换路径，不宣称畸形字段可通过 DDS。
三个文件 test_execution_node.py、test_accepted_run_resolver.py、
test_snapshot_timeout.py 一次 **76 passed in 2.84s**，实际 exit 0，
无 skips/warnings；新增六项全部执行。命令未使用 --junitxml，未生成
本轮 JUnit，stdout 保留在执行代理工具记录。两个修改 Python 文件
py_compile、ament_flake8 --linelength 99、测试文件 ament_pep257 与
diff 检查均 exit 0，保留既有依赖。属于实现后的语义保持验证，无前置 RED。

主代理另加载逐字匹配 git show 3484d80 的完整旧 execution_node.py，
核对当前 checkout import resolve 及 models/resolver/manager/snapshot/
Product 五个依赖模块完整基线字节。三个原生规划的完整新旧投影与
实际 AcceptedRunResolver/ExecutionManager 符号派发一致，立即完成的
recording backend 分别记录 3/4/4 条命令，重复序号仍拒绝；成本分别
3/1/13、3/2/23、20/20/220。每份投影保留的 SymbolicState 对象实测
4/8/24 -> 2/2/6；相同消息再次转换的状态对象集合互不相交。
完整 ROS 输入字段、pickle 字节保持，五次 CDR roundtrip 均还原原
消息；六种错误的精确 type/args 及有效不可哈希值子类亦与旧模块一致。
只统计投影持有对象，不是总分配、总内存或时间/加速测量。

原生对照辅助脚本有两次实际失败，均保留：首次 exit 1 因 tiny
planning fixture 没有 PlannerNode lifetime 身份，执行仲裁拒绝空身份；
run2 先通过 single，随后 safe 的 CDR 原始字节比较失败。只读诊断
exit 0 证明，未调用转换时同一消息五次连续 CDR 序列化已出现不同
字节，而完整旧/新投影、输入对象/pickle 相同。run3 对输入补有效
fixture 身份，旧/新空身份拒绝仍单独核对，并以完整消息、pickle 和
CDR 反序列化字段验证语义，实际 exit 0。原辅助检查不适合用非规范
CDR 字节判定输入变化；不是产品缺陷或 pytest 失败，没有更改生产
代码、规划条件或用户验收标准以通过这些检查。

Windows Temp/probe_exec_state_reuse_3484d80.py、_run2.py、_run3.py 和
diagnose_exec_snapshot_bytes_3484d80.py 保留，旧源码分别留在隔离目录
execution_node_baseline_3484d80.py 及 _run2/_run3 版本；
成功 receipt 为 execution_state_reuse_3484d80_run3.json，工具输出另
保留为 execution_state_reuse_3484d80_tool_results.json。首次统计脚本
inspect_exec_state_counts_3484d80.py 未重跑；旧七包冻结闭包不改写。
环境仍为既有 WSL Ubuntu-22.04-D / ROS 2 Humble / Python 3.10.12
隔离 overlay，原生 translator 为 /home/yuhling/.local/bin/ltl2ba。
没有七包、LLM、benchmark、完整演示、物理仿真、实机/机器人示范或
Jazzy 验证；上述派发仅为 ROS-independent 符号 recording backend。
11.76 的 634 项只属于 b555100 历史源码资格，不作当前整包声明。
README 同步；前 76 节正文完整保留，五文件范围与本地链接检查通过。

### 11.78 接受运行状态分组的合法值契约与无哈希比较（2026-10-07）

基线为干净 `87ac8d578d595209173f85bf2b35aa048b9e9aa1`，本地
upstream 与 GitHub PR#10 head 相同。只读审计发现，SymbolicState
允许非空 str 子类值，快照转换也保留其类型，但 resolver 将状态
加入 source/target set；有效子类若定义 __hash__=None，会抛 TypeError，
不能解析合法命令。该缺口涉及直接 Python 模型/字符串子类；普通
ROS DDS 字符串没有该失败，不扩大到新的接口或兼容框架。

生产修改仅在 AcceptedRunResolver.resolve：source 以首个有序 ID
的状态和其它候选按 dataclass 值比较；target 保留首个匹配值及
ambiguity flag，仍遍历所有匹配并收集完整 ID 集合。首次 target
以目标 ID 集合尚空判定，避免用 None 值充当首个状态标记而改变
已有直接输入的歧义行为。状态值/类型不转换，不调用状态 hash；
原 no-target、distinct-source、ambiguous-target 消息保持。
快照索引、retained-pair 转换、结构/漏边/漏节点/重复 ID 错误与
索引提交点不变；有效图索引安装后的命令拒绝仍保留该有效索引，
只有索引重建失败才保留前一有效索引。未改规划、代价、接受性、
执行身份/TS 观测权威、消息定义或默认关闭的可选 IRL。

补强现有多候选测试，不新增测试函数：已有两种 node_ids 顺序
加 None/1/3 的不可哈希状态位置参数，原两项扩为六项、净增四项。
断言完整 ExecutionStep、全部排序后的匹配 ID、reversed 输入及
合法子类输入类型保持。生产改动前 RED 实际 exit 1：**2 passed /
4 failed / 25 deselected**；四项分别在 source/target hash set 触发
精确 TypeError。首版两文件 GREEN 为 63 passed；按审查修正首个
target 判定后，resolver 与 execution-node 两文件最终一次
**63 passed in 2.77s**、exit 0，0 errors/failures/skips，无 warnings。
两次 GREEN 为同一测试人口，不能相加；六项 targeted case 都执行。
最终源码/测试 py_compile、ament_flake8 --linelength 99、测试
pep257 与 diff 检查通过。根代理静态工具 yield 后继续原 session
56139，最终 terminal exit 0，没有重新启动该检查。

原 RED XML 为 /tmp/accepted_run_unhashable_red_3484d801.xml，
首版 GREEN 为 /tmp/accepted_run_unhashable_green_3484d801.xml；
3484d801 只是这两个文件的标签，本轮权威基线为 87ac8d5。最终 XML 为
/tmp/accepted_run_unhashable_green_run2_87ac8d5.xml。主代理只读核对
三份 XML 的精确计数、时间顺序、六项 targeted case、旧 source/
target traceback，并保存 SHA256 于隔离目录
resolver_state_equality_87ac8d5_pytest_receipts.json；原 stdout 保留
在执行代理工具记录，没有重跑 RED 或覆盖任一 XML。

主代理加载逐字匹配 git show 87ac8d5 的完整旧 resolver，并核对
当前 resolver import resolve 与 models/manager/execution-node/snapshot/
Product 五个未修改模块的完整基线源字节。三个原生 single/safe/KTH
快照经实际 manager/resolver 与立即完成的 symbolic recording backend
分别派发 3/4/4 条命令，完整旧/新步骤、诊断、重复序号拒绝相同；
成本保持 3/1/13、3/2/23、20/20/220。仅在解析调用内观察实际
SymbolicState.__hash__，调用数 6/8/8 -> 0/0/0；输入快照 deepcopy/
pickle 保持。九种原错误的 type/args、正确阶段的缓存提交/保留与
后续代际恢复保持，包括漏闭合边先于漏节点、重复缺边顺序/重复项、
重复 ID、不同来源、结构错误、目标歧义及直接 None target 控制。
最后一项不是合法 SymbolicState 或 DDS 输入，只检查旧直接调用行为。

首次独立 helper 在三个原生场景通过后实际 exit 1：缓存断言把
“有效图建立索引后，命令歧义拒绝”也误算为重建失败，要求回到旧
索引；该断言过宽。run2 区分这两个阶段，实际 exit 0，生产源码不变。
Windows Temp/probe_resolver_state_equality_87ac8d5.py 与 _run2.py、
两个逐字校验的完整旧模块 accepted_run_resolver_baseline_87ac8d5.py
及 _run2.py 均保留。成功 receipt 为
resolver_state_equality_87ac8d5_run2.json，失败/成功工具输出为
resolver_state_equality_87ac8d5_tool_results.json；旧七包冻结证据不改写。

环境仍为既有 WSL Ubuntu-22.04-D / ROS 2 Humble / Python 3.10.12
隔离 overlay，原 translator 为 /home/yuhling/.local/bin/ltl2ba。
状态 hash 调用减少不是总分配、总内存、规划耗时或整体加速证据。
本轮没有七包、LLM、benchmark、完整演示、物理仿真、实机/机器人
示范或 Jazzy 验证；原生对照仅为 ROS-independent symbolic 派发。
11.76 的 634 项仍只属于 b555100 历史源码；11.77 的 76 项属于
87ac8d5 局部资格，不作本轮整包通过声明。README 同步，前 77 节
正文完整保留，五文件范围、本地链接/锚点与 diff 检查通过。

### 11.79 执行快照与状态解析改动后的七包组合资格（2026-10-07）

资格源码为干净 `d6f49838c2fba0f7e96bd7faf03fbd53f187b9be`。
11.77 的单次状态转换复用与 11.78 的不可哈希合法字符串值解析
本轮纳入整包组合。七包 inventory 与 aggregate 的六个 exec_depend
一致，使用既有 WSL Ubuntu-22.04-D / ROS 2 Humble / Python 3.10.12 /
NetworkX 2.4 隔离 build/install，原 translator 保持
/home/yuhling/.local/bin/ltl2ba。

build 使用 --executor sequential、--symlink-install、
--packages-up-to ltl_automaton_core、-DBUILD_TESTING=ON；执行代理
实际 session 34300 terminal exit 0，耗时 28.852778987 秒。
test 选择全部七包、默认并行、--return-code-on-test-failure；实际
session 19272 terminal exit 0，耗时 51.195945840 秒。各执行一次，
没有重启或重跑；新 helper 使用 exclusive run marker，工具 yield
仅等待原句柄。主代理本轮没有独立观察运行中的 PID，不把旧轮 PID
或完成 marker 作为该项证据。测试 domain 215/216/217/218 保持，
无 pytest 筛选、缩时或修改条件。

主代理独立解析实际 test_start_ns 之后的六份新 JUnit，核对 testcase
数量、错误/失败/跳过及冻结副本与当前 XML 的完整字节：

| package | tests | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 188 | 187 | 1 |
| ltl_automaton_planner | 159 | 158 | 1 |
| ltl_automaton_execution | 134 | 134 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 49 | 48 | 1 |

合计 **644 tests = 640 passed + 4 skipped，0 errors，0 failures**。
四项跳过均为已有 copyright；接口 CTest wrapper 一项通过，实际
colcon test-result --verbose 汇总 **645 tests，0 errors，0 failures，
4 skipped**。11 份历史 CTest XML 按时间排除，不混入本轮
JUnit 或重复计数，aggregate 没有独立 pytest case。
新增六项快照转换 case 均执行：重复状态与输入次序、跨消息不复用、
合法不可哈希 str 子类、三个畸形输入的原校验顺序。解析器完整六项
多候选参数 case（两种次序 × 普通/source/target 不可哈希位置）均
执行，其中四项为 11.78 净新增；相对 b555100 总数净增十项。
近期 Planner 参数、TS 缺 action/weight 与剩余 zip 隔离、其它已列
回归、四个真实 DDS 场景、Studio consumer、快照 fallback、IRL
commit/step reset、native translator/POSIX、HIL、monitor、launch
与 lint 亦核对。保留 np.int 和 SelectableGroups 弃用警告，五包
有 stderr，不作为零警告结果。

构建/测试前后 HEAD 与清洁树核对。start gate 实际核对十个源码
模块 resolve 与隔离生成接口；主代理另核对执行节点、解析器、
Planner、Product、snapshot、IRL、2D generator、KTH driver 八模块
resolve、SHA256 及完整 git 源字节，均绑定资格源码。
collector 只执行一次，verification_d6f4983.json、
verified_summary_d6f4983.json、verified_changed_imports_d6f4983.json、
historical_hashes_before_d6f4983.json 与新 JUnit/当前 CTest、完整
构建/测试实体日志冻结于 verified_results_d6f4983；清单 83 文件
逐项 SHA256 通过，无便利 symlink。正确查询使用独立 log_query_d6f4983_correct，
不改冻结闭包。执行代理首次查询遗漏隔离 test-result-base，读到工作
目录旧 build 的 86 项；原 log_query_d6f4983.txt 保留且不参与资格。
主代理显式指定 /tmp/ltl_ros2_completion_20261006/build 只读查询，
实际 exit 0、645 项；没有重跑构建/测试或改写新 XML。

执行前先校验 b555100 的 83 文件闭包与此前 213 份选择清单，再将
该闭包及近期独立 receipts、旧模块、三份 RED/首版/最终 XML 等
共 314 份历史证据固定哈希；本轮前后完整保持。b555100 等旧资格、
最初五项失败、11.77/11.78 的 helper 失败与最终成功分别保留，
没有重跑旧 helper 或覆盖旧证据，局部测试人口不累加到本轮。

仓库本次只更新 README 与本记录，源码/测试保持 d6f4983，前 78 节
历史正文完整保留。未运行 LLM、benchmark、完整演示、物理仿真、
实机/机器人示范或 Jazzy；执行仍为符号级 FakeBackend。IRL 按用户
选择保留原示范学习 β 范围，默认关闭。命令耗时不是规划性能，
组合通过不证明 IRL 收敛、逆最优性、示范效果或整体加速。

### 11.80 执行接受运行相邻边的尾部切片消除（2026-10-07）

基线为干净 `d4d8c05a1f1f570d31cd4f56a14e714bae6a0b78`。
AcceptedRunResolver._retained_pairs 的 prefix[1:]/suffix[1:]
改用 islice，省去两次尾部切片；输出仍为完整 tuple，prefix/suffix
次序、重复边、单节点自环及唯一隐式闭合边保持。原 prefix/suffix
非空、共享边界与重复 suffix 起点校验位置和诊断保持，索引构造、
提交/失败保留及下一代恢复规则不变。不改消息、身份、状态分组、
搜索、接受性、代价或可选 IRL，不扩大为单次 generator 输入。

执行代理一次运行现有 test_accepted_run_resolver.py 与
test_execution_node.py，**63 passed in 1.47s**，实际 exit 0，
0 errors/failures/skips、无 warnings。未新增测试；主代理独立解析
/tmp/accepted_run_pairs_islice_d4d8c05.xml，确认全部 63 项及既有三项
有序边对、三项结构拒绝/恢复、一项重复缺边诊断和六项多候选 case
实际执行，XML SHA256 为
79f0aa95b8628623767d49f993be2c91fe861a692c5e922741ba68bd41e8283d。
py_compile、ament_flake8 --linelength 99 与 git diff --check 通过。

主代理完整旧 resolver 逐字匹配 git show d4d8c05，当前 import resolve
绑定 checkout；models、manager、execution-node、snapshot、Product
五模块完整未修改字节匹配基线，原 translator 保持。旧/新三个原生
single/safe/KTH 经实际 manager/resolver 与立即完成的 symbolic
recording backend 派发 3/4/4 条命令，完整步骤、诊断与重复序号拒绝
一致，成本保持 3/1/13、3/2/23、20/20/220。调用生产边对转换的
tuple 子类记录器测得每例尾部切片 **2 -> 0**，复制尾部引用
**2/3/3 -> 0**；不声称总分配、总内存或整体加速。

单节点、普通与重复路径的 tuple/list 六种直接输入保留全部 pairs、
输出类型及原输入 pickle 字节。九种错误的 type/args、正确阶段的
缓存安装/保留与后续恢复一致，包含漏边先于漏节点、重复缺边次序、
重复 ID、不同来源、空 prefix、显式闭合 suffix 和目标歧义；None
target 仅为历史直接调用控制，不是合法模型或 DDS 输入。原生普通
快照 deepcopy/pickle 不变。独立 helper 一次实际 exit 0，完整旧模块、
helper 与 resolver_state_equality_d4d8c05.json 独立保留；主代理工具
输出和明确标记的执行代理报告保存于
resolver_pairs_d4d8c05_tool_results.json，没有重跑验证。

此前 d6f4983 的 83 文件冻结闭包与 314 份选定历史证据 SHA256
重新核对保持，未覆盖旧 XML 或重跑旧 helper。11.79 的 644 项仅
属于 d6f4983 历史整包资格，不作当前修改后的整包声明；本轮 63 项
独立计数。README 与执行包说明同步，前 79 节历史正文完整保留。
本轮未运行七包、LLM、benchmark、完整演示、物理仿真、实机示范
或 Jazzy；原生派发仍是符号级记录后端，IRL 范围与默认关闭保持。

### 11.81 合法不可哈希维度的状态与观察契约修复（2026-10-07）

基线为干净 `8548a3bd8ffe142125dcffe21c641868b4bed317`。
SymbolicState 原已允许非空 str 子类且保持原字段对象，但 dimension
去重的 set 对 __hash__=None 的合法名字泄漏 TypeError；执行观察的
set 匹配、dict 构造及按 expected 名字查询也有相同缺口。仅修模型
会使合法新状态随后在观察管线失败，本轮同时覆盖两处源码。
普通/hashable 字符串保留原 set/dict 路径；仅这些 hash 操作出现
TypeError 时用本次调用的值比较及序列索引。名称非空仍先于唯一性，
唯一性仍先于 values 校验，重复维度保留精确原 ValueError；观察不
匹配先按原 warning 拒绝，匹配后按活动快照的维度顺序发布。
不转换名字/值或改变模型 hash、消息、身份、调度、规划/接受性、
代价或可选 IRL。异常分支按值比较，维度数较大时可为平方复杂度，
常用可哈希路径保持；不声称整体加速。

净新增八项定向 case：既有字符串子类保留测试新增不可哈希参数，
三种混合/双侧重复名字保持 duplicate 诊断先于非法 value，既有
快照转换测试新增维度参数，三个 observer 参数覆盖 observed-only、
expected-only、both。最终 observer 使用实际 ExecutionManagerNode、
RecordingObserver 与生成消息的 spy publisher，反序维度有效→未知
→有效反馈发布数 1→1→2，值按计划重排，backend.calls 保持空。

原始阶段 XML 分别保留，主代理独立核对完整计数、失败、mtime
先后、所有新/既有关键 case 与 SHA256：

| phase | passed | failed | child tool exit |
|---|---:|---:|---:|
| 原模型/快照 targeted RED | 2 | 5 | 1 |
| 修模型后的初始 GREEN | 105 | 0 | 0 |
| 原观察节点 targeted RED | 0 | 3 | 1 |
| GREEN run2 | 107 | 1 | 1 |
| GREEN run3 | 108 | 0 | 0 |
| 最终 GREEN run4 | 108 | 0 | 0 |

首 RED 另有 67 deselected，observer RED 33 deselected；失败均为
TypeError。run2 漏将 expected-only 的 dict 查询放入 try，同一缺口
导致一项失败；随后修正，不改变输入或验收。run3→run4 仅增强
valid→unknown→valid 与无派发断言，生产源码未再改动。初始 105
项 stdout 另含 “The following exception was never retrieved: late
exception”，原诊断保留，不记为零诊断结果。最终三个现有文件
test_backend.py、test_accepted_run_resolver.py、test_execution_node.py
一次 **108 passed in 1.77s**、实际 exit 0，0 errors/failures/skips，
无 warnings，XML 为 /tmp/symbolic_dimensions_green_run4_8548a3b.xml。
各版属于不同阶段/重叠人口，不相加；未重跑原 RED 或覆盖 XML。
静态首次误写不存在的 ltl_automaton_core/.../execution_node.py 路径
而 exit 1，原错误保留；改为正确四文件后 py_compile、
ament_flake8 --linelength 99、测试 pep257 与 diff 检查实际 exit 0。

主代理独立 helper 一次实际 exit 0。完整旧 models/node 逐字匹配
git show 8548a3b，当前 import resolve 与源 SHA256 核对；resolver、
manager、snapshot、Product、IRL 五模块完整未修改字节匹配基线。
十种普通构造/精确错误保持，字段与 frozen 契约保持，hashable
名字构造的 hash 调用 2/2 保持；五种不可哈希名字按既有契约修正。
未绑定/绑定活动维度的普通 observer 控制一致，三个不可哈希位置
完成重排、未知维度拒绝与恢复。三个原生 single/safe/KTH 快照的
完整字段投影、实际 manager/resolver 派发步骤、诊断与重复序号
拒绝一致，派发 3/4/4，成本 3/1/13、3/2/23、20/20/220；原消息
deepcopy 相等。该对照按字段比较两个模型类，不把不同类身份当作
公开字段差异；记录后端仍为立即完成的符号后端，不是物理验证。

完整旧模块、helper、symbolic_dimensions_8548a3b.json、
symbolic_dimensions_8548a3b_xml_receipts.json 与明确标记代理报告的
symbolic_dimensions_8548a3b_tool_results.json 独立保留。此前 83
文件冻结闭包、314 份选定历史哈希及上一轮 63 项 XML SHA256 保持。
README 与执行包说明同步，前 80 节历史正文完整保留。本轮未执行
七包、LLM、benchmark、完整演示、物理仿真、实机示范或 Jazzy；
11.79 的 644 项仍只属于 d6f4983 历史整包资格，IRL 原范围/默认
关闭保持。108 项局部通过不证明完整系统或 IRL 科学效果。

### 11.82 丢弃快照回调时读取 Future 异常（2026-10-07）

基线为干净 `6d8466a7360790a56a1ec704674effa3d95e57a0`。
11.81 初始 105 项 stdout 中的未读取异常诊断原样保留。核对实际
Humble rclpy/task.py：exception() 非阻塞地返回错误并标记已读取，
Future 析构时报告未读取的错误；取消/完成会调度并清空 callbacks。
原测试在销毁并取消之后再注入异常，回调未必会执行，不能仅凭
那条诊断认定真实晚到回调已经执行。本轮改用真实 executor 排队：
完成 Future 后销毁节点，再 spin 执行已经排队的回调，明确复现
节点销毁后未读取错误的缺口。

生产修改仅在 _on_snapshot 的三个丢弃返回点调用 future.exception()：
节点已销毁、deadline 已过、请求已被替换。保留原 guard 与 detach/
latest-observation 恢复顺序，不提前调用 result()，不访问已销毁
logger。当前请求的异常/None/unsuccessful 仍按原 warning 与重试
处理，成功响应仍按身份、schema、快照转换及最新观测派发。消息、
身份、调度、planner/接受性、代价、可选 β 学习与默认关闭均保持。

既有销毁测试的 success/failure/exception 三参数使用真实 Humble
Future + SingleThreadedExecutor，检查无 Destroyable warning、无
pending/request/派发；weakref 与 gc 确认 Future 已实际回收，再检查
捕获的 stderr 没有未读取异常。既有 timeout late-error 测试检查
exception 被读取，既有 callback-deadline 测试新增异常参数（净增
一项 case），仍断言旧请求零派发及替换请求成功恢复。受控 Future
只补齐真实 exception() 的读取语义；没有过滤生产 stderr 或放宽
错误/恢复条件。

执行代理原始 targeted RED 一次实际 exit 1：**3 failed / 4 passed /
47 deselected**，XML 为 /tmp/snapshot_discard_red_6d8466a.xml；
失败为真实销毁异常、timeout 晚到异常与 callback 过期异常。修复后
test_backend.py、test_accepted_run_resolver.py、test_execution_node.py、
test_snapshot_timeout.py 四个完整既有文件一次 **126 passed in 3.11s**，
实际 exit 0，0 errors/failures/skips，无 warnings；XML 为
/tmp/snapshot_discard_green_6d8466a.xml。真实排队三参数、timeout
两参数、deadline 两参数与此前维度/解析回归均执行。RED 与 GREEN
计数、失败、时间顺序、关键 case 与 SHA256 核对后分别保留，不
重跑或覆盖原 XML，不相加测试人口。三份修改文件 py_compile、
ament_flake8 --linelength 99、两测试文件 pep257 与 diff 检查实际
exit 0；静态 session 9353 在原 handle 上等待至完成。

主代理独立 helper 一次实际 exit 0。完整旧 execution_node.py 与
git show 6d8466a 逐字匹配，当前 runtime import/源字节核对；models、
manager、resolver、snapshot、Product、IRL 六模块完整未修改字节
绑定基线，原生 translator 路径保持。真实 Humble Future 的 shutdown/
expired/superseded 三种丢弃边界中，请求/替换请求、pending、timer、
warning、缓存与维度状态一致，Future 实际回收，baseline 原始 stderr
有未读取诊断而 current 无。当前请求的 exception/None/unsuccessful
三个控制保留原 warning/最新重试及请求释放，且没有未读取诊断。
三个原生 single/safe/KTH 通过实际成功快照回调、manager/resolver
和符号 recording backend，对照完整快照、派发步骤、诊断与重复
序号拒绝一致；派发 3/4/4，成本 3/1/13、3/2/23、20/20/220。

完整旧模块、probe_snapshot_discard_6d8466a.py、
snapshot_discard_6d8466a.json、snapshot_discard_6d8466a_xml_receipts.json
与明确区分主代理实际结果/执行代理报告的工具记录独立保留。
此前 83 文件冻结闭包、314 份选定历史哈希、11.81 六阶段 XML 与
上一轮 63 项 XML SHA256 保持。README 与执行包说明同步，前 81
节历史正文完整保留。本轮未执行七包、LLM、benchmark、完整演示、
物理仿真、实机示范或 Jazzy；11.79 的 644 项仍只属于 d6f4983
历史整包资格。本轮为局部行为验证，不证明整体加速、完整系统
或 IRL 科学效果。

### 11.83 近三轮执行改动后的七包组合资格（2026-10-07）

源码资格为干净 `ef300b4eb2a6f3c709e402679c8e7d8ba48fc9d2`。
11.80 的相邻边 islice、11.81 的维度值契约及 11.82 的丢弃回调
异常读取此前只有局部验证，本轮将它们一起纳入完整七包组合。
测试前固定源树/七包清单、预期执行包 143 项与总 JUnit 653 项，
保全此前 83 文件闭包、314 份旧哈希及近三轮产物共 424 文件。
不改源码、测试、pytest domain、超时、过滤或验收条件。

环境沿用 WSL Ubuntu-22.04-D / ROS 2 Humble / Python 3.10.12 /
NetworkX 2.4，translator 为 /home/yuhling/.local/bin/ltl2ba。
aggregate 六项 exec_depend 完整对应六功能包，测试 domains
215/216/217/218 保持。build 使用 --executor sequential、
--symlink-install、--packages-up-to ltl_automaton_core 和
-DBUILD_TESTING=ON；test 选择全部七包及 --return-code-on-test-failure，
保持默认并行。执行代理 build session 44331 与 test session 33138
各启动一次，均在原 handle 等待至实际 exit 0；receipt 命令耗时
分别为 35.918813251 与 60.804561879 秒，不作为规划加速比。
主代理未采到运行中 PID，不将代理报告或状态文件当成活进程观测。

六份 test_start_ns 之后的新鲜 JUnit 独立核对如下：

| package | tests | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 188 | 187 | 1 |
| ltl_automaton_planner | 159 | 158 | 1 |
| ltl_automaton_execution | 143 | 143 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 49 | 48 | 1 |

合计 **653 tests = 649 passed + 4 skipped，0 errors、0 failures**。
跳过均为既有 copyright，接口 CTest wrapper 另有一项通过。主代理
仅查询一次，显式 --test-result-base /tmp/ltl_ros2_completion_20261006/build，
实际 exit 0，Summary: 654 tests, 0 errors, 0 failures, 4 skipped。
12 份历史 CTest XML 按 test_start_ns 排除，没有重跑构建或测试。

相对 d6f4983 净增九项执行包参数 case，完整覆盖合法维度子类、
重复维度诊断、快照转换、observed-only/expected-only/both 重排及
callback-deadline 异常。真实 executor 排队销毁回调三参数、timeout
两参数、deadline 两参数均执行；既有接受路径/解析缓存、Planner
参数、TS 错误/剩余迭代器、四个真实 DDS 场景、Studio consumer、
快照 fallback、IRL commit/step reset、native ltl2ba/POSIX、HIL、
monitor、launch 与 lint 也执行。保留 np.int/SelectableGroups 依赖
弃用警告，五包 stderr 非空；完整 stderr 未见未读取 Future 诊断。

start gate 核对十个源码 import resolve 与隔离生成消息路径。主代理
另外核对 models、执行节点/解析器、Planner、Product、snapshot、
IRL、2D generator、KTH driver 九模块完整 git 源字节。collector
仅执行一次，新 XML、命令 receipt、导入记录、历史哈希及完整实体
构建/测试/查询日志冻结为 85 文件 SHA256 闭包；独立 audit 对比
fresh/live/frozen 字节、全计数、关键 case、wrapper、命令次序和
完整源码，实际 exit 0，424 份历史哈希保持。记录位于隔离目录的
verification_ef300b4.json、verified_changed_imports_ef300b4.json、
verified_summary_ef300b4.json、colcon_query_ef300b4.json、
verified_results_ef300b4/sha256_manifest.json 与独立工具记录。

本轮仅刷新 README 与验证记录，源码与测试仍为 ef300b4，前 82 节
正文完整保留。此前 d6f4983 的 644 项、其他整包历史、局部 63/108/
126 项及原始失败分别保留，不与本轮重复累加。本轮没有 LLM、
benchmark、完整演示、物理仿真、实机示范或 Jazzy 验证；符号级
FakeBackend 的组合通过不证明整体加速、IRL 收敛、逆最优性或
机器人示范效果。IRL 保持原示范学习 β 范围，默认关闭。

### 11.84 IRL 示范选择中复用本次软距离评分（2026-10-07）

基线为干净 b3097ffc4ee32cdfaca7583f62197ea34dea80f8，其源码/测试
沿用 11.83 的 ef300b4 资格。learn_beta 原先在 min 的 key 中评分
全部示范，再对选中的路径重新评分。ROS worker 已隔离候选
Product，学习过程本身不改调用者输入；本轮将 (path, score) 流式
交给带显式 score key 的 min，直接复用选中分数。同分保留输入
迭代顺序中的首条，不按 path tuple 排序，不合并重复路径，也不
跨调用缓存。全部路径仍先验证，私有 deepcopy、margin 算术、
gradient、step、20 次上限、<=0.3 停止与结果字段均保持。

原 test_irl.py 新增三项 case：同分 bad-first/good-first 两参数，
固定规划 suffix 隔离选择手算，beta_sequence=(0.0,) 且匹配分数
分别为 2/3；下一次调用改 hub→good 软距离为 2，选中示范从
good 变为 bad，gradient=-1，前十步 beta=1..10，第十一步
10+1/11 满足停止规则，匹配分数为 (2,)*11。各次私有 margin
按选择路径手算，输入 edge/weight/initial/possible/beta 保持。
既有真实 planner 与全部二十步大梯度检查未删减。

执行代理初轮 73 passed / 1 failed 的 XML 原样保留：fixture 将
good 两条边都改为 2，软距离为 4，实际 gradient=-3，手算不符。
改为只修改 hub→good 后，完整 test_irl.py 与 test_plan_ltl_action.py
一次最终 **74 passed**，session 36936 实际 exit 0，0 errors/
failures/skips，保留两项既有 NetworkX/NumPy 弃用 warnings。
两 XML 分别为 /tmp/irl_demonstration_score_b3097ff.xml 和
/tmp/irl_demonstration_score_b3097ff_run2.xml，不将初轮称为原算法
RED 或累加人口。静态 session 30763 实际 exit 0，两文件
py_compile、ament_flake8 --linelength 99、测试 pep257、diff 检查通过。

主代理完整旧 learner 与 fixture 逐字取自 git show b3097ff，当前
import/source SHA256 核对，Product、discrete_plan、ltl_planner、
TS、planner_node、snapshot 六模块完整字节绑定基线。独立 helper
一次实际 exit 0，七种实际 Product/Dijkstra 小图（其中一项两次
调用）全部结果字段相同、调用者完整公开图及 possible_states
保持；输入评分调用 R+1→R，每次少读选中示范的 L-1 条软距离。
普通两路径为 3→2 次、6→4 次读取；重复长路径为 4→3 次、
12→8 次读取。计数在输入 edge 字典读取处记录，私有副本用普通
属性字典；没有测量速度或内存。六种错误类型/精确消息保持，
前五种在评分前拒绝；无接受环控制的原始两条诊断也保留。

主代理独立核对两 XML 的计数/失败/mtime/SHA 和三项新增、
二十步、权重 overflow 与全部 IRL 提交/失效场景。首次 collector
把既有 snapshot preparation 的 copy/ids 两参数错计为一项，
helper exit 1 保留；核对未修改的基线声明后，只更正独立计数
脚本，run2 exit 0，没有重跑测试或修改 XML/条件。此前 85 文件
闭包及 424 份历史哈希保持，合并选定历史记录为 518 文件。
完整旧模块/fixture、probe、irl_demonstration_score_b3097ff.json、
irl_demo_b3097ff_xml_receipts.json、历史清单与区分根代理实际结果/
执行代理报告的工具记录分别保留。

README 同步，前 83 节正文完整保留。本轮未重跑七包，11.83 的
653 项只属于 ef300b4 历史源码资格，不作为当前 IRL 改动后的整包
声明。本轮无 LLM、benchmark、完整演示、物理仿真、实机示范或
Jazzy 验证，不证明整体加速、IRL 收敛、逆最优性或机器人示范效果。

### 11.85 执行快照索引复用每条边的 ID 对（2026-10-07）

基线为干净 4d047cca0ac9042d8e9ddbb53353b3f2b1b7a640。
_snapshot_index 原先为匹配检查和 matched_pairs.add 分别构造
(source_id, target_id)。本轮在每条边的循环内构造一次 pair，
匹配后复用。完整有序运行对及重复项、保留边顺序、缺边先于
缺节点的校验、目标歧义判断和全部校验后提交索引缓存均保持。
没有跨快照缓存或增加依赖，IRL 和测试文件未修改。

执行代理完整 test_accepted_run_resolver.py 与 test_backend.py
各执行一次，共 **72 passed**，0 errors/failures/skips，无 warnings；
现有两文件分别 31/41 项。JUnit 为 /tmp/resolver_edge_key_4d047cc.xml，
SHA256 为 8fc8982f19a73e8508fb05fe31ec40d996b2aa4ff2365484562c5ba3ab849ca0。
源码 py_compile、ament_flake8 --linelength 99 与 diff 检查通过。

主代理完整旧解析器逐字取自 git show 4d047cc，核对当前 import
及源码 SHA，并绑定未修改的 models、manager、execution_node、
snapshot、Product 五模块。对照 helper 一次实际 exit 0，三个原生
single/safe/KTH 的完整步骤、诊断、重复序号拒绝与输入保持相同，
派发 3/4/4 次，成本分别为 3/1/13、3/2/23、20/20/220。
六种 tuple/list 运行对及九种错误的精确消息、缓存完整性和恢复
一致。计数使用单独的 ProductEdge 子类快照，不改原生快照：
首次索引的 ID 读取分别为 22→16、36→28、104→96，缓存再次
命中均为零；重复保留边与重复运行对控制的索引结果也相同。
这里只验证每条匹配边减少两次字段读取，未测速度或内存。

主代理检查原 XML、计数与源码绑定，没有重跑测试。首次审计
脚本误写 XML classname/后端文件名，exit 1 保留；读取真实 XML
和文件清单后，仅修正审计脚本，run2 exit 0。完整旧模块、helper、
resolver_edge_key_4d047cc.json 与 resolver_edge_key_4d047cc_receipt.json
保留在既有隔离目录。README 同步，前 84 节正文完整保留。
本轮未重跑七包；11.84 的 IRL 74 项与 11.83 的 ef300b4 整包
653 项分别属于此前验证，不累加为当前人口。IRL 继续从示范学习
β，默认关闭；无 LLM、benchmark、物理仿真、实机或 Jazzy 验证。

### 11.86 IRL 与执行索引优化后的七包组合资格（2026-10-07）

干净源码资格为 e5a663c06ce45533cf098edd9eef91e69b3f5f6c，将
11.84 的 IRL 示范评分复用和 11.85 的索引键复用纳入完整组合。
本轮只更新 README 与验证记录，源码、测试、domains 和验收条件
保持。测试前固定预期 JUnit 656 项，其中 Core 191 项；其余包
与上次资格一致。此前 85 文件冻结闭包与 518 份选定历史哈希
核对，追加最近局部证据后预先固定 529 文件，不覆盖原始失败。

WSL Ubuntu-22.04-D / ROS 2 Humble / Python 3.10.12 / NetworkX 2.4
及 /home/yuhling/.local/bin/ltl2ba 保持。aggregate 六项依赖对应
六功能包；build 使用 --executor sequential、--symlink-install、
--packages-up-to ltl_automaton_core 与 -DBUILD_TESTING=ON。
test 选择完整七包，默认并行并带 --return-code-on-test-failure，
无筛选、缩时或条件调整。执行代理 build session 17106 与 test
session 22338 各启动一次，在原 handle 等待至实际 exit 0；
命令耗时分别 37.042412937 / 63.917228888 秒，不作为加速比。
主代理实际观测到 build runner/colcon PID 4332/4353，以及
test runner/colcon PID 4854/4879，未用状态文件推断活进程。

| package | tests | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 191 | 190 | 1 |
| ltl_automaton_planner | 159 | 158 | 1 |
| ltl_automaton_execution | 143 | 143 | 0 |
| ltl_automaton_hil_mic | 103 | 102 | 1 |
| ltl_automaton_std_transition_systems | 49 | 48 | 1 |

六份新鲜 JUnit 合计 **656 tests = 652 passed + 4 skipped**，0 errors/
failures。四项跳过均为既有 copyright。接口 CTest wrapper
另有一项通过；主代理对实际隔离 build 查询一次，exit 0，
汇总为 657 tests、0 errors、0 failures、4 skipped。13 份历史
CTest XML 按 test_start_ns 排除，不把旧结果或 wrapper 重复累加。

新增 IRL 同分顺序两参数及跨调用评分一项、原完整二十步和
四个溢出参数、IRL commit/step reset、执行解析/缓存及四个真实
DDS 场景执行；既有 Studio consumer、snapshot fallback、原生
ltl2ba/POSIX、HIL、monitor、launch 与 lint 均执行。保留 np.int/
SelectableGroups 弃用警告，五包 stderr 非空；检查完整 stderr
未见未读取 Future 诊断。start gate 核对十一项源码 import 与
隔离生成消息，主代理再绑定九模块完整 git 源字节，包含当前
IRL 与 resolver，不使用旧 receipt 代替当前源码证明。

collector、独立 fresh/live/frozen audit 和日志 receipt 检查均
各一次 exit 0；新 XML、构建/测试/查询完整实体日志、命令 receipt、
源码 import 与历史清单冻结为 85 文件 SHA256 闭包，529 份历史
哈希保持。记录在既有隔离目录的 verification_e5a663c.json、
verified_summary_e5a663c.json、verified_changed_imports_e5a663c.json、
colcon_query_e5a663c.json、inspected_combo_receipts_e5a663c.json 与
verified_results_e5a663c/sha256_manifest.json，独立工具结果另存。
前 85 节正文完整保留，旧 74/72 局部与 ef300b4 的 653 项保留
各自范围，不相加为本轮人口。无 LLM、benchmark、完整演示、
物理仿真、实机示范或 Jazzy 验证；通过不证明整体加速、IRL
收敛或逆最优性。IRL 沿用原示范学习 β 范围，默认关闭。

### 11.87 Product 快照节点的维度名列表隔离（2026-10-07）

基线为干净 07d7d14afda036a851748d4c2fdea6f6fca27d5f。
Python builder 原先把同一个 dimension_names 列表交给所有
ProductGraphNode 的 TransitionSystemState；生成消息的 setter 保留
该列表，因此编辑一个节点会改变其余节点。主代理原生 single/
safe/KTH 复现分别为 4/8/24 节点、3/7/23 个受影响兄弟节点，
源 TS 维度定义保持。该问题针对 Python 对象，未声称 DDS 反序列化
后仍有同一对象别名。本轮仅改为每个节点 list(dimension_names)，
保留字段值、验证顺序、节点/边/运行次序、ID、代价与接受性。

扩展既有 test_reused_ts_values_keep_message_state_arrays_independent
的两个 soft_task 参数，检查状态值及维度列表独立、源 TS 格式和
下一次完整快照/ID 保持，没有增加用例人口。执行代理首次直接
pytest 因 PATH 无命令 exit 127，在启动前终止、未生成 XML；改用
python3 -m pytest 后，修复前两用例实际 exit 1，2 failed、18 deselected。
修复后完整 test_planning_graph_snapshot.py 和
test_snapshot_service_copy.py 一次 **23 passed**，实际 exit 0，
0 errors/failures/skips。两轮各保留两项既有 NetworkX/NumPy np.int
弃用警告。静态 session 88471 终态 exit 0，两文件 py_compile、
ament_flake8 --linelength 99、测试 pep257、diff 检查通过。

两份原始 JUnit 为 /tmp/snapshot_dimensions_red_07d7d14.xml 与
/tmp/snapshot_dimensions_green_07d7d14.xml，SHA256 分别为
6591e4160a76722f07b746b77e22254a64ce684cdb2618407bf07f003cd1df52 和
8774dd9c364b53de31342aa63a8bfcf08e864dae1f96c8392834b1af9f8e01a9。
主代理独立读取 XML，核对计数及两个参数的失败/通过，没有重跑测试。
首次 inline XML 读取命令因 shell 引号错误 exit 1，未启动 Python；
随后改用保存的 helper，一次实际 exit 0。

完整旧 serializer 来自 git show 07d7d14；当前运行 import 路径与
源码字节绑定，确认仅上述一行改变。旧/新原生 single、safe、KTH
全部消息字段与 Product ID 相同，成本分别为 3/1/13、3/2/23、
20/20/220。旧维度列表共享、本轮各节点值/维度列表均独立；编辑
首节点后其他节点、源 TS 格式、下一次完整快照与 ID 保持。
比较使用生成消息字段值，不使用有 padding 的 CDR 字节作判据。
原复现、完整旧模块、verify_snapshot_dimensions_07d7d14.py 和
snapshot_dimensions_verified_07d7d14.json 保留于既有隔离目录及
主机临时目录。当前 serializer SHA256 为
4c7e2a654cd60a5c0cb04bb01d4315f9cc2d5d20bd3750f2e583528aa903c8c5。

README 与 Planning API 同步，前 86 节正文保留。本轮未重跑七包，
11.86 的 656 项属于 e5a663c 历史源码资格，未与局部结果累加。
IRL 学习 β 的范围和默认关闭保持；无 LLM、benchmark、物理仿真、
实机或 Jazzy 验证，列表隔离不构成整体加速或 IRL 科学效果证据。

### 11.88 HIL 拒绝重复 TS 维度并保留合法状态（2026-10-07）

基线为干净 90ccd8e1613fa35a0fa9631a0c74703acb36fbee。
主代理用生成的 ROS 消息复现 ['load', 'load'] 被 HIL validator
接受；BoolCommandPolicy 随后用 index=0 选取 empty→loaded，
保留重复维度和第二个状态值。这证明输入校验缺口，未声称实机
执行了错误动作。本轮在既有长度及 required dimension 检查后
验证所有维度名唯一性，重复时 ValueError；普通名称走 set，
TypeError 时按值比较，保留合法不可哈希 str 子类。没有更改
Bool/Velocity 仲裁、缓存更新、查询身份、超时、IRL 或规划语义。

扩展既有 validator 用例，覆盖 required/其他维度重复以及
不可哈希字符串；两个新增 async 用例各含 bool/velocity 参数，
共四项，检查无缓存拒绝后恢复、合法缓存/revision/pending query
保持及后续合法状态更新。执行代理先改测试后运行 RED，实际
exit 1：5 failed、73 deselected；修复后完整 test_policies.py 与
test_hil_async.py 一次实际 exit 0：**78 passed**，0 errors/failures/
skips。两轮各保留两项既有 NetworkX/NumPy np.int 弃用警告。
静态 session 37917 终态 exit 0，三文件 py_compile、
ament_flake8 --linelength 99、两测试 pep257 和 diff 检查通过。

RED/GREEN XML 为 /tmp/hil_duplicate_dimensions_red_90ccd8e.xml 和
/tmp/hil_duplicate_dimensions_green_90ccd8e.xml，SHA256 分别为
3446b54d85fcbf05a7907a4edec2bd3a3d5611a8c0e108a59053355ee8845056 和
bbc8720b6d13e12740cd470a9b4b7c2c5424167034bdfe16d5a03e801e0585c7。
主代理独立读取 XML 核对 5/78 项及四个回调参数，不重跑测试；
完整旧 policies 来自 git show 90ccd8e，运行 import/源码字节
绑定，确认生产改动仅在 validator。四种实际生成消息的合法
输入（单维、多维、重排、不可哈希字符串）结果相同且原对象/
字段保持；三种重复输入均从接受变为拒绝。长度先于重复、缺
required 先于重复的精确诊断保持。独立 helper 一次实际 exit 0。

原复现、完整旧模块、verify_hil_duplicate_dimensions_90ccd8e.py
及 hil_duplicate_dimensions_verified_90ccd8e.json 保留在既有
隔离目录/主机临时目录，当前 policies SHA256 为
e05fe6e719dc72e784e9af5bb313e996f2619cb7450fc9bfca1c7c4efe718421。
README/HIL README 同步，前 87 节正文保留。本轮未重跑七包，
e5a663c 的 656 项与 90ccd8e 的快照 23 项保留各自资格，不相加
为当前结果。验证使用真实 ROS 节点和受控 Future，没有实机、
LLM、benchmark、物理仿真或 Jazzy 验证，也未改变 IRL 学习范围。

### 11.89 快照隔离与 HIL 校验后的七包组合资格（2026-10-07）

干净源码资格为 aa7acf862749651b3e2b7eaaba70e1b6cff029d0，
将 11.87 的快照维度列表隔离和 11.88 的 HIL 重复维度校验纳入
完整组合。本轮只更新 README 与验证记录，源码、测试、domains
和验收条件保持。测试前固定预期 JUnit 660 项、4 项 copyright
跳过；四个新增 HIL 参数使该包从 103 到 107，快照扩展既有
两参数不增加人口。此前 85 文件冻结闭包和 529 份历史哈希
核对，加入最近整包与两轮局部证据后预先固定 625 份历史哈希。

沿用 WSL Ubuntu-22.04-D / ROS 2 Humble / Python 3.10.12 /
NetworkX 2.4 及 /home/yuhling/.local/bin/ltl2ba。七包 build
使用 executor sequential、symlink install、既有隔离 build/
install、packages-up-to ltl_automaton_core 与 BUILD_TESTING=ON；
test 使用完整七包默认并行及 --return-code-on-test-failure，
没有筛选、重跑、缩时或改变测试条件。执行代理 build session
27747 和 test session 75846 各启动一次并等待原 handle 至实际
exit 0，耗时分别 42.331240952 / 81.227143791 秒，不作为性能
测量。主代理实际从 /proc 观测 build runner/colcon PID
11213/11234 及 test runner/colcon PID 11703/11733。

| package | tests | passed | skipped |
|---|---:|---:|---:|
| ltl_automaton_msgs | 11 | 11 | 0 |
| ltl_automaton_planner_core | 191 | 190 | 1 |
| ltl_automaton_planner | 159 | 158 | 1 |
| ltl_automaton_execution | 143 | 143 | 0 |
| ltl_automaton_hil_mic | 107 | 106 | 1 |
| ltl_automaton_std_transition_systems | 49 | 48 | 1 |

六份 test_start_ns 之后的新鲜 JUnit 合计
**660 tests = 656 passed + 4 skipped**，0 errors/failures，跳过均为既有 copyright。
接口 CTest wrapper 另有一项通过；主代理对实际隔离 build 的
colcon 查询一次 exit 0：661 tests、0 errors/failures、4 skipped。
14 份历史 CTest XML 按开始时间排除，不与当前人口或 wrapper
重复累加。快照两个列表隔离参数、原子服务复制三参数、HIL
validator 和新增四回调参数均执行；IRL 完整二十步、四个 overflow
参数、IRL commit/step reset、四个真实 DDS 场景，以及 Studio、
fallback、原生 ltl2ba/POSIX、HIL、monitor、launch 和 lint 均执行。

启动门槛核对十四项源码 import 和隔离生成消息；十二模块完整
源码字节与 Git 资格版本绑定，含 snapshot、IRL、resolver 和
HIL policies/两个 mixer。主代理 collector、独立 fresh/live/
frozen audit、query 及完整日志 receipt 检查各一次实际 exit 0。
保留 np.int/SelectableGroups 弃用警告，五包 stderr 非空；完整
stderr 未见未读取 Future 诊断。新 XML、原命令 receipt、源码
导入和完整构建/测试/查询实体日志冻结为 85 文件 SHA256 闭包，
625 份历史哈希保持。记录为既有隔离目录的
verification_aa7acf8.json、verified_summary_aa7acf8.json、
verified_changed_imports_aa7acf8.json、colcon_query_aa7acf8.json、
inspected_combo_receipts_aa7acf8.json 及
verified_results_aa7acf8/sha256_manifest.json。

README 同步，前 88 节正文保留；旧局部 23/78 项及 e5a663c
整包 656 项保留各自源码资格，不相加为本轮人口。IRL 沿用原
示范学习 β 范围，默认关闭；执行验证仍为符号级 FakeBackend，
没有 LLM、benchmark、完整演示、物理仿真、实机示范或 Jazzy
验证。通过不证明整体加速、IRL 收敛、逆最优性或机器人效果。

### 11.90 IRL 轨迹消息的维度列表隔离（2026-10-07）

基线为干净 7feb701902d4ef831f12b4372ca2dc56766acdd4。
IRLPlugin.publish_possible_runs 原先将同一个 dimensions 列表
交给所有 LTLState。扩展既有 composed-state 列表独立性用例后，
直接 unittest RED 实际 exit 1：1 failed、0 errors，六个轨迹点
只有一份维度名列表（1 != 6）。本轮仅改为 list(dimensions)，
每个出现点独立持有列表，保留消息字段值、排序、历史集、源 TS
格式、缓冲规则、默认关闭与仅学习 β 的原范围。该问题针对
Python 消息对象，不声称 DDS 接收端仍有同一对象别名。

首次按普通 pytest 类名/方法节点定位因 launch_testing 的
LaunchTestModule 包装失败，实际 exit 1，未执行目标用例；原始
/tmp/irl_dimension_lists_red_7feb701.xml 保留，不把该 invocation
错误称为算法 RED。collect-only 实际 exit 0，显示一个聚合入口；
随后直接运行既有 unittest 完成上述 RED，没有改变验收条件。
修复后完整 test_irl_plugin.py 与 test_irl_preference.py 一次
实际 exit 0：两个 pytest 入口 passed，含插件 launch_testing
包装与真实 ROS β 偏好学习集成；两项既有 np.int 警告保留。
另直接运行强化的同一 unittest 一次 GREEN，1 passed；它与
聚合入口不相加为三个独立用例。静态 session 49156 在原 handle
等待至实际 exit 0，两文件 py_compile、flake8 --linelength 99、
pep257 和 diff 检查通过。

完整旧插件来自 git show 7feb701，运行 import/source 字节核对，
确认生产改动仅上述一行。单维、多维各六出现点及空轨迹对照，
完整字段/次序保持；编辑首点后受影响兄弟从 5 变为 0，历史集、
源格式和下一次完整发布保持。直接 RED JSON、完整旧模块及
irl_dimension_lists_verified_7feb701.json 保留在既有隔离目录，
helper 位于主机临时目录。GREEN XML 为
/tmp/irl_dimension_lists_green_7feb701.xml，SHA256 为
6aad9e08dfb1061f9cbca8cc8f59cf3cfa1e68835975fbe5173b045dfb570010。
当前插件 SHA256 为
f0f01ffbe90c7fe95c45b71f83e387a92c1b004222f50d932f338670800c4857。

README/HIL README 同步，前 89 节正文保持。本轮未重跑七包，
11.89 的 660 项属于 aa7acf8 历史源码资格，不作本轮整包声明。
没有 LLM、benchmark、物理仿真、实机或 Jazzy 验证，不将列表
隔离或局部集成通过称为整体加速、IRL 收敛或机器人示范效果。

### 11.91 丢弃 HIL 回调时读取 Future 异常（2026-10-07）

基线为 8f8c93739d1b9bc9f925ebfd005fa0f720b3704c，运行环境为
WSL Ubuntu-22.04-D / ROS 2 Humble，使用既有隔离 overlay。真实
rclpy Future 在异常完成并调度 callback 后，若回调因节点销毁、
context/Future 身份替换或 deadline 而提前返回，旧实现没有读取
异常，GC 会报告 exception was never retrieved。Humble 的
Future.exception() 不等待并标记异常已读取；已完成 Future 的
cancel() 不会代替这一步。本轮只在 Bool trap、Velocity closest
和 Velocity trap 三个入口各增加四行读取，保留所有原 guard、
deadline、result、错误日志、请求释放和导航回退顺序。对既有受控
Future 缺少 exception() 方法的情况沿用原 result() 路径。

新增参数化用例覆盖三回调 × 四丢弃条件，使用真实控制器节点、
Future 和 SingleThreadedExecutor。先异常完成并排队，再真实
destroy_node()、替换身份或将受控 steady clock 推进到原 deadline，
随后 spin 一次。检查旧命令零派发、替换请求保留、超时释放及速度
零导航回退；weakref/GC 确认 Future 实际回收且没有未读取异常。
executor 在 finally 关闭，fixture 不重复销毁节点。

第一次 RED 为 12 failed、47 deselected；第一次两文件 GREEN 为
90 passed。随后静态检查发现三处 E731，改用 partial。审查还发现
首版 fixture 在完成前改变丢弃条件，closed 只切换标记；它没有验证
已排队回调与真实销毁的完整时序。保留原 XML，不将它们作为最终
测试字节的资格。修正上述时序和清理后，暂时仅移除十二行生产修复，
run2 RED 实际 exit 1：12 failed、47 deselected、2 warnings，
4.10 秒；失败均为 late HIL failure 未读取。恢复相同源码字节后，
最终两文件 GREEN 实际 exit 0：90 passed、2 warnings，5.27 秒。
两项警告均为既有 NetworkX np.int 弃用，0 errors/failures/skipped。
没有改变参数人口、丢弃条件、deadline 或验收标准。

最终命令在 source Humble 与隔离 install/setup.bash 后执行：

```bash
python3 -m pytest -q ltl_automaton_hil_mic/test/test_hil_async.py \
  -k discarded_real_future_exceptions_are_consumed \
  --junitxml=/tmp/hil_future_discard_red_run2_8f8c937.xml
python3 -m pytest -q ltl_automaton_hil_mic/test/test_hil_async.py \
  ltl_automaton_hil_mic/test/test_policies.py \
  --junitxml=/tmp/hil_future_discard_green_run2_8f8c937.xml
```

RED、GREEN 均无持续 session，各自等待至上述实际退出。最终静态
session 1571 在原 handle 等待至 exit 0：三个改动文件 py_compile、
flake8 --linelength 99，回调测试 pep257 及 git diff --check。
GREEN XML SHA256 为
c3e0c4a0e9c4b48f5c7f295576d13d48d260ef2ddde8f917df49f3b8d0725d3f。
最终 Bool/Velocity 源码 SHA256 分别为
a17ab247306a9de8b3b9e2d60caef9a1761f571fce4b73d92e1c5c997e90707d、
1e2d07ac8b1bd03d36df111bbd8db07ff439b245fd0d19dbe6eab7062e9b2347；
测试 SHA256 为
fe9d51dfb4c252fd81a5a0f2e6be622fc50e487d938eaa9b645b99edeebcebc0。

主代理从 git show 8f8c937 加载完整旧模块并核对运行 import 与
源字节，采用真实 Future/executor、受控 host hooks，独立对照
三回调 × 五条件（另含当前请求失败）共十五格。完成先于条件改变；
十二个丢弃格旧版有诊断、新版 stderr 为空，三项当前失败保持
日志/释放/回退 trace，全部旧新 trace 相等且 Future 实际回收。
此对照的 closed 使用 host 标记，真实销毁由上述节点测试覆盖。
未把十五格重复加到九十项 pytest 人口。

原 XML /tmp/hil_future_discard_red_8f8c937.xml 与
/tmp/hil_future_discard_green_8f8c937.xml 保留；run2 两 XML 如上。
完整旧模块、hil_future_baseline_8f8c937.json、
hil_future_compare_8f8c937.json、hil_future_inspected_results_8f8c937.json
位于 /tmp/ltl_ros2_completion_20261006，helper 在主机临时目录。
主代理逐一检查四 XML 计数/新用例名/SHA、最终三文件 SHA 与仅十二行
生产差异。README/HIL README 同步，前九十节正文保持。本轮未重跑
七包，11.89 的 660 项仍属于 aa7acf8 历史源码。没有 LLM、benchmark、
物理仿真、实机或 Jazzy 验证，不声称整体加速或 IRL 科学效果。

### 11.92 KTH driver 状态消息的维度列表隔离（2026-10-07）

基线为干净 ad4d1d6fe2a426080d5f5a33705f3230c4fae194。
先检查执行入口：ROS 消息的可变列表已转换为 frozen 模型内的 tuple，
缓存只持有该不可变投影，本轮没有修改 resolver 或执行缓存。继续检查
演示发布时发现 KthDemoDriver._publish_state 将模块 STATE_DIMENSIONS
直接赋给每条 ROS 消息。原生生成消息实证两次发布只有一份维度名列表；
编辑首条会改变第二条、模块定义和下一次发布。状态值原本分别 list(state)。
本轮生产改动只有 list(STATE_DIMENSIONS) 一行，保留字段值、排序、时间戳
获取、日志、scenario、max_steps、timer、任务切换与合法偏离流程。

新增一个检查，用现有 isolated ROS Context/真实 Node 构造 fixture，
publisher 记录真实生成消息。核对两条消息字段与两种列表独立，编辑首条
后第二条、模块常量、两个输入状态元组及下一次发布保持；finally 恢复
模块常量并销毁节点/context，RED 失败不污染其他用例。旧实现定向运行
实际 exit 1：1 failed、21 deselected，0.92 秒，失败为维度列表 is not
断言。修复后该完整测试文件实际 exit 0：22 passed，1.44 秒，无 pytest
warnings、errors、failures 或 skipped；原21项和新增一项均执行。
没有修改阶段、步数、超时或验收条件，也没有运行完整演示。

source Humble 与既有隔离 install/setup.bash 后的实际命令：

```bash
python3 -m pytest -q ltl_automaton_planner/test/test_kth_demo_driver.py \
  -k published_state_messages_own_dimension_and_state_lists \
  --junitxml=/tmp/demo_dimension_lists_red_ad4d1d6.xml
python3 -m pytest -q ltl_automaton_planner/test/test_kth_demo_driver.py \
  --junitxml=/tmp/demo_dimension_lists_green_ad4d1d6.xml
```

两次测试均无持续 session，各自实际退出；没有中间静态失败，GREEN 后
未改变源码/测试。静态 session 40080 在原 handle 等待至 exit 0：两个
文件 py_compile、flake8 --linelength 99、pep257 与 diff 检查通过。
GREEN XML SHA256 为
14af687d35a5d56e8a236ca0b0f729fd47b40661e2a6db1aa02ebf6faf4f6274。
最终 driver/test SHA256 分别为
01d84081b5ea27642bfdb71ccf98f5b24ca5f09fd185f4dda1f6a927b28b7a24、
8660340ca4e57612e5a3e04fa6ac0ff72661b45d454d14c04b3a0965bf908af0。

主代理从 git show ad4d1d6 加载完整旧 driver，核对运行 import、旧新源
字节及仅一行生产差异。原生 ROS 消息配合受控 clock/publisher/logger
hooks 对照：两条消息的完整 header、状态字段与三次日志一致；维度列表
份数由1变2，编辑首条对兄弟、模块定义和下一次发布的影响均由有变无，
状态列表份数保持2、输入元组保持。这里验证 Python 消息对象所有权，
没有声称 DDS 订阅端保留同一别名；该独立对照不加到22项 pytest 人口。

XML 如上；完整旧模块 demo_dimension_baseline_ad4d1d6.py 及
demo_dimensions_baseline_ad4d1d6.json、demo_dimensions_compare_ad4d1d6.json、
demo_dimensions_inspected_ad4d1d6.json 在 /tmp/ltl_ros2_completion_20261006，
helper 在主机临时目录。主代理核对 XML 计数/用例名/SHA 和最终两文件
字节，README/演示说明同步，前九十一节正文保持。本轮未重跑七包；
660 项仍属于 aa7acf8 历史源码资格，HIL 的90项与 IRL 的两个 pytest
入口保留各自源码资格，不相加。没有 LLM、benchmark、物理仿真、实机
或 Jazzy 验证，不称为整体加速、IRL 科学效果或完整演示验收。

### 11.93 IRL、HIL Future 与 driver 修复后的七包组合资格（2026-10-07）

资格源码为干净 0beaa3ed08cc456e8c7f0ac6c3e9586aa3c8256c，
包括 11.90–11.92 的三个生产修复。本轮没有新的算法/接口改动。
测试开始前固定七包、预期六份 JUnit 673项与4项 copyright 跳过，
保留完整默认并行人口、domain、timeout、max_steps 和原验收条件。
环境为 WSL Ubuntu-22.04-D / ROS 2 Humble / Python 3.10.12 /
NetworkX 2.4，原生 translator 为 /home/yuhling/.local/bin/ltl2ba。

使用既有隔离 build/install，build session 43807、test session
95248 均沿原 handle 等待至实际 exit 0，各执行一次，真实 elapsed
分别 43.926285402秒与81.327542842秒。根代理从 /proc 确认 build
runner/colcon PID19057/19070，随后 test runner/colcon PID19407/19428；
没有用标记文件或观察超时推断进程停止，也没有启动替代运行。

```bash
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_combo_0beaa3e build \
  --executor sequential \
  --base-paths /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2 \
  --build-base /tmp/ltl_ros2_completion_20261006/build \
  --install-base /tmp/ltl_ros2_completion_20261006/install \
  --symlink-install --packages-up-to ltl_automaton_core \
  --cmake-args -DBUILD_TESTING=ON
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_combo_0beaa3e test \
  --build-base /tmp/ltl_ros2_completion_20261006/build \
  --install-base /tmp/ltl_ros2_completion_20261006/install \
  --packages-select ltl_automaton_core ltl_automaton_msgs \
  ltl_automaton_planner_core ltl_automaton_planner ltl_automaton_execution \
  ltl_automaton_hil_mic ltl_automaton_std_transition_systems \
  --return-code-on-test-failure
```

构建后 source 同一隔离 overlay，start gate 核对16项源码 import
和生成消息路径；13个相关生产模块完整字节与 git show 0beaa3e 绑定，
包含本次三个修复及原执行/规划模块。aggregate exec_depend 正好为
六个功能包。新鲜六份 JUnit 为
**673 tests = 669 passed + 4 skipped**，0 errors/failures：
msgs11/0skip、core191/1、planner160/1、execution143/0、
HIL119/1、std49/1。四项跳过均为既有 copyright。

新增 HIL 十二个真实 Future 丢弃参数与 driver 列表检查均执行，
IRL 插件 launch_testing 聚合入口与真实 β 偏好学习入口各一项通过；
聚合内部用例不另加到 JUnit 人口。原二十步/overflow/commit、
快照隔离、原子服务复制、执行 resolver/timeout、四个真实 DDS 场景、
Studio、fallback、原生 ltl2ba/POSIX、monitor、launch 与 lint 保持通过。
接口 CTest wrapper 另一项 passed，实际隔离 build 查询为674tests，
0 errors/failures、4 skipped；15份历史 CTest XML 按开始时间排除。

完整 stderr 中五包各923bytes，包含既有 np.int/SelectableGroups
依赖弃用警告；未见 exception was never retrieved 诊断。旧AA的
85文件冻结闭包及731份选定历史哈希在前后核对均保持；新的完整 XML、
receipt、import与colcon日志冻结为另一份85文件闭包。根代理查询、
collector、独立 audit 与 receipt 检查各一次实际 exit 0，核对全部
计数/required cases/时间边界/源字节/原日志，未用历史绿项替换当前结果。

证据位于 /tmp/ltl_ros2_completion_20261006：
verification_0beaa3e.json、verified_changed_imports_0beaa3e.json、
verified_summary_0beaa3e.json、colcon_query_0beaa3e.json、
historical_hashes_before_0beaa3e.json、inspected_combo_receipts_0beaa3e.json
及 verified_results_0beaa3e/sha256_manifest.json。日志在
log_combo_0beaa3e 与 log_query_0beaa3e，helper 在主机临时目录。

README 改为当前组合表，前九十二节正文保持。旧660项组合、IRL/HIL/
driver 局部资格与各次原始失败仍按各自版本保留，不累加为本轮人口。
IRL 沿用原示范学习 β 范围，默认关闭；执行仍为符号级 FakeBackend。
没有 LLM、benchmark、完整演示、物理仿真、实机/机器人示范或 Jazzy
验证，通过不证明整体加速、IRL 收敛/逆最优性或机器人效果。

### 11.94 Trap 初始相交判断省去临时集合（2026-10-07）

基线为干净 9d2eca3c6d3d624b67405118d99232a405c013f1。本轮只有一行
生产改动：possible_states & visited 改为 not possible_states.isdisjoint(visited)。
保留 set/frozenset 与 DiGraph 的原入口检查、逆向单次遍历、缺失节点和
列表输入的原 has_path 分支，以及每次查询重新读取活动图的行为。
这是布尔查询的容器优化，没有增加测试或修改算法/IRL 学习范围。

WSL Ubuntu-22.04-D 中 source Humble 与既有隔离 install/setup.bash 后，
一次运行两个完整现有测试文件，实际 exit 0：21 passed，0 errors、
failures 或 skipped，终端报告3.99秒，无持续 session；两项警告均为既有
NetworkX np.int 弃用。

```bash
python3 -m pytest ltl_automaton_hil_mic/test/test_trap_detection.py \
  ltl_automaton_hil_mic/test/test_trap_plugin_launch.py \
  --junitxml=/tmp/trap_disjoint_green_9d2eca3.xml
```

静态 session 57990 沿原 handle 等待至实际 exit 0：改动源码 py_compile、
flake8 --linelength 99、pep257 与 git diff --check 通过。根代理检查新鲜
XML 的21个入口、计数与 SHA256；JUnit suite time 为3.972秒，XML SHA256为
d8e5b3f748584c2f30d21b87862a3ec76cfde4a761a4f69ed4c95d863ff3e7e1。
最终源码 SHA256 为
a81bb4dc536da6f9f0c6be91b1544ef3e132667fe8fd7802495c47cee64f15f0。

独立旧新对照加载完整 git show 9d2eca3 模块，核对运行 import 和仅一行
源差异。16个双节点有向图（含全部自边组合）×4候选子集×4接受子集×
4种 set/frozenset 配对，每版1,024格，全部与 NetworkX has_path 参考
结果一致，包含空集合及零边续行。二进制交集字节码位置由1变0；此数值
是静态结构检查，没有测量时延/RSS或声称整体加速。对照不加到pytest人口。

完整旧模块 trap_disjoint_baseline_9d2eca3.py、baseline/compare JSON 与
trap_disjoint_inspected_9d2eca3.json 位于 /tmp/ltl_ros2_completion_20261006，
helper 位于主机临时目录，XML 如上。README/HIL 说明同步；此前93节正文
保持。本轮未重跑七包，11.93 的673项资格仍属于0beaa3e历史源码。
没有 LLM、benchmark、物理仿真、实机或 Jazzy 验证。

### 11.95 6D monitor 搜索复用入口位置校验（2026-10-07）

基线为干净 93841ea9a52acb5285a5c9d1c4c127dcb03d77d1。旧版 update
在入口校验位置后，_find 通过 is_in_region 为每个候选区域重复校验。
本轮把几何主体提取为私有 _contains_position，内部 _find 复用 update
入口校验；公开 is_in_region 仍先独立校验。不返回或缓存新坐标对象，
保留 math.hypot、严格 <、额外关节忽略、候选与连接优先级、状态更新及
错误优先级。_find 的现有调用均来自已校验的 update。

WSL Ubuntu-22.04-D 中 source Humble 与既有隔离 install/setup.bash 后，
一次运行三个完整现有测试文件，实际 exit 0：46 passed，0 errors、
failures 或 skipped；两项警告为既有 NetworkX np.int 弃用，终端4.27秒，
无持续 session。37项模型、8项节点输入、1项 launch_testing 聚合入口；
聚合内部两 monitor 的通信及关闭检查不另计数。没有增改测试或运行 RED。

```bash
python3 -m pytest ltl_automaton_std_transition_systems/test/test_region_models.py \
  ltl_automaton_std_transition_systems/test/test_monitor_inputs.py \
  ltl_automaton_std_transition_systems/test/test_monitor_launch.py \
  --junitxml=/tmp/joint_validation_green_93841ea.xml
```

静态 session 29716 沿原 handle 等待至实际 exit 0：改动源码 py_compile、
flake8 --linelength 99、pep257 与 git diff --check 通过。根代理逐项核对
新鲜 XML 的数量、入口与 SHA256；JUnit suite time 为4.25秒，XML SHA256为
cea8150f23023aef2538ba4832b5a02e08ceae550838055b0f0e5066ae8dc578。
最终源码 SHA256 为
19544ada9177b6fa934d9850c0fd94c6f5d527456af1d6586c395f02f23d8508。

完整旧模块与当前 import 独立对照43格，返回、错误类型/文本/cause、状态
及输入/配置不变性一致。包含连通/断连回退、未命中、后续恢复、额外关节、
tuple/bool、首末坐标的非有限值/溢出/非数字、未知区域、严格半径相邻浮点
与直接调用 hysteresis。初次/连通/断连三种 update 校验由2/3/6次变1次，
每格仍执行一次输入校验；计数不证明整体加速，不加入46项pytest人口。

完整旧模块 joint_validation_baseline_93841ea.py、baseline/compare JSON 与
joint_validation_inspected_93841ea.json 位于 /tmp/ltl_ros2_completion_20261006，
helper 位于主机临时目录，XML 如上。README/标准 TS 说明同步，前94节正文
保持。11.93 的673项组合与11.94的trap局部资格保留原源码版本，本轮未重跑
七包。没有 LLM、benchmark、物理仿真、实机或 Jazzy 验证。

### 11.96 2D station 判定复用单次 yaw 差值（2026-10-07）

基线为干净 abc12b4103a8f17600f826864345522d30c3a9db。旧 is_in_station
分别在 sin/cos 内重复计算同一个 pose 的 yaw 和角度差；本轮在 distance
之后按原先先读 heading 再读 quaternion 的顺序计算局部 yaw_difference，供两者
共用。保留原未归一化 quaternion/yaw 公式、sin/cos/atan2/abs 次序、±π
环绕、严格边界、threshold 优先级、station access、滞回及错误优先级。
没有跨调用缓存，后续调用仍读取 pose 和区域配置；其他源码/测试保持。

source Humble 与既有隔离 overlay 后，一次运行三个完整现有文件，实际
exit 0：46 passed，0 errors/failures/skipped。37项模型、8项节点输入、
1项 launch_testing 聚合入口；内部通信/关闭用例不另计数。终端4.33秒，
无持续 session，两项警告均为既有 NetworkX np.int 弃用，无新增测试/RED。

```bash
python3 -m pytest ltl_automaton_std_transition_systems/test/test_region_models.py \
  ltl_automaton_std_transition_systems/test/test_monitor_inputs.py \
  ltl_automaton_std_transition_systems/test/test_monitor_launch.py \
  --junitxml=/tmp/station_yaw_green_abc12b4.xml
```

静态 session 83155 沿原 handle 等待至实际 exit 0：改动源码 py_compile、
flake8 --linelength 99、pep257 与 git diff --check 通过。根代理检查 XML
入口、数量与哈希，JUnit suite time 为4.308秒，XML SHA256为
3f2902ec45860249edfb9f6ea1a8cfb4c8bfbabf4dd2a816146743ea1235e07f。
最终源码 SHA256 为
9e64af55ac56ec4b5ac6e79a88611e5b8d19422db0c6707c9d5640e2e24c0cbe。

完整旧模块与当前 import 独立对照43格：原生 Pose 的±π及相邻角度、
严格半径相邻浮点、距离/角度滞回、非单位 quaternion、threshold/tolerance
优先级、station 请求/释放/离开与无效输入。返回、错误类型/文本/cause、
状态及输入/配置不变性一致。缺失 heading 仍先于缺失 orientation 报错；
正常 station 判定 yaw 调用由2次变1次。此计数不证明整体加速，不加入
46项pytest人口。

完整旧模块 station_yaw_baseline_abc12b4.py、baseline/compare JSON 与
station_yaw_inspected_abc12b4.json 位于 /tmp/ltl_ros2_completion_20261006，
helper 位于主机临时目录，XML 如上。README 同步，前95节正文保持；11.93
的673项组合及11.94–11.95局部资格保留原版本，本轮未重跑七包。没有 LLM、
benchmark、物理仿真、实机或 Jazzy 验证。

### 11.97 Trap 与2D/6D monitor 优化后的七包组合资格（2026-10-07）

资格源码为干净 9c9a80d6f5a0ef91291fe0fc04689e0bdcc1552d，包括
11.94–11.96 的三个生产优化；本轮没有新的算法/接口或测试变更。
开始前核对与0be资格之间仅三源文件和四文档变化，固定七包、六份JUnit
673项与4项 copyright 跳过，保留默认并行、domain、timeout、max_steps
和原验收条件。环境为 WSL Ubuntu-22.04-D / ROS 2 Humble /
Python3.10.12 / NetworkX2.4，原生 ltl2ba 路径与完整二进制SHA保持。

既有隔离 build/install 下各执行一次。build session94245、test session
88838 沿原 handle 等待至实际 exit0，receipt elapsed 分别43.635586786秒
与78.790072845秒；import/start gate session9367 实际exit0。构建后核对
18项源码 import 与生成消息路径，16个完整相关生产模块与 Git 字节匹配，
包含三个最新优化。主代理未捕获运行期PID，终态按原执行handle及原始
receipt/log核对；没有据空进程观测、marker或观察超时启动替代运行。

```bash
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_combo_9c9a80d build \
  --executor sequential \
  --base-paths /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2 \
  --build-base /tmp/ltl_ros2_completion_20261006/build \
  --install-base /tmp/ltl_ros2_completion_20261006/install \
  --symlink-install --packages-up-to ltl_automaton_core \
  --cmake-args -DBUILD_TESTING=ON
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_combo_9c9a80d test \
  --build-base /tmp/ltl_ros2_completion_20261006/build \
  --install-base /tmp/ltl_ros2_completion_20261006/install \
  --packages-select ltl_automaton_core ltl_automaton_msgs \
  ltl_automaton_planner_core ltl_automaton_planner ltl_automaton_execution \
  ltl_automaton_hil_mic ltl_automaton_std_transition_systems \
  --return-code-on-test-failure
```

六份新鲜JUnit：**673 tests = 669 passed + 4 skipped**，0 errors/failures。
msgs11/0skip、core191/1、planner160/1、execution143/0、HIL119/1、std49/1；
四项跳过均为既有 copyright。Trap 九种可达性、缺失节点/短路/图变更，
2D station access/closest、6D连通/严格半径/extra joint及monitor/plugin
launch入口均执行；原12项HIL Future、driver列表、IRL launch/真实β偏好、
二十步/overflow/commit、快照隔离/原子复制、resolver/timeout、四个DDS、
Studio、fallback、原生translator/POSIX、readonly参数、launch和lint通过。
聚合内部与此前独立旧新对照不重复累加。接口CTest wrapper另1项通过，
实际隔离build查询674tests、0 errors/failures、4 skipped；16份历史CTest
XML按测试开始时间排除。完整stderr五包各923bytes，保留np.int/
SelectableGroups依赖弃用警告，未见未读取Future异常诊断。

前一0be的85文件闭包与833份选定历史hash前后均保持；本轮XML、receipt、
imports、完整常规colcon日志另冻结为85文件闭包。根代理query、collector、
独立audit与receipt检查各一次实际exit0，核对源字节/人口/入口/时间/日志。
证据位于 /tmp/ltl_ros2_completion_20261006：verification_9c9a80d.json、
verified_changed_imports_9c9a80d.json、verified_summary_9c9a80d.json、
colcon_query_9c9a80d.json、historical_hashes_before_9c9a80d.json、
inspected_combo_receipts_9c9a80d.json及verified_results_9c9a80d/sha256_manifest.json。
日志在log_combo_9c9a80d/log_query_9c9a80d，helper在主机临时目录。

README改为当前组合表，前96节正文保持。旧0be/AA组合、各版局部资格和
原始失败仍按原源码保留。IRL仅学习β、默认关闭，执行仍为符号级FakeBackend；
没有LLM、benchmark、完整演示、物理仿真、实机/机器人示范或Jazzy验证。
通过不证明整体加速、IRL收敛/逆最优性或机器人效果。

### 11.98 单维 TS 初始状态容器隔离（2026-10-07）

基线为 d8431042334fb325f93e7fdc705691c811a3ae6c。单维 build_full 直接
引用输入 initial 容器，导致组合 TS、输入与兄弟实例的成员修改互相污染；
多维组合原本生成独立集合。修复用 copy.copy 复制单维 initial 容器，
保留 set/list/tuple/frozenset 类型和值，其他图属性、guard、节点和边不变。
源ts.py SHA从 f6a235c1c3b10972d3ceb9afea397d9b31eb528d43d6ff31a6e16ceaf05453f4
变为 3b8c4f8ff2fc67be00a87d12dff750ac0229d047a5a0795af478f1fd6f159d44。

新增 set/list 两个行为回归：组合/输入双向隔离、兄弟实例、有效及未知
set_initial、重建读取当前输入且再次隔离，保留边值。初稿RED实际exit1，
2 failed/13 deselected（0.88秒；JUnit0.835秒），第120行输入被污染断言失败。
前两次完整尝试均72 passed/2 failed：初稿先向model添加r2，后来却要求
model只含r1，错误预期在第124行失败；对应JUnit3.286/2.901秒。修正用例
使用clear并核对空集合与来源后，第三次完整运行实际exit0，**74 passed**
（15项TS、33项Product、26项LTLPlanner），0 errors/failures/skipped；
pytest3.06秒、JUnit3.030秒，保留两项np.int依赖警告。

```bash
export PYTHONPATH=/mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2/ltl_automaton_planner_core:$PYTHONPATH
python3 -m pytest ltl_automaton_planner_core/test/test_ts.py \
  ltl_automaton_planner_core/test/test_product.py \
  ltl_automaton_planner_core/test/test_ltl_planner.py \
  --junitxml=/tmp/ts_initial_green_run3_d843104.xml
```

环境沿用11.97；最终import明确绑定当前checkout，源与测试SHA核对。
第一次尝试只记录build路径而未保存当时源SHA，对旧build字节的疑虑不能
作为失败归因；XML实际支持上述预期错误。四份XML保留原名并逐一冻结，
原stdout/receipt未单独保存，退出码按原工具终态记录。静态session47125
实际exit0：py_compile、ament_flake8 --linelength 99、ament_pep257、diff检查。

主代理独立六格旧新对照实际exit0：四种容器的完整节点/边、初始值、
类型、set_initial成功/拒绝及重建结果一致；set/list双向及兄弟实例污染
由旧实现复现，修复后隔离。对照不累加到JUnit或作为加速证明。
证据在 /tmp/ltl_ros2_completion_20261006：ts_initial_baseline_d843104.py、
ts_initial_{baseline,compare,inspected,attempts_inspected}_d843104.json；
XML位于/tmp：ts_initial_red_d843104.xml、ts_initial_green_d843104.xml、
ts_initial_green_run2_d843104.xml、ts_initial_green_run3_d843104.xml。
最终XML SHA为 3f417326b6e5dc1acbccdd4a6700f6fb80e3f55d7104a041dc5699335bc42ad0。
README同步，前97节正文保持；673项组合保留为9c源码历史资格。
本轮未重跑七包、调用LLM、跑benchmark/物理仿真/实机或Jazzy。

### 11.99 冻结成员集合的完整快照转换（2026-10-07）

基线 a25622f0b7dd8ed41803abe8509ccd3294f407a8 的 _membership 支持
set/list/tuple，却拒绝同值frozenset。真实single/safe Core计划冻结
Büchi/Product initial及accept后Dijkstra仍给出原代价，但转换报类型错误。
修复只在既有容器判断中加入frozenset；整个value作为已有图节点时仍优先
匹配，成员标记、ID、公式、代价、运行边界及输入图保持原行为。
源SHA从 4c7e2a654cd60a5c0cb04bb01d4315f9cc2d5d20bd3750f2e583528aa903c8c5
变为 45dda1335c5c229671b0cf875af0ee2d9fffeae1096a03169ff7ae24f092dc3b。

新增single/safe任务 × Product/Büchi × initial/accept八格完整消息回归。
RED实际exit1，8 failed/20 deselected，JUnit2.021秒；原错误为membership
拒绝。随后三次启动各有2/2/1个collection error，分别为源目录遮蔽生成
消息、缺rosidl_parser和缺core.configuration，没有完成测试人口。
三份失败XML保留。第四次实际exit0，31 passed（28项snapshot、3项服务
复制），pytest1.92秒、JUnit1.894秒，保留两项np.int依赖警告。
这些子代理运行未单独保存stdout/receipt，绑定输出不含当时完整SHA。

根代理针对运行绑定/记录缺口，沿已验证ROS overlay保存一次相同两文件
完整运行：六个生产模块resolve路径及完整字节与checkout/Git核对，另有
一个生成消息模块和两份测试SHA。先绑定模块再调用pytest.main，无filter、
timeout或验收变化。原工具chunk c33bb4实际exit0，receipt5.496040565秒；
**31 passed**，0 errors/failures/skipped，pytest1.25秒、JUnit1.228秒，
输出未列pytest警告汇总。命令、环境、原stdout/stderr、import证明均保存。
首个结果检查器误要求此前警告文本，实际人口和状态已通过；读取原日志
后修正该文本检查，未重跑测试，最终证据检查实际exit0。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_frozen_membership_a25622f.py
```

wrapper子进程在隔离workspace执行pytest.main，参数为两个checkout完整
测试路径，XML=/tmp/frozen_membership_green_root_a25622f.xml。静态session
23654实际exit0：py_compile、ament_flake8 --linelength 99、ament_pep257、diff。
根代理15种独立输入中既有13格结果/错误保持，含tuple/frozenset节点优先级；
空/非空冻结集合恢复。两份真实single/safe ROS消息及ID表逐字段与set基准
相等，run与冻结成员对象保持，Core代价不变。独立对照不累加JUnit人口。

证据在 /tmp/ltl_ros2_completion_20261006：frozen_membership_baseline_a25622f.py、
frozen_membership_{baseline,compare,root_run,root_imports,inspected}_a25622f.json，
原日志frozen_membership_root_run_a25622f.log。六份XML在/tmp，原RED、
GREEN、GREEN_run2/3/4及GREEN_root分别冻结，文件名见inspected清单。
根代理最终XML SHA为 243982ff3389f4e92c6b75569387956e03a2dfd038f875ec5a3ce1760d36b446。
README同步，前98节正文保持；本轮未重跑七包或做LLM/benchmark/物理仿真/
实机/Jazzy验证，不改变消息schema、算法、IRL范围或学习规则。

### 11.100 TS 隔离与冻结集合快照修复后的七包组合资格（2026-10-07）

资格源码为干净 6ce560f340cd2ca1e96f31c8e0b0237700f2be0d，包含11.98–11.99
的两个修复。开始前核对相对9c资格仅两生产文件、两测试与两文档变化，
固定七包、六份JUnit的683项与4项copyright跳过。新增两项TS及八项快照
回归计入各自文件，不把先前74/31项局部运行或独立对照再相加。保留默认
并行、domain、timeout、max_steps及原验收。环境沿用WSL Ubuntu-22.04-D /
ROS2 Humble / Python3.10.12 / NetworkX2.4；原生ltl2ba二进制完整SHA仍为
d4785c387b67be41052800f6913b8476dbaff56730ef962553fd3d339c378ed3。

在既有隔离build/install下各执行一次。build session89524与test session
82507沿原handle等待至实际exit0，receipt elapsed分别38.235287731秒、
64.205967504秒。主代理运行中观察到build wrapper PID31275及colcon
PID31304；未捕获运行期test PID，测试终态由原handle、receipt和日志核对，
没有据空进程观测或观察超时启动替代运行。构建后18项源码import及生成
消息路径核对通过，原16个完整生产模块与Git字节一致；另补核对改动TS的
import、完整Git字节及SHA，单独保存证明，合计17模块。

```bash
source /opt/ros/humble/setup.bash
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_combo_6ce560f build \
  --executor sequential \
  --base-paths /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2 \
  --build-base /tmp/ltl_ros2_completion_20261006/build \
  --install-base /tmp/ltl_ros2_completion_20261006/install \
  --symlink-install --packages-up-to ltl_automaton_core \
  --cmake-args -DBUILD_TESTING=ON
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_combo_6ce560f test \
  --build-base /tmp/ltl_ros2_completion_20261006/build \
  --install-base /tmp/ltl_ros2_completion_20261006/install \
  --packages-select ltl_automaton_core ltl_automaton_msgs \
  ltl_automaton_planner_core ltl_automaton_planner ltl_automaton_execution \
  ltl_automaton_hil_mic ltl_automaton_std_transition_systems \
  --return-code-on-test-failure
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_query_6ce560f test-result \
  --test-result-base /tmp/ltl_ros2_completion_20261006/build --verbose
```

六份新鲜JUnit：**683 tests = 679 passed + 4 skipped**，0 errors/failures。
msgs11/0skip、core193/1、planner168/1、execution143/0、HIL119/1、std49/1。
四项跳过均为既有copyright；接口CTest wrapper另1项通过，查询684tests、
0 errors/failures、4 skipped；17份历史CTest XML按测试开始时间排除。
新增TS初始容器隔离/重建两格与冻结集合八格均执行；此前IRL插件及真实β
偏好、完整二十步/overflow/commit、HIL十二项Future、driver列表隔离、
Trap/monitor、快照/服务复制、resolver/timeout、四个DDS、Studio/fallback、
原生translator/POSIX、参数、launch和lint通过。聚合内部不重复计数。
五包stderr各923bytes，保留np.int/SelectableGroups依赖弃用警告，未见
未读取Future异常诊断；本轮时间仅记录该次运行，不作为加速比较。

先前9c的85文件闭包及944份选定历史hash前后均保持。本轮XML、receipt、
原16模块证明、TS补证与完整TS源码、完整常规colcon日志冻结为87文件闭包。
根代理query、collector、独立audit与receipt检查各一次实际exit0；核对
人口、所有要求入口、源字节、日志、时间、新鲜度、聚合依赖及闭包哈希。
证据位于/tmp/ltl_ros2_completion_20261006：verification_6ce560f.json、
verified_changed_imports_6ce560f.json、verified_ts_import_bytes_6ce560f.json、
verified_summary_6ce560f.json、colcon_query_6ce560f.json、
historical_hashes_before_6ce560f.json、inspected_combo_receipts_6ce560f.json
及verified_results_6ce560f/sha256_manifest.json；日志在log_combo_6ce560f/
log_query_6ce560f，helper在主机临时目录。

README同步当前组合表，前99节正文保持，旧组合、局部资格及原始失败
按原源码保留。本轮不改消息schema、算法或IRL学习规则；IRL仅学习β且
默认关闭，执行仍为符号级FakeBackend。没有LLM、benchmark、完整演示、
物理仿真、实机/机器人示范或Jazzy验证；通过不证明整体加速、IRL收敛、
逆最优性或机器人效果。

### 11.101 Product 权重更新复用边属性（2026-10-07）

基线为26f1cf0424d23e30fb2d1ab0e8a37bc007465a48。仅改ProdAut.update_beta：
从edges(data=True)获取当前边属性，省去每边三次self[u][v]邻接查找。
仍先写graph['beta']，按原边顺序计算transition_cost + beta * soft_task_dist，
保留属性字典对象、其它字段与缺失属性/无效beta时的原异常及部分更新行为。
不增加参数验证或跨调用缓存，不改IRL、接受性、消息schema和其它方法。
源SHA从77cf0812e699381fc9b8e880469754ef83d368f6acf577105b7e839d1c34bf23
变为6e99f3f906f0402ddf355208420aa5005aa69aee2ed097bebde02164625c53d5。

WSL/Humble环境沿用11.100；两个完整相关测试文件在修改前按原XML固定
33项Product与24项discrete_plan，没有新增测试或改变filter/验收条件。
一次正式运行session65325沿原handle等待至实际exit0：**57 passed**，
0 errors/failures/skipped，pytest0.96秒、JUnit0.940秒，receipt5.19313363秒。
启动前核对三个生产模块的真实import/完整字节及两个测试的Git字节，
保存原命令、环境路径、stdout/stderr和receipt。先绑定模块再pytest.main，
输出未列pytest警告汇总，没有额外警告过滤。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_beta_update_26f1cf0.py
```

worker在隔离workspace调用pytest.main，参数为checkout完整路径的
test_product.py、test_discrete_plan.py和
--junitxml=/tmp/ltl_ros2_completion_20261006/beta_update_26f1cf0.xml。
静态helper session14824实际exit0：py_compile、安装的ament_flake8.main
API（--linelength 99分开传参）、ament_pep257.main与git diff --check通过。
首个静态命令误用python -m ament_flake8，无__main__而exit1；随后内联
入口探查遇PowerShell引号解析错误，未启动Linux检查。改为临时脚本读取
已安装API并调用。结果检查器首次在静态handle尚未结束时读取receipt而
FileNotFoundError；等待原handle终态后再次核对通过，没有重跑正式测试。

完整旧模块独立13格对照：空图、零/大/负beta、Fraction、NaN/Infinity、
None/字符串、重复更新后重新读取软距离，以及缺首个cost、后续distance、
同时缺字段的错误优先级。返回、错误类型/文本、部分权重、graph beta、
节点/边引用、TS与initial/accept/cycle/possible_states均保持。
三个手算场景gamma=1：beta=0选a环总代价2，beta=5选b环总代价5，再回到
beta=0恢复a环；旧新完整run字段、路径、动作及代价一致。四边计数探针
邻接查找12次变0；首次探针计数器未初始化而AttributeError，修正辅助
类后完整对照通过。此计数与对照不加入57项JUnit，不证明整体加速。

证据在/tmp/ltl_ros2_completion_20261006：beta_update_baseline_26f1cf0.py、
beta_update_26f1cf0.xml、beta_update_{run,imports,compare,static,inspected}_26f1cf0.json
及beta_update_run_26f1cf0.log，helper在主机临时目录；原工具失败诊断如上，
未另外保存失败尝试的独立stdout/receipt。最终XML SHA为
da35c42e68b0cc8d3037c8dbf1f6774d4e2087333f453e71b46dc81f594d9b0d。

README同步当前局部资格，前100节正文保持；11.100的683项组合仍按
6ce源码保留，本轮未重跑七包或推算新组合人口。IRL仍仅学习beta且默认
关闭，执行仍为符号级FakeBackend；未做LLM、benchmark、完整演示、
物理仿真、实机/机器人示范或Jazzy验证。

### 11.102 TS 维度名容器与来源/兄弟实例隔离（2026-10-07）

基线a152954be18540fa8552e7b8c542a23b36e1a638。配置加载器生成合法
ts_state_format=[维度名]，单维TSModel直接引用该列表，多维组合的每个
内部列表也共享来源；编辑成品会污染来源/兄弟，来源修改也污染已有成品。
修复仅用既有copy浅复制这两处格式容器，保留格式类型/形状与值；
显式build_full重新读取来源最新格式。节点、边、guard、initial、
算法、IRL与消息schema不变，不深拷贝其它图属性或嵌套任意对象。
源SHA从3b8c4f8ff2fc67be00a87d12dff750ac0229d047a5a0795af478f1fd6f159d44
变为786d6366a3d0eb880a185fca872a687dec4f2a3905ccdf042c56e97e0d2938fd。

新增真实state_models_from_ts配置的单维/双维两例，验证双向及兄弟隔离、
显式重建刷新、再次隔离与节点/边/initial不变。初稿RED session53031
实际exit1，2 failed/15 deselected；其列表比较把维度字符串拆成字符，
另有修改成品后错误要求恢复原值的未执行断言。修正预期后RED2实际exit1，
2 failed/15 deselected，来源实得['model_only']而非['region']，明确复现
共享列表污染；生产源码当时仍与Git基线完全相同。两次原XML/日志保留。

开始前从旧XML固定相关文件59项加新两例为61项。修复后一次完整GREEN
session59543沿原handle等待至实际exit0：**61 passed**，0 errors/failures/
skipped；TS17、configuration18、LTLPlanner26，pytest1.43秒、JUnit1.406秒，
测试子进程receipt4.761738248秒。五生产模块真实import/完整字节与测试SHA
记录，未改模块与基线Git字节一致；ltl2ba真实路径及原二进制SHA核对通过。
先绑定模块再pytest.main，无额外警告过滤，输出未列pytest警告汇总。
编译、源码和新测试flake8 --linelength 99、源码pep257、diff检查通过。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_ts_format_a152954.py \
  green 786d6366a3d0eb880a185fca872a687dec4f2a3905ccdf042c56e97e0d2938fd
```

worker在隔离workspace运行checkout绝对路径的test_ts.py、
test_transition_system.py、test_ltl_planner.py完整文件；XML位于
/tmp/ltl_ros2_completion_20261006/ts_format_green_a152954.xml，SHA为
e2c154a3cfe042195901e3c71360277c659880d37da55250cfcdbcf1911aac78。
同目录保存ts_format_{red,red2,green}_run_a152954.json/.log、三份imports
证明、三份XML、ts_format_population_a152954.json和ts_format_inspected_a152954.json。
根代理结果检查实际exit0，核对原始失败/人口/入口/新鲜度/源码/日志哈希；
只两处格式复制变化。helper位于主机临时目录，所有尝试按原版本分别计数。

README同步当前局部资格，前101节正文保持；57项权重更新资格按a152源码、
683项组合按6ce源码保留，本轮未重跑七包或推算新组合人口。验证为
WSL Ubuntu-22.04-D/ROS2 Humble符号级；未做LLM、benchmark、完整演示、
物理仿真、实机/机器人示范或Jazzy验证，不作为整体加速或IRL科学效果证据。

### 11.103 权重更新与维度名隔离后的七包组合资格（2026-10-07）

资格源码为干净0b6b7ebf604a2acfea04c6ce2b82e771011ac258，包含11.101–11.102
的两个生产改动。开始前核对相对6ce仅两生产文件、一测试和两文档变化，
新增TS格式隔离的单维/双维两例，固定七包、六份JUnit的685项及4项既有
copyright跳过。保留默认并行、domain、timeout、max_steps与原验收条件。
WSL Ubuntu-22.04-D/ROS2 Humble/Python3.10.12/NetworkX2.4及原生ltl2ba路径
和完整二进制SHA核对通过，聚合六个exec_depend完整。

既有隔离build/install下构建与测试各一次：build session37422、test
session88762沿原handle等待至实际exit0，receipt elapsed分别47.323844525秒
与84.698237344秒。主代理观察到build wrapper/colcon PID37236/37249和test
wrapper/colcon PID37662/37683，终态仍由原handle与receipt/log核对；没有
替代运行。构建后18项源码import及生成消息路径通过；16完整生产模块及
独立TS补证合计17模块，均与Git字节匹配，包含两个最新改动。

```bash
source /opt/ros/humble/setup.bash
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_combo_0b6b7eb build \
  --executor sequential \
  --base-paths /mnt/d/Robotics/Robotics4LLM/ltl_automaton_core-ros2 \
  --build-base /tmp/ltl_ros2_completion_20261006/build \
  --install-base /tmp/ltl_ros2_completion_20261006/install \
  --symlink-install --packages-up-to ltl_automaton_core \
  --cmake-args -DBUILD_TESTING=ON
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_combo_0b6b7eb test \
  --build-base /tmp/ltl_ros2_completion_20261006/build \
  --install-base /tmp/ltl_ros2_completion_20261006/install \
  --packages-select ltl_automaton_core ltl_automaton_msgs \
  ltl_automaton_planner_core ltl_automaton_planner ltl_automaton_execution \
  ltl_automaton_hil_mic ltl_automaton_std_transition_systems \
  --return-code-on-test-failure
colcon --log-base /tmp/ltl_ros2_completion_20261006/log_query_0b6b7eb test-result \
  --test-result-base /tmp/ltl_ros2_completion_20261006/build --verbose
```

六份新鲜JUnit：**685 tests = 681 passed + 4 skipped**，0 errors/failures。
msgs11/0skip、core195/1、planner168/1、execution143/0、HIL119/1、std49/1。
四项跳过均为既有copyright；接口CTest wrapper另1项通过，查询686tests，
0 errors/failures、4 skipped；18份历史CTest XML按测试开始时间排除。
两例维度名隔离和update_beta入口均执行，原单维initial/frozenset快照、
IRL插件/真实β偏好/完整二十步/overflow/commit、HIL十二项Future、driver、
Trap/monitor、snapshot/服务复制、resolver/timeout、四个DDS、Studio/fallback、
原生translator/POSIX、参数、launch与lint通过。聚合内部和局部对照不加总。
五包stderr各923bytes，保留np.int/SelectableGroups依赖弃用警告，未见
未读取Future异常诊断；上述时间只记录该次运行，不作为加速比较。

先前6ce的87文件闭包及1058份选定历史hash前后均保持；本轮新XML、receipt、
imports/TS补证和完整TS源码、完整常规colcon日志另冻结为87文件闭包。
query、collector、独立audit与receipt检查各一次实际exit0；核对完整
人口、要求入口、新鲜度、source/日志字节、时序、历史及闭包哈希。
证据在/tmp/ltl_ros2_completion_20261006：verification_0b6b7eb.json、
verified_changed_imports_0b6b7eb.json、verified_ts_import_bytes_0b6b7eb.json、
verified_summary_0b6b7eb.json、colcon_query_0b6b7eb.json、
historical_hashes_before_0b6b7eb.json、inspected_combo_receipts_0b6b7eb.json
及verified_results_0b6b7eb/sha256_manifest.json，日志在log_combo_0b6b7eb/
log_query_0b6b7eb，helper在主机临时目录。

README改为当前组合表，前102节正文保持，旧组合/局部资格/原始失败按
原源码保留；57/61项局部运行不再叠加。IRL仍仅学习β且默认关闭，执行仍
为符号级FakeBackend；未做LLM、benchmark、完整演示、物理仿真、实机/
机器人示范或Jazzy验证，不证明整体加速、IRL收敛、逆最优性或机器人效果。

### 11.104 历史重规划省去尾部列表副本（2026-10-07）

基线af8bb38782679a86b3e0e2f089b190a070df68e1。唯一生产改动为
discrete_plan.py引入islice，并将prod_states_given_history的trace[1:]
替换为islice(trace, 1, None)。仓内唯一生产调用LTLPlanner.replan已
传入新建列表；空/单节点、来源标签、后继筛选、逐项次序、gamma及
规划目标保持，不增加提前返回或跨调用缓存。输入应为调用期间稳定的
可索引序列；惰性遍历不承诺外部同时修改历史时的切片快照行为，亦不
新增generator输入支持。

从Git加载完整旧discrete_plan.py，与实际导入的新模块独立对照：
两个手工图分别覆盖单初态和多初态/非确定性后继，各十二种历史再分别
使用list与tuple，共48组；空、未知初态、不合法跳转、分支收敛、循环
及4097状态长历史均与手算预期一致。输入、图节点/边和Büchi初态保持。
另一个list子类计数探针尾部切片从1次变0，不加入JUnit，不测量耗时、
RSS或端到端加速。

在既有WSL Ubuntu-22.04-D/ROS2 Humble overlay中，一次正式运行
session60191沿原handle等待至实际exit0：**50 passed**，0 failures/
errors/skipped；两个完整未修改文件为discrete_plan24项、LTLPlanner26项，
pytest1.78秒，含对照/lint的worker receipt9.964176289秒。六个生产模块
的真实import与完整字节核对通过，未改模块及两个测试与Git基线一致；
原生ltl2ba路径及既有二进制SHA保持。源码编译、ament_flake8.main
--linelength 99、ament_pep257.main及git diff --check通过。lint保留
--max-complexity的既有optparse弃用提示，没有额外警告过滤。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_history_slice_af8bb38.py
```

证据在/tmp/ltl_ros2_completion_20261006：history_slice_af8bb38.xml、
history_slice_af8bb38_{baseline.py,proof.json,run.json,run.log}；helper在主机
临时目录。新源码SHA为82413a403a1fcf6b8b10c72ef5cdcc9cc3e946c999c82a58ce9596380532ca9d，
XML SHA为74d14cd090541faf324756f47ca5407ea3df8d656eed60cd335cda44df629b6e。
README区分当前局部资格与11.103的685项组合基线，前103节正文保持。
本轮未重跑七包、LLM、benchmark、完整演示、物理仿真、实机/机器人示范
或Jazzy验证；IRL仍仅学习beta且默认关闭。

### 11.105 旧重规划服务的候选/快照提交与有限代价（2026-10-07）

基线4e7cd929c4859da93f6630e260f3b72ac39132b4。旧/replanning回调直接
调用活动LTLPlanner.replan_task；核心成功时先替换自身run/Product/TS，
之后wrapper才准备快照。快照copy/IDs准备失败不在异常边界内，并且
旧服务没有Action/IRL已有的有限候选代价检查。

修复只修改此服务回调及copy导入：浅复制外层planner，在该对象调用
核心既有replan_task（内部继续一次深复制），不增加第二次整图深复制。
搜索、有限公开代价、快照和计划消息均先准备；快照提交准备成功后才
在锁内替换活动planner和TS。准备失败返回false、恢复ACTIVE，旧运行、
快照、ID映射、generation/step及TS引用保持。成功复用已准备消息，
发布顺序仍为possible_states、prefix/suffix、next_move、execution_observation，
保留发布日志；不修改核心目标、source-label、Action/IRL及状态恢复回调。

新增三项native回归：copy/ids两种可控快照准备失败，以及beta=1e308、
gamma=1.0的有限初始运行，改soft task为(missing1 && missing2)后产生
非有限代价。测试不修改算法或伪造run cost，失败后检查完整旧authority
引用/快照/身份与ACTIVE，再经真实TaskPlanning服务有效重试，generation
只增加1且step重置。首份草稿中重试soft task未恢复，主代理在任何运行
前纠正；RED/GREEN使用同一最终测试字节，没有按结果放宽预期。

生产字节仍为Git基线时，RED session27159实际exit1：**3 failed / 46
deselected**，pytest3.51秒、JUnit3.461秒、receipt11.077337952秒。
copy/ids分别泄漏Controlled snapshot准备RuntimeError；溢出用例旧服务
返回success=True。两种失败和原始日志/XML保留，不计为修复后通过。

开始前从冻结0b6的原XML固定90项（Action46、节点30、序列化14）加新3项
为93项。一次完整GREEN session31105沿原handle等待至实际exit0：
**93 passed**，0 errors/failures/skipped；Action49、节点30、序列化14。
pytest26.55秒、JUnit26.515秒、含lint的worker receipt37.586069558秒。
八个实际生产import/完整字节、生成消息路径、三个测试SHA及原生ltl2ba
二进制核对通过；未改模块与Git基线一致。源码/测试编译、ament_flake8.main
--linelength 99、ament_pep257.main、git diff --check通过，lint既有
optparse提示保留，没有额外警告过滤。这些时间不用于性能比较。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_legacy_task_4e7cd92.py \
  green c71109a3122b66f21233284992a537f3e18f79bcbd790c4bf7d5c1012a2f4f9f
```

证据在/tmp/ltl_ros2_completion_20261006：legacy_task_4e7cd92_population.json、
legacy_task_4e7cd92_{red,green}.xml、对应_{red,green}_{imports.json,run.json,run.log}
及legacy_task_4e7cd92_inspected.json；helper在主机临时目录。独立检查
实际exit0，核对原失败文本、人口、时序、新鲜度、完整import字节和日志哈希。
新源码SHA为c71109a3122b66f21233284992a537f3e18f79bcbd790c4bf7d5c1012a2f4f9f，
最终XML SHA为8a13f7c0a4e6cb3c2e74be6f8a746408fb41c79e21a06cfa7aacc45178aec1e2。
README同步服务契约和当前局部资格，前104节正文保持；11.103的685项
仍属于0b6源码基线，未重跑七包或推算新组合人口。IRL仍仅学习beta且默认
关闭；未做LLM、benchmark、物理仿真、实机/机器人示范或Jazzy验证。

### 11.106 意外状态恢复的候选/快照提交与观测保持（2026-10-07）

基线b524d8f3b5130d72c911dd575897660b4e5f7173。自动恢复回调直接调用活动
LTLPlanner.replan_from_ts_state；核心成功时先替换自身run/Product/TS，
wrapper随后才准备快照。快照copy/IDs准备失败会泄漏异常，自动恢复也缺少
Action/IRL/旧服务已有的有限候选代价检查。

唯一生产改动在_recover_from_ts_state：浅复制外层planner，在候选调用
核心既有恢复（内部继续一次深复制），不增加第二次整图深复制。搜索、有限
公开代价、快照及计划消息先准备；锁内先完成快照提交准备，再替换活动planner
和TS。准备失败返回false并恢复ACTIVE，原运行、图、快照、ID映射、
generation/step及活动TS引用保持。成功状态发布在提交异常边界之后；复用
已准备计划消息，possible_states、prefix/suffix、next_move、execution_observation
和plugins的发布/调用顺序保持。

观测事实与计划提交分开：_ts_state_callback已接收的canonical状态、revision
及时间戳保持最新；恢复失败不把实际观测的r3回滚为r1。replan_on_unplanned_move
为false时的既有belief分支字节保持。核心目标、source-label、接受性、IRL、
Action、服务、参数及其余生产方法保持。

新增三项native回归：copy/ids两种可控快照准备失败，以及合法有限动作权重
1e308的r3→r4→r2两边恢复路径。后者保留正常初始运行，真实计算候选代价，
不伪造run cost。失败检查旧authority引用/快照/身份与ACTIVE，同时检查
canonical=r3、revision加1及原始反馈时间戳。移除快照故障后直接调用native
恢复；溢出场景先接收另一条生成的r2反馈再直接恢复，成功代价有限、generation
只增加1、step为0。这里的恢复重试为直接方法调用，不称为DDS重试。

既有延迟恢复用例的计数补丁在任何运行前从旧planner实例移至类方法，调用
原始非绑定方法，覆盖隔离候选；原请求、同步条件、期限及调用次数保持。
同时要求恢复后的新planner与原对象不同、旧对象仍在r1。这一条修改既有用例
不增加测试人口。主代理在运行前去除测试中多余的时间戳/状态赋值，改用生成
反馈维护观测；RED与GREEN使用同一冻结测试SHA，没有按结果放宽预期。

生产仍为Git基线时，RED session54088沿原handle等待至实际exit1：
**4 failed / 48 deselected**，pytest3.47秒、JUnit3.434秒、receipt10.309644303秒。
copy/ids泄漏Controlled snapshot准备RuntimeError；溢出用例替换了原run，
延迟恢复仍复用原planner对象。原始失败日志/XML保留，不计为修复后通过。

开始前固定11.105原XML的93项（Action49、节点30、序列化14），加新3项为96。
一次完整GREEN session50523沿原handle等待至实际exit0：**96 passed**，
0 errors/failures/skipped；Action52、节点30、序列化14。pytest26.85秒、
JUnit26.805秒、含lint的worker receipt37.209725057秒。八个实际生产import
与完整字节、生成消息路径、三个测试SHA及原生ltl2ba二进制核对通过；未改
模块与Git基线一致。源码/测试编译、ament_flake8.main --linelength 99、
ament_pep257.main及git diff --check通过，保留lint既有optparse提示，没有
额外警告过滤。这些时间不用于性能比较。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_state_recovery_b524d8f.py \
  green 7f428d591b11415f6b47d1d2a02b355ac83fa40ef8379b4f0213156dfb752d3e
```

证据在/tmp/ltl_ros2_completion_20261006：state_recovery_b524d8f_population.json、
state_recovery_b524d8f_{red,green}.xml、对应_{red,green}_{imports.json,run.json,run.log}
及state_recovery_b524d8f_inspected.json；helper在主机临时目录。独立检查实际
exit0，核对原失败文本、人口、时序、新鲜度、完整import字节和日志哈希。
额外只读scope检查位于主机临时目录state_recovery_scope_b524d8f.json，确认
其余方法/测试及模块级非函数AST不变、禁用自动恢复分支字节不变。
首次文档检查helper错误地把旧try行纳入分支切片，实际exit1；修正切片边界，
保留初稿helper和失败输出，未改生产/测试字节或重跑GREEN。
旧源码SHA为c71109a3122b66f21233284992a537f3e18f79bcbd790c4bf7d5c1012a2f4f9f，
新源码SHA为7f428d591b11415f6b47d1d2a02b355ac83fa40ef8379b4f0213156dfb752d3e；
最终XML SHA为916af565c037e784a84c746f40ae1edb8b7758f34966661049ed1022e6fda78a。
README同步自动恢复契约和当前局部资格，前105节正文保持；11.103的685项
仍属于0b6源码基线，未重跑七包或推算新组合人口。IRL仍仅学习beta且默认
关闭；未做LLM、benchmark、完整演示、物理仿真、实机/机器人示范或Jazzy验证。

### 11.107 近期重规划改动的七包组合资格（2026-10-07）

资格源码917c4cc8c4f6ed9e5fcdaa14d476e8cc96e4b652。本轮在既有隔离WSL
Ubuntu-22.04-D/ROS2 Humble、Python3.10.12、NetworkX2.4环境运行；原生
ltl2ba路径/home/yuhling/.local/bin/ltl2ba及SHA保持。启动前核对干净
HEAD、包列表、环境和近期两个生产模块/Action测试完整Git字节及SHA。
人口从11.103的685项加11.105/11.106各3项新回归固定为691，planner174；
既有延迟恢复用例的修改不增加人口。required cases在观察结果前固定，未按
结果缩减测试或调整配置、期限、验收条件。

唯一七包构建session88111沿原handle等待至实际exit0，receipt47.507938646秒。
唯一默认并行完整测试session25292沿原handle等待至实际exit0，receipt
91.177000534秒；主代理在运行中读/proc确认build wrapper/colcon PID47177/
47190与test wrapper/colcon PID47627/47648，未启动替代运行。保存完整原命令、
起止时序、stdout/stderr及terminal receipt。构建仍为sequential、symlink-install、
packages-up-to ltl_automaton_core、BUILD_TESTING=ON；测试不设置sequential或
单独pytest参数，七包保持默认并行和return-code-on-test-failure。

六份新鲜JUnit：**691 tests = 687 passed + 4 skipped**，0 errors/failures。
msgs11/11/0、core195/194/1、planner174/173/1、execution143/143/0、
HIL119/118/1、std TS49/48/1（tests/passed/skipped）。四项跳过均为既有
copyright。接口CTest wrapper另有1项通过，实际隔离build的colcon查询为
692 tests；19份历史CTest XML按测试开始时间排除，旧结果不计入新人口。
query、collector、独立audit和receipt检查均实际exit0。

历史遍历、旧服务与状态恢复的六项新事务回归、既有延迟恢复及两个Core
history用例明确执行。四个真实DDS执行场景、Studio consumer、IRL完整二十步/
β偏好/overflow/commit、HIL十二项Future及其余查询/状态恢复、driver、
Trap/monitor、snapshot/服务复制、resolver/timeout、参数、launch、原生
ltl2ba/POSIX及lint同时通过。局部50/93/96项、聚合内部检查和独立旧新对照
均不重复计入本轮JUnit。

构建后、测试前再次核对18条源码import路径及生成消息路径；主gate为17个
完整生产模块，新加入discrete_plan，另有TS完整字节补证，合计18模块与Git
资格字节一致。八十七文件的新冻结结果/receipt/import/完整日志闭包通过
SHA核对，1177份历史哈希保持，包括0b6闭包与后来三个局部阶段的原始证据。
五包stderr各923字节，保留np.int/SelectableGroups依赖弃用警告；本次日志
未见未读取Future异常诊断。没有以空stderr或警告过滤冒充通过。

临时helper在任何正式运行前经主代理审阅，修正历史manifest锚点与模块数
断言，并补齐人口来源、源码/测试SHA和历史闭包87项检查；未因此产生新的
build/test失败或改变生产/测试字节。本轮仓库只更新README与本节，前106节
正文、原始失败与版本资格保持。

```bash
source /opt/ros/humble/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/snapshot_history_before_917c4cc.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/prepare_full_package_verification_917c4cc.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/run_build_917c4cc.py
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/verify_changed_imports_917c4cc.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/verify_ts_import_bytes_917c4cc.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/start_full_package_tests_917c4cc.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/run_test_917c4cc.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/query_full_results_917c4cc.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/check_full_package_results_917c4cc.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/audit_full_results_917c4cc.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/inspect_combo_receipts_917c4cc.py
```

证据位于/tmp/ltl_ros2_completion_20261006：verification_917c4cc.json、
verified_changed_imports_917c4cc.json、verified_ts_import_bytes_917c4cc.json、
verified_summary_917c4cc.json、colcon_query_917c4cc.json、
historical_hashes_before_917c4cc.json、inspected_combo_receipts_917c4cc.json
及verified_results_917c4cc/sha256_manifest.json；原始日志在log_combo_917c4cc/
log_query_917c4cc，helper在主机临时目录。IRL仍仅学习β且默认关闭，执行
仍为符号级FakeBackend；未做LLM、benchmark、完整演示、物理仿真、实机/
机器人示范或Jazzy验证，不证明整体加速、IRL收敛、逆最优性或机器人效果。

### 11.108 启动规划的准备/提交与有限代价（2026-10-07）

基线77bf3ca9fbc6a4c57ca86ee4dadfede5bc082050，生产与11.107资格917c4cc
相同。原_initialize_planner只捕获搜索异常，快照copy/IDs和计划消息准备
位于异常边界之外；活动planner/canonical先于快照提交安装，也缺少已有
模块级_validate_candidate_run_costs检查。

唯一生产改动在_initialize_planner：新建候选继续原static搜索，保留无接受
运行的独立诊断；有限公开代价、canonical、快照及共享时间戳的计划消息
均先准备。锁内先完成既有原子快照提交，再安装planner/canonical。准备
失败返回false并恢复READY，保留有效TS/yaml/hash，无活动计划、快照、IDs、
canonical或generation增加。agent分支仍按原行为重建有效TS，不要求保留
原TS对象引用。成功ACTIVE发布在提交异常边界之外，原possible_states、
plugins、成功/动作日志、prefix/suffix、next_move、execution_observation
顺序和发布日志保持，复用已准备消息。加载/初态/缺参数分支、其余37个
生产方法及方法外完整内容保持；不修改核心目标、source-label或接受性。

新增八项native回归：快照copy、ID映射及计划消息三类可控准备异常，各
覆盖direct和agent；另两项以有限beta=1e308、gamma=1.0、soft任务
(missing1 && missing2)真实计算溢出，未伪造run cost。使用真实LoadTS服务，
agent通过生成的r1反馈调用原_ts_state_callback。失败后检查完整初始
authority、READY、等待状态/时间戳和未初始化插件；移除故障或仅改soft
为恒真任务后直接初始化/再次生成反馈，成功代价有限、generation=1、step=0。
此处agent反馈为native callback，不称为DDS重试。

测试草案在任何运行前修正任务配置、重复fixture、agent重建TS身份预期及
时间戳格式；默认fixture仍使用原构造参数，旧21个函数字节保持。RED和
两次完整验证使用同一冻结测试SHA，未按结果修改预期或缩减人口。
基线生产完整Git字节下RED session10732沿原handle至实际exit1：
**8 failed / 30 deselected**，pytest2.80秒、JUnit2.762秒、receipt8.850753322秒。
copy/ids/plans异常泄漏；direct溢出返回true，agent溢出进入ACTIVE。

首次完整修复验证session32724实际exit1：**8 failed / 96 passed**，pytest
25.38秒、JUnit25.349秒、receipt30.662648252秒。主代理方案错误地把已有
模块级检查函数接成self方法，所有有效重试被拒绝。完整候选源码、原命令、
import、XML、日志与receipt保留，未将这次运行标为通过。仅更正该调用，
测试、配置、期限及验收条件不变。

观察结果前由11.107冻结原XML的96项（Action52、节点30、序列化14）加八项
固定为104。最终完整验证session23973沿原handle至实际exit0：**104 passed**，
0 errors/failures/skipped；节点38、Action52、序列化14。pytest26.05秒、
JUnit26.016秒、含lint的receipt35.538960137秒。八个实际生产import完整字节、
生成消息路径、三个测试SHA及原生ltl2ba核对通过；其余模块与Git基线一致。
源码/测试编译、ament_flake8.main --linelength 99、ament_pep257.main及
git diff --check通过，保留lint既有optparse提示，没有额外警告过滤。
独立检查实际exit0，核对全部三次原始时序、新鲜度、失败文本、人口、完整
导入字节和日志哈希。这些时间不用于性能比较。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_startup_77bf3ca_retry1.py \
  green 17d2ac337ef85e6a41a68a731d5bf091dd0e7e3357394b1054b7d3b3917a2a07
```

证据在/tmp/ltl_ros2_completion_20261006：startup_77bf3ca_population.json、
startup_77bf3ca_{red,green}.xml及对应_{red,green}_{imports.json,run.json,run.log}、
startup_77bf3ca_failed_planner_node.py、startup_77bf3ca_retry1_green.xml及其
_{imports.json,run.json,run.log}、startup_77bf3ca_inspected.json；helper在主机
临时目录。旧源码SHA为7f428d591b11415f6b47d1d2a02b355ac83fa40ef8379b4f0213156dfb752d3e，
首次候选SHA为9a4c712993c4b9695c7d165dea76de6c61ea0ff9405a26665e4823f25daeb800，
最终源码SHA为17d2ac337ef85e6a41a68a731d5bf091dd0e7e3357394b1054b7d3b3917a2a07，
冻结测试SHA为0e3a23b5d42d6870e8614f42c5d3a485189d8daac8d3266758e63fcce04bd6ae，
最终XML SHA为68b497410a0022e13f961a0205a1c4919622e85426ab034cf9d28ced86f103f1。
首次文档helper错误将新文本写为CRLF，diff检查实际exit2；更正为原LF，
保留初稿helper及文档字节，生产/测试字节和验证结果未改，未重跑测试。
README同步启动契约及当前局部资格，前107节正文保持。11.107的691项仍
属于源码917c4cc七包基线，本轮未重跑七包或推算新组合结果。IRL仍仅学习β且
默认关闭；未做LLM、benchmark、完整演示、物理仿真、实机/机器人示范或Jazzy验证。

### 11.109 启动规划修复的七包组合资格（2026-10-07）

资格源码02d426f17e1629ab3b22c53f0bd07b415b450a3a。本轮复用既有WSL
Ubuntu-22.04-D/ROS2 Humble、Python3.10.12、NetworkX2.4与原生ltl2ba，
没有安装或更换依赖。启动前核对干净HEAD、七包列表、近期生产与测试完整
Git字节/SHA及历史冻结闭包；人口由11.107的691项加11.108八项启动回归
固定为699（planner182），required cases在结果前固定。direct/agent的
copy、IDs、plans和真实代价溢出参数组合均核对，没有缩减期限或验收条件。
资格脚本草案的历史引用/长度及人口推导在任何本轮构建或测试前纠正，
保留初稿；最终十二个资格入口静态编译通过，原版本helper与证据未覆盖。

七包构建session69103及默认并行完整测试session57321各执行一次，沿各自原handle至实际exit0；
完整命令、起止时序与stdout/stderr保留。build receipt为
45.753871134秒，test receipt为87.378641092秒。
构建保持sequential/symlink-install/packages-up-to ltl_automaton_core及
BUILD_TESTING=ON；测试保持默认并行、七包select和return-code-on-test-failure。
主代理在运行中读取/proc确认实际wrapper/colcon进程，没有以marker推断存活
或因观察超时启动替代运行；build PID54788/54810，test PID55249/55270。
这些时间不用于性能比较。

六份新鲜JUnit：**699 tests = 695 passed + 4 skipped**，0 errors/failures。
msgs11/11/0、core195/194/1、planner182/181/1、execution143/143/0、
HIL119/118/1、std TS49/48/1（tests/passed/skipped）。四项跳过均为既有
copyright；接口CTest wrapper另有1项通过，实际隔离build查询为700 tests。
20份历史CTest XML按测试开始时间排除，旧结果不计入新人口。
query、collector、独立audit和receipt检查均实际exit0。

启动八项、旧服务/状态恢复六项事务回归、延迟恢复和两个Core history用例
均执行。四个真实DDS场景、Studio consumer、IRL完整二十步/β偏好/溢出/
事务提交、HIL十二项Future、driver、Trap/monitor、快照与服务隔离、resolver/
timeout、参数、launch、原生ltl2ba/POSIX及lint同时覆盖。104及此前各版局部
资格不重复加入人口；11.108原RED、首次修复失败和最终通过均按原源码保留。

17个主gate生产模块加TS补证共18个完整模块字节与Git资格提交相同，生成
消息路径和原生译器SHA核对通过；新冻结闭包87文件、历史1286份SHA
保持。完整stderr保留依赖弃用提示，未发现未读取Future异常诊断，未过滤warning。
生产代码与测试本轮未改，README同步当前组合表和历史范围，前108节正文保持。

```bash
source /opt/ros/humble/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/snapshot_history_before_02d426f.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/prepare_full_package_verification_02d426f.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/run_build_02d426f.py
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/verify_changed_imports_02d426f.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/verify_ts_import_bytes_02d426f.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/start_full_package_tests_02d426f.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/run_test_02d426f.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/query_full_results_02d426f.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/check_full_package_results_02d426f.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/audit_full_results_02d426f.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/inspect_combo_receipts_02d426f.py
```

证据位于/tmp/ltl_ros2_completion_20261006：verification_02d426f.json、
verified_changed_imports_02d426f.json、verified_ts_import_bytes_02d426f.json、
verified_summary_02d426f.json、colcon_query_02d426f.json、
historical_hashes_before_02d426f.json、inspected_combo_receipts_02d426f.json及
verified_results_02d426f/sha256_manifest.json；原始日志在log_combo_02d426f/
log_query_02d426f，helper在主机临时目录。IRL仍仅学习β且默认关闭，执行仍
为符号级FakeBackend。未做LLM、benchmark、完整演示、物理仿真、实机/
机器人示范或Jazzy验证，不证明整体加速、IRL收敛、逆最优性或机器人效果。

### 11.110 Action 与 IRL 成功消息的提交前准备（2026-10-07）

基线5e61d4a1dad464f9d8175715fa869288d8ad5525。原共享提交方法在替换活动
计划后才准备计划消息和成功Result；这两类准备异常导致Action被rclpy中止并
返回默认ERROR_NONE，或从IRL executor回调泄漏，新计划却已经提交。
仅修改_commit_plan_ltl_candidate：原新鲜度谓词通过后，在现有锁及提交
try边界内先准备时间戳、计划消息、完整成功结果，再提交快照和planner/TS。
准备失败使用既有ERROR_INTERNAL恢复路径，保留旧权威并释放事务；发布仍在
提交之后，其顺序保持。其他37个生产方法、核心代价/接受性及IRL规则未改。

新增六项原生回归：action_ready/action_active/irl分别组合plans/result。
LoadTS、PlanLTL、快照服务和候选规划均为真实接口/实现；ACTIVE与IRL用DDS
反馈推进旧step到1。IRL沿用既有注入learn_beta返回β+7并执行真实候选重规划，
不将注入视为真实学习测量。plans仅注入当前节点方法；result保留生成类，
其planning_time默认0.0使用原setter，仅非零值触发准备故障，失败结果可正常
构造及传输。每项检查旧planner/run/Product、β/weights、TS/YAML/hash、
snapshot/IDs、instance/generation/step、canonical与事务字段，并在解除
故障后验证有效原生重试generation+1、step=0。Action返回ABORTED/
ERROR_INTERNAL；IRL保留ACTIVE和旧β。已有55个测试函数正文保持。

人口在结果前由11.109冻结XML固定为104+6=110，三个文件Action58、节点38、
序列化14，collection hook核对全部名称；测试完整SHA在RED/GREEN间不变。
首次辅助脚本使用pytest6不支持的item.path，session44499在收集阶段停止，
Python receipt exit3、JUnit仅含一条internal error，未执行回归。只将helper
改为item.fspath并另存retry1；原helper、日志/XML/receipt和人口清单均保留，
两份人口JSON相同，生产源码和测试均未因收集错误修改。

原Git生产字节上的RED session33876实际exit1：**6 failed / 52 deselected**，
四项Action默认错误码与两项IRL受控异常均核对。单次生产修复后的GREEN
session84131沿原handle至实际exit0：**110 passed**，0 errors/failures/skipped。
pytest29.87秒，JUnit29.841秒，receipt38.949717397秒；不用于性能比较。
源码和测试编译、flake8、pep257及diff检查通过，保留lint既有optparse提示。
八个实际生产import完整字节、生成消息路径及原生ltl2ba SHA核对；独立receipt
检查exit0，并确认新鲜度谓词、成功发布顺序及其他方法不变。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_payload_5e61d4a_retry1.py red 17d2ac337ef85e6a41a68a731d5bf091dd0e7e3357394b1054b7d3b3917a2a07
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_payload_5e61d4a_retry1.py green aa6c5dd384638cee38b5019c035a0ee3b73ee4fb319414052751f7aa5090f0b6
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/inspect_payload_5e61d4a.py aa6c5dd384638cee38b5019c035a0ee3b73ee4fb319414052751f7aa5090f0b6 a552f57541c9c1bbe6154be55963fed76ebf6b6286e92bc27aaa753bc50d63d9
```

证据位于/tmp/ltl_ros2_completion_20261006：payload_5e61d4a和
payload_5e61d4a_retry1的_population.json、_red.xml/_red_imports.json/
_red_run.json/_red_run.log，以及retry1的对应green文件和_inspected.json。
当前源码SHA为aa6c5dd384638cee38b5019c035a0ee3b73ee4fb319414052751f7aa5090f0b6，
Action测试SHA为a552f57541c9c1bbe6154be55963fed76ebf6b6286e92bc27aaa753bc50d63d9。
README同步当前局部范围，前109节正文与原始失败保留。未重跑七包，699项仍
属于02d426f组合基线，局部110项不相加；IRL仅学习β且默认关闭，执行仍为
符号级FakeBackend，未运行LLM、benchmark、物理仿真、实机或Jazzy验证。

### 11.111 Action/IRL 消息准备修复的七包组合资格（2026-10-07）

资格源码d5f2faa28837bfe8d077e7af1492bc0d5ff59f0e。复用既有WSL Ubuntu-22.04-D/ROS2 Humble、
Python3.10.12、NetworkX2.4与原生ltl2ba，未安装或更换依赖。启动前核对
干净HEAD、七包列表、近期源码/测试完整Git字节及历史冻结闭包。人口由
11.109的699项加11.110六项消息准备回归固定为705（planner188）；
六个plans/result × action_ready/action_active/irl参数名、八个startup参数名
及required cases均在结果前固定。准备helper的旧HEAD引用在运行前纠正，
保留草案，旧helper与原始失败未覆盖；十二个最终入口静态编译通过。

七包构建session97855与默认并行完整测试session7350各执行一次，沿各自原
handle至实际exit0。完整命令、stdout/stderr和起止receipt保留；build为
37.853319897秒，test为74.570586708秒，不用于性能比较。
构建保持sequential/symlink-install/packages-up-to ltl_automaton_core及
BUILD_TESTING=ON；测试保持默认并行、七包select与return-code-on-test-failure。
/proc确认实际wrapper/colcon：build PID60397/60410，test PID60875/60909，
没有以marker推断进程存活或因观察超时启动替代运行。

六份新鲜JUnit：**705 tests = 701 passed + 4 skipped**，0 errors/failures。
msgs11/11/0、core195/194/1、planner188/187/1、execution143/143/0、
HIL119/118/1、std TS49/48/1（tests/passed/skipped）。四项跳过均为既有
copyright；接口CTest wrapper另有1项通过，实际隔离build查询为706 tests。
21份历史CTest XML按开始时间排除，旧结果未计入新人口。query、collector、
独立audit与receipt检查均实际exit0。

六项payload、八项startup、旧服务/状态恢复六项事务回归、延迟恢复与两个
Core history均执行。四个真实DDS、Studio consumer、IRL完整二十步/β偏好/
溢出/事务提交、HIL十二项Future、driver、Trap/monitor、snapshot/服务隔离、
resolver/timeout、参数、launch、原生ltl2ba/POSIX/lint同时覆盖。110及此前
各版局部资格不重复相加；11.110原收集错误与旧代码RED仍按原源码保留。

17个主gate模块加TS补证共18个完整生产模块字节与资格Git提交一致，生成
消息路径和原生译器SHA核对通过。新冻结闭包87文件、历史1392份SHA保持。
五包stderr各923bytes，保留np.int/SelectableGroups弃用提示；未发现未读取
Future异常诊断，未过滤warning。生产代码与测试本轮未改，README同步当前
组合表和历史范围，前110节正文完整保留。

```bash
source /opt/ros/humble/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/snapshot_history_before_d5f2faa.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/prepare_full_package_verification_d5f2faa.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/run_build_d5f2faa.py
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/verify_changed_imports_d5f2faa.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/verify_ts_import_bytes_d5f2faa.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/start_full_package_tests_d5f2faa.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/run_test_d5f2faa.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/query_full_results_d5f2faa.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/check_full_package_results_d5f2faa.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/audit_full_results_d5f2faa.py
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/inspect_combo_receipts_d5f2faa.py
```

证据位于/tmp/ltl_ros2_completion_20261006：verification_d5f2faa.json、
verified_changed_imports_d5f2faa.json、verified_ts_import_bytes_d5f2faa.json、
verified_summary_d5f2faa.json、colcon_query_d5f2faa.json、
historical_hashes_before_d5f2faa.json、inspected_combo_receipts_d5f2faa.json及
verified_results_d5f2faa/sha256_manifest.json；原始日志在log_combo_d5f2faa/
log_query_d5f2faa，helper在主机临时目录。IRL仍仅学习β且默认关闭，执行仍
为符号级FakeBackend。未做LLM、benchmark、完整演示、物理仿真、实机/
机器人示范或Jazzy验证，不证明整体加速、IRL收敛、逆最优性或机器人效果。

### 11.112 IRL 无匹配反馈后的记录恢复（2026-10-07）

基线dd51014cfe3820f38016e77ef67df9d22834c814。原插件在示范无法延伸到
Product 后继时清空 possible_runs，却保持 learning_trigger=True；后续合法
反馈仍无法延伸空集合。仅在原空集合分支增加 learning_trigger=False，保留
原 warning/return，停止该次记录且不请求空学习。再次发送 True 从当前有效
Product belief 开始新记录；可直接 True 或先 False 再 True。后续非记录状态
的反馈及单独 False 不请求学习，不自动将旧前缀接到新示范。

新增一个 fake-host 回归，含两种重启流程。检查空集合、记录标志、无空学习/
无空诊断发布、仅一次新示范提交，以及 Product 边、belief、宿主实例、代次
和状态保持。旧测试 AST 完整保持；核心 β 学习规则、默认关闭、接口未改。
人口在运行前固定为旧 fake-host 5 + 新回归 1 + 原真实 ROS preference 1 +
optional safety 2 = 9；测试完整 SHA 在各次尝试及 RED/GREEN 之间不变。

原 helper session65505 在收集阶段 exit3，launch-testing 将文件转换为
LaunchTestModule，指定用例未收集；retry1 关闭 launch_testing 后仍因
launch_ros 依赖的 hook 无注册而 exit3，未执行用例。原日志/XML/receipt
均保留。retry2 同时关闭两个收集插件，沿用原人口和测试，不修改验收条件。
原生产 Git 字节上的 RED 实际 exit1：**1 failed**，失败断言为候选清空后
记录标志仍 True。一次生产修复后的 GREEN session98974 沿原 handle 至
实际 exit0：**9 passed**，0 errors/failures/skipped；pytest2.64秒，
receipt11.689448731秒，不用于性能比较。无匹配恢复由 fake-host 检查；
既有 preference 用真实 ROS 接口、原生学习及重规划，未新增无匹配 DDS 场景。

源码/测试编译、flake8、pep257、diff检查通过。11个实际生产 import 完整
字节、生成消息路径及原生 ltl2ba SHA 核对；独立 receipt/scope 检查 exit0。
关闭收集插件产生的 UnknownMarkWarning 和 lint optparse 提示均保留。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_recording_dd51014_retry2.py red f0f01ffbe90c7fe95c45b71f83e387a92c1b004222f50d932f338670800c4857
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_recording_dd51014_retry2.py green 1a323b80576da2fa556e73964096f7bec677ccd4c40b15f7eb1f2316d9b8d5be
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/inspect_recording_dd51014.py
```

证据位于/tmp/ltl_ros2_completion_20261006：recording_dd51014_population.json、
recording_dd51014[_retry1/_retry2] 的 red.xml/red_imports.json/red_run.json/
red_run.log，retry2 对应 green 文件及 recording_dd51014_inspected.json。
当前源码 SHA 为1a323b80576da2fa556e73964096f7bec677ccd4c40b15f7eb1f2316d9b8d5be，
测试 SHA 为fca325f76a7355678a1c4fccea894d0ccf791c7c1a8cdf09dd391feec536fb70。
两份 README 同步恢复约定；前111节正文和原失败记录保留。未重跑七包，
705项仍属于d5f2faa组合源码，9项局部结果不相加。未做LLM、benchmark、
物理仿真、实机或Jazzy验证，不据此宣称IRL收敛或机器人示范效果。

### 11.113 IRL 单元测试与 launch 收集入口拆分（2026-10-07）

基线9d51dfb7436e5956d36910fa5ec33d1da2748f0c。11.112已经记录默认
launch-testing 将混合文件转换成 LaunchTestModule、无法直接选择单元类的
收集失败，本轮核对该日志 SHA 和当时测试 SHA 与基线相符，不重复运行失败。
将完整 fake-host helpers 和六个单元方法移至 test_irl_plugin_unit.py；
原 test_irl_plugin.py 保留 HUB fixture、launch 入口和唯一 DDS 方法。
移除原文件未用 imports，仅更新模块说明；测试正文原始字节保持，未新增
测试函数、依赖或共享 helper 模块。拆分草案中残留的重复单元类在运行前
核对并移除；最终两个文件从 Git 基线原始字节构造，实际验证未运行草案。

运行前固定六个单元方法、原 launch 的一个 DDS 方法、原 preference 一个
方法与 safety 两个方法。默认 launch_testing 和 launch_ros 均启用，直接
选择新文件的 TestIRLPluginFakeHost，同时执行其余三个完整文件；收集钩子
在用例执行前核对全部十个 pytest 名称，以及 launch loader 的精确 DDS
方法 test_real_action_and_irl_commit_contract，避免残留或遗漏单元类。

单次运行 session30224 沿原 handle 至实际 exit0：**10 passed**，
0 errors/failures/skipped，单元6、launch item1、preference1、safety2。
launch 的一个 pre-shutdown DDS 方法实际执行，post-shutdown 没有测试；
不把内部方法与外层 pytest item 重复计数。pytest3.46秒，receipt
10.432461725秒，不用于性能比较。使用 -s 保留完整 ROS/launch 输出；原
DDS 事务提交及真实 β preference 学习/重规划同时通过。编译、flake8、
pep257、diff检查通过，lint既有 optparse 提示保留。

11个实际生产 import 完整字节与基线一致，生成消息路径和原生 ltl2ba SHA
固定；本轮生产实现未改，旧学习/恢复规则及全部原测试断言保持。四个测试
文件 SHA 在运行前冻结，收集 proof、完整日志、JUnit 与时序 receipt 保留。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_irl_test_split_9d51dfb.py
```

证据位于/tmp/ltl_ros2_completion_20261006：irl_split_9d51dfb 的
_population.json、_imports_collection.json、_run.json、_run.log 和 .xml。
launch文件 SHA 为9189d5dd3ed16501d92b981907005737d33c61969cba1f9bc885ec15ee167b7c，
unit文件 SHA 为e670a4661283dd4bdd593948fbd7be654b2f619d85026adc67f3c6f79dbaf7df。
两份 README 同步直接选择入口，前112节正文和历史失败保留。未重跑七包，
10项是当前局部运行范围，不推算或与历史705/9项相加；未运行LLM、benchmark、
物理仿真、实机或Jazzy，不证明整体加速或新增机器人示范效果。

### 11.114 IRL 测试拆分后的 HIL 整包发现验证（2026-10-07）

资格源码0c151a25710964fae46fd0541e1c044c34ce6f85。11.113直接选择文件的
局部运行未证明常规 colcon 自动发现新单元文件，本轮在独立临时目录构建和
测试 HIL 包；其他包使用既有 Humble 安装环境。运行前固定旧 HIL JUnit 的
119项和一个 copyright skip，以及从当前 AST 提取的六个独立单元方法，
完整预期名称为125项。旧 XML/manifest SHA 核对，HIL 全部30个 tracked
输入文件与资格 Git 字节一致，在结果前冻结。生产源码和测试本轮未修改。

构建 session75378、测试 session96180 均沿原 handle 至实际 exit0，
实际 colcon PID66138、66220；命令、完整日志、起止时序和退出码保存。
build4.936563432秒，test17.748827654秒，不用于性能比较。构建仅选择
HIL、symlink-install、独立 build/install，测试仅选择 HIL、默认测试发现、
return-code-on-test-failure、console_direct 与 -s，无筛选用例或关闭插件。
构建关于依赖来自既有安装目录的提示及原 np.int/SelectableGroups 弃用
提示保留；未更换依赖或改动其他包。

独立新结果目录仅一份新鲜 JUnit：**125 tests = 124 passed + 1 skipped**，
0 errors/failures；全部旧119项及六个 TestIRLPluginFakeHost 名称逐项核对，
跳过项与旧 copyright 一致。原 HIL policy、异步回调、控制器 launch、Trap
服务/替换计划、IRL DDS 提交与真实 β preference 均执行，flake8/pep257
也属于该次整包结果。launch 外层 item 与内部 unittest 不重复计数。
colcon test-result 查询实际 exit0，同样报告125/0/0/1。

14个实际生产 import 完整字节、生成消息路径和原生 ltl2ba SHA 核对；
HIL package share 指向新安装前缀，安装 README 与资格源码一致。独立结果
及日志闭包17文件保存 SHA manifest，旧冻结 HIL 证据未改。完整证据位于
/tmp/ltl_ros2_completion_20261006/hil_package_0c151a2：population.json、
imports.json、build/test/query_run.json、build/test/query.log、verified.json、
result_manifest.json及 results/ltl_automaton_hil_mic/pytest.xml。

```bash
source /opt/ros/humble/setup.bash
source /tmp/ltl_ros2_completion_20261006/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_hil_package_0c151a2.py prepare
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_hil_package_0c151a2.py build
source /tmp/ltl_ros2_completion_20261006/hil_package_0c151a2/install/setup.bash
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_hil_package_0c151a2.py test
python3 /mnt/c/Users/Yuhling/AppData/Local/Temp/qualify_hil_package_0c151a2.py verify
```

两份 README 同步 HIL 整包范围与自动发现命令；前113节正文保持。本次不
替代七包组合资格，125项不与此前局部10/9项或历史705项相加。未运行LLM、
benchmark、物理仿真、实机或Jazzy，不证明整体加速或机器人示范效果。
