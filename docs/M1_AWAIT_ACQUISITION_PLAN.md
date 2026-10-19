# P4：await 获取、资格与持续执行体的完整连接

2026-10-19；基线 `0bbc6235992e89e2a5735287e94622cfe0755cf8`。
上轮为 progress：连续 async 组合、1308 affected focused、归档及远端核验完成。
原 F12–F24/X25–X27 十六组和 M0–M2 总目标保留，不缩减为新增 helper 的局部成功。

## 1. D0 审计与范围冻结

五类实体 Operation / Value / StateLocation / Region / Resource 保持不变。
本轮要补类型规则及原端口间关系，而非增加 detector/backend 或业务节点。
三路独立只读审查已检查原协议合同、源码、P3发生关联及现 fixtures，未运行代码。

**Observed（原源码与版本限定主源）：**

- 旧 `AWAIT_SITE_V1` 固定 lookup/call/result-adapter；当前 continuation resolver
  核 receiver 来源和 Reference/packet 结果，却未核一般 `__await__` 返回资格。
- `continuation_site_program(kind='wrapper')` 没有 Create、BodyDrive 或持续 body，
  只能证明 helper 端口，不足以证明 F15。
- 原 `PYTHON_CONTROL_PROTOCOLS.md` §7.4 已要求 native coroutine、适用 generator
  coroutine、一般协议三路；不能把旧 helper profile 当成全部 await 获取。
- 当前 CPython 3.14.7 的 `_PyCoro_GetAwaitableIter` 对 exact coroutine 或带适用
  code flag 的 exact generator 直接返回原对象；一般 `am_await` 分支才调用并检查
  返回对象。后者不能返回 coroutine/generator-coroutine，也不能返回非 iterator。
- 显式 `coro.__await__()` 是另一站点：构造独立 W，保存指向 B 的引用。它不是
  隐式 acquisition 的第四互斥分支，也不是 W/B 普通 copy。

