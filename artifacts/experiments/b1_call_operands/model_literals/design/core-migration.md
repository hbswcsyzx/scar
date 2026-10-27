# L0：PythonLiteral 接入 canonical core 的迁移审查

基线：干净 `13201ad24e0d8236623e28709f86e13a887ed4fb`。**Proposed，未实施；只读源码及官方材料，没有运行 Python、pytest、full、workload 或采集。** 本文只写此新 ignored artifact，不修改旧归档/产品。

## 1. 决策：保留 legacy，分别表达内容与对象求值

推荐保留 `LiteralOrigin(value)` 的旧字段、类型限制、行为和 wire；新增独立、非继承的 `ExactLiteralOrigin(literal: PythonLiteral)`，但**只允许 DataValue**。新 Python 对象求值必须保留原 OperationResult 或 INVOKE 的实际完成端口，另附 LiteralEvaluation payload，不得把 ReferenceValue 改成 activation 预装常量。

这是当前模型的实质约束：`execution/flow.py:153–171` 将 literal 值按 activation 预装；`program/validation.py:415–425` 让 literal 绕过普通 dominance/availability-root 检查。若直接把新对象 origin 放进该分支，loop 重复求值、两次 LOAD、yield 前后对象 availability/身份就可能被错误合并或提前提供。即使 payload 相等，实际对象也不必相同；也不能反向宣称每次一定 fresh。

| 方案 | 结果 | 建议 |
| --- | --- | --- |
| 扩 `LiteralOrigin.value` union 接 PythonLiteral/raw bytes/tuple/complex | 旧 `{"value": ...}` 形状含义改变；新内容可潜入 v1–15；`.value` 消费者将 descriptor 当 raw Python 值；继承 literal availability 的对象问题仍在。 | 拒绝。 |
| 新 ExactLiteralOrigin 同时允许 Data/Reference | wire 可区分，但新 Reference 仍被 activation literal 规则错误预装。 | 拒绝宽版本。 |
| 新 ExactLiteralOrigin **仅 Data** + 原 producer 的 LiteralEvaluation 附件 | 内容可精确表示，真实求值/异常/效果/对象 occurrence 不变；既有 literal 和老 wire 不强制迁移。 | **采用。** |

旧 ReferenceValue(LiteralOrigin(...)) 为 legacy 兼容保留，不据此增加 runtime/object/identity 权限。新能力不能把它们批量改成新表示，也不把保留 legacy 称为已恢复真实 LOAD_CONST 的对象行为。

## 2. 最小 canonical 字段与关系

### 2.1 Data 内容 origin

```text
ExactLiteralOrigin(literal: exact PythonLiteral)
Origin = legacy LiteralOrigin | ExactLiteralOrigin | BlockArgument | OperationResult
```

- frozen/slots/exact typed；不继承 LiteralOrigin，不暴露兼容 `.value` 属性诱使旧消费者把 descriptor 当 raw scalar。
- DataValue 的 data_type 按 literal.kind 机械对应精确 builtin 内容类型；不用 `.to_python()` 才决定类型。bool/int、float64/complex、str/bytes、tuple 等分别对应；新 kind 的名字映射在合同中明确冻结。
- ReferenceValue、StateVersionValue、LocalBindingValue、ProtocolValue **拒绝**新 ExactLiteralOrigin，含私有属性篡改后的重新验证。现 `_value_fields(...allow_literal=True)` 被 Data/Reference 共用，不能只扩 Origin union 而忘了拆允许策略。
- origin 无 SourceReference、CodeID、ObjectID、producer、runtime_verified。内容 payload 不是源码、求值事件或实体身份。来源仍用原 ValueSource/ProviderBinding 等关联。

### 2.2 Python 对象求值：附件不能替换原 producer

```text
LiteralEvaluation(
  site: original OperationResult
      | InvokeLiteralResult(edge: original ControlEdgeReference,
                            result: original CompletionResult),
  literal: PythonLiteral,
  source: SourceReference | ProviderFactReference
)
```

不需要新 LiteralID 或独立 provenance graph。附件唯一锚定一个原输出 site，不再存第二份 ValueID、Use、before/after、实际 producer 或实际对象 ID。

**direct 规则：** OperationResult.operation/index 必须选择原 Operation.results[index]；原值 origin 必须准确相等，且属于该 op/region。不能将 BlockArgument、callee 的结果或一个已删除 producer 冒充本 op 输出。允许 Data/Reference 内容声明，但不允许 State/Binding/Protocol。Data 类型与 payload.kind 必须一致；Reference 的既有 identity/targets/selector 限制不因附件放宽。

