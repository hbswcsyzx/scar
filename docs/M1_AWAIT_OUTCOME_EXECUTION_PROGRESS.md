# P4：原结果与失败义务的逐次执行连接进度

2026-10-19；开发基线 `287c906c95658d25200d057fe9002fc3d1f8479c`。
**PROGRESS；完整程序建模、原完整A–H与16组尚未完成。**
延续[原整门计划](M1_AWAIT_OUTCOME_PLAN.md)与
[D4原结果库存](M1_AWAIT_OUTCOME_LINK_PROGRESS.md)，本轮接口是
[冻结D5合同](M1_AWAIT_OUTCOME_EXECUTION_CONTRACT.md)。不是重新定义验收终点。

## 模型与代码如何对应

核心类型仍为Operation / Value / StateLocation / Region / Resource。
静态Operation不是一次调用；同操作每次发生保独立OperationOccurrence。
OwnedUse、completion ordinal、原CFG successor和状态Use仍是唯一规范端口，
没有平行producer图。K/Σ/A/R/Q/M仍是正交视角，不将source、packet、consumer
当作互斥的节点类别。

程序图描述所有原端口义务，执行图记录具体activation、visit、segment和occurrence；
本轮新增查询仅把两者连接，**不是新增事实**。它不会将supplied capture声明升级
为源码/原生实现对应、数值相等或变换授权。Program23/Execution8记录与codec未改。

| 已实现连接 | 核对依据 |
| --- | --- |
| source→advance→Drive→本次body outcome | 原静态key先保留，再沿确切CallActivation/BodyDriveExecution关联；多次同代码调用不混配。 |
| constructor NORMAL | 本次own Reference→准确PacketDefinition.exception组件；whole packet P另存，P→terminal packet Q→parent R分两段核原copy支持。 |
| constructor RAISE / extractor own N/R | 分别取自身真实selected successor/slot，另一腿保NOT_APPLICABLE，不冒充正常完成。 |
| 最终consumer / state | 原actual Use或HostTerminal先存在；沿当前caller同segment后缀找发生，不借兄弟调用；produced slot和forwarded position不混用。 |
| source自身失败 / expanded失败 | 无advance仍保own R义务；expanded lookup/call/Qreject在同source准确callee activation核prefix、own edge及exact completion，然后接parent R与consumer。 |
| qualification scope | 原method scope保自己的Q；source scope经原Expanded引用及该source的准确CallActivation接Q，无关region或无关联同site发生不进入分母。 |

`scar/ir/execution/await_outcome_evidence.py`复用原copy recipes建立bounded ancestor
证据；identity compatibility独立逐端点与实际support边刷新。不同root不直接证明
值不同，Reference→whole packet不进入copy闭包。ancestor用单份线性support，
组装和逐边兼容性都付同一shared budget；未付费的检查不留下True。

`scar/ir/execution/await_outcomes.py`在原`await_body_links(scope)`内增加
outcomes/failure_paths及库存。每项保原definition与动态occurrences；删adapter、
receipt、consumer Use、suffix或全部capture，原静态义务不会随之消失。
没有任何捕获parent时只枚原静态key，详细静态证明明确NOT_CHECKED并延后；不为
不存在的发生搜索路径，也不把缺采伪装为预算不足。静态Program查询默认仍完整
推导。原已捕获parent-site数量与checked/pending、Drive派生route数分别报告；截断不
用已查prefix充总数。原静态总数另存，未完成关联总数为None并保cursor。

静态完整性与本次选择分开：inactive RAISE缺合同仍保在definition，不能污染
实际NORMAL腿；实际所选腿缺合同仍PARTIAL。缺CallActivation或completion不挑
同型terminal补齐，缺parent transfer不崩溃。所有子项三值结论向父项汇总。

## Observed / Verified：真实验收记录

证据目录：`artifacts/experiments/b1_call_operands/model_await_outcome_execution/`。
每attempt保命令、完整log/JUnit、前后source清单；执行期间全部作者冻结。
全部Python/pytest由root在既有conda lewm串行执行，子代理只写新测试及只读审查。

| attempt | 结果 | 归因 |
| --- | --- | --- |
| first-execution | 21F | 15项新字段缺失、1项真实无关联同helper捕获污染、5项新test解包错误。 |
| second-execution | 16P5F | 4项新test静态ID/发生ID定位错误，1项budget1空库存缺cursor。 |
| boundary-first-red | 3F | 真实late-budget仍称完整、inactive异常腿gap污染、P→Q动态证据字段缺失。 |
| third-execution | 24P | 所有新例通过；随后补exact-completion缺采显式gap，不能归给最后字节。 |
| accepted-focused（原attempt名，失败） | 1499P2F | 旧budget1零capture用例暴露新查询伪预算耗尽；旧断言未改，失败目录原样保留。 |
| empty-capture-regression | 28P | 新24与旧4缺采例通过；之后补raw准备计数，仍待最终统一。 |
| accepted-final | **1501P/0F/0E/0skip** | 最终783源前后固定，待归档器逐一核1477旧caseID与24新例。 |

最终源码SHA：`c57e88db124d8b7f11409120acff3218339170bc63f8808030383e58a6e053c2`。
pytest147.30s，runner148.2066199425608s。此为受影响focused范围，不是组件/全仓
或完整A–H；历史5822项full仍只属于`81389862ee3f1dfe88c59f74ca1bfeff732779ff`。
最终源码包括exact-completion缺口、零capture延后细节与raw准备计数，不能借早期
24P或28P的旧SHA宣最后字节已验收。完整命令/日志/前后清单均保留。

新24例由A outcome10、C failure6、B boundary8组成。新test自身错误按真实日志
修正，不将其冒称产品缺陷；原既有tests/fixtures无修改。字段缺失、真实错误与
源审推断分别记录在`attempt-notes.md`和`independent-review.md`。
缺parent transfer、support内部兼容性及exact-completion guard是有限源码审查
发现并修复，没有把它们谎称单独重现的runtime失败。测试耗时不是workload性能。

## 原整门仍OPEN的内容与下一步

本轮是supplied IR及其发生记录的连接测试，**没有自动从完整LeWM恢复这些图**。
实际runtime correspondence与完整capture仍未证；flags全部False。
原F12–F24/X25–X27十六组、完整A–H、P5、M2原113构造/196字段与M0–M2均未关闭。

1. 按原A–H继续连接call actual→entry formal的内部consumer，保caller/current/
   guards整tuple；未知callee、递归/opaque等继续有具体边界，不造消费证明。
2. 补C1完整后继/terminal与原三路来源、W、多cut、BodyRaise等剩余组合，逐原
   清单给证据；不能拿本轮局部green替代原整门。
3. 原16组齐后再统一组件/冻结full，接P5/M2原分母；完成M0–M2后才宣第一阶段
   建模完成并讲解。M3自动全程序图、M4证据精化、M5依赖闭合、M6化简指导继续
   按[完整路线](WHOLE_PROGRAM_MODEL_PLAN.md)执行。

无新detector/backend、LeWM业务规则、profiling/benchmark或加速结论。两个受
保护原checkout保持原HEAD与status；工作在独立structured-program-model worktree。
