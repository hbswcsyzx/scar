# 原存储访问的值关系：计划与验收门

2026-10-20。冻结基线 `5fd5a7f0b246f72ff708f53ba000728817a8feca`。
接 [上一门](M1_FRAME_IDENTITY_GUARD_NEXT_GATE.md)，仍属原 M0–M2，未关闭 F19 或整阶段。

## G0：合同审计与基线诊断

已核 StateAccess/StateAddressRefinement/ContentRead/WriteAssociation/BindingDefinition：
原存储访问没有 owned payload→槽内值→load own result 关系。环境 LocalBindingValue
不是堆字段；当前 state 和透明区间不自动给出这一关系。保存现有公开查询与原
字段清单诊断，区分“缺合同”和“已有合同但 native/source 依据未采”。

五类实体仍为 Operation / Value / StateLocation / Region / Resource。不另造 heap、
producer、state carrier 或全局 copy union；存储关系是原访问上的不可变附件。

## G1：类型、完成与 wire

新增两种声明，名称固定：

```text
StoredValueWrite(site, effect_index, payload, completion=None)
StoredValueRead(site, effect_index, result)
```

- site 复用 ExistingAccess / InvokeStateOperand，effect_index 指 refinement.effects。
  owner/path 不重复存储，原粗效果、coverage/effects_complete 均不提升。
- Write 表示**该完成的 post-state**中直接槽含原 owned payload Use 的值；普通访问
  completion=None，INVOKE 必须给本操作准确 ControlEdgeReference，可分别声明 N/R。
  未声明 R 不是回滚保证。普通 after 与 INVOKE 各 state signature/landing 从原图派生。
- Read 表示 own result 是原 **before-state** 下直接槽的值。result 复用
  OperationResult / InvokeLiteralResult；后者是已有的 completion-slot 记录，
  不要求该值为 literal。INVOKE 仅 NORMAL 存取结果，不把异常包当槽值。
- payload/result 仅 Data/Reference；不能是 state、protocol 或环境 binding token。
  原端口所有权、slot/landing 区分、真实 state before/after 全部校验。
- 这是显式直接槽语义声明，不从 ObjectField 名称猜 getter/setter。descriptor、
  自定义访问、slice/range 聚合或未知 owner/selector 不能因此变成直接值 copy；
  内部无法给 pre/post 合同的复合操作须保留边界或沿原 Region 展开。
- 新表 stored_value_writes / stored_value_reads 默认空，仅非空选择 Program27。
  原 1–26 字段/标签/字节含义不变；Execution8 不变。27 无能力、旧 wire 注入新字段
  和错 tag 拒绝。使用独立冻结旧 encoder 核 v26 字节。

## G2：实际派生连接

公开 `ExecutionIndex.stored_value_sources(result_site, occurrence, *, budget=4096)`。
必须是准确 own READ 结果及实际操作 occurrence，不能用期望 payload 反选来源。
先保原 read/write 声明和实际 operation 库存，再在同一总预算下检查所有实际候选。

每个候选要求：实际原输入/结果/当前 state；明确直接单槽；owner 有普通原 copy
或独立 scoped identity 支持，selector 准确相等；WRITE 选中其声明完成；从该 post
到 READ before 的原实际区间透明。复用已有 state_preservation，不让它负责解释
新 payload；中间新写会阻旧来源，其自己的 post 可重新建立新来源。

推导保持查询局部。来源值、原附件、地址比较、状态端口和区间证据分列；
“同对象”不等于对象内容不变。未知 alias/opaque/缺捕获/预算仍 Unknown；不同
Location 不当隔离证明。原 caller、selected CFG/loop visit、所有当前版本端口
各自验证，不按静态 op 或字典最后一项选实际来源。跨 call 复用完整展开与准确
CallActivation；不为该接口放宽普通 copy/compatible。

## G3：有限而有区分力的验收

- store P→load，后续 store Q→load：分别来源 P/Q，旧 P 被实际覆盖写阻断。
- 原真实 N/R 与重排 state/result ports；未采/非选中完成不能借另一边。
- 实际 branch/重复 loop visit 与两个相同 callee 的独立 activation；缺本实例
  association/Use/state 不借兄弟，完整分母不缩减。
- alias/opaque/未知 owner/selector、删除语义附件、tiny budget/截断，不能留下假 True。
- 原 wire golden 不变。旧 codec 测试只允许显式迁移“最大版本/未来版本/新空字段
  排除”的断言，保旧 wire=26（或更低）的检查。保存旧源码与 case-ID 迁移表，
  不把错误旧最大版本断言当产品语义回归，也不删除原义务。
- root 仅在全体源码作者 FROZEN 后串行执行；保存每次首败、准确源码、命令/JUnit。
  独立只读审查，自验报告、普通 commit/push 与远端 SHA/clean 核验。

所有自动 source/native/runtime 身份及 transformation 权限仍 False。M3/M4 自动
恢复、F19 历史消费者的后续整合、其非 finished/graceful/illegal-close 原组合、
其余七族/P4 component/full/P5/M2 原113构造/196字段及整阶段保持原分母。
不新增 detector/backend/LeWM 规则，不把手工供采当自动完整 LeWM 建图或加速。

## 所有权

A：stored_values.py 类型/validator、model.py、validation.py、codec.py、program 导出；
root：执行派生查询、公开入口、计划/归档/有限旧 codec 迁移/串行执行与 Git；
B：仅新增通用 fixture/test；C：独立只读审查。作者不运行解释器或 Git。
