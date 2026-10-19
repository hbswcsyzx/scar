# 下一门：把完整效果展开用于原 F16，再完成第一阶段原分母

2026-10-19。本文件供 root 审阅，不是验收报告或新增实现授权。
基线为本门计划中的 51a6eb3354eb05f7c02c9ff189239166f2cd4081。
本门 **45 个新测试定向及 2016 项最终相关回归均已通过**，884 个源码指纹稳定。
最终结果和验收范围见 [实际进度](M1_CALL_EFFECT_EXPANSION_PROGRESS.md)；
原义务守恒及档案核对由本门 checkpoint 验证。本文件不是整族或第一阶段完成声明。

依据：[本门 PLAN](M1_CALL_EFFECT_EXPANSION_PLAN.md)、
[普通 CALL 当前状态修复](M1_CALL_EFFECT_EXPANSION_STATE_FLOW.md)、
[测试前提更正](M1_CALL_EFFECT_EXPANSION_TEST_PREMISE.md)、
[原 F16 下一门](M1_ASYNC_SESSION_OWNERSHIP_NEXT_GATE.md)、
[本门 family ledger](../artifacts/experiments/b1_call_operands/model_call_effect_expansions/family-obligations.json)。

## 1. 本门真实进展和有限性

- CallEffectExpansion(operation, callee) 精确引用原调用及其整个 callee Region，
  声明完整效果已在真实 entry、CFG、exit 操作中表达。它不是 purity 位，也不
  自动建立 source/native 适用性。只有原 callee、provider coverage 或结果
  copy 时，原边界阻断仍在。
- state_preservation 复用原 CFG position、CallActivation 和端口，核实际
  suffix → caller → prefix；区间外写与区间内写分开。独立 writer 不因不消费
  被查值而消失；primitive opaque、缺采及预算截断仍为 Unknown。
- 普通 CALL 的原 StateVersionValue 结果进入动态 current/state definitions；
  缺结果变为 None，不沿用旧状态。它不证明内容相等，INVOKE/BodyDrive 仍只在
  准确实际完成 EDGE 有后态。
- Program25 只由非空新表选择并要求显式 tag；无能力图保持旧 1–24 wire，
  Execution8 不变。旧测试仅按冻结迁移 ledger 改指定 reader/future/字段断言；
  隔离基线 encoder 的 Program24 oracle 与旧 Program23 oracle 分别保留。
- Graph 子类用例按隔离基线的 address_graph 拒绝校准；本门没有修复旧公共
  Graph 子类支持，不能把局部关系校验正常返回写成整个公共入口已支持。

下表给原条件的证据入口，不以 45 这个数量代替条件。简写 selector 均位于
tests/unit/test_execution_call_effect_expansion.py：

| 已核条件 | 精确测试入口 |
| --- | --- |
| N/R、区间外写、同 callee 不同实际调用 | test_outside_writes_do_not_pollute_the_actual_suffix_caller_prefix |
| 显式展开细化未知摘要；删关系恢复阻断 | test_complete_expansion_refines_the_unknown_summary_without_rewriting_it |
| source 无关写与真实 opaque 仍阻断 | test_an_independent_interval_writer_cannot_hide_behind_source_relative_consumers；test_a_real_opaque_primitive_inside_the_interval_is_not_an_expansion |
| 本实例缺边不借 sibling；prefix 不借未来完成 | test_missing_this_instances_required_edge_does_not_borrow_a_complete_sibling；test_a_real_prefix_does_not_require_its_future_completion |
| 普通 CALL current、缺未来结果、预算 | test_ordinary_calls_keep_data_state_ordinals_without_requiring_future_results；test_budget_one_keeps_endpoints_and_never_grants_an_unchecked_expansion；test_a_checked_prefix_does_not_replace_the_remainder_of_the_actual_interval |
| 关系/FK 与版本字节 | tests/unit/test_program_call_effect_expansion.py；tests/unit/test_program_call_effect_expansion_codec.py，含独立 Program24 encoder oracle |

没有把旧 opaque getter/terminal 改成 pure，没有证明任意 native call 都有完整
展开，没有自动生成整程序，也没有产生优化授权或 LeWM 加速结论。

## 2. 原 F16：核剩余关系，不重造已经接通的流水线

机器 ledger 的 F16_current_scope_review 是当前分项依据；其
remaining_other_families.F16 关于 reuse、competition、scheduler 的旧文字明确
保留为历史输入，不能再当作“没有实现”的证据。已有四种来源、同 R/B 三次实际
驱动、completed reuse 供采链、R1/R2 竞争、R2 COMPLETE 与 R1 继续、后续
scheduler THROW/CLOSE packet 均应复用。

