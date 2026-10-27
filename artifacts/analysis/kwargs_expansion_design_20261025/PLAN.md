# kwargs 展开的最小实现方案

2026-10-25，DESIGN ONLY，待 root 审阅后授权实现。只针对既有四个真实 `Call(**mapping)`
首前沿，通用支持任意 mapping 值、多个 `**` 和交错 named keywords；首版不接 `*positional`、
comprehension、Try 或新解释器。原 typed ProgramGraph/Use/ReferenceValue/world/CallTarget
继续负责事实，不创建另一套 producer/use/state。第一阶段与动态语义完整性仍 OPEN。

来源为 [SOURCE_FRONTEND_NEXT_PROTOCOL.md](../../../docs/SOURCE_FRONTEND_NEXT_PROTOCOL.md) 与
[SOURCE_RECEIPTS.json](SOURCE_RECEIPTS.json)。本次只审接口、原诊断和两份小型 UTF8 快照 AST；
未打开 SG body/context archives、CodeType payload、raw，未运行 lowerer、测试或目标。

## 1. 精确首门范围

从原 `exact-ast-frontiers.json` 的 rows 机械选 `Call`、至少一个 keyword.arg=None、无 Starred
positional，得到 sequence 4/5/10/12；最后一项同 span 的 Expr 包装不应重复派工。两份归档源码
SHA/字节与原 receipt 相符，AST 独立重核。以下 calls=5 只是原诊断的既有 Run 权重，不是新采集。

| sequence / 原 body_key 前缀 | 原 Call span | positional 数 | keyword 源顺序 | 原 calls |
| --- | --- | ---: | --- | ---: |
| 4 / c355399c2069 | eval.py 22:12–22:67 | 0 | ** | 2 |
| 5 / 120960f8d4c1 | eval.py 58:12–58:58 | 0 | **、named | 1 |
| 10 / 31b5db542f49 | world.py 64:10–64:75 | 1 | named、** | 1 |
| 12 / ca14e20344a9 | world.py 614:8–614:40 | 0 | ** | 1 |

完整 body/work identity、原 source atom/fingerprint、body locator 和诊断 pointer 都在 receipt。
它们是审计期望，不作为手写业务名单：第一门以原诊断 predicate + 准确 AST span/SG Call
operator/输出槽重新选择，并与当前 inventory 的准确 source/context/body 身份核对。来源已变或
SG 不唯一即拒绝/保前沿，不能照抄旧 ordinal。仅派这四个仍失败的 body，每项至多一次；不
重 lower 已完成 tuple body、不扫全部 source、不扩大预算刷更多 UNSUPPORTED。

## 2. 已有接口及必须补的接线

| 真实接口 | 可复用及明确限制 |
| --- | --- |
| environment_lowering.StructuredEnvironmentBuilder.expr | 加 capability-gated Call 分支；原 Dict 仍走 lower_dictionary。 |
| structured_lowering.StructuredBuilder.invoke_results / finish_exit | 现成 NORMAL/RAISE 的 payload+各自 post-world、FRAME_EXIT；不能吞异常或把 raise 送回 pre-world。 |
| source_heap_lowering._hold / _source_definition / _associate | 原引用持有、缺旧 overlay 时按准确 SG atom 恢复；不是制造 StaticValue。 |
| source_mapping_lowering._transfer / BUILD_MAP / MAP_ADD | 复用有序持有实例转移与建精确 dict；现 validator 只准 Dict，不能直接给 Call 贴合法标签。 |
| source_slice_lowering._invoke | 复用 completion-specific consumed 形状，不把一个全局消费集合套给所有 primitive。 |
| source_semantics_v2 Call operands | 已有 callee/argument/keyword:name/keyword_unpack 及 expansion barrier；保留原来源，不迁移 SG 身份。 |
| SourceCodeEvidence + readonly CodeWitnessStore | 准确 original composition/code link、完整 describe_code、snapshot/definition 验证已实现；不编译、不执行。 |
| CallTarget / function_binding.bind_call | 保 callee 与候选调用接口；DOUBLE_STARRED 仍 INCOMPLETE，不凭静态 map 推实际 formal/value binding。 |
| source_tuple_validation 的 CFG pending dataflow | 可复用独立查询思路；现检查器专门核 tuple-key，不能把其返回值当 kwargs lifetime 已验。 |

现 `StructuredBuilder.expr` 与 heap recovery 都显式排除 keyword.arg=None。另一个实际拦点是
`source_environment_validation.validate_environment_body`：非自身 _KINDS 的 protocol 必须没有
semantic_operation。最终 CALL 必须继续连原 SG Call，因此这里必须加精确新 capability/protocol
分支；不能删此 guard 或把所有 call 都改成无 source 的 synthetic operation。

## 3. 最小公共协议，不增加图字段

