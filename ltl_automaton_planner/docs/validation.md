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