**INVOKE 规则：** edge 指原 terminator 的准确 successor；result.index 指该 completion signature 的原 produced slot。沿原 successor.arguments 找唯一同 index 的 CompletionResult，再派生 target block 对应 formal，原 producer 保持 BlockArgument。不能把 landing 位置直接当 produced-slot index，也不能接受 forwarded Use 充当本 INVOKE 新产出。没有实际 transfer 的动态查询只返回 DECLARED + gap，不默选 NORMAL。

最小 Python literal 求值协议只需显式 NORMAL 成功输出；RAISE 仍走原完成状态/异常对象，不把异常 message 的同值字符串当作 literal 求值结果。若要支持一般 helper 的 RAISE 数据槽，需另有明确协议，不能因通用 completion 形状允许就默认解释。已有 NormalResultPort/ProgramIndex.normal_result 可复用 NORMAL 槽解析；若本门选择上述显式 edge 形式，可复用其机械解析逻辑，勿另存一张端口映射表。

附件内容是条件声明，不代表此 producer 无 allocation、异常、retain/release、RNG、对象身份或其他效果。原 op 的全部 Uses/Access/完成状态继续存在；payload 只展示/核验，不能授权删除该 op 或外围 import/调用。

## 3. 现 PythonLiteral 可复用什么、缺什么

`scar/ir/literals.py:15–103` 已有 NONE/BOOL/INT/FLOAT64/STR/BYTES/TUPLE/ELLIPSIS；INT 是 canonical decimal，BYTES 是 hex，FLOAT64 是 16 位 lowercase big-endian bits，可保存 signed zero/Inf/NaN payload。共享于 SourceSemanticsGraph 和 OIR，不能另造 core-only literal 编码。

当前明确缺口：

- 不支持 complex（`from_python(1j)` 目前被拒绝，现有测试也明确要求拒绝）；若本门补齐 ast.Constant 类型，需要独立冻结 COMPLEX128 的实/虚两个 binary64 bit payload，不用 repr、JSON float 或算术重构。它是共享 PythonLiteral 的扩展，不只是 core 多一个分支。
- `__post_init__` 只检查 tuple 项类型，没有深度/累计节点/总 payload 预算；from_python/to_python/as_dict 和 record_codec 递归。不能拿 current constants evaluator 的局部预算冒充全入口已受限。
- 用户子类/可变容器/任意对象继续拒绝，不调用 repr/hash/eq/descriptor。tuple 仅可递归含受限不可变 payload；list/dict/set 是构造操作。trace.code_snapshot 支持 frozenset/slice/CodeType 是 **code fingerprint 能力**，不等于 PythonLiteral 也必须把它们都当源 literal。
- 精确 payload 能携带非有限 float，不等于已有 evaluator 可以计算其结果。constants_v2 对非有限算术当前有明确拒绝策略；新增表示不能顺便放开计算/替换。

推荐共用受限 literal validator/descriptor helpers，而非各消费者 `.to_python()`。至少分：`is_data_literal_origin`（legacy + 新 Data），`literal_payload(origin)`（bounded，返回 descriptor），`literal_builtin_type(payload)`，以及精确 INT 比较 helper（拒 bool）。LiteralEvaluation **不属于** origin-availability 谓词。

预算必须在 recursive schema validation/encode 前预检新 literal，包含 max_nodes/depth/cumulative bytes/int digits or bits；不能每个 tuple child 重置。int decimal 转换前检查大小与现 interpreter 限制，不修改全局 int conversion setting。carry/roundtrip 与重建 Python 对象/算术各有独立预算；不要为显示 query 自动重建大 bytes/tuple/int。

### Wire 的一个必须关闭的实际边界

当前 `program/codec.py:240–241` 用 ensure_ascii=False；`execution/snapshot.py:11` 随后严格 UTF-8 encode。PythonLiteral STR 可以含 lone surrogate，因此仅把现 descriptor 塞入 program origin，不能保证该图能生成 snapshot bytes。新能力 wire 应采用可无损 UTF-8 存档的 JSON escaping（例如仅新版本采用 ensure_ascii=True），或明确的等价严格策略；**不改旧 v1–15 的编码字节**。现 legacy 同类边界不应被悄悄修成新 wire 后宣称优化。

