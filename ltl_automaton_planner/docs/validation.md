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

