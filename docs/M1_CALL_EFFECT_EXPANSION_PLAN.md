# 调用效果的完整展开与精确执行区间

2026-10-19。基线 `51a6eb3354eb05f7c02c9ff189239166f2cd4081`。
上一门已提交推送，1956 项相关测试通过、878 源码稳定；本门开始重核 checkpoint。
原 M0–M2、16 族 F12–F24/X25–X27、P5、M2 的 113 构造/196 字段不缩减。
本门不增加 detector、backend 或 LeWM 特例，不关闭整个 F16 或第一阶段。

## E0：模型判断与冻结合同

五种核心实体仍是 Operation / Value / StateLocation / Region / Resource。
现 `.callee`、`CallActivation` 及原 N/R 全槽只表达准确调用与端口；不排除
callee 外的副作用。`ProviderCoverage`、`NativeBoundary`、结果 copy 和
source-relative consumer graph 也不提供完整效果实现覆盖。

采用 **`CallEffectExpansion(operation: OperationID, callee: RegionID)`**：

- 以原 Operation 为自然键、精确引用其已有 `.callee`；每个 call 最多一份。
- 声明该调用的完整效果由这个原 callee 整 Region 表达，入口、退出的额外效果
  也已放进其真实 CFG 的普通操作；不存在未纳入展开的剩余边界效果。
- wrapper 可递归包含原 CALL/INVOKE、READ、WRITE、分支及 N/R；不另存状态、
  producer、actual path、truth 或“允许保持”位。entry、exit 和全槽从原接口派生。
- 这是明确的模型声明，不是 source/native 适用性证明或优化授权。
  可通过已有来源机制追踪其程序事实，后续 adapter 必须建立真实性。
- 完整展开不等于纯函数。允许展开里有 WRITE、opaque primitive、RNG、回调等。
  查询仍按区间逐个原 CFG position 检查，而非只沿某个值的 consumers。

`effects_complete=False` 表示原摘要不完备，不是“已知存在 callee 外副作用”。
新增的明确完整展开可以条件性细化这项 UNKNOWN；父摘要及其 RW 不改写、不删除，
在结果中说明改由完整实现核对。只有普通 callee 或 provider coverage 时仍保原阻断。
已知端口/身份/状态矛盾不能被关系覆盖；展开内真实 unknown/WRITE 仍阻断。

## E1：规范关系和原端口

ProgramGraph 新增 `call_effect_expansions` 空默认 tuple；新记录严格 exact typed IDs。
构造拒绝错命名空间/畸形记录/重复 operation；图校验拒绝不存在的 operation、
primitive 无 callee、错 Region，以及与原 callee 不一致。所有 entry、call arguments、
N/R signatures、CompletionResult/landing/state 仍由既有 core 完整校验，不复制图。
`ProgramIndex.call_effect_expansion(operation_id)` 仅返回原声明或 None，不给 proof 位。

只有存在显式新关系时，保持查询才能改用被关联的原 implementation；缺关系使用原逻辑。
普通 CALL 与 INVOKE 都属于关系可表达范围；不把 BodyDrive、异步 temporal resume
伪装成同步调用。actual activation 仍由本次 CallActivation 决定，不按 RegionID 猜实例。

## E2：精确 suffix / caller / prefix

复用 `_Walk` 的原 position、selected transfer、call inputs/outputs 及完整 state domains：

1. source 在第一个 callee 内：从 source AFTER 检查真实 suffix，再经准确 child
   completion、N/R 全槽和 caller landing 返回。source 前写入不混入区间。
2. caller 中间的每个原操作照常检查；不消费被查询值的独立写入也不能漏掉。
3. 进入第二个 callee，准确核 call entry 和全部实参/形参，只遍历到 target BEFORE。
   target 后写入不提前混入区间；未经过的未来 completion 不能被借作前缀证明。
4. 原父摘要保留为库存/上下文；效果检查由显式完整展开承担。原 input Uses、
   results、关联、所有 state 输入和需要跨越的完成槽不能因展开而被跳过。
