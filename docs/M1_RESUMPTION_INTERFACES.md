# C2：可恢复 body、驱动协议与跨挂起依赖

2026-10-17。**架构审查与实施合同；C2 产品接口尚未实施，C2.0 字段冻结门仍未关闭。**
基线 `fec9f5b`；现产品仍为已验收的同步 core/C1、schema v9。本文件不是新 schema、
自动 lowerer、trace adapter、detector 或 backend 的发布声明。第一阶段仍未完成。

## 1. 这批模型要补什么

同一个可恢复函数涉及不同身份：代码定义、创建出的对象、持续的 body activation、
一次驱动请求、实际 body 恢复、一次 suspension generation、驱动的 host 返回。
它们不能用同一个 RegionID、调用次数或 `NORMAL` 标签替代。

```text
参数求值/绑定 → Create → resumable 对象/初始私有 frame
对象 + request + 当前状态 → driver 协议/状态检查
    ├─ 拒绝：本次 host 失败，无 body entry
    ├─ 委托：可能直接产生 host 结果，也可能稍后进入父 body
    └─ 真正开始/恢复 body → 执行 → Suspend / Return / Raise
                                      ↓
                           具体方法的 host outcome adapter
```

创建不执行 body；接受请求也不必恢复父 body。每次真实恢复接保存的私有值、
当时共享状态和实际交付的输入。body 的 `Suspend` 不完成函数或最终释放 frame。
host 正常返回不证明 body 正常 Return，更不证明 GPU/文件资源 ready。

五类核心实体不变：Operation 表示 create/drive/协议/数据操作，Value 保留数据、
引用、binding 和协议值，StateLocation 表示可变内容与生命周期，Region 展开 body
与 driver 子区域，Resource 承担物理实现。新增的是有类型的连接规则，不是业务节点。

## 2. 架构决定：一个逻辑 body，显式 temporal successors

选择 A：一个逻辑 body Region 保持唯一规范 producer、Uses、CFG 和词法 scope。
新增的 Suspend 必须有自己的 typed terminator，区分对本次 driver 的 handoff 与
未来恢复边。它不是 RETURN、RAISE、普通 JUMP 或立即继续执行的保证。

每个恢复 case 使用独立 landing block，不接普通前驱；处理后可沿普通边合流。
真实端点是既有操作的 owned UseID 和目标 BlockArgument：

- 保存值沿 explicit saved Use → 新参数传递；引用传递不恢复对象内容。
- 本次新输入使用有 signature/slot/role 的 `ResumeInput`；它不能包装旧 world。
- 每个共享 StateVersion 参数来自实际 body ingress 前、context 安装前的 ResumeInput：
  必须包含 gate、delegate callback 等已经发生的全部效果后态，不能复用最初 gate
  的旧 world。所有实际安装/卸载的后态继续用 StateAccess/results，不混淆阶段。
- LocalBinding 的 unbound 状态、临时值、求值栈、delegate 引用及 pending/context
  都有保存角色；类型从现规范 Value 和参数取得，不另存一份 actual/producer。
- request/frame 协议参数不是新的 Python formal。原 FunctionEntryLayout 不静默放宽；
  Start 按 creation 保存的引用/环境及首次驱动的当前状态填原 body entry。

B 的 dispatcher/分段 Region 只保留为后续 lowering/执行投影；必须由 A 派生并保留
原 body/activation 对应，不能生成另一套可修改的依赖或在恢复段伪造新 CleanupEnter。

### 2.1 同一边记录，两个派生查询

1. **logical CFG：**包含 temporal 边，判断结构可达性、持续 cleanup activation、
   原 pending/context 转发和 entry-relative freshness。
2. **availability：**以原 entry 和每个 resume landing 为定义可用性 roots。只有
   在本段定义、经保存槽接成新参数或由 ResumeInput 提供的值可用；LiteralOrigin
   可保持全局可用。不能沿普通 dominance 直接读取挂起前未保存的结果/入口参数。

