# Running 嵌套体：依赖表达与 read-from/coherence 分界

2026-10-18；仅本批既有字段只读审查。新 fixture 不增加产品记录、producer、状态链或 execution 捕获。

## 原图中可表达且实际构造的关系

`ResumableCreate.captures` 将 root 的实际 holder Reference Use 绑定到同一个 canonical body 的 `resume.x` formal。成功 NORMAL handle 原 Value，经 `reentry.store.handle` Use 进入 holder WRITE；不是异常创建结果，也不是凭 source 名称查找。该 WRITE 的 `StateAccess.after` 是 root 调用 outer driver 的当前 world actual；Gate/BodyDrive/initial body entry 的状态映射沿原端口派生。body Attach 后 `reentry.holder.read` 实际消费捕获 holder 和 body 当前 world，产生一个原 Reference OperationResult；该结果的原 Use 是 inner Running driver 的 receiver actual。WRITE/READ 各自 `StateAddressRefinement` 保留自己的 ReferenceOwner Use、ObjectField selector 和原粗 StateAccess；不以 field name 推导 alias。

body 的实际 inner INVOKE 将各 N/R 的当前 world/context CompletionResult 送到独立 Attached landing，caller token 仅以 CFG owned edge Use 精确转发。RAISE landing 实际消费本次 packet，产生新的 continued Reference；原 CFG 将它送到共享 YIELD block，Detach 后 Suspend.exported 精确引用该 continued formal。实际用户体并非普通 callee；普通 INVOKE 的 callee 是专用 driver，其 BodyDrive 才指同一个 body 定义。

最终 fixture 在 RAISE landing 另保留一个原 caught-context 操作：消费本次 packet 和 completion 的当前 context，READ_WRITE 产生新 StateVersion；jump → YIELD 的 context formal → Detach 必须消费这个 after。它只声明无 callback、completion-preserving 的抽象 context 写，随后数据计算单独产 continued Reference。没有把完整 native except／用户 callback 混进 effects_complete；真实 native 对应及其它引用释放副作用仍未证明。现 C1 HandledContextRead 消费 SAVED_HANDLED_CONTEXT，是保存上下文的读取协议，不能拿来冒作接收 EXCEPTION_PACKET 的 install 操作，因此此处复用普通原 StateAccess，不新增类型。

## 为什么不伪装成现 content/provenance 证明

- `execution/content.py::ValueDenotation` 的 Reference 对应 `ObjectIdentity(ObjectRef)`；`content_validation.py` 明确拒 Reference 使用 `DataIdentity` 永久冒充内容版本。
- `ContentRead` 可以引用原 UseRef/AccessRef、当前 state support、StorageContent/EndpointContent，但 placement 是 materialization/内容选择；没有静态 heap 存入某 Reference Use 后，指定 later READ Reference result 的 read-from 字段。
- `production.py::WriteAssociation` 可保留 StateProduction 原 AccessRef 及实际 effect；`ValueProduction` 指动态原 ValueOccurrence，不能在此静态 fixture 自造 occurrence。
- ValueGraph provenance 的 inputs/outputs 是 `ValueVersionID`；将 Python 对象引用假装成 tensor/materialized pointer bytes 会混淆对象 identity、内容版本和存储。
- 若之后提供真实或明确 supplied execution，可给 Create handle 与 load result 的原 ValueOccurrence 各自声明同 scoped ObjectIdentity，并保留 basis/source；那是显式对应声明，不是 heap write→read coherence 推导。仅同 ObjectRef 也不能取代 state/source 闭合。

## 精确尚未证明的事实

上述 actual/formal、holder selector、stored-value Use 和 state 依赖都可表示/验证；当前产品不据此自动证明“这次 READ 必然取到刚才存入的 handle”、没有其它 alias writer、或确为同一个运行 body 实例。ReferenceValue.referent_identity 保持 None；StateAddress query 的 address_interpretation_verified/source_runtime_verified/transformation_authorized 均 False。手工声明和本地 CPython 重入观察不能弥补 native heap read-from/source applicability 的缺口。本 P2 可验收的结论限于这些明确条件下的静态嵌套路径，P3 occurrence 与整体 M0–M2 仍保留原分母。