建议显式 opt-in `SourceLanguageCapability.CALL_KWARGS_314_V1 =
PYTHON_CALL_KWARGS_314_V1`，新增三个 source protocol kind：

- `BUILD_CALL_POSITIONALS`：固定普通位置参数的 compiler tuple packing；refs+world → tuple+world
  或 exception+world。没有源码 Tuple atom，来源只能是原 Call，不能伪挂一个新 SG Tuple。
- `DICT_MERGE`：有序 callee、当前 exact kwargs dict、update mapping、world；normal 只返回 world，
  raise 返回 exception+post-world。callee 必需，CPython 用它格式化 kwargs 错误；不能省掉。
- `CALL_FUNCTION_EX`：原 callee、准备好的 exact positional tuple、exact kwargs dict、world；
  normal 返回 result+world，raise 返回 exception+world。这是 source call 边界，真实 target/
  formal binding、内部 effects 和运行身份仍未证。

复用已有 `BUILD_MAP/MAP_ADD` 构造 named-keyword run；只在新 capability 下由 call-specific
validator 接受 Call 来源。原 Dict 的 `DICT_UPDATE` 合同保持。空 positional tuple 若实际 compiler
为 LOAD_CONST，复用 `READ_CODE_CONSTANT/CodeConstantSource` 精确 co_consts 路径，新增受限
Call 来源检查；不可伪造成 BUILD_TUPLE 分配。非空固定 tuple 复用 BUILD_TUPLE 的 success-only
steal 合同；不引入 global tuple() 调用。遇 compiler 的其它 packing 形状保 CODE_VERSION 前沿。

优先不增加 SourceLanguageOverlay 字段：现有 PythonProtocol、OperationSource、UseSource 的
原 child/role/index、CodeConstantSource 与独立 AST/CodeWitness 足够索引阶段和顺序。
中间 packing/merge 为原 Call 来源的 synthetic protocol；只有最终调用连原 SG Call/Opcode.CALL。
callee、原 argument 和 keyword child 的语义来源经各自实际 Use 保留，bundle 引用不冒充
原静态单值。需要的新 shape 若实现中不能由这些记录无歧义核回，须另审明确 typed 字段和版本，
不能放 metadata。无需改 ProgramGraph schema 或另造 call IR。

扩展 EXTENDED_PROTOCOLS、structured validator dispatch 与历史 wrapper 拒绝规则；旧 v1–v4/v8
不得获得新语义。v5 只在明确新 capability + validator 存在时接受，旧 reader 会拒绝新 enum。
`SourceLanguageOptions` 当前默认 `tuple(SourceLanguageCapability)` 会随 enum 生长静默启用新
能力，必须改为显式原三项默认，新 cap 由此次 runner 明确选择。不能只长 enum 绕过验证。

## 4. 求值、重复 key 与异常

按准确 compiler 顺序：先求 callee，普通 positional 从左到右并完成原 packing，再处理 keywords。
named run 按源码顺序求值后建 subdict；遇 `**` 先提交前一 named run，再求 mapping 并 merge；
尾 named run 也先完整求值再 merge。比如 `f(**m, a=x(), b=y())` 的重复 a 检查不能提前到 y()
之前；任一步失败，后续 child/merge/call 都不能执行，已发生副作用/局部 dict 修改不可回滚。
原 callee 只求值一次（包括 `getattr(...)(**m)` 的内层 call），不能在错误格式化时重新求表达式。