所有普通合流、循环回边和多次暂停都参与检查；只检查 landing 第一条 use 不够。
C1 freshness 使用 logical CFG，不因 availability 新 root 而重置：在 Enter 后、
暂停前构造的 replacement，恢复后仍可能属于同一次清理激活。

本轮 `availability-probe.py` 在现有合法同步 loop fixture 上运行了5个设计检查：
普通图、缺保存槽、显式转发、第二个 cut 暴露传递缺口、两处均转发；结果均符合预期。
这些假想 cut 不是产品的 Suspend 记录，也没验证 shared-state/context 或 C1 组合。

## 3. 当前状态、context 片段和本次 caller token

私有 frame 保存的是引用/协议关系，不能保存并重放共享 StateVersion。不能凭
`INTERNAL` 或 location 名字宣布某个 coarse world 为私有；owner/escape 精化另验收。
挂起期间 caller 可修改 Tensor、NumPy alias、cell、global 或容器；恢复读取当前版本。

异常上下文至少区分：

| 内容 | 归属与含义 |
| --- | --- |
| frame-owned handler/context 片段 | 可跨挂起保持；包含可重定位的“继承本次 caller”边界。不是 `sys.exception()` 的扁平结果。 |
| C1 saved-context / pending | 原 CleanupEnter 的持续私有锚；暂停不 pop、不重 Enter、不重 pack。 |
| 本次 driver caller-context token | 只用于归还该次 caller；不能放入下一次挂起的保存槽。 |
| 当前可见 handled exception | 从已安装的 frame 片段与本次 caller、当前状态读取；不是以上任一 token 的别名。 |