主源：[genobject.c](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c)、
[bytecodes.c](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c)、
[3.14 数据模型](https://docs.python.org/3.14/reference/datamodel.html#awaitable-objects)。
这些是版本限定规则依据，不直接证明任何供应 IR 或被跟踪对象的 native 对应。

## 2. 完整单位与验收分母

目标单位是：**独立输入来源 → acquisition/资格 → 本次 iterator → 首次或继续
advance → 原 body/外部 iterator → 中间 handoff 或最终表达式/异常消费者**。
必须有同图、跨调用及发生实例组合，不用换 enum 的两个孤立 fixture 代替。

| 格 | 必需正反例及边界 |
| --- | --- |
| A | native coroutine self、generator-coroutine self、一般 am_await 三路；显式 W 单列。普通 generator 直接 await 拒绝，但作为一般 `__await__` 返回 iterator 可以合法；后者返回 coroutine/generator-coroutine/非iterator不能被继续当合法 iterator。 |
| B | lookup、call、资格检查各自真实 N/R 与当前 state；错 lookup/旧求值/错 completion 不能补位；失败保本次 packet。不能把正常返回一个不合格对象与错误消除 TypeError 混为一件事。 |
| C | 零次挂起：首 advance 完成→本次提取→最终表达式；无假父 Suspend/Attach/Drive；非正常完成异常不被吞。 |
| D | 至少两 cut；中间 handoff 和最终值区分，恢复按原 slot，保原状态和异常。 |
| E | 同一 generator-coroutine B 的 direct 与 await 驱动共用准确持续 activation/segments/结果；多 Create 同代码、另一 body/旧 state/另一 Drive source 拒绝。 |
| F | 显式 wrapper W 与 B 不同身份；原创建 W、真实 advance、准确 held B/Drive 与 outcome；缺 owner 关系保原义务，不能按类型或唯一可见候选配对；外部 iterator不伪造B。 |
| G | 共享 incoming/caller 整 tuple 全覆盖；删整 stage/附件仍留原 scope/acquisition/consumer 分母；一个好来源不代表全部来源。 |
| H | 预算1保原 source/branch/N-R/jobs与cursor，shared flow/budget/index不重置；必要 copy 祖先、fresh denotation、snapshot与detach原合同保留。 |

F12/F15 及相关 F13/F14 的原格都在本门范围；完整 P4 其余组继续按原表推进。
原已验 async三Drive、C1两cut、helper/call回程作为组合基础复用，不重新宣称未实现。
source/native/runtime/值身份/变换权限仍分别记录，声明完整不等于其余权限为真。

## 3. D1 字段决定：先验证，再冻结产品合同

以下是当前设计方向，**尚非最终 wire 合同**；产品实现须等 D1 精确字段与反对性
复审冻结，不把设计草案误作已实现能力：

1. 原 GET_AWAITABLE 操作仍是唯一 producer，输入/own N-R result/state 由 core持有。
   acquisition 附件独立指出语言站点 expected operand，不能从实际 Drive 反选来源。
   固定新 profile 的来源库存先于可选展开/owner rows；删附件不删分母。
2. native/self 与一般协议分支按独立已知来源或原分类/选择证据解释。展开只引用
   真 lookup/call/资格操作；opaque native 获取保原 N/R与具体条件，不造假调用。
3. 一般协议的资格是对原返回对象的检查；“Reference”与“合法 await iterator”
   不等价。不能因检查会失败就把正常建模的 TypeError 路线本身当成错误 IR。
4. 显式 wrapper 的独立 W 和 held B 用薄 typed 关系引用原 constructor/receiver/
   result；B可在原 lookup.receiver，不能给零参数 call伪加B实参。W不进入B的普通
   copy/身份闭包。没有原 native 字段/端口的外部关系保具体缺口。
5. acquisition/iterator 到实际 body 的桥须指原 source、advance/callee 和 Drive。
   actual instance只读原Drive Use；先保所有独立原来源，再查owner/attachment。
   动态桥以 exact occurrence、selected completion和持续activation/segment为准。
6. 旧 v1/helper profile、旧 fixture和旧 schema字节保留；确需新closed contract/
   profile才新增能力版本。无新table优先；确需全局跨region附件则用现薄表。

`CapturedCode.flags` 和现 source witness可复用，但loaded flags、来源重编译、
concrete receiver/type、B持有关系不是同一证明。`types.coroutine`会变更flags，
现source replay不重放此变换；不得把它的 mismatch 一概写成源错误。不造新code
registry，也不依据类名、函数名或LeWM变量选择路线。

## 4. 自主关卡及分工

| 门 | 输出与自验 |
| --- | --- |
| D0 | 本范围/矩阵冻结、三路只读审计、版本限定主源；完成。 |
| N | root在conda lewm跑有限纯Python native例，保版本、flags、实际结果/异常/中间对象身份，不用GPU或LeWM。其结果是语言证据，非IR实现证明。 |
| R | 原公开API、core-valid正反图复现一般 am_await返回不合格对象仍被当 iterator继续的缺口；不是新字段缺失；不合法fixture错误如实保留。 |
| D1 | 根据N/R和原端口冻结精确records/profile/版本/源码语义与连接合同，独立反对性审查；未完成前不改产品。 |
| S | 统一静态acquisition/资格/owner/source-first resolver，闭A–H对应格。 |
| X | 同图持续B/direct-await/explicit-W、零cut/多cut与真正P3发生关联；缺采/错接/fresh/预算。 |
| V | 作者冻结、独立复审、受影响定向保旧1308义务；原16全齐才component/frozen-full，不按小helper重复full。 |
| A | 原fixture/失败/源码/合同/wire/保护目录核验与报告、commit/push。 |

本轮root拥有计划、native证据和串行执行；C先仅写新首红fixture/test；A/B保持产品
冻结，待D1决定再分原文件所有权。所有子代理不运行Python/tests/probes/compile/
commit；不同拥有者不交叉改文件，不边测边写。

证据目录：`artifacts/experiments/b1_call_operands/model_await_acquisition/`。
所有失败留原命令、日志、JUnit和前后源码指纹；不删失败、不拿测试数量当完成度。
LeWM与保护主checkout不修改，不增加优化backend/profiler/新加速结论。
