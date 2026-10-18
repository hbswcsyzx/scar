# D2：生命周期连接审查与实施门

2026-10-18；已验收基线：D1 `382363c`，证据归档 `cc44e14`。
**本文件保留设计审查及实施计划；D2.0合同已收敛，D2产品按后续门实施。**
冻结字段、来源、E/F/P与失效规则见[规范合同](M1_DRIVER_LIFECYCLE_CONTRACT.md)；
下文§4是本轮审查的问题记录，按新合同逐项解决，不再作为未定字段。
[D2.1 publication](M1_BODY_PUBLICATION_ACCEPTANCE.md)已通过组件及冻结全仓验收；
D2.2–D2.4及完整第一阶段仍未完成。
不更改五类核心实体，不增加detector/backend，不把语言小实验算自动程序建图。

## 1. 补的是什么依赖

Operation仍表示检查、发布状态、更新请求和放弃引用；Value承载真实输入、结果和
协议端口；StateLocation承载当前可变内容；Region可展开这些步骤；Resource仍是
物理承载身份。输入/输出与完成不是新增业务节点类别。

需要接通的是：**哪条真实路径、哪个owner、哪个当前状态版本，支持哪一个结论。**
例如缓存/上移不能跨过会写状态的回调，不能因host收到异常就删除尚存的续体，
不能把frame引用放弃当作GPU或文件资源完成。这些关系决定未来子图能否替代。

```text
D1 BodyDrive 的实际私有 source 边
  → 首个无callback publication（当前 StateAccess）
  → session 更新 / 引用放弃 / 实际 host adapter
  → NORMAL 或 RAISE，各自携带实际后态

真实 current-state predicate → BRANCH
  ├ true → 私有首个 NoBodyFinish → 引用放弃
  └ false → 原有正常协议路径，可能进入 body
```

## 2. 已确定的约束

| 问题 | 决定及理由 |
| --- | --- |
| body outcome来源 | 继续用D1的 `(drive, source)`，不复制结果签名或另造permit。Suspend保留续体；Return/Raise才是该body的终结来源。 |
| publication位置 | 私有outcome landing的首操作；无callback的状态提交与可callback的引用放弃分开。状态只由真实StateAccess/results定义。 |
| no-body成功 | 不承认“任意helper NORMAL”。Created-close必须有版本化typed检查及真实成功控制边；不能伪造body Return。 |
| 非raising条件 | 当前状态检查的false应走真实BRANCH替代路径。禁止为方便校验，把合法的非Created close凭空变成RAISE。 |
| 原始请求角色 | scheduler S与request中的latent请求是不同端口。BODY的effective request可来自S；ASYNC_REQUEST须接实际关联，不能按同RAW类型互换。 |
| session后置 | 结论属于精确after-StateVersion/真实边。helper先写状态、再触发回调、最后NORMAL，不保证原结论仍成立；RAISE也可能已写部分状态。 |
| 多路合流 | Return/Raise/no-body完成可合法合流到共同release/session操作。不得要求唯一静态completion锚；须逐实际路径核对owner与当前状态。 |
| 引用放弃 | 放弃/转移owner所持引用不保证对象free、finalize或资源ready。body内部DEL、终态frame清理、traceback后续drop保留各自实际位置。 |
| 窄规则与宽helper | 符合FrameRules的窄drop若完成则保留pending，允许unraisable副作用与不完成。真正会向外raise的wrapper保留普通INVOKE/部分后态，不能借窄规则吞异常。 |
| D1兼容 | 新的生命周期检查须显式启用。旧v11 D1图仍按原范围合法，但不得因此被报告为生命周期已验证。 |

这些是合同约束；actual owner/generation、native guard执行与source/runtime对应仍需
独立证据。粗粒度world允许保守表达；同Location或有owner Use不证明已精化到该实例
的字段。不能用一个created/running/suspended/closed枚举替代全部native状态。

## 3. 原始证据与审查修正

本轮在conda `lewm`、CPython3.14.7运行小型stdlib CPU程序；没有LeWM/GPU或新
profiler运行。[原始审查目录](../artifacts/experiments/b1_call_operands/model_driver_lifecycle_design/README.md)
保存脚本、输出、各独立报告与root决定。

- **Observed：**终态与未启动generator的close引用清理中，所测析构回调看见
  GEN_CLOSED；body内DEL的时点不同，不能全部后移。