本机3.14.7见证确认：无自身 handler 的 generator 随不同 caller 看见不同异常；
自身 KeyError handler 可跨 yield 保持；退出自身 handler 后重新继承 caller。
pending Return 的 finally 也可能看到 caller 的活动异常。
源码依据为 [genobject.c](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L225)
与 [errors.c](https://github.com/python/cpython/blob/v3.14.7/Python/errors.c#L108)。

### 3.1 统一的 Attach/Detach 合同

拟议 Attach 在真正 body 初入/恢复 landing 捕获**本次** caller token，以规范结果
产生它，再把 frame 片段接到当前 caller。ResumeInput 不另外生成另一份 caller token。
初入使用 INHERIT 片段；恢复使用保存片段。Detach 保存 body-owned 片段、归还本次
caller；保存片段可跨 temporal 边，caller token 不可。

二者是无用户回调、completion-preserving 的抽象协议 intrinsic，只操作声明的
context 状态域；coarse 域仍按实际覆盖保守读写。真实引用管理、lookup、hooks、
释放失败等必须独立建模，不得塞进该 intrinsic 后漏掉异常/部分效果。真实实现
若不满足合同，就不能宣称与此 primitive 对应；未返回也不推导已完成 handoff。

必须有全 CFG attachedness 检查：Detached → Attach(t) → Attached(t) →
Detach(同一个当前 t) → Detached。Attached block 携带唯一当前 caller-token 参数，
普通逐边实际操作数精确转发到该槽；不能只比较 constructor 集合。Detached landing
不接旧 caller token。实际 body 用户操作仅在 Attached 段；Detach 到 terminal handoff
之间只许规范转发。真实异常的 packet/chaining 在正确上下文完成；host adapter
自己产生的错误则在恢复 caller 后按该方法规则处理。

### 3.2 委托 fast path 不先安装父 context

新增4组3.14.7独立见证确认：父 generator 在自身异常 A 中暂停，caller 处于异常 B；
普通 next/send 时 delegate 的方法看见 A，但父 throw/close 的直接 delegate callback
看见 B。delegate.throw 可直接给 caller 新 item；父 body 只有在确实被恢复时才 Attach。
不能把所有接受的请求先接父 landing、再统一调用 delegate。

因此 **drive epoch 与 body suspension generation 分开**：driver 执行了委托协议
不证明父 body continuation 已消费。父 continuation 未恢复时可继续保持；实际 body
恢复仍不得复制执行同一 generation。具体实例/互斥/代次匹配属于声明 gate 与后续
运行证据，不从静态 site 或 use 数证明。

## 4. frame 生命周期的组合缺口

旧同步 FrameModel 的 `FrameExit` 必须紧邻 RETURN/RAISE；不能再要求同一出口的
另一个 Detach 同时紧邻 terminal。更不能为了满足两条邻接规则就把实际引用释放
全移到 body context 中。

CPython3.14.7 的实现先恢复 caller exception state，再清理 generator frame，见
[ceval.c](https://github.com/python/cpython/blob/v3.14.7/Python/ceval.c#L1835)。这是版本化
实现依据，不是本轮实际 finalizer 见证。C2 必须拆清：body completion、Detach、
driver/host 阶段的 frame-release/最终化及其状态/异常历史。Suspend 不做最终释放；
正常终止后的释放也不可直接套旧同步 FrameModel。现旧 reader/规则保留；C2 新
生命周期 profile 及其与 finalizer 观测的对应仍待实施和验证。

## 5. 代码前需冻结的字段与验收顺序

字段应引用规范 IDs/Uses/端口，不引入可写 verified/authorized 位：

| 门 | 必需交付和拒绝条件 |
| --- | --- |
| C2.0 合同冻结（进行中） | Create/Start/driver 与实际 body ingress 分开；accepted 无 body 路径；typed Suspend/Resume signature/slot、附着状态和生命周期阶段。exact records、driver→body 映射与跨域状态来源尚需最后字段审查。 |
| C2.1 类型与规范连接 | 新 capability、严格 source/owner/site/layout；saved Use→formal 与 ResumeInput；没有第二份 producer/实际值表。旧 schema 拒绝新能力。 |
| C2.2 可用性与状态 | 上述双投影；缺保存、循环/多恢复合流、旧 world/旧 caller token 拒绝；所有当前共享域完整接入。 |
| C2.3 context/C1/frame | Attach/Detach 全路径配对，继承片段，原 pending/context/freshness，活动清理不 pop；独立处理真正结束后的 frame release。 |
| C2.4 协议适配 | Next/Send/Throw/Close、generator/coroutine/asyncgen、委托与 await；request 创建/接受/交付/实际 body entry/host 结果分开。按控制分册§7保留全部家族与失败路径。 |
| C2.5 公开自验收 | codec/query/CLI、独立反例、冻结源码后单次全仓与报告；手工 IR 不计 source/runtime 自动恢复，不授变换。 |

C2.4 不能缩成只有一个 yield 数值：首次非法 Send/reentry 不进入 body；Close 失败
后不一定 Closed；正常 Return 和主动抛 StopIteration 分开；asyncgen request-awaitable
创建不驱动 body；await 可零次挂起；取消请求不证明异常已交付或 task 已结束。
委托的 sent/returned/failed 路线必须接具体当前状态和真实 ingress，不能按方法名
或词法包含补猜。未知实现保留有类型的保守 normal/raise 边界，不吞掉周边结构。

详细分母复用[控制协议§7](model/PYTHON_CONTROL_PROTOCOLS.md)；不重新设计语言或
重跑已有17组见证。复用 inspect/dis/sys.monitoring 的现有状态、code 与事件事实；
FX/Export 只提供自己的子图。模型阶段不扩大 source lowerer、Tensor tracer 或 backend。

## 6. 本轮交付和权限边界

[证据目录](../artifacts/experiments/b1_call_operands/model_resume_interfaces/README.md)
保留3份独立设计审查、语言见证、设计投影探针与新发现的组合约束。初批为23组动态
观察、4种静态code shape；另有4组委托context观察、5个availability设计检查。
观察组不是断言式测试；设计探针不是 C2 validator 实现。完整请求×状态、实际
finalizer、实例/并发、源码到 IR、ETO 或 GPU 均未据此验收。

当前仅 C1 代码已验收并推送；本批 C2 仍是规格工作，源/测试产品指纹保持不变。
完整 M0–M2、自动 LeWM 全过程建图、具体化简与加速比仍未完成。不会以某个子门
通过改写第一阶段的完成条件；满足完整清单后才停下来向用户讲解。