## 4. 全部直接 LiteralOrigin 消费者与迁移动作

只读 `rg -l LiteralOrigin scar -g '*.py'` 得到以下 **13 个产品文件**。此表区分必须扩展与保持 legacy；不把所有判断机械换成一个宽谓词。

| 文件/实际位置 | 当前用途 | 必须处理 |
| --- | --- | --- |
| `ir/program/model.py:157–171,190–234,289–313` | scalar origin、Data exact type、Reference literal限制、共用 origin 检查。 | 保留 Legacy；加新 Data-only variant、按 kind 类型；明确拒新 Reference/State/Binding/Protocol；不自动改旧值。 |
| `ir/program/__init__.py` | 公开 record API。 | 新类型/必要 helper 显式导出，旧 API 保持。 |
| `ir/program/validation.py:117–137,415–425` | producer/argument 对应、literal availability/dominance 豁免。 | origin family 精确分流；新 Data 可作为 activation 内容，附件对象绝不能进入 literal 豁免；先受限检查再递归/索引。 |
| `ir/execution/validation.py:300–320` | literal ValueOccurrence 的 origin 必须为同 region activation。 | 认新 **Data** literal；仍拒 Reference 使用 activation origin 冒附件真实产出；原 Op/Visit 来源核验保持。 |
| `ir/execution/flow.py:153–171` | literal 按 activation 预装到环境。 | 只 preload 旧 literal/新 Data 内容；LiteralEvaluation 对象保留真实 OpOccurrence/Visit 路由，循环/两次求值不按 payload 合并。 |
| `ir/execution/query.py:70–87` | denotation.literal 展示。 | 显示 descriptor/origin，原 association 不改；附件由 producer 派生独立展示，不把 payload 当 ObjectIdentity。 |
| `ir/execution/state_addresses.py:52–72` | owner/key operand.literal 展示。 | 能展示新 Data descriptor；Reference 附件另沿其实际 origin 查，不能因同 key payload 推 Python equality/alias。 |
| `ir/execution/production_ranges.py:190–197` | 精确 int literal 与 raw written_bytes 比较。 | 保持 Data-only/INT-only、拒 bool；可比较受限 canonical decimal，无需重建大 int。相等仍不证明 native return port。 |
| `ir/execution/validity_validation.py:174–204` | literal count 不是 native 返回槽的专门 gap。 | 新 Data literal同样保留 port-unverified；附件对象继续原 actual producer/CompletionResult 对应，不以 payload 跳过。 |
| `analysis/program_inventory.py:317–324` | ast.Constant 当前是否落在 lowerer scalar 子集。 | 不可仅 PythonLiteral 支持就算 frontend 已接；应与实际 lowerer profile 一致，未接 source producer attachment 继续明确 gap。 |
| `analysis/program_lowering.py:458–466` | 当前源码 literal 生成 Legacy ReferenceValue。 | 保留旧 profile；新对象路径必须显式 producer/INVOKE+附件，不能换成 ExactLiteralOrigin Reference。未开发该路径不得声称 bytes/complex 自动全程建图。 |
| `analysis/frame_queries.py:61–80` | **Reference-only** frame payload来源分类，直接读 origin.value。 | 保留 legacy literal分类；新附件对象仍是 OPERATION_RESULT/COMPLETION boundary，最多另展示 payload。不能广泛改谓词后将对象移成“预装 literal”。 |
| `analysis/call_operand_routes.py:128–138` | **Reference-only** CoreReferenceKind 分类。 | 同上，不将新 LiteralEvaluation/同内容引用统一成 LITERAL，不按 payload 接调用 actuals。 |

### 非关键词命中但必须接的边界

