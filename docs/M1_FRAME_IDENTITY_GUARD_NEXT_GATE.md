# 下一门：先界定存储值来源，再返回原 F19 组合

2026-10-20。原计划仍为 [M1_ASYNC_CLOSE_CONTINUATIONS_PLAN.md](M1_ASYNC_CLOSE_CONTINUATIONS_PLAN.md)。
本批当前对象身份接口不关闭 F19 第一个单位、整族或第一阶段。

## 1. 先分清已实现和仍缺的连接

规范实体仍为 Operation / Value / StateLocation / Region / Resource。身份、来源、
内容和时序是这些实体之间不同的关系，不通过新增业务节点混为一谈。

当前独立 `ObjectIdentity` 声明可条件性回答：这次 READ 看到的对象是否就是先前
已终结的 frame？它不回答：这个引用值如何经由 R 的字段和各次状态版本传来？
新接口也不证明两个对象的数据内容相等或恒定。

现有接口的准确边界：

- `RequestAssociationRead` 指定当前 request Use 和 own body/latent 结果，不承诺
  创建后字段保持不变。
- `StateAddressRefinement` 指定 owner、selector、mode 及覆盖度，不指定写入的
  Reference payload 与后续 load result 的值关系。
- `ContentRead` 指定 consumer、placement、effect、anchor 和 state support，不是
  通用 Python 堆字段的 store/load 值传递合同。
- 原 Use/CFG/call copy 保留本义；对象身份比较不能给它补一条假 copy 边。

## 2. G0：已有合同审查结果与下次设计输入

A 已只读审查上述合同及 `BindingDefinition` / `BindingRead`：后两者的 payload
关系限定于 `LocalBindingValue` 环境 slot，不能拿来表示对象字段；校验还限制这些
binding token 穿越普通调用。`StateAccess.reference` 是访问引用，不是所存 payload。
`content_validation` 仍明确记录 `content_state_version_unverified`。因此不是漏用
某个已经完备的 stored-value 合同，当前确有类型关系缺口。该审查没有运行解释器
或新增手工图；原注入身份分支本身不要求立即补完所有 heap 语义。

下次先设计并审查**原访问 site 上的存储值关系**：精确引用 refinement 的 effect
ordinal、store 的原 owned payload Use、load 的 own result port，复用原状态 SSA。
normal/raise 各自在哪一版本建立事实、调用展开怎样传递这些事实，以及 descriptor
和普通槽的界限，都必须先确定。不另造 heap 图或可修改 producer/use。

据此核现有初始化、显式 store、load 和可能干扰操作的原端口，给出最小例子的
逐边解释：`store(owner, selector, payload, state0) -> state1 -> load(...) -> value`。
必须区分以下情形，不能从名称、观察到的 bool 或期望结果推导 load 值：

1. 同 owner/selector，准确 payload 和当前 state，区间没有可能改写：可有条件
   推导原 Reference 的来源，但不能顺带推导对象内部内容保持。
2. 中间实际写为另一个 payload：旧来源失效，采用新版本的来源。
3. 可能 alias 写、descriptor/自定义访问、未展开调用、外部/native 写或未知覆盖：
   保留准确阻断点，不凭 host 顺序推字段不变。
4. 跨分支/loop/call 的 state 合流：保留全部原候选及 guard；只在必要的来源分支
   均支持时得出 must 结论。不能借用另一实例的完整证据。

先判断已有合同能否表达这些关系。若确实缺少“存储的值是什么”的接口，先写
类型、normal/raise 端口、版本转移、失效规则和迁移说明，再实现最小通用合同。
不能直接给 async request 追加 immutable 假设，也不另造可修改的 heap/copy 图。
自动从源代码/运行时恢复属于 M3/M4；供采声明的正确查询属于当前 M1。两者分别报告。

## 3. G1–G3：有限实现、自验与返回原单位

只复用目前已有的实际 terminal/new-request/current-state 组合：

- 先在冻结基线复现缺口，再实施；正例和上述有区分力的反例使用同一通用合同。
- 原无身份声明用例保持未知，除非新接口独立提供了足够的实际存储值来源证据；
  如果必须迁移旧期望，先记录旧 case、原义和新增证据，不能直接改成绿色。
- 独立审查后，root 串行运行直接受影响的选集；保存首败、原始源码、命令及 JUnit。
  不因为一项未通过而扩大到无关的全乘积。
- 若审查确认当前只缺实际 native/source 对应，则登记该边界，停止为它增添手工图。
  返回 F19 剩余的非 finished 路径、graceful close 的 AWAIT/HOLD 两层回复、
  illegal yield 后 same/new R、finally、真实 F 与 release。各自当前状态和 own N/R
  端口仍独立验收。

## 4. 完整分母保持

F12/F13/F14/F15/F16/F17/F18/F21/F23 九族和 await A–H 保持限定接受；
F19/F20/F22/F24/X25/X26/X27 七族、P4 component/full、P5 和 M2 原
113 构造/196 字段仍开放。完成原 M0–M2 后先向用户解释类型及连接，再进入入口
驱动的 Python shell 与 FX/Export 子 Region 自动恢复。当前不增加 detector/backend，
不声称自动完整 LeWM 建模、可信变换或新加速比。
