# P4 查找失败：独立来源与三条 packet 路径

2026-10-18，基线 `8585d7f2aa013896fa58c3759d540338b78d43a5`。
上一轮为实际进展：通用 ExceptionMatcher、真实反例修复、880 affected focused
与 WIP 推送。继续原 M0–M2/P4；F12–F24/X25–X27 的 16 组仍全部 OPEN。

## 1. 模型与接口决定

Operation / Value / StateLocation / Region / Resource 不变。E0 是原注入整包，
EL 是本次 lookup RAISE 整包，EM 是本次 matcher RAISE 整包；不是三个别名。
仅 RawRequestTrigger 的 1–3 原参数不能确定 E0；扫描唯一 PacketConstruction
或从 true 实际消费者倒选 E0 均拒绝。

三路只读审查提出两种设计：复用 lookup case.trigger，或独立窄绑定。选择在
既有 protocol_bindings 闭合 union 中增加窄绑定，不增加新图表、不改变 lookup
零请求参数/无 trigger 的旧语义。该记录补的是 fallback 输入关联，而非查找的
实际参数或第二份 producer/state 图。

- `NormalizedThrowSource(raw: OwnedUse, packet: ExpectedSourcePort)`：独立保存
  原 raw 与已意图规范化的 whole packet。名字不是规范化已证；缺原构造/normalizer
  或 body-ingress 来源证据时保 `normalized_packet_source_unproved`。
- `DelegateLookupFallback(lookup: ProtocolOperationRef, matcher: OperationID,
  request: NormalizedThrowSource | InjectedPacketTrigger | StaticProtocolGap,
  guard: ControlEdgeReference | None = None)`。
- natural key 为准确 `(lookup, matcher, guard)`。规则由原 lookup 的 THROW/CLOSE
  种类及 selected RAISE 固定；不接受 NEXT/SEND、NORMAL 或任意用户规则。

source 可用性、receiver/source tuple 和 caller/CFG 相关性必须联合检查。THROW
只接受原 THROW raw；CLOSE 的 packet 是独立原边界，GeneratorExit 类别仍未证。
matcher source 必须来自准确 EL；Builtin AttributeError 只是条件解释，FactRef
或 enum 不授 native 身份。未知类别保 gap，已声明错误类别不得冒缺方法规则。

## 2. 从原图派生，不存 route 列表

```text
lookup 的自身 RAISE EL → 原 matcher input
  matcher NORMAL bool → 原 BRANCH
    true  → E0
    false → EL
  matcher 自身 RAISE → EM
```

实际 branch 的 0=true/1=false 沿 core 契约；matcher only-RAISE 不造 NORMAL
或 bool 分支。每一腿分别使用准确 lookup RAISE、matcher N/R、bool edge 和
case guard；不能把三种包 union 后 ANY 成功。每腿所有已知传播 frontier 都需
准确 source/current-copy。原 lookup/matcher/独立 source 再求值必须 cut，保本次
visit 缺口；普通 loop、opaque call、缺 consumer 或预算截断不当空成功。

公共查询遍历原位置、边和 owned Uses；收集 host RAISE、parent BodyResume 的
packet slot、fresh pending 与 active C1 action。复用 prepared index、共享预算、
source binding 和原 C1 验证。C1 active pending 由动作实际消费的 token 确定；
死 pack 不能解除义务或污染正确 active pending。C1 frontier 不冒到达 host；
若尚无准确 PendingPayload 投影，明确报告 continuation 未证。合法 finally 的
新 Return/Raise 是 OVERRIDDEN 边界，不强迫旧 E0 永远传播。后续 X25 的全部
dispatch/context/cut 闭环保持原义务，不能因当前 frontier 检查而关闭。

lookup RAISE 和真实 matcher consumer 先建立分母，再找可删绑定；删绑定、
matcher 附件或消费者 targets 仍 MISSING/具体 gap。多 matcher/多 guard 保全部
原输入与 incoming 分母；不得只选某个匹配路径。

语言规则依据 [PEP 380](https://peps.python.org/pep-0380/#formal-semantics)及
[Python 3.14 generator 方法](https://docs.python.org/3.14/reference/expressions.html#generator-iterator-methods)。
此处为普通同步 delegation 的结构连接，不将原生适用性当已证。

## 3. 自主关卡

| 门 | 必需证据 |
| --- | --- |
| D | 三路模型审查，记录设计取舍；独立 E0/EL/EM 与原 port/guard 不变量 |
| R0 | 真实旧 query 首红，不以新 API 不存在冒充 |
| C | CLOSE/THROW 1–3 args 原正常路径保留；三腿及同型错包、错 kind/lookup/handler |
| F | only-RAISE/删除/预算；opaque/循环 cut、active C1/死 pack 与 frontier 边界 |
| W | Program22 仅新绑定能力；独立旧21 encoder oracle，旧1–21字节与 strict 降级/假升级；Execution8不变 |
| V | 三路只读复审→作者冻结→统一 affected focused；原880义务及旧 fixture/证据守恒 |
| A | checkpoint/源码/保护 checkout 核验、报告与独立 WIP commit/push |

串行运行必要定向，保留每次失败。原 16 组全部就绪前不跑组件/full；不加
detector/backend，不跑重型 LeWM，不产生新加速比。新证据在
model_lookup_fallback/。完成本轮检查不等于完整 P4、自动 LeWM 建图或 M0–M2。