| 原义务/接缝 | 剩余条件及验收证据 |
| --- | --- |
| COMPLETE → 同 R 后次 READ 的内容支持 | 对旧 R3 的 adapter.construct、incomplete host terminal、未证隔离的 context RW、第二 primitive association 四个 blocker 逐一定位。只有真实完整实现及本次端口足够时才能消解对应项；区间内真写/opaque 继续 Unknown。新通用区间正例不等于旧 R3 已保持。 |
| HOLD → 独立 R2 当前 occupancy READ | 同 B 来源投影和实际竞争链已有证据；本门未自动恢复主图中的完整调用及 primitive 边界。真实 supplied implementation 穷尽效果时可按新关系核区间，否则保原来源/端口及具体阻断。R2 COMPLETE 不推出 B 空闲或 R1 完成。 |
| 首次 ASEND 联合控制 | 独立 R.initial、B.Created、首次 latent SEND 的原 operand ordinal 和 None 判断，接原 bool/BRANCH、实际 gate 或拒绝 own N/R 与后态；孤立 bool、规则 enum 不能代验。 |

首次 ASEND 的有限验收围绕真正改变选择的条件：

1. R 初始、B Created、non-None latent operand 的拒绝，准确原异常来源、
   无 body entry 和实际 request/body 后果。按限定版本合同及原证据核后果，
   不预填 B.Closed，也不把所有失败当作同一 COMPLETE。
2. R 初始、B Created、None operand 的合法路径到真实 body entry/首 outcome；
   另核 B 已挂起时新 R 的 non-None operand，防止拒绝所有“初次 non-None”。
3. R 后续 step 仍选当前 scheduler S，不回借初次 L；竞争拒绝仍组合 R.initial
   与 occupancy，不能仅凭 occupied 拒绝原 R1 的继续。
4. 一个准确错 R/B/operand 或过期 current support 反例，复用已有缺采、预算、
   删除关系证据；仅对新接缝的具体风险补节点，不铺无界参数积。

先核原接口和 profile/clause 允许范围，再冻结必要变化。typed 条件够用就接
原端口；确有不可表达事实时报告准确位置和最小语义，不先建通用 async phase 图。
历史 predicate 可以解释旧分支，不能为当前 gate 快照授权。不同 LocationID
不证明隔离，F 的 no-reset 历史合同不外推为可变 P。

## 3. 原九个开放家族仍逐条验收

保留原 16 行。F12、F13、F14、F15、F17、F21、F23 七个条件性 M1 结构验收、
原 await A–H 的已接受结构证据继续复用，本门没有新关闭家族。其余九行按原
计划和 ledger 核已有证据及实际欠项，不把 OPEN 解释成全未实现。

| 原编号 | 仍需合账/完成的原义务 |
| --- | --- |
| F16 | 上节接缝，连同已有四种请求来源、真实复用/竞争、当前 scheduler 逐项合账。 |
| F18 | 自然完成、主动终止异常、源级非法非空 return 分开；准确当前结果/packet/adapter/consumer，不能用自然完成规则吞主动异常。 |
| F19 | 限定版本的 closed、athrow、aclose 及失败续体；native bit、request 完成、continuation 和 frame release 分开。 |
| F20 | yield-from 求值、GetIterator、首次 advance、零次父挂起及各自失败；lookup RAISE 不冒 exhaustion，不造未执行的父 Suspend/Attach。 |
| F22 | 本次 THROW 的 1–3 原参数/ordinal，经真实方法或 missing matcher 到 item/exhaustion/父是否恢复；原注入包、lookup 新包、matcher 新包分别核。 |
| F24 | cancel 请求、准确 target 与实际 delivery、handler 抑制/C1 后再 await 或终态；请求成功不代交付、waiter 转发或最终 cancelled。 |
| X25 | local binding、pending/context/delegate 跨至少两 cut 及 loop/merge 的完整组合；旧值、旧状态、fresh Replace/token 不混。 |
| X26 | 真 publication、当前 session、partial RAISE、窄 release 与宽 helper 组合；Suspend 不种 F，request 结束不授 frame 释放。 |
| X27 | 剩余家族逐次接准确实际 Drive、持续 activation、ingress/outcome、run/thread/实例；缺采保原 consumer/来源分母，不借 sibling。 |

每行采用“原条目 → 已有 exact selectors/关键断言 → 实际残项 → 同源证据”
合账。已满足条目不因 source/native authority=False 而无限重做；缺自动获取的
事实另列 M3/M4，M1 本身尚缺的类型/连接也不能推迟或抹掉。

## 4. adapter 自动获取完整展开真实性仍缺失

当前关系是 supplied graph 明确声明。原 callee、CallActivation、相同代码、
provider coverage、NativeBoundary 的端口分区和输出 copy 不能自动生成“所有
call 效果都在这个 wrapper”这一事实，source-relative consumer graph 也不是
完整效果清单。adapter 后续须建立限定版本/表示、准确 callsite 与 wrapper、
入口/退出剩余效果、异常出口和全部 state ports 的真实性及覆盖依据；缺失时
保边界，不能给所有 callee 批量补关系。