- `program/codec.py`：Origin union 的本地新 tag/capability 门、含新附件表时的字段集、v1–15严格拒新能力。数据 origin 与对象附件都必须被探测；不能只检查新增表非空，漏仅新 Origin 的图。
- `record_codec.py`：可复用现 dataclass/union/local tags。它默认 union 逐一尝试且 exact fields；新 origin 显式 discriminator，不修改旧 scalar encoding。通用 JSON 有 duplicate-key/NaN 拒绝，但新深度/大小预算尚需入口闭合；不必重写 JSON/AST 解释器。
- `program/queries.py`：producer() 保持原 origin；新增只读 literal/evaluation 视图应派生原 result/edge/formal/Use，不储存新 def-use。当前只返回 origin，不等于已有 payload-aware 视图。
- `execution/composition_routes.py:135–156` 的 producer 依 occurrence/visit/activation 自动派生，通常无需新表；其 origin展示与缺采集必须涵盖新 Data，附件对象仍原 observed op。`content_validation` 的 DataIdentity/ObjectIdentity 分离保持原样。
- `execution/snapshot.py`/ProgramSnapshot：新 program schema/hash 正确封存即可；若无新 dynamic record，不应仅为 payload 再升 ExecutionModel wire。当前 snapshot.schema_version 不硬编码最大15，但仍要测试准确版本/hash拒错。
- `program/resumption_validation.py`/availability root逻辑：新 Data 与 legacy 合法字面内容可跨 cut；对象附件不是 literal，要保存原实际 Use 才能跨 Suspend。不得依“内容 immutable”恢复一个未保存对象引用。
- `v2/codec.py:345–351`、semantics_v2/OIR：已复用 PythonLiteral，扩其 kinds 会同时拓宽这些旧 schema parser。若它们没有新 profile/version gate，就不能承诺其旧读者也理解新 kind；须明确该迁移而非只做 program codec 门。
- `analysis/constants_v2`、`import_values_v2`、`source_semantics_v2`、`local_statement_semantics_v2` 已有独立类型/预算/运算 whitelist。复用内容描述，不把更丰富 kind 自动升级成 evaluator 支持。尤其 `source_semantics_v2` 对 LITERAL 有 release_safe 分类，新增 kind 必须保持 exact immutable 约束。

## 5. 来源：复用现有四层接口，不复制 provenance/producer

| 层 | 原接口 | 能说明什么/不能说明什么 |
| --- | --- | --- |
| Payload | 现 PythonLiteral | exact type/content/bit descriptor；不是原词法拼写、对象、捕获或合法替换证明。 |
| AST/source | SourceVersion + SourceReference；现 ValueSource/OperationSource/UseSource/LoweringMetadata | 指定源码快照/跨度与 canonical ports。`0x10` 与 `16` 同 payload 可不同 source；负号/加法/tuple display 不能仅因最终同 payload 擦掉原操作。 |
| compile/co_consts | 现 CallCompilationProfile、`trace.code_snapshot.describe_code/site`、ProviderArtifact/FactReference | code snapshot 的结构 key 已包含 co_consts，支持 bounded exact builtin 检查，无 repr/hash/eq。code key + const slot 必须 scoped；不同 code 的同 index、同payload、同 filename 都不证明同来源。 |
| runtime | 原 OperationOccurrence/ValueOccurrence/UseOccurrence/actual ControlTransfer + ValueDenotation | 回查此次原 producer/输出；对象身份仍来自 scoped ObjectRef，Data 内容版本仍来自 VersionRef/Mat/current-state。附件不授新 identity。 |

当前 code_snapshot 公开接口并没有一个已验证的通用 co_consts-slot fact catalog/parser。可用 ProviderFactReference 精确声明 artifact+locator；缺该 artifact/profile 的实际重放应是具体 source-unverified，不应宣称 URI/FactRef 相等已证明实际加载。不要新增独立常量 provenance 图，也不要执行任意 provider 或目标代码来“确认”。

常量折叠/运行计算得到相同内容也不是新 origin：若已有 OperationResult，保留该 producer，通过附件/已有 SourceSemantics constant fact 显示内容；删除其效果是后续 Q/proof/backend 的事。原 source semantics 的 Opcode.LITERAL 与 operation.literal 接口，不可为了展示一个计算结果就把非 literal opcode 改成 LITERAL。

## 6. 官方材料的事实边界

