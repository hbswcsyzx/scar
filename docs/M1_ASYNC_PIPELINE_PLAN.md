# P4：连续请求、handoff 与本次 session 的组合

2026-10-19；基线 `a5ff0f937015c225ba5d46c71bdc4e75866316d4`。
上一 goal turn 为 progress：packet continuation、1032 affected focused、归档推送。
原 F12–F24/X25–X27 的16组、P5/M2和完整第一阶段继续 OPEN，不缩减原分母。

## 1. 从类型与连接审查得到的任务

Operation / Value / StateLocation / Region / Resource 五类不变。BodyDrive 是原操作，
BodyDriveExecution 是其真实/声明 occurrence 与持续 activation/segment 的关联。
SessionUpdate 是已有操作上的状态后态约束。R=request、B=body、L=固定latent请求、
S=本次scheduler请求，都是原端口角色，不增加另一套 phase、epoch、permit 或 SSA。

三路只读源码审查发现的机械缺口（尚未全部运行复现）：

1. `protocol_validation.connection_errors` 只核 YIELD→host RETURN exact copy，
   AWAIT 的原 export→scheduler/host handoff 尚未获得同等消费者检查。
2. `protocol_async.session_outcomes` 从 update 表枚举义务。删 update 与附件后，
   原 AWAIT/ASYNC_YIELD 仍在，却没有逐 source 的“缺少 post/消费者”库存。
3. 旧 `ctx.reaches` 仅 may-reach，不能作为“本次结果”的证明；共享 update 的
   incoming/context 要逐来源联合核，不可把不兼容分支拼接或任意选一个好来源。
4. P3 body query 有 actual drive/entry/outcome/owner，但没有其准确 SessionUpdate
   occurrence、R/B Uses、post-state及host handoff。静态标签不能补这条动态连接。

F12/F15 wrapper iterator→body projection仍是另一真实欠账，不在本轮偷改为普通copy。

## 2. 本轮完整程序图

```text
实际 caller：Create B → Create R(L)
  → INVOKE R/S0 → Start B → AWAIT1 → HOLD → host RETURN(awaitable1)
  → INVOKE 同R/S1 → Resume(AWAIT1) → AWAIT2 → HOLD → host RETURN(awaitable2)
  → INVOKE 同R/S2 → Resume(AWAIT2) → ASYNC_YIELD
     → COMPLETE(R) → 原item adapter/packet → 实际host consumer
```

三个 driver 调用各有自己的 activation。B 只有一个持续 activation、三个 segment；
本次 ResumeIngress 精确引用前次 Suspend occurrence/edge。R 用原 forward Uses
从同一个 Create NORMAL 结果传入，各次调用传最新完成状态；S0/S1/S2 各为准确
原 pack，不能拿 S 冒 L。最终 request item 可以用真实 RAISE StopIteration(item)
adapter；不为使流程好看改成虚假 NORMAL。R COMPLETE 不等于 B 终结/释放。

另建一个同源共享 HOLD update 组合：两条真实 AWAIT frontier 的私有 landing
经准确 JUMP/incoming 与 R/B/state 并行传递，合流后一个真实 update。不能用
跨调用两次旧 AWAIT 充它的 incoming，也不在一次 native request 调用里凭空串
多个 scheduler step。所有例是供应 IR/执行记录；不冒 native 源码等价证明。

## 3. 产品接口与不变量

### 静态来源与消费者

- 从原 scope 的每个 BodyDrive/outcome 派生 session 来源义务，再查 update/
  AsyncSessionOutcome 附件。删除整张 update 表不删除 source；budget1仍保原
  source inventory、NOT_CHECKED/cursor，不只给空结果。
- 现 `session_outcomes` 原 update 收据继续保留；新增 `session_consumers` 为
  每个原 `(scope, DriveOutcomeRef)` 的派生结论，至少含 expected post、原
  targets/update、条件/缺口、完整性和cursor。它实际接入 async report/errors/
  obligations，不是孤立 getter。native/source 未证与机械连接分开。