- **Observed：**generator的close中finally yield可使请求RuntimeError而body仍
  GEN_SUSPENDED；该同步样例重试后关闭。
- **Observed：**asyncgen的item请求可完成而body仍AGEN_SUSPENDED；另一样例第二次
  aclose抛StopAsyncIteration后inspect仍报告AGEN_SUSPENDED。host结果和传感器标签
  均不是完整machine状态，更不直接证明续体不存在。
- **Observed：**三项带断言的通用helper实验分别显示：callback改写先前post、写后
  RAISE留下部分状态、unraisable finalizer保留返回但有真实写入。三项通过。
- **Rejected：**一个独立报告初稿将上述async重试误写成CLOSED。root逐项核对JSON
  发现矛盾；初稿保留，终稿修正。该lifecycle脚本只有观测输出，没有assert，不能
  把exit 0报告为六项断言通过。没有为修正文案重跑实验。
- **Rejected：**把非Created条件false建模成新RAISE。core审查提出后撤回；真实分支
  方案保留合法的非Created→body路径。

这些小程序约束模型，不是D2产品、完整Python协议或运行适配器验收。

## 4. 字段冻结前必须解决

1. **状态覆盖：**已收紧为BodyOutcomeCommit只提交body，不带session后置；实际
   非空写集W从原StateAccess派生，W⊆L⊆D，未写域保留当前版本。不强制写全L，
   不从publication推断session结束。尚须冻结端口覆盖检查及与未来owner/selector
   的对应边界；有新state或role名字不证明真实body字段已更新。
2. **no-body检查：**确定typed predicate的owner、S、effective request、可选session、
   bool结果及真实BRANCH端口。检查到mark之间不得有callback/写；async关联与family
   准入的具体责任要分开，不能以普通NORMAL代替。
3. **合流与失效：**从canonical CFG派生当前完成锚及逐路owner转发；分析须有真实
   seed、处理合流/循环、在新gate/commit或不保留结论的写入处停止旧事实。引用锚
   的候选集合不能代替must事实；查询结果不是另一份可修改状态机。
4. **session和drop范围：**HOLD/COMPLETE/ABANDON不是完整family规则。需明确哪个
   版本/哪条边承诺何种后态；若terminal drop表示聚合frame所有权，就不能扩张到任意
   slot/bundle或traceback。通用重复bundle判定依赖尚缺的selector精化，不凭同owner猜。

## 5. 有序实施与自主验收

| 门 | 交付 | 必须通过的正反例 | 通过不代表 |
| --- | --- | --- | --- |
| D2.0 字段与来源冻结 | 解决§4，冻结最小records/来源/失效/迁移；独立复核没有未决实质矛盾。 | 真实BRANCH替代路径、两种request角色、多terminal合流、callback写后post失效。 | 产品或全D2已完成。 |
| D2.1 body publication | 接D1源边、owner/current-state、首commit；原StateAccess/CFG唯一规范。 | Return/Raise/Suspend、额外域、空frontier；错source、假owner、旧state、Suspend伪终结必须拒绝。 | no-body/session/drop已完成。 |
| D2.2 no-body路径 | typed current-state检查→真实BRANCH→mark；保留false的原程序路径。 | Created-close无body入口；非Created可走body；S/latent互换、guard后写/回调、任意helper NORMAL冒充成功拒绝。 | 完整close/delegate/cancellation协议。 |
| D2.3 session与引用放弃 | 精确后态、共享合流、真实callback/失败边及窄drop边界。 | 同body不同request、item后body暂停、失败部分写、合法多锚共享release；早release、旧post、丢RAISE拒绝。 | 对象free/ready或任意bundle判重。 |
| D2.4 组合与公开面 | C1/context组合、旧wire严格兼容、新capability、原Use查询及CLI范围报告；独立审查、冻结回归、归档推送。 | 全部有限路径及反例不漏；旧v11不冒授新scope，未知规则不升级为授权。 | D3全family、source/runtime、M0–M2或第一阶段完成。 |

实现按门逐步进行，每门保存原失败、修正、源指纹与验收报告。已有D1测试不为
纯设计文字重跑；有产品改动后先定向验证，最终冻结后一次全仓。第一阶段完整分母
继续见[完成矩阵](FIRST_STAGE_COMPLETION_MATRIX.md)；满足全部项目后先向用户讲解。