第一阶段要明确事实类型、映射合同和拒错边界；从实际程序入口自动恢复并核实
它们属于后续 M3/M4。复用 [MODELING_INTEGRATION](MODELING_INTEGRATION.md)
划定的 source/bytecode、FX/Export、profiler/provider 接口与成熟工具，不另写
业务规则、detector、backend 或 LeWM 专用解释器。手工小图只验证模型关系，
不算自动建图完成。

## 5. 最小有界步骤与停止/汇报点

1. **先收本门。** 等最终相关回归结束，核同源指纹、原 1956 项义务及冻结
   ledger 五个 future ID 显式迁移，保失败/前提更正，再归档、checkpoint、
   版本。失败先报告原问题与授权范围，不在运行中改源码。
2. **只做下一条真实缺口。** 核 F16 主图边界是否有真实完整实现可接；不能恢复
   的 primitive 明确保留 Unknown。随后以原首次 ASEND 联合控制为完整有限
   单位冻结合同和验收，不重铺已通过基础图，不追加无关参数积。
3. **每个单位结束即合账。** 报告成立条件、反例、缺采/预算结果、精确 selectors。
   字段或原生阻断就定位，不弱化断言或换简单例收尾。整行原义务足够才关 M1
   结构行，不以测试数量增长直接关 F16 或九族。
4. **返回原阶段门。** 九行逐项完成后执行 P4 component/冻结 full，再核 P5
   完整 F01–F24/X25–X28（含公共面、兼容、预算）与 M2 原 **113 构造/196 字段**：
   逐构造 phase、顺序、隐式调用、效果、完成规则有映射及反例。affected focused
   不替这些门，清单或 enum 齐全不等于完成。
5. **第一阶段停止点。** 对照 [完整性矩阵](FIRST_STAGE_COMPLETION_MATRIX.md)
   和 [全程序计划](WHOLE_PROGRAM_MODEL_PLAN.md) 核完整 M0–M2；真正齐备后先停下
   向用户解释实体、端口、状态及表达边界，再继续原 M3–M6 自动建图、实际对应、
   观察根闭合与化简顺序。当前没有自动恢复、变换或加速证明。

本文件写入时 scar/tests/scripts/gates 全部冻结；不修改旧合同、机器 ledger
或任何运行中的源码，不额外运行解释器/测试/Git。后续执行及门报告由 root 统一负责。

## 6. root 复审：防止模型验收无限扩张

独立只读审查指出，继续逐细节堆 supplied 组合会拖延原完整建模目标。下一轮
先合账原九族、P5 和 113/196；只有定位到原义务中确实缺少的字段、关系或反例，
才增加模型实现。113/196 不是 113 个自制 lowerer 的任务数，也不是与九族、
每种 N/R 做笛卡尔积的测试要求。native Unknown 的真实性义务不能无穷倒灌为
第一阶段新增前置；声明内尚缺的依赖也不能因该区分而漏掉。

主矩阵和工具复用文档中的历史阶段摘要须与近期专项验收合账。历史段落不是
撤销既有验收或重开已接通协议的依据。阶段完成数、自动恢复数、实际对应和
化简权限分别报告，不能互相替代。

三名审查者已对其余八个开放族作有限只读合账，见本门档案
`remaining-source-review.json`：每行最多三个现有 selector、实际关键断言和剩余
连接。该文件明确区分本门 JUnit 真正重验的用例与仅源码/历史证据，所有行仍为
OPEN。其中 F20 旧台账的“缺独立方法 lookup”已过时；X25–X27 未发现必须新增
规范字段的依据，应先复用既有接口连接整链。F18 的主动终止异常适配、F19 的
asyncgen 专属失败续体、F22 的 delegate 到父恢复、F24 的抑制后再 await 各有
具体未合账项，不应再从 enum 或基本 occurrence 字段重新开始。

原 M0–M2 真正完成并向用户解释后，固定下一项自动恢复交付为：
**入口驱动的“两文件 Python 外壳 + 一个 FX/Export 子区域”自动连接。**

- 用户仅提供入口、项目边界与预算；不提供函数名单、手工 IR、slot 映射或纯性标记。
- 复用现有 source discovery、program inventory、有限 lowering 与原生图合同；
  不重写 Tensor tracer、TreeSpec 或 graph signature。
- 公开查询须自动从 caller 输出 Use 追到原生输出槽、有序输入和上层来源，
  保留重复 Uses、当前状态与 mutation 写回；原生表示不与原执行混为一图。
- 错 source digest、缺 artifact、错 slot、graph break、预算截断须给出具体
  关系缺口，外围结构仍保留；opaque 外壳不计内部已展开。
- 自动生成及独立重放须在函数重命名/移动后仍成立。只围绕这条主链及真正的
  错接风险验收，不增加优化 backend 或 LeWM 特例。

这是后续自动恢复的明确验收目标，本门未实施、未验收；也不替代第一阶段的
原剩余义务或用户要求的阶段完成讲解。
