# Await原始结果、失败端点与消费者：进度验收

2026-10-19；基线 `69ed9e334a479132935d3493ab4f879ae181081d`。
依据原 [完整单位计划](M1_AWAIT_OUTCOME_PLAN.md) 和冻结
[D4视图合同](M1_AWAIT_OUTCOME_VIEW_CONTRACT.md)，本轮为 **PROGRESS**。
原完整A–H、F12–F24/X25–X27十六组、P5、M2原113构造/196字段及M0–M2仍OPEN。
这是供应IR的原端口连接验收，不是任意Python/LeWM自动恢复全图的完成声明。

## 模型：连接原节点，保持数据和状态角色

原五类实体Operation / Value / StateLocation / Region / Resource未变。
获取、资格检查、推进、原body终端、异常构造、packet和最终提取仍沿原Operation、
owned Use、state SSA及CFG边连接。新增的是查询派生视图，不是第二个producer图。

```text
原source → 获取/资格 → iterator → advance → 原DriveOutcome
  ├─ Suspend → 中间handoff
  ├─ Return → 转换own NORMAL → 原whole packet → callee RAISE
  │                                      → 本advance RAISE → 最终提取own N/R → consumer
  └─ BodyRaise / 转换own RAISE / 获取失败 → 自己的packet/state → 准确caller consumer
```

异常Reference不等于whole packet；转换结果不等于普通copy。原始结果、转换和
consumer的义务先建库存，附件只做左连接。必要source条件通过原入口edge-cut
核必要性，不从实际Drive或已有adapter反选。Program23、Execution8记录/codec
字节未改；没有新增可写phase、普通identity事实、detector或backend。

## Observed：真实失败和最终验收

各次command、完整stdout/stderr、JUnit、前后源清单保存在
`artifacts/experiments/b1_call_operands/model_await_outcome_links/`。归因详见
`attempt-notes.md`，源码意见与实际实验分开记录。

| attempt | 实际结果 | 说明 |
| --- | --- | --- |
| first-outcomes | 3P/10F | 7项新接口缺失；2项parent RAISE仍误证NORMAL；1项新fixture删row未删receipt的FK错误。 |
| second-outcomes | 13P/0F | 首批原outcome/失败端点与parent edge修复通过，尚非最终源码。 |
| boundary-outcomes | 20P/2F | 全删producer/final附件、budget1和handoff通过；source必要accept条件与reject请求冲突却抛异常。 |
| red-forwarded-state | 1F | 原图core合法；edge独立Use转发当前state，却被视图遗漏为0项。 |
| third-outcomes | 23P/0F | 所有新测试通过，776源前后固定；旧1454尚待统一。 |
| affected-outcomes | 1477P/0F | 第一统一受影响回归；之后才补最后的子项状态汇总，不归给新字节。 |
| accepted-focused | **1477P/0F/0E/0skip** | 最终776源固定；保上一全部1454精确caseID，新增23。非组件/full或完整A–H。 |

最终源码SHA为
`fb0fc2fbaf9292421bc7c873297e77fcad0668a489eeb06f6e4fc831e64061f6`；
pytest127.76s，runner128.72808583267033s。测试时长不能作为workload加速数据。
新23项为outcomes13、failure5、guard/forwarded边界5。三项旧机制本已能拒绝的
负例在首轮就通过，不冒称新产品缺陷。既有tests/fixtures与基线逐字节一致，
无输入、caseID或schema词汇迁移；失败日志不覆盖。历史5822 full仍只属于81389862。

## Implemented / Verified：本门实际连接

- 新 `outcomes` 从原source/advance/case与BodyDrive所有后继建立；各原N/R保在
  子legs。全删final或producer适配及准确receipt，原BodyReturn key/count与原
  提取consumer不消失；缺语义保gap，不自动补完成证明。
- 转换NORMAL的Reference经准确PacketDefinition组件到whole packet，与转换
  自身RAISE失败packet分开。最终提取own N/R、原output consumer和各state支持
  分别核。只同型、只targets非空或另一RAISE行不能补准确NORMAL证明。
- 新 `failure_paths` 保原source自己的Get RAISE和wrapper构造RAISE，即使缺row/
  成功advance附件；展开lookup、method call和bool资格拒绝按准确prefix分开。
  拒绝边仍是原ControlEdgeReference，不伪造BRANCH的INVOKE结果。
- packet、callee出口、parent completion与state按准确kind/slot/Location核；
  原edge转发state保独立Use、position、landing formal与slot=None，不造新版本。
  packet组件来源不认证TypeError类别，也不证明native实现与源码对应。
- may库存复用原Value→Use索引，按consumer位置fresh membership筛，再作must。
  已知source条件冲突是False/显式空可行库存，不抛异常或伪装unknown；未知仍
  留gap。HANDOFF/BodyRaise另核准确caller delivery，不将另一completion当成功。
- 子项False/None和缺腿向父项汇总；不靠family全局issue掩盖局部DECLARED。
  原Drive后继总数与source/case关联job总数分开。budget1实际验证前者不变，
  后者未完成时为None并保cursor，不把已查prefix当总数。

上述范围经A/B/C独立测试作者和有限只读复核。具体风险、修复与最终文件SHA见
证据目录 `independent-review.md`。所有执行由root串行完成，源码作者冻结；
全部native/source/runtime/value验证与变换授权仍False。

## 原整门还缺什么

| 原A–H方面 | 本门证据与仍OPEN的部分 |
| --- | --- |
| 来源/资格 | 既有三路来源保持；一般合法失败packet/state/host与原ownR新增验证。implicit native CORO、mixed/noniterator、反极性/INVOKE检查等完整组合仍须核。 |
| 零/多cut | supplied零/两cut最终结果及中间handoff静态连接已测；BodyRaise/构造失败/C1的完整组合与当前原tuple覆盖未因此全齐。 |
| body身份/W | 旧sameB/第二Create/Wgetter证据保留；W own构造R无Drive link已测；W持续多cut完整最终consumer仍OPEN。 |
| caller/current/case | 按原choices和准确端口核；跨callee内部消费者仍显式pending，不能把return-copy摘要当已理解整个helper。多caller/current/mixed组合还须完整验收。 |
| 分母/预算/缺采 | 整删适配附件与budget1原后继总数已测；原source→case关联总数不完整就明确未知。实际Execution最终提取缺采与动态完整投影仍待实现/验证。 |

公开Execution原body/link捕获机制保留，本门没有把新静态outcomes冒作真实执行
采集或对应证明。自动全程序前端、完整来源/逻辑版本、最小依赖化简及优化计划
仍须在原路线中验收，不能用1477测试计数替代它们。

## 下一步，继续原计划

1. 用原CallActivation/DriveExecution/selected transfers投影完整结果和失败路线；
   缺extract/packet/callee capture保静态义务与准确gap，不能反选expected。
2. 从真实call actual→entry formal继续展开内部consumer，保caller/current/guards
   完整tuple；C1使用完整后继/terminal而非只有首frontier。补原A–H剩余组合。
3. 原16组齐后才统一组件与一次冻结full，之后P5、M2原清单和完整M0–M2。
   每个原验收点自验收、归档、commit/push并核远端，不请求用户批准局部green。

没有新LeWM规则、profiling/benchmark、变换或加速比。两个受保护原仓库保原
HEAD与干净状态；本轮归档核验不启动测试或workload。