- Python3.14 ast.Constant 覆盖 str/bytes/int/float/complex/bool/None/Ellipsis；tuple display 是 ast.Tuple；`3+4j` 含加法，不是一个 imaginary token。源码结构和内容描述分开。[AST](https://docs.python.org/3.14/library/ast.html#ast.Constant)、[imaginary literals](https://docs.python.org/3.14/reference/lexical_analysis.html#imaginary-literals)。
- co_consts 是 code 的常量池；immutable 同类型同值操作可返回既有或新对象，不能用内容等同自动推出对象同一。[code/data model](https://docs.python.org/3.14/reference/datamodel.html#codeobject.co_consts)、[object identity](https://docs.python.org/3.14/reference/datamodel.html#objects-values-and-types)。
- ast.literal_eval 也不能替代预算或用作任意 target 验证器；官方说明其仍有资源耗尽风险。[literal_eval](https://docs.python.org/3.14/library/ast.html#ast.literal_eval)。官网此次为3.14.8文档，不冒称本机3.14.7新运行证据。

## 7. 拟定验收分母：20组（全部待实施）

| ID | 必需正反构造 | 必须判定 |
| --- | --- | --- |
| L01 | legacy scalar/Reference origins 与 v2–15 goldens；v1原迁移 | 不自动迁移、不改旧 bytes/tags/角色。 |
| L02 | 新 Exact Data-only bytes/tuple/Ellipsis/float bits | 类型准确；Reference/State/Binding/Protocol 放新 origin 拒绝。 |
| L03 | 新 payload-only 图；仅对象附件图 | 两者分别触发新 capability；不能只靠某一表选择版本。 |
| L04 | 每个 v1–15 偷带新 origin、新表空字段/标签 | 严格拒绝；普通 label 字符串等于 tag 不误拒。 |
| L05 | bool/int、signed zero、不同 NaN payload、Inf、bytes与str、complex bits | descriptor 类型/位型不合并；不按 Python == / repr / JSON float 作为 identity。 |
| L06 | direct OperationResult 附件 | 回查原 slot/原值；错 owner/index、缺 producer、State结果拒绝。 |
| L07 | INVOKE completion slots反排/多状态/显式NORMAL | 按 produced slot找到准确原 formal，不按 landing序号猜，不造 after/producer。 |
| L08 | forwarded Use 放附件、新 RAISE 分支、未观察 completion | forwarded不是产出；失败不补成功literal；缺 transfer保留声明+gap。 |
| L09 | 两次 object求值/loop同payload的两个实际occurrence | 原 producer/Uses完整保留；既不合并为同对象，也不无证强制不同对象。 |
| L10 | 同 compiled const slot/不同 code同index/相同source payload | exact code/source范围不混；同pool仍需实际对应条件，不给跨activation永久identity。 |
| L11 | newData literal可用性；Reference附件普通dominance/跨region | Data规则准确；附件不绕定义/跨region端口。 |
| L12 | Suspend前新Data、对象附件已保存/未保存 | Data内容可用；对象引用只能沿原 saved Use，未保存被cut guard拒绝。 |
| L13 | 新Data动态ValueOccurrence绑定activation；附件绑Op/Visit | origin类型/region/visit准确；附件伪activation或旧incarnation拒绝。 |
| L14 | denotation/state_address/frame/call/composition查询 | payload可查但仍原producer/identity；不因常量文本删当前state/原Use。 |
| L15 | literal INT count匹配/不匹配 raw；bool/float伪count | 精确kind，已知矛盾拒；相等不证native返回槽。 |
| L16 | 深tuple、累计大payload、大int、私有循环/篡改、预算截断 | 先受限后遍历/转换；受控错误/明确gap，不改全局环境。 |
| L17 | surrogate/NUL/非ASCII、bytes0xff、坏JSON/重复键 | 新snapshot bytes可封存重查，旧wire不悄改；非标准JSON NaN仍拒绝。 |
| L18 | subtype/custom repr/hash/eq/to_python；mutable nested值 | 拒绝/不执行用户代码；不把容器构造伪装literal。 |
| L19 | AST复杂常量、unary/binop/tuple display、compile-folded const | payload支持不冒充frontend接通；原操作/effects/失败保留。 |
| L20 | SourceSemantics/OIR新kind、原evaluator/oldreference profiles | 表示与计算支持分开；原budget/whitelist/old API继续验收。 |

这是20组设计分母，不是20 tests PASS；legacy frozen tests、new records、canonical graph/port、dynamic/cut、来源与budget必须分别报告。L0完成只表示设计审查交付，不关闭整个literal/whole-program建模或授权优化。

## 8. 阅读指纹

```text
3e1c8e95c1a32e8454007f0b8c35e3724028732d376a5550ca1c5d6e7ce949d3 scar/ir/literals.py
bb9993520ee76ab6dd5531884944f96a990379fff74d7935c81a10b818df4d61 scar/ir/program/model.py
81cac8e544bfab868d95b037bd8149c4e73cb9e18b128c244bdc104136084089 scar/ir/program/codec.py
2facc7de22eadf2c095181a6f258ecbb7a529079d5c92b6414bbb0a0968ec6c4 scar/ir/record_codec.py
277c32f7434bf1a7c08c0ac458792b5dd6971dc3b14f8b7ccbfcd50ba7923a09 scar/ir/program/validation.py
d3519de9474369bb20d25950ae7f45d151f5ca54a78d367452d6c30825116134 scar/ir/program/queries.py
4b828b9a95b5d46b82c5fb3045d514b277dd586bfa3747376807e64f2a624896 scar/ir/execution/validation.py
2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501 scar/ir/execution/flow.py
450535f82df6a48ea66953480b9bfc3dfad12cfbb5356898db43fefc010fa131 scar/ir/execution/query.py
321875f5327920c33dcef0ed48a785096720c4252076830005397d23a3770221 scar/ir/execution/state_addresses.py
2ee63f5d74cb9e75d3c7991318ca6fdcc125f2b9b3b09cfc0912726ce952ed17 scar/ir/execution/production_ranges.py
45e5e6cf5daf1a29b91778c03f7334a580e5bca311e76fb7895c5ab8a048a84f scar/ir/execution/validity_validation.py
43c5b3d603bc95b80f270fe9376cd4b9d6f236e7ad2d98b2bc583291f2f3db54 scar/analysis/call_operand_routes.py
4db3d0ca485ef345ad2625673a97f5a5490d4c42a682f752864e99632ac6ca40 scar/analysis/frame_queries.py
f22ffebf03f6f255e26b7d60f20dff73f4bebdf68362a30800e9ef08c771d634 scar/analysis/program_inventory.py
5ab3f166d4f949fe3efa0905dfacc39657562cf3dc0bc96bb1193c1a94b75068 scar/analysis/program_lowering.py
3a00de3ef3dbac1e0ceca379f89dc501e95f9256dc59d77b318cc6f9f4c332cb scar/trace/code_snapshot.py
dbff369035e06452de1f6c0e741e68553f188addac8483859ae47a444f5a002b scar/ir/program/source.py
511daa3a5d1ee89ae7f7c545dd5f7161ea3a3a6c9f3c1b01b4224c0ba751fcc1 scar/ir/v2/codec.py
```

## 9. Root 最后来源变体提案的限定复核

Root 补充方案：ExactLiteralOrigin(literal,definition=UnlocatedLiteral) 仍只用于 Data；LiteralEvaluation 的 literal 可为 PythonLiteral 或 UninterpretedConstant(reason)，definition 用 SourceExpression(SourceReference) / CodeConstant(ProviderFactReference,index) / UnlocatedLiteral(reason)。这与本文的 content/evaluation 分离**无实质矛盾**，可直接采用以下限制，不引入新 producer 或来源图：

- definition 是来源阶段/定位声明，runtime 求值仍由原 site；不能让 CodeConstant 或 SourceExpression 标签自行升级为实际已加载/已求值/对象同一证明。
- ExactLiteralOrigin 必须 known PythonLiteral；UninterpretedConstant 只允许 producer 附件，不可用于新 Data exact origin，也不进入 availability/preload 谓词。reason 必须明确，不能把 unknown 转成 NONE。
- CodeConstant.index 是 exact nonbool 非负整数。建议 FactRef 明确指一个 code/const-pool **容器**，index 单独选择其槽，避免 locator 已指槽后再二次索引；如合同允许 locator 指槽，则必须规定其与 index 一致，不能择其中一个。artifact/code scope 与原索引必须可回查；没有 whitelist 解码/对应时保留 source-unverified，不打开 URI/执行 provider。
- SourceExpression 可以保留 BinOp、tuple display 等原表达式来源，但不能凭名字把整个表达式变成一次无效果 literal 加载。原 ValueSource/OperationSource 的连接保留；不同声明不机械合并为独立真实来源身份。
- UnlocatedLiteral 使用不可变、明确 reason 的默认实例或等价 default_factory；这是未定位声明，不是“没有来源”或已证明纯性。新 definition variants 同样必须被新 wire capability gate 覆盖，不混入旧 origin。
- `program/validation.py:321–324` 当前对每个 INVOKE edge 要求逻辑 CompletionResult 槽恰好绑定一次，重复/漏槽被 `completion_slots` 拒绝。因此本文的唯一 landing formal 派生是**原源码事实**；root 一度提出 fanout 可能性的审查假设已撤回，本门不放松旧规则。

本轮至此停止。此前“新 exact origin 同时可容纳 Reference”的宽设想被本报告明确撤回，以 root/C 的 activation 反例为准。
