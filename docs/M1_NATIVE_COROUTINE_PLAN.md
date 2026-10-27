# 原 F14：native coroutine 的状态、调用与当前输入

2026-10-19，基线 `f26829c126f519043943af85c0faa62a9c76dd3b`。
上一门 VERIFIED_PROGRESS：1890相关测试、原1865精确身份保留、862稳定源码；
本轮起点重核 checkpoint。M0–M2全范围、原16族/P5/M2原113构造/196字段不变。

## 1. 从原图出发的设计修正

五类实体 Operation / Value / StateLocation / Region / Resource不变。沿原
Operation/Use、call/return、Create/Drive/ResumeIngress/terminal连接，不增
canonical phase/identity/state、codec、优化backend或detector。

前门 next-review 将 admission 路径误写为 `scar/ir/execution/admission.py`；
真实代码为 `scar/ir/program/admission.py`。旧冻结报告不覆盖，本门在此更正。
它目前提供历史READ/branch到gate快照兼容性，尚无动态native phase来源桥。

源码复核发现两项必须由新供图准确表达的关系：

1. 旧CHECK_SEND只有RAW+state实际参数，没有显式B operand→ownN copy。
   不能仅把caller raw operand改B就声称内层receiver是B。新增原Reference
   actual、RequestOperandBinding与真实knowncallee N/R，N出口返回原formal；
   沿ownN/准确landing→SENT_VALUE→inner receiver逐口核copy。
2. 旧两cut是YIELD，且第二cut没有THROWN_PACKET successor。native迁移须准确
   改AWAIT；后次THROW/CLOSE须新增独立private packet landing并保原saved/ingress
   端口，不能只改rawkind、共享第一landing或伪造运行中的cut。

## 2. 三种事实不能混用

| 事实 | 原合同与失效方式 |
| --- | --- |
| StateLocation内容 | generic state_preservation逐原效果；UNKNOWN/未隔离写/缺路阻断，不凭Location名隔离 |
| request当前P，例如COMPLETE | 原SessionPost/support；后续未知效果可失效；前门query保持原R3四阻断 |
| body终止历史F | 原DriverLifecycle显式scope下的fixed native/no-reset合同；原lifecycle_flow明确callback/newgate不撤销已经发生的terminal历史，但新Reference incarnation不继承F |

F的固定条件来自 `docs/M1_DRIVER_LIFECYCLE_CONTRACT.md` §1/§6，
`LifecycleScope.applicability=UNKNOWN`。不能人为新增monotone flag、把它
泛化到custom wrapper/native reset、或把它当任意field内容不变。跨调用的F
必须通过实际同B copy与原CallActivation桥重建，不能借另一callee的静态F。

Running则来自本次真实active Drive区间：准确entry→READ→该Drive首outcome，
同creation B与inner完整call ancestry均独立核验；不是前次AWAIT内容保持。
这些都是条件profile关系，source/native runtime与transform权限仍False。

## 3. 原五个场景与验收

| 节点 | 完整原场景与必须保留的反例 |
| --- | --- |
| N0 | 三方只读设计、原合同/源码/上一checkpoint核对，冻结本计划 |
| N1 | 共享native迁移与重新供采：COROUTINE_BODY_V1、两AWAIT、准确native return conversion；一个Create/持久B；原N/R/fullstate元组不改解释 |
| N2 | Running：三次真实Drive，两AWAIT；第二SEND把B经known normalizer ownN→SENT_VALUE→inner driver；READ在该Drive active区间，true拒绝helper/host RAISE后context RW/handler再AWAIT，第三Drive真正完成/最终提取；缺inner association/缺SENT_VALUE sourceUse不得借另实例 |
| N3 | 同B完成后NEXT/SEND(None) reuse：真实terminal/commit/转换/提取后继续forward B与最新states，再进入真实IS_CLOSED READ/branch/拒绝helper N/R；无重新Create/第二BodyDrive。F历史与普通内容保持分别列证据；callback历史bool控制合法但不能为当前gate提供快照 |
| N4 | Suspended THROW/CLOSE：两实际AWAIT及当前raw；normalizer ownN准确packet→独立THROWN_PACKET ingress，ownR自己的packet→host RAISE/fullstate。THROW保body RAISE，CLOSE保其自身Return/close adapter语义；旧packet/缺source不冒充当前源 |
| N5 | 派生body_state_history：原Drive/commit库存、实际occurrences、同B/来源、active interval或F历史、当前READ/ownbool/branch与每条gap独立；共享budget1/中段截断保全部原分母/游标，不授成功前缀 |
| N6 | 逐原F14条款独立核表；相关回归保原1890精确身份/全部旧tests/fixtures/schema；报告、checkpoint、commit与远端SHA核验。完整组件/冻结全仓/P5/M2仍需自己的验收 |

五场景是原F14残项，不是新简化分母。未实现的组合继续OPEN；只有原条款
完整证据匹配才关该条件结构门，不以source/native权限False反复重开已证结构。
反之不能把source/native权限False当作内部缺连接的通行证。

## 4. 接口与写入责任

root：NEW `tests/fixtures/native_coroutine_common.py`，提供
`native_resume_program(zero_cut=False, extra_creation=False)`、
`capture_program(program,details,...)`，从当前图重供采，不把旧snapshot改名；
NEW `scar/ir/execution/body_state_history.py` 和旧query.py只读入口、全部文档/
归档/Git与所有串行Python。无source作者冻结前不运行任何解释器。

A：仅NEW `tests/fixtures/execution_coroutine_running_graphs.py`、
`tests/unit/test_execution_coroutine_running.py`。
B：仅NEW `tests/fixtures/execution_coroutine_closed_graphs.py`、
`tests/unit/test_execution_coroutine_closed.py`，包含callback历史读取。
C：仅NEW `tests/fixtures/execution_coroutine_packets_graphs.py`、
`tests/unit/test_execution_coroutine_packets.py`。

作者必须在各自新图中保原opaque effects，不修改旧fixture来制造pure；只能
对新展开的真实knowncallee明确其实际读写。首测失败按构图/接口/产品分开留证。
协作者禁止解释器/pytest/probe/compile/Git；每次root运行前所有作者明确FROZEN。
任何角色改写其它文件先与root协调。新helper是测试供图工具，不是自动lowering。

## 5. 后续原范围

F16原R1/R2竞争、初始ASEND联合条件仍开放；前门P内容保持能力不被F特例放宽。
F18/F19/F20/F22/F24/X25/X26/X27继续各自原义务，然后P4组件/冻结全仓、P5及
M2原113/196总验收。建模阶段全部齐备后先向用户解释，再进入M3自动lowering/
M4真实采集对应。自动整个LeWM建图、可信TRANSFORM和新加速比仍未建立。
