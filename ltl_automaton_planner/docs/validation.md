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