5. interval 内不完备 primitive、WRITE/RW、悬挂/BodyDrive、缺捕获、缺原 Use/transfer、
   不能排除的别名或 shared budget 截断仍为 Unknown。不同 LocationID 不证明隔离。
6. 对确实只需 prefix 的查询，未来退出缺捕获与区间内缺捕获应有区别；需要返回
   caller 的 suffix 则必须有准确 completion/output/transfer。不要不加区分要求未来事实。

不从 source-relative region stages 构造效果库存：独立 writer/callback 可能不消费
source，仍然必须沿实际 CFG 检查。

## E3：真实供图与有限验收

复用 `_preservation_program/_formals/_uses/_terminal` 和 execution `_model`，不改旧 fixture。
同一 caller 连续调用同一原 getter 两次、两个独立 child activation，每图两实例。
原 full-call 摘要如实保留 RW；在新供图中将边界操作展开为原操作，不翻旧 opaque。
source 为 child1 WRITE AFTER，target 为 child2 READ BEFORE，且 prefix 非空。
实际 capture 保留区间外写入；query 应只证明实际 suffix→caller→prefix。

最少核对：

- N/R 两路径的原乱序 CompletionResult 与全部 state slots，区间外写不阻断。
- 显式展开细化不完备父摘要；删除关系恢复原阻断，不修改原摘要标记。
- suffix 或 caller 中独立真实 WRITE、展开中的 opaque primitive 必须阻断。
- 缺本实例 association、选中 transfer/原 Use 不借完整 sibling。
- prefix 不借未来 completion；suffix 缺所需完成不能通过。
- budget1 及已有 checked-prefix 截断保留库存/游标，不授保持 True。

先由 root 冻结源码运行新测试，保存真实首红/源码快照，再修改查询、重测。
若某设计不能表达原要求，报告并修模型，不削弱原测试或缩窄原族义务。

## E4：Program25 与旧 wire

新增 table/tag 为 Program25 能力，必须非空且显式 tagged；没有新关系的图保持
原 1–24 字段/版本/字节。Execution8 不变。旧 schema 不接受新表或新 tag。
旧最大 reader/future 参数及四个 current-fields 断言的准确迁移单独冻结，
不能豁免整份旧测试，不能把变化后的参数伪装为旧 testcase ID。

## E5：自主验收与版本

保留原 1956 项义务；相关选择在原选择器上追加新模块。5 个 future-version
身份显式迁移，其余 1951 精确身份保留。所有原 fixture 与其它测试字节不动。
所有失败保存准确源码、命令、JUnit、日志、前后指纹；最终源码冻结后一次相关回归，
逐条原义务审计、checkpoint、正常 commit/push，核远端 SHA/clean。
本门不代替 P4 component/frozen-full/P5/M2；旧 R3、真实 primitive getter、
初始 ASEND 联合控制及其余原八族继续逐项处理。

## 分工和执行纪律

root：本计划/迁移合同/档案/Git；旧 model/validation/queries/public export 接线；
旧 `execution/state_preservation.py` 的精确区间查询。所有解释器仅 root 串行执行。
A：仅 NEW `scar/ir/program/call_effect_expansion.py`、
`tests/unit/test_program_call_effect_expansion.py`，记录/图级拒绝/public read。
B：旧 `scar/ir/program/codec.py`、仅 NEW
`tests/unit/test_program_call_effect_expansion_codec.py`；另按冻结迁移合同精确改旧测试。
C：仅 NEW `tests/fixtures/program_call_effect_expansion_graphs.py`、
`tests/fixtures/execution_call_effect_expansion_graphs.py`、
`tests/unit/test_execution_call_effect_expansion.py`，复用原图构造与真实捕获。

作者不运行 Python/pytest/probe/compile/Git，不编辑其它文件。全部源码作者明确
FROZEN 后 root 才启动解释器；失败后先保存首红，再定向解冻所有权文件。
所有供图结果仍为条件性结构/查询证据，不冒充自动 LeWM 恢复、TRANSFORM 或加速比。
