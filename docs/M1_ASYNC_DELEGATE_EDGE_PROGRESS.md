# N1/F17 与 N2/F21：原结果连接验收

2026-10-19；基线 `601faf6dc93e594b4542bcd58513e42c569d8ded`。
[冻结计划](M1_ASYNC_DELEGATE_EDGE_PLAN.md) SHA
`253d697ee2bb450a0e63ac01f9d3e6e340edc183654a73d777be1d7bf099ae2e`。
原 G 已关闭；本轮不重置原 A–H、十六组、P5 与 M2 原113构造/196字段。

## 当前模型与具体检查

Operation 的 own result、下一操作的 actual Use、最终消费者、StateLocation
版本和实际 occurrence/call 分别连接。类型相同不能代替原来源；request 完成
后态不能代替当前 ASYNC_YIELD→adapter→packet/host 的值来源证明。

三路独立只读审查已确认 F17/F21 的有限缺项可用现规范记录表达。N1 使用原
第二次 AWAIT caller 的准确 own NORMAL 值作为可支配旧候选，经原 SEND/raw
与 delivery 同步传递；当前 item 仍从 B 的 saved slot 恢复。旧候选不是先前
ASYNC_YIELD 或 native StopIteration 的断言。独立旧 packet 有真实 producer/
components，与当前 adapter packet 分开。

N2 的 None/nonNone 分流、调用自身 RAISE 与旧 item 回边都保原完整 CFG/状态。
静态协议非法图应在动态前置校验拒绝；捕获 Use 与静态 Use 不同属于 core
错接，不能伪称新协议证明。动态完整链与三处当前 Use 缺采另行核验。

## 证据状态

- **Observed → Implemented → 局部 Verified**：ASYNCGEN_YIELD_TO_REQUEST_ITEM
  漏在通用异常 adapter 的 own-output→host 校验集合之外。真实首轮9项为
  8P/1F，core 合法，current item→adapter→component 都 True、当前 packet→host
  False、旧 typed packet→host True，但 full validation 无 issue。已将该规则
  纳入原检查集合，复用现 own 类型/host kind/packet component/current completion
  校验；修后9P，未添规范记录或第二 provenance 图。
- N2 新六个节点均实际通过，无须产品修改；完整原 F21 条目经独立核表未见
  额外结构缺项，最终同源1793项全部通过。
- 首红848稳定源码SHA
  `21987574d128ec776afb4761af0ac9bf945b559ba899aafe531be17973fcd177`；
  修后848稳定源码SHA
  `c2a79924b4e420880ff9f6d7dc38077d0697036ca788b1af6fcaff3ba5b2a5d4`。
- 动态完整链及三处当前 Use 缺采已实际通过；`dynamic-first`13P，849份稳定
  源码 SHA
  `9b301a26b2fb7ec54b2a93766f63d8ff73f0d77dcb57369e920b317e680ac4e3`。
  保同一 B 的三 segments、准确 Drive/ResumeIngress/CallActivation、当前
  packet/state 到 caller 的全结果槽。删 adapter input / packet component /
  host payload 任一个当前 Use，session post 仍 True，值关系保持 PARTIAL，
  不借仍被捕获的旧 packet。没有额外产品修改或作者 oracle 迁移。
- root 独占所有解释器/测试/归档/Git，作者全部冻结后串行运行；每次命令、
  日志、JUnit 和源码前后清单独立保存于
  artifacts/experiments/b1_call_operands/model_async_delegate_edges/。

最终统一源码的1793项受影响定向回归全部通过，无失败、错误或跳过；其中原
1780个准确 JUnit identities 全部保留，新增13项。849份源码运行前后 SHA
均为 `9b301a26b2fb7ec54b2a93766f63d8ff73f0d77dcb57369e920b317e680ac4e3`。
pytest 用时579.17秒，含清单记录的 runner 用时580.2155146459118秒。这是
受影响定向集合，不是完整 component/full 回归或性能 benchmark。

归档 checkpoint 同时核冻结合同/codec/旧归档/两原仓库保护与逐原条目合账，
满足后关闭 F17/F21 条件结构格。当前不授自动恢复或变换权限，不产生新
LeWM/GPU 性能结论。

## 逐原条目合账

独立审查未发现 F17/F21 额外 M1 条件结构缺项；最终统一源码回归通过，归档
以逐原 selector 的准确 JUnit identities 核验此结论。两格按原条件结构要求
验收，不将其它家族或完整 M0–M2 记为通过。

| 原条目 | 本轮与既有证据的分工 |
| --- | --- |
| F17 同 R/B 的 AWAIT→ASYNC_YIELD | 原 pipeline 核一持续 B、三次 Drive、准确 ingress/outcome、HOLD/HOLD/COMPLETE，暂停与终结分开；新动态正例逐结果槽贯通当前 packet/state 到 caller。 |
| F17 当前 item/packet | 两条静态拒例独立核 export→adapter 与 own result→packet/host；新动态正例核实际 occurrence/value，三缺 Use 各保 PARTIAL，post True 独立成立。 |
| F17 current/shared/deletion/budget/fresh | 原 async_pipeline / async_session_edges 正反例保持；本轮同源码重新回归。F16 reuse、F18终止、F19 closed 是各自原格。 |
| F21 lookup/call/state/None | 原 bound-method N/R、ordered tuple、跨 incoming 错配和 loop 当前性保持；新 None/nonNone 分流与合法 SEND 保原 ordinal0。 |
| F21 调用自身异常 | NEXT/SEND 两节点均无 extractor，own R packet槽0与 state槽1到准确 host，N item腿仍保；错取 lookup own R 的同型期望被拒。 |
| F21 item 与最终值 | 原 item/exhaustion/own N/R 保持；真实回边将 item 保存至 previous formal，支配合法地替换 final 后被拒，没有跨互斥臂制造无效 SSA。 |
| F21 删除与有界 | 原 paired-call/method inputs/consumer-target 删除、partial guard、tiny shared budget 等 selectors 保持；动态全族交叉仍归 X27。 |

精确 selectors 和其他家族真实残项在本轮 family-obligations.json；机器归档
收录各选择器对应的实际 JUnit identities，并保原1780义务与原 G 关闭。

## 执行记录

| 尝试 | 实际结果 | 范围 |
| --- | --- | --- |
| first-red | 8P/1F，848源码稳定 | 旧 wholepacket 被错接受；core 与原来源绑定准确指明缺边。 |
| after-async-host-fix | 9P，848源码稳定 | 补原 adapter 检查集合，全部新静态节点通过。 |
| dynamic-first | 13P，849源码稳定 | 当前动态完整链与三缺采通过，无额外产品修复。 |
| verified-final | 1793P，0F/E/skip，849源码稳定 | 最终同源码旧1780加新13；全部准确旧 identities 保留。 |

下一步继续原 N3 close/C1 和其余家族；[下一门只读审查](M1_DELEGATE_CLOSE_NEXT_REVIEW.md)
记录可选附件不应决定原控制库存、真实 Drive 构造与来源许可的待测假设。
该审查没有新增代码或通过结论。组件/full、P5、M2 按各自原要求齐备后验收。
M0–M2 完整后按用户要求先讲解模型，不以这两族替代整个阶段。
