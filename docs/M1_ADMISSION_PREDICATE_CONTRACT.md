# P2 amendment：只读谓词、原分支与调用来源

2026-10-18，基线 `b88670b`。本文件是 [P2完整矩阵计划](M1_GENERATOR_MATRIX_PLAN.md)
中的字段收敛，不重写已冻结[P1原合同](M1_PROTOCOL_CONTRACT.md)。原五种contract
及Program17范围保留；新增能力选择Program18，实施前保存独立v17 golden。
本轮又发现一般仅RAISE调用的表达缺口，按[completion amendment](M1_INVOKE_COMPLETION_AMENDMENT.md)
将当前未发布18扩为 AdmissionPredicate 或 single-completion INVOKE。
本设计尚需产品验收；写下字段不代表完整 P2 已通过。

## 1. 为什么需要 amendment

基础合同能约束处理结果、packet 和 body/host 出口，却没有表达原状态读取、
该次 bool 与其控制分支的关系。一个有状态输入的 bool 结果并不自动表示
“当前 body 正在运行”。把 Closed helper 换标签也不能补 Running 的拒绝路径。

还有一个更基础的输入边界：读取 body 状态本来不需要 raw request；判断
`arg is None` 本来不需要 body 或整包 raw。不能为满足合同向原操作虚增 Use。
这要求分开两种只读 condition，同时仍引用原 bool producer 和原 branch。

## 2. 新增的最小 contract

```text
BodyStatePredicateRule = IS_CREATED | IS_RUNNING | IS_SUSPENDED | IS_CLOSED

BodyStateCondition(
    instance_use: UseID,
    state_sites: tuple[ExistingAccess, ...],
    rule: BodyStatePredicateRule,
)

ReferenceIsNoneCondition(input_use: UseID)

AdmissionPredicate(
    subject: BodyStateCondition | ReferenceIsNoneCondition,
    result: 原 OperationResult,
    branch: 原 OperationID,
)
```

它是 `ProtocolOperation.contract` 的第六种变体，outer.operation 仍为原谓词
操作；`result` 只允许它自己的 ordinary bool 结果，不复用 State、Protocol、
INVOKE completion 或任意等类型 sibling。`branch` 指定原 BRANCH，condition
Use 和两条 successor 从原 CFG 取，不新增边或另存 true/false 数据。

新增 variant 只允许在 body driver 的 RAW_ADMISSION clause 下使用。
本 P2 先支持同步 GENERATOR_BODY；其他 family 的适用扩展仍按 P4 逐项审查。
`ReferenceIsNoneCondition` 不吞掉原 binary IS_OP 的另一个 None 输入；原操作
全部 Uses/producer、效果及 source 仍保留，它只标明被检查的那个原引用。

## 3. 局部与跨记录校验

所有 ID/tuple/枚举保持严格类型和不可变记录规则。

- condition 的操作、result、branch 必须属于同一原 driver region；不得按相同
  label、bool 类型或结果内容猜 branch。bool 到 condition Use 要是本次 must-copy。
- result 必须是原 DataValue 的 `builtins.bool` 端口。错误 result owner、STATE
  槽、不同 bool producer 或不同 branch 的同类型输入是已知错接。
- BodyStateCondition 的 instance_use 是真实 owned Reference Use；state_sites
  是非空的原 READ access，不能写、释放、隐藏 callback 或另产状态。只列实际
  读取的域，不要求人为补齐整个 interface.lifecycle。coarse access.reference=None
  可以保留，不能假装已知道更精确的物理 owner/alias。
- ReferenceIsNoneCondition 的 input_use 是真实 owned Reference Use；原 predicate
  不读写 heap/state。不能把抽象 ExactData literal 当 Python 对象引用。
- predicate 的完整性是声明的只读原语条件，不证明某份 native/source 真实现了
  该原语；source/native 适用、运行对象 identity 和 purity 权限继续分开。

## 4. 当前状态支持与时间边界

predicate 的 READ before state 经原 CFG 到 branch 当前 state 的对应另行派生。
原数据与状态 Use 保序，parallel rename 使用原边；相同 StateLocation 不能替代
准确 version。未知 callback/写入后无法证明原 read 在 branch 仍 current 时，
返回具体 support gap，不断言 phase 一定改变，也不把合法历史 bool 程序判非法。
该 branch 不再凭这个缺支持的谓词获得“当前阶段”解释。

branch 之后可以发生规范化、异常构造或 callback。FinalBodyGate 继续独立检查
最新状态，NORMAL 唯一地进入原 BodyDrive；不要求 gate 前后 StateVersion 相同，
不把早先 predicate 的当前性延长成跨 callback 的永久资格。

## 5. 静态调用来源 recipes

driver scheduler 是原 entry 参数，raw pack 经常来自 caller，不能把 pack 结果
强塞成 entry。使用原 CALL/INVOKE 的 ordered actual/formal 逐层回查；每个实际
静态 call site 独立保 recipe，不 firstmatch caller 或把多源合成唯一值。

raw kind/ordinal/None 的已知事实仅来自相应 recipe 的原 pack/operand/literal。
Reference None 可用旧合法 LiteralOrigin(None)，或原 Reference producer 的
LiteralEvaluation；内容附件不删除原 producer/effects，不证明实际对象身份。
opaque helper/CompletionResult/动态 ResumeInput 缺关联时返回准确 gap。
回边旧 evaluation、递归和预算截断保留未处理义务/游标，不借相同 ValueID 填齐。
范围仅 supplied static callers；外部入口和动态 occurrence 另有未证条件。

## 6. 完整 P2 的消费者规则

本批必须从原 predicate branch、raw recipe 和实际 gate/body route 核对
Created NEXT/SEND(None)、non-None 拒绝后重试、Running 四请求拒绝、Suspended
NEXT/SEND/THROW/CLOSE、Closed 四请求。未恢复 source 不能删 scope/分母，也不能
把普通未解 bool branch 当作已经有当前阶段证明。

CreatedCLOSE 继续以原 CreatedCloseTest / NoBodyFinish 为权威，不增加第二谓词。
close 的 Return、GeneratorExit 消解、其他异常、非法 YIELD 与 retry 分别连接：
只有真实终结出口提供历史 F；host 报错和 body 终结不能互相替代。

## 7. 版本与验收

Program18 由新 AdmissionPredicate variant 或 single-completion INVOKE 选择；
没有二者的原 protocol 图仍为17。
新 nested subject/rule tag 在旧版本必须拒绝；不能靠字符串字面量碰撞检测能力。
Execution 仍为7，本门不提前实现 O 发生关联。

验收按父计划：精确 records/wire、原 bool/state/branch 正反连接、静态多caller、
完整16格和变体、旧声明兼容、共享预算与具体gap；最后一个组件门和一次干净
冻结全仓。原失败、撤回假设、native观察及产品结论分别归档。
