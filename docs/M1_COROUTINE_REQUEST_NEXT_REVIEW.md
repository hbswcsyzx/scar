# 下一有限门：原F14/F16的确切结构接缝

2026-10-19，只读审查。原16组分母、P5与M2原113构造/196字段保持。本文件
没有新运行、没有产品实现或关账声明；当前门结果另见
[M1_AWAIT_SOURCE_FAMILY_ACCEPTANCE](M1_AWAIT_SOURCE_FAMILY_ACCEPTANCE.md)。

## 1. 已有基础不重写

F14已有program/execution_await_wrapper_final的native COROUTINE_BODY_V1、
零/两cut、持续B、准确entry/outcome/state/final结果。本轮又补self无W路径。
parent_resume的四种非state原slot已有准确typed恢复。profile/codec准入不能
冒充phase语义；generator矩阵也不自动代验coroutine。

F16已有program_async_connections四种NEXT/SEND/THROW/CLOSE的原Create、
独立R/B/latent L与首次normalized packet/RAISE state，外来R的独立来源可
明确保gap。program/execution_async_pipeline已经是**同R/B三次真实调用**、
三个CallActivation/Drive及最新state、HOLD/HOLD/COMPLETE；旧台账“没有
真实多调用”应收敛，不再重复构造这个基础。request_admission已有current
COMPLETE/ref、callback历史谓词与当前资格分离，但不是完整实际reuse链。

## 2. 原F14确切欠项

复用已有native coroutine完整驱动图，在原READ→bool→BRANCH真实控制上补：

- 同一B的Running重入；不能用两B同类型或core非法segment替代。
- 本次完成后同B再次使用，不能通过重新Create绕过reuse。
- THROW/CLOSE的当前输入packet、结果与post-state；别借generator协议表。
- callback后旧predicate仍是合法历史控制，但不足以支持当前gate资格。

先对照原Phase/Admission/NoEntry/driver接口，寻找可复用记录。只读未见必须
扩schema的阻断；真正供图/运行发现无法表达才记录原端口后决定。不以native/
source authority=False重开已核结构，也不以same-type布尔值猜新phase事实。

## 3. 原F16确切欠项

1. 前次真实COMPLETE→同R后次调用→当前read/branch→拒绝，保原R/B与状态。
2. 独立R1/R2关联同B时的竞争和当前拒绝路线，保每个request的来源与latent。
3. 首次ASEND：R initial与B Created是独立条件；nonNone SEND的合法/拒绝
   路线必须由原参数、read及branch联合决定，不能只有rule enum。
4. 后续scheduler S的THROW/CLOSE packet。明确源码缺口是protocol_async的
   async_scheduler_packet_normalization_unresolved；现NEXT/SEND后续来源
   已有。沿原scheduler request tuple/normalization端口接当前packet，不能
   回借首次latent L，也不把request R、body B、scheduler S合并身份。

四种来源的基础不重新铺大矩阵，剩余格先最小完整图及准确反例。缺采、旧state、
预算和detach使用已有pipeline/admission证据，只在新接口有实际风险时补。

## 4. 顺序与验收边界

先核原条款与这些具体残项→明确端口及状态关系→冻结有限计划→最小真实首测→
只修失败公共关系→独立核表→必要定向/归档/版本。所有Python/pytest/probe/
compile仍由root串行，所有作者冻结后才运行。不要让一个缺少桥接的真实反例
变成另一个更容易的例子；不删除原分母，也不无限新增未要求的参数乘积。

其余F18/F19/F20/F22/F24/X25/X26/X27仍须自己的原义务；之后P4组件与冻结
全仓、P5、M2完整总核。模型阶段齐备后先按用户要求解释，再进入M3/M4自动
lowering及实际采集对应。没有新增backend、LeWM特例或性能结论。