[CPython codegen v3.14.7](https://github.com/python/cpython/blob/v3.14.7/Python/codegen.c#L3937)
决定 named runs、packing 和 DICT_MERGE/CALL_FUNCTION_EX；实现应以原 readonly CodeWitness
的 dis positions、ordered opcodes/arity、co_consts 和栈角色验证此对应，不能只搜一个 opcode。
原 store 的 runtime 为 CPython 3.14.7/conda-forge、magic 2b0e0d0a、marshal5；这不是当前运行
CodeType 实例或监控状态的证明。无准确 witness/不匹配即 CODE_VERSION 前沿，不新 compile。

| 方面 | kwargs DICT_MERGE | dict display DICT_UPDATE |
| --- | --- | --- |
| 同 key | 当前 accumulator 与本 mapping 内重复均可导致错误；使用原 hash/equality 语义 | 后值覆盖前值；不能借此实现 kwargs |
| 非字符串 key | merge 本身不能一律预先拒绝；最终 call/binding 保留 key 类型错误及 callee-dependent 路由 | 原 dict 允许 hashable 非字符串 key |
| 失败与 effects | 可调用户 keys/迭代/getitem/hash/equality，保部分修改与 raise world | 同样不纯；覆盖与 kwargs 错误合同不同 |

[dict_merge](https://github.com/python/cpython/blob/v3.14.7/Objects/dictobject.c#L3723) 的通用 mapping
路径先取 keys/iterator，逐 key 查重，未重复才取 item 并插入；重复 key 的第二次 getitem 不得
凭空执行。exact dict/subclass 快路不是强制调用 .keys()。keys 获取、不可迭代返回、next、getitem、
hash/equality 及 allocation 的失败都在 primitive 内，不伪造实际 key、value、内部调用或事件。
[FormatKwargsError](https://github.com/python/cpython/blob/v3.14.7/Python/ceval.c#L3223) 还会改写
特定 AttributeError/KeyError；不能笼统说所有 mapping 异常原样传播，也不能只硬编码重复 key。
[call.c](https://github.com/python/cpython/blob/v3.14.7/Objects/call.c#L1007) 的字符串 key 检查说明
不能在 merge 前挪动此错误、删除非字符串项或声称已绑定 actual/formal。原 post-world 承担这些
潜在 effects，effects_complete=False；未证的 state/alias/content/ready/finalizer 继续具体 OPEN。

## 5. pending 引用与 call 边界

独立核有序 hold 实例（FRAME_HOLD operation identity + Use），不以 ValueID 集合去重；外层
RHS/receiver/iterator prefix 必须原样保留。每个 child 成功立即 hold，后 child 失败仍归 FRAME_EXIT。

| 阶段 | NORMAL | RAISE |
| --- | --- | --- |
| positional BUILD_TUPLE | 转移其 elements，持有 tuple | success-only steal：elements 留 pending；不得提前丢引用 |
| keyword BUILD_MAP / MAP_ADD | 消费该 run 的 key/value；保 receiver | 依原 bytecode 完成 input cleanup；外层 prefix 保留 |
| DICT_MERGE | 消费 update；callee/args tuple/kwargs receiver 保留 | update 已 CLOSE；其余三者及外层 prefix 随 exception/post-world 到 FRAME_EXIT |
| 最终 call | result 发布一次，输入清理 effects 保在 call world | 不能无条件套“所有输入均消费”或“全留 pending” |

归档 [bytecodes.c](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L4858) 的
CALL_FUNCTION_EX 含早期 ERROR_NO_POP、普通调用清理、Python frame transfer 和后继 periodic
检查等不同路径。最小 source primitive 应明确采用“call + 其自有顶部 call operands 的异常
unwind”边界：raise world 在这些 operands 已清理后返回，只将 untouched 外层 prefix 交
FRAME_EXIT。早期 no-pop 路径是在此局部 unwind 内清理，不能谎称 raw opcode 已消费。
不展开 callee 内部解释器；所有 call 输入与内部临时结果的 cleanup effects 属于该显式边界。
若不能从 pinned primary contract 独立核此边界（含监控早期失败/periodic 路径），保
CALL_EX_CLEANUP_UNVERIFIED，禁止 full lifetime Verified；不得靠 self-reported consumed 参数
或 normal/raise 出口相减授予证明。可以报告 kwargs 准备协议已越过、后继 call/lifetime 前沿仍在。

## 6. 最小落地与第一门验收

实现改口集中于：新 `source_call_lowering.py`（固定无 * 的 pack/run/merge/final-call）、
`source_call_validation.py`（独立 AST/compiler/CFG/ordered pending 审核）；在 environment
expr、structured/environment/language validators 与 protocol/capability enum 连接这两者。
只抽取现有 mapping build/transfer 的必要共享 helper，不能把 dict display 全重写。现有
SourceProgram replay 是一项检查，不能作为 lowerer 自证的唯一验收；独立 validator 要核：
准确 source/SG 和 final Call 对应、callee唯一、child/merge顺序、exact kwargs receiver 来源、
原 compiler packing、两种 completion 自有 world/payload、失败未执行后继、pending suffix/prefix。
历史 cap/旧 wrapper 应拒绝新协议；错误使用 DICT_UPDATE 或丢 callee/重复 hold 必须可拒绝。

第一门 compile0/target0/prepare0，复用原 readonly 20-key archive，只打开两份既有 source context
及四个准确选中 body；每项一次，操作/时间/字节预算沿原 worker独立上限，超限留失败和精确
cursor/第一新前沿，不自动重试、不扩全 source。门前另冻结参与 producer、准确输入与 runner；
本设计不是该运行许可。只重试实际缺这项 capability、尚未成功的四项；若已有 accepted 新图，
先核准确 source/producer/capability 资格并复用，不再 lower。公开结构回读、独立 source/CodeWitness
核验与局部 pending 审核分别列结果，不预言四个 body 全成功，不因 UNSUPPORTED 消失便宣称
lifetime/effects 完成。实际 full call 关系与当前 Run 接线仍是后继独立义务，不借静态恢复制造动态值。