- 来源到 first post/consumer 的规则遵循原 selected edge、合流incoming与本次
  caller；下一 Drive/新独立来源不能沿 may-reach 冒旧结果。shared update 的
  相关 R/B/当前state/source 整组核，每条适用 incoming 都保留。
- AWAIT→HOLD；ASYNC_YIELD→R COMPLETE/B暂停；其他 terminal/classification/helper
  的原缺口保留，不删除 unproved 文本冒作语义实现。当前 P 在callback/call后
  仍按原 session_flow 失效，不新增跨调用保活规则。

### 执行证据与组合视图

- 扩展现 `ExecutionIndex.drive_execution` 的启用 async 情形，返回原实际
  Drive/outcome对应的 `session` 组合收据。无新 canonical record/schema；普通
  body 路径保旧能力，不因新查询制造调度或原操作。
- 由原 occurrence/activation/segment、actual ControlTransfer/selected successor
  和同次 driver 后继定位 Update occurrence，不能按 OperationID/类型/唯一可见
  候选猜绑定。原静态消费者分母即使该 occurrence/关联缺采仍保留。
- R 与 B 分别比较原 UseOccurrence/ValueOccurrence，复用原 CFG/CALL/body copy
  predecessor、fresh scoped denotation compatibility。中间 copy 的已知冲突也
  必须拒绝；只比较端点或相同静态 ValueID 不够。新的必要ancestor加入原索引，
  不造第二图、不保存逐迭代 Tensor 数值。
- actual update 的 AFTER_OPERATION 与 NORMAL_COMPLETION 分开；后者只有本次
  NORMAL授post，RAISE保准确packet和所有partial state。输出到 caller 再到下一
  driver 的状态是原返回/实参路径，不是复制一份 session/world 状态机。
- 使用原一个预算；准备/外部刷新/detach成本分列。截断保原job count和位置，
  missing/unknown/CONFLICT区分，缺采不冒 dead work。全部运行/source/native/
  identity/transform权限仍未证明；没有自动恢复/LeWM优化/新backend。

## 4. 自主关卡

| 门 | 必需验收 |
| --- | --- |
| D | 三路源码审查与本计划冻结；现有模型足以表达，无新wire/state图。 |
| R | 既有公开 async/validation 上复现 AWAIT wrong host 或 update删除分母缺失；core-valid，不以新字段缺失冒首红。 |
| S | 来源先于update；shared incoming全覆盖；wrong R/B/source/遗漏/预算；AWAIT handoff和item消费者分开。 |
| P | 同一个真实 caller/B/R 三CALL图及原 N/R/state/post/adapter，不能把三个旧图并列计组合。 |
| E | 同一B activation三segment的P3完整模型；session/update/host发生对应，wrong instance/request/outcome/旧state/缺采反例。 |
| V | 独立复审→冻结所有作者→一次统一 affected focused，保前1032项及新增必要P3旧覆盖；原16组未齐不跑component/full。 |
| A | 原失败/旧fixture/合同/wire/保护目录守恒、报告、commit/push/远端核验。 |

若公开查询旧case断言需因正确扩大消费者范围而迁移，保ID和原义务，写精确原因。
不为凑全家族关闭而放宽断言/改旧fixture/提高旧预算。

## 5. 分工及后续

A拥有静态产品 `protocol_validation.py`、`protocol_async.py` 及确需的单独来源
解析模块；B拥有新的 static pipeline fixture/tests；C拥有新的 execution fixture/
tests；root拥有 Execution 组合桥接/原P3 hook、证据与集成。先协调原端口/API，
不同文件所有权；子代理不运行Python/tests/probe/commit，root串行执行并保每次失败。
证据写 `artifacts/experiments/b1_call_operands/model_async_pipeline/`。

本门闭合上述连续组合单位，不代替整个 F13/F16/F17/X26/X27 的所有原格。
其余 family/phase/normalization/cancel/source/occurrence仍逐项保OPEN；全P4后再
统一component/frozen-full、P5、M2原113构造/196字段，完整第一阶段后停下来讲解。
