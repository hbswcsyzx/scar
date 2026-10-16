# 第一阶段模型审查：函数环境、现有接口与工具字段映射

**状态：独立设计审查草案；不是 M1/M2 验收，也不是全程序建模完成声明。**

审查目标是把 `ProgramGraph.environments` 接回现有函数签名、canonical call Uses、状态端口和可复用执行工具，并列出完整第一阶段尚缺的模型协议。只读审查 `/tmp/scar-structured-model-280qf4mi`；工作树当时为 CPython 3.14.7 目标版本，源码处于并行实施状态，HEAD `f80af0f` 且有未提交改动。没有运行 LeWM 或新增测试。下面“当前实现”指审查时读到的文件，不等于被冻结验收。

## 1. 结论与最小完整连接

`EnvironmentInterface` 有明确的结构价值：它把函数对象、globals、builtins、defaults、keyword defaults 和按 `co_freevars` 顺序声明的 cells 作为一个 Region 的**隐藏入口端口**，引用已存在的 `ReferenceValue`，状态域继续引用 `StateVersionValue`。`ProgramIndex.environment_call()` 从既有 `Operation.call_arguments` / `invoke_arguments` 派生这些端口对应的 caller `UseSite`，返回 `DECLARED`、`NO_DECLARED_CALLEE` 或 `NO_DECLARED_ENVIRONMENT`。这足以让 validator/query 表明“图声明了什么入口依赖”和“canonical Use 接到了哪里”。

不需要在本批新增名为 `EnvironmentRead` 的源码操作，也不应把一次 helper `Invoke` 插进图里来伪造 Python 解释器的函数环境查找。普通 `f(x)` 并没有执行用户源码 `f.__globals__` 或 `f.__closure__` 读取；额外的普通 READ/INVOKE 会把一个隐式调用绑定步骤错报成用户可见操作、源码求值或可独立抛错的调用。静态环境接口可以作为声明及 entry-port 合同，而不冒充发生记录。

但这个组件的当前结论只能是 **DECLARED**。它不证明 caller 运行时传入的 function object 与 `code_definition` 对应，不证明当前 `__globals__`、builtins、defaults 或 cells 与这些端口对应，也不证明同 code 的两个 function 有同一个环境。要关闭动态连接，后续应增加**绑定在一次真实 Call/Invoke activation 上的 typed environment correspondence**：以实际 callee `ObjectID`/弱身份证据、该次 code witness、call occurrence 和 state-version scope 为键，逐 role 对应观察到的函数属性/namespace/cell 引用及内容状态。它是 dispatch/environment evidence overlay，不是另造一套可修改的 call Uses，也不是普通 Python `Operation`。目前 call-operands 只捕获 Name/LOAD 与 CALL 形状、weak/snapshot reference、code/layout；元数据明确 `callable_environment_established=False`，所以不能生成这种对应。

**最小闭合顺序：**

1. M1 静态结构：一套 entry layout 精确分开 explicit formals、环境 refs、state ports；一个 Region 的 interface 绑定唯一 signature/code declaration；validator 覆盖位置/类型/状态域；query 只从 canonical Uses 派生声明映射。
2. M2 源码阶段：按 Python 版本建模函数对象创建、defaults/decorator/type params/annotation 何时执行，闭包 cell 创建与捕获，global/builtins 查找顺序；不因有 body 就删除这些定义期操作。
3. M4 动态绑定：真实 function object identity、code witness、环境 role 引用和 state versions 对应到一次 invocation；无此证据继续停在条件候选，不按函数名、qualname、相同 code 或静态环境表升级。

最初审查时的 entry-layout 冲突已由新的 `FunctionEntryLayout` 处理。旧 `BodyEntryInterface` 仍使用它原有 source profile 的 `formal refs + world` 契约；当前未生成会把这个 legacy source record 伪称为含 env ports 的新 profile/source adapter。新 core graph 通过独立的 entry-layout record增加 canonical environment/formal分区；不能要求旧 source profile突然产出新 cap。明确反例 `(formal_ref, state_version, env_function_ref, ...)` 是合法的：ValueID/typed variant 布局精确标注逻辑端口，物理 entry 参数无需改成同一组固定分段顺序。

新增的 canonical entry-port partition 是精简且兼容任意物理端口顺序的；不需要另一份 actual binding 表：

```python
@dataclass(frozen=True)
class FormalPort:
    slot: ValueSlotID
    value: ValueID

@dataclass(frozen=True)
class FunctionEntryLayout:
    environment: EnvironmentInterfaceID
    parameters: tuple[FormalPort, ...]

ProgramGraph.function_entries: tuple[FunctionEntryLayout, ...]
```

`region` 和 `code_definition` 从唯一引用的 `EnvironmentInterface` 派生，不复存；environment/interface 与 entry layout 应一一对应。`parameters` 保留 source signature logical order，`EnvironmentInterface.members` 保留规范 role/cell order；两者值与 `StateVersionValue` 参数按 ID/typed variant 分类后，物理 `Region.entry.arguments` 可以任意交错排列，例如 `(formal_ref, world_state, env_function_ref, capture_cell, ...)`。验证器不靠分段或 zip 猜语义：它要求三类 exact ValueID集合两两不交并且完整覆盖 entry；formal是此 Region精确 entry `ReferenceValue`，environment refs继续按 `environment_errors`核验，state端口是全套 canonical state domains且无重复。`ProgramIndex.environment_call()` 用 entry ValueID到物理索引的映射，再按原 `UseID` 派生每个 formal、environment role和state domain对应的 caller Use。共享 location仍可由多个环境 member声明，actual call state Use只按canonical state port存在；不同formal/env ports可以合法连接到同一 actual Python reference。源码 signature 完整性不能从 core record单独证明；source inventory/replay必须要求 `(FormalPort.slot)` 等于 `FunctionSignature.parameters` 的完整顺序，并将source、旧/新profile与graph layout对齐。

**类型判定：** 新 layout 和 validator只接受exact entry `ReferenceValue`作为Python formal，拒绝 `DataValue`。这是正确的 Python对象边界，也与旧 `validate_body_interface()`一致；source annotation不能证明某次动态值是 builtin scalar。若将来有不经 Python object identity 的 unboxed ABI/formal，需要单独ABI/primitive-value interface，而不能把普通源码参数放宽成 `DataValue`。现有 literal/reference/Data distinctions继续生效。

**调用参数的源映射也须随布局重算。** `FunctionInterfaceBuilder.record_body()` 当前按 `invoke_arguments[index + 1]`（把 callee置于首位、source actuals连续排列、world位于末尾）连接 `CallArgument.use`；环境 ports引入后，这一硬编码偏移不再安全。应按 `FunctionEntryLayout.parameters`、`CandidateBinding` 的 formal slot routes 和 source `CallArgument` 精确映射 canonical `UseID`；隐藏 env/state uses不能被列成 Python actual。`DEFAULT_STATE` 和 varpos/varkw pack仍是计划，除非有真正的 typed binding/packing producer，否则不能拿布局捏造已产生的 formal对象。旧 profile 继续按原规则重放；未来 source adapter 需把同一个映射作为 source evidence核对，而非另存可编辑的第二份 canonical formal table。

`function_entries` 与 `environments` 作为同一个新 capability用严格的新schema版本；旧 v1—v4历史格式保持原字节与严格解码语义。根代理确认本工作树当前 v5 是未提交的新环境/entry-layout wire，不是此前已冻结的历史v5，所以没有另一个“环境有、layout无”的历史 v5 record需要兼容。未来若某一v5格式冻结发布，再改变record字段必须另升版，不能把新layout字段静默补进该既有schema。

## 2. 当前环境 API 逐字段边界

审查时 API 在 `scar/ir/program/environments.py`，挂于原 `ProgramGraph.environments`；codec 已计划/实现 `scar.program-graph` v5 显式 capability，v1—v4 走旧严格字段迁移。实际状态以冻结 gate 为准。

| 字段 | 可以规范表达 | 不能推出 |
|---|---|---|
| `EnvironmentInterface.id` | 一个静态环境接口身份。 | 动态闭包/函数对象生命周期身份。 |
| `region` | 该接口属于哪个静态函数 body Region；每 Region 至多一个接口。 | 此次执行使用了此 Region。 |
| `code_definition` | 声明对应的静态 operation-definition ID。 | runtime `function.__code__` 匹配；装饰器未替换 callable；代码对象未热替换。审查时 `environment_errors()` 没有把此 ID 与 `FunctionSignature`、源码重放或 `CodeID` 交叉验证。 |
| 固定前五个 `members` | `FUNCTION_OBJECT`, `GLOBALS_NAMESPACE`, `BUILTINS_NAMESPACE`, `DEFAULTS`, `KEYWORD_DEFAULTS` 各一个、有序、各自不同的 entry `ValueID`。缺省 defaults 可由 `None` reference 表示。 | 各引用指向的 runtime object、属性是否缺省/改变、各容器内容或隔离性。 |
| `CAPTURED_CELL` 成员 | 每个 capture 的 `cell_slot` 和从零连续 `cell_position`；独立 entry ref；可有共享 `LocationID`。 | position 与当前 `co_freevars` 完全对应，cell 运行时相同、cell 内值 bound，或两个函数实际共享 cell。 |
| member `reference` | 当前 validator 可要求该值为本 Region 精确 entry `ReferenceValue`。成员 ref ID 不同，所以这是不同端口。 | 不同 ID ≠ 不同 Python object；接口 doc 正确允许 alias。也不表示对象内容不可变。 |
| `locations` | 必需状态域声明；当前环境 validator 要求 location 存在、位于该 Region entry state-domain 集合，且不与已知 reference targets 矛盾。 | 完整读写集合、键/元素 selector、对象字段 owner、状态内容版本或“省略即无副作用”。 |
| `EnvironmentCall.arguments` | 从已有 call/invoke `Use` 及 entry args 派生每 role actual Use 和对应 declared state-argument Uses；无接口/无静态 callee分别给出明确 status。 | 运行时 binder 把这些值装进了函数对象，或它们来自真实 `__globals__`/`__closure__`。status `DECLARED` 不是 observed。 |

接口可作为 M1 的入口合同；但“唯一 interface per Region”和 `code_definition` 需要被 core/source validator 的身份连接真正核对，而不是仅 record shape 校验。Cell `cell_position` 应由当前代码对象/source replay 对 `co_freevars` 校验，显式 formal slots 与 cells 的命名空间不应混为同一个 Python `ValueSlotID` 集合。

## 3. 必须保留的 Python 反例

这些例子是一般语言语义反例，不是 LeWM 特例。CPython 的函数对象属性、闭包、全局名字解析、lazy annotation 与赋值规则见 Python 3.14 官方 [数据模型](https://docs.python.org/3.14/reference/datamodel.html)、[执行模型](https://docs.python.org/3.14/reference/executionmodel.html)、[复合语句](https://docs.python.org/3.14/reference/compound_stmts.html) 和 [表达式](https://docs.python.org/3.14/reference/expressions.html)。工作环境是 3.14.7；官方网页当前为 3.14 文档版，patch-level 不同。

| 反例 | 现有结构必须怎样保守表示 |
|---|---|
| 两次 `factory(v)` 返回同一个静态 `f` body 的闭包，但 `f1()`/`f2()` 返回不同 `v`。 | 一个静态 `code_definition` 可有不同动态 env denotation；不能按 CodeID 合并。 |
| 两个闭包共同 capture 同一个 `nonlocal x`，一次 call 更新后另一个 call 读到新值；另一个 factory 实例则各有自己的 cell。 | 共享 cell identity 和 cell contents/current version 两种关系分开；闭包逃逸后仍存活。不同 cell id 不证明内容不同。 |
| 函数默认 `arg=[]`，函数外修改 `__defaults__` 中 list，之后又重新赋 `f.__defaults__`；`__kwdefaults__` 字典被改键或删除。 | default tuple/dict 引用、槽/键绑定和容器元素 state 分层；`DEFAULT_STATE` 路线需绑定当前对象/版本，不能重新评估默认表达式或缓存 AST default。 |
| 两函数体 code 相同，但由两个 globals dict 创建；修改 `globals['name']` 后行为改变。全局缺名时再按 function 所关联的 builtins namespace 查找，可能与另一个 function 不同。 | namespace identity 与逐名字 lookup/state 分开；查找是 globals-first、builtins fallback 的有序依赖。不能用当前 module dict 或全局内建表替换。 |
| globals 内绑定了 `__builtins__` dict 或 module，和函数的 `__builtins__` 关系被替换/改变；builtins 名被重绑。 | Builtins namespace 是函数环境 role，不可按 `globals['__builtins__']` 的当前静态值猜。builtin fallback 先需证明 globals 中缺名。 |
| `f.__code__` 被换成签名不同/同码复制的 code；装饰器 `@d` 返回 wrapper 或非 callable；`classmethod`/descriptor/partial/callable object 改变 dispatch。 | static FunctionDef 不等于 runtime callable。只按精确 code+callable witness 接口；未支持 descriptor/method wrapper 保留 unknown/incomplete。绑定错误可在 body entry 前抛，body 内异常则已有 entry。 |
| 方法 `obj.m(x)` 实际绑定到 `m.__func__`，隐式 receiver 成为第一个 formal 实参；descriptor 查找可自定义并改写。 | receiver 是 Python 绑定的 actual/formal 路由，不是 defaults/cell env。当前窄 Name-call route 应拒绝属性调用，不能假装这是普通 `f(x)`。 |
| 3.14 annotations 延迟求值；函数 `__annotate__`/`__annotations__` 可执行或缓存求值，type params 及 annotation scopes另有规则。 | 定义期与首次取注解期要分离；AST field 顺序不能推断执行顺序；annotations 不是无效果的静态字典。 |
| 内层函数/回调逃逸到容器、线程、注册表；outer frame 结束仍可运行；同函数递归/reentrant；Namespace 与 cell 在 callback 中变化。 | activation/resume/occurrence 是动态键；不以 frame return 结束 closure/callback 环境生命周期。无观察到 consumer 不代表无 consumer。 |
| `exec`/`eval`、自定义 `__builtins__`、module `__getattr__`、自定义 descriptor、callable object。 | 明确外部/动态边界；不要把未知协议降成“不访问 environment”。 |

## 4. 对现有 SCAR 类型的精确字段映射

### 4.1 静态源码、scope 与 code witness

| 现有来源/字段 | SCAR 可映射字段 | 时态/证据等级与边界 |
|---|---|---|
| `SourceSnapshot(path, decoded text/fingerprint)`、`SourceReference`/`SourceAtomID`、AST `FunctionDef`/`AsyncFunctionDef`/`Lambda`、`arguments` | `FunctionSignature.definition/source/parameters/kind/decorators`；`OperationDefinitionID`, `ValueSlotID`, `ValueSource`, `OperationSource`, source-call candidates。 | **Static source fact**。AST/symtable 可给函数 lexical scope、posonly/kwonly/varargs/freevars；独立 code witness 可确认编译所得 code descriptor。不能证明加载进某个 runtime function object。 |
| CPython `CodeType`: `co_argcount`, `co_posonlyargcount`, `co_kwonlyargcount`, `co_varnames`, `co_freevars`, `co_cellvars`, `co_flags`, constants/names/bytecode, `co_filename` | `pycode-v2`/`loaded_code_id`、`FunctionLayout`, source/code witness、cell position 候选、bytecode call-site offset。 | **Static loaded-code identity**。`filename/qualname/CodeID` 单独不是 identity；marshal/code witness 和 exact function `__code__ is` 复核才是该 source connector 的当前规则。仍不记录 function globals/defaults/cell objects。 |
| Function definition phase：defaults、decorators、type params、annotations | `FunctionSignature` 当前记录 formal slot/parameter source/default source/decorator source/kind。 | 仅声明来源和 raw signature。没有定义执行时的值、次序、抛错、decorator 替换结果、lazy-annotation求值 occurrence。 |
| `EnvironmentInterface.code_definition`, `members`, `cell_slot/position`, `locations` | 对应 body Region 隐藏环境 port + required state-domain declaration。 | **Static declaration**。source replay 需核 member/Region/signature一致性；dynamic runtime relation另需 M4 evidence。 |

### 4.2 调用、frame 与动态环境

| 现有来源/字段 | 可以接到 | 不能接到 |
|---|---|---|
| `FunctionSignature.parameters`：类型、名字、slot、源码、default_source；`CallArgument(index, source, kind, keyword, use)`；`CandidateBinding` route/status/issues | `ParameterBinding` 对 exact pos/kw candidate 的显式 formal 路由；`DEFAULT_STATE`、variadic pack计划及不完整边界。 | 不执行实参、不枚举 `*`/`**`、不证明 binder 成功/TypeError，也不测当前 `__defaults__`/`__kwdefaults__`。参数缺省路线需连接当前 env default container 的元素状态。 |
| `FrameEntry`/`FrameExit`: `(process, thread, invocation)`、code、caller/line、locals/parameters、return/exception anchor | 一次动态 frame entry/exit + 参数实际引用候选；与 source `CodeID` 的精确 link 后可作为 occurrence evidence。 | frame entry不证明该 source 函数签名完整或环境内容；采集视野外 no frame不证明 no-call。 |
| `CallOperandTrace`: `INSTRUCTION(site, loads[suboperand, namespace, slot, slot_index, reference, callable_shape])`; `CALL_ATTEMPT(site, dispatch, arg0, arg0_missing)`; `ENTRY_HANDSHAKE(attempt_index, entry_index)`; metadata.rule、scope/epoch、raw anchors/drop/error | 有序 lexical load occurrence→CALL window→真实 Python frame entry的窄 route；`EXACT_FUNCTION`提供 weak reference/code/layout条件。重复使用同一引用仍保留 occurrences。 | 当前 capture 明确 `callable_environment_established=False`；没有 globals dict、builtins dict、defaults、kwdefaults、closure cell或 cell-content version。snapshot token不能变为完整对象 identity。`METHOD`/`LOAD_ATTR`、kwargs/dispatch等未支持处要停边。 |
| `CallSourceScope`, `CallSourceLink`, `ReferenceIdentityRoute`, `FrameBinding` / `ProgramIndex.environment_call` | 以现有调用 Use/目标入口形成静态声明 route 或窄动态 source/load/frame条件 route。 | `DECLARED` 和 `CONDITIONAL` 都不等于 `OBSERVED`/`PROVEN`；无环境采集不能把 FunctionType ref 升级为“目标 Region 的实际环境”。 |

### 4.3 现有 ProgramGraph 与环境位置

| Core 字段 | 对环境模型的作用 | 空缺 |
|---|---|---|
| `Region(entry, blocks, exits, parent)` | body activation 的静态控制边界；入口参数是 typed `ValueID` 序列。 | 需一处规范入口 layout区分 explicit formal / env / state / continuation协议端口。 |
| `BlockArgument`, `ReferenceValue(origin, referent_identity, targets, selector)` | 显式 argument/capture refs 的 Value port；literal reference有 unknown selector/empty targets限制。 | `referent_identity` 字符串不是动态 `ObjectID` 绑定；ref targets缺owner/field/cell element具体selector，`UNKNOWN`不能收紧。 |
| `StateLocation(id,label,extent,stability)`、`StateAccess(location,before,mode,after,footprint,reference)` | 当前 namespace/cell/defaults 内容变化可用 state SSA 表达；call/invoke可携带当前 state/version。 | location 没有完整 owner、object identity-generation、key/index/field selector及跨粗细域 alias coverage；name lookup的globals→builtins短路规则未typed。 |
| `Use(id,value,role)`, `Operation.call_arguments/invoke_arguments` | canonical ordered actual/state/env ports，不需并行复制一份实际绑定表；callee interface arity/type/current-state可校验。 | explicit Python actual与IR隐式上下文 port必须有 typed分区。只按 zip不能识别源实参与环境引用。 |
| `ExitKind.NORMAL/RAISE`, `CompletionSignature/Result/Successor` | direct invoke的normal/raise与逐边 post-state端口；body raise与binder/call setup failure可保持不同阶段。 | cleanup/finally/with/suspend/resume/continuation generation还不完整；异常期间部分 namespace/cell mutation不可回滚成输入world。 |
| `LiteralOrigin` | exact None/bool/int/finite float/str scalar，且 `DataValue.data_type` 要与 exact builtin类型匹配。 | bytes、complex、Ellipsis、容器/tuple/dict构造、identity literal、constant tensor/object等协议需继续列域/值构造规则，不用 mutable constant伪装为 scalar literal。 |

### 4.4 执行/张量工具的字段映射矩阵

| 工具/API及原始字段 | 可提供给 SCAR 的端口/证据 | 明确的缺口/验证方式 |
|---|---|---|
| `torch.fx.GraphModule.graph.nodes`: `op`, `target`, ordered `args/kwargs`, `users`, `name`, `type`, `meta`; GraphModule code | operator/region候选；遍历 args/kwargs 中每个 Node occurrence可生成 ordered `Use`；`get_attr`对应模块状态候选。 | `users` 是唯一consumer map，不能代替重复 operand occurrences；stack/module metadata是hint。symbolic trace执行普通root Python，有些子module当leaf不执行，control特化/side effects/RNG可能缺失。官方：[FX](https://docs.pytorch.org/docs/stable/fx.html)。 |
| `torch.fx.experimental.proxy_tensor.make_fx`: concrete example execution中的FX节点及堆栈/targets | 单次 dispatcher-op候选，可用于 ATen粒度 Value/Use模型，不必自己再实现 PyTorch operator tracing。 | 执行目标，输入/guards限定单路径，可能推进RNG/IO/mutable状态；未捕获全部 Python control, globals, exceptions, env。官方：[make_fx](https://docs.pytorch.org/docs/stable/generated/torch.fx.experimental.proxy_tensor.make_fx.html)。 |
| `torch.export.ExportedProgram`: `graph_module`, `graph_signature.input_specs/output_specs`, `state_dict`, `call_spec`, `range_constraints`, module/source stack hints | lifted params/buffers/constants/user inputs/output and mutation/gradient roles；图 stage内的状态端口和约束候选。可将 input/output specs变为 typed Region ports。 | capture-relative specialization/guards；不等于 load→save完整 Python程序，不证明原函数 environment。raw train graph与decomposed functional graph alias/mutation schema不同，保留stage/epilogue。官方：[Export](https://docs.pytorch.org/docs/stable/export.html), [IR spec](https://docs.pytorch.org/docs/2.14/user_guide/torch_compiler/export/ir_spec.html)。 |
| ETO `inputs/outputs`, `ctrl_deps`, `attrs`, `name`, `id`, `op_schema`, `rf_id`, tensor tuple (`TensorImpl`, storage ptr, offset, numel, itemsize), `shape/stride/dtype/device`, `scope/tid/fw_tid/seq_id/fw_parent` | dynamic operator occurrence、物理表示/allocation候选、CPU event/Tensor storage hints；映射未来 `OperationInstance`, `ValueOccurrence`, `Materialization`。本地 report记录一次 CPU小探针rf_id与Kineto CPU correlation吻合的有限样本。 | `rf_id` 不直接是 Program `OperationID`、logical `ValueVersionID`、function env或ready token；裸地址不带生命周期代次。禁止额外采 tensor内容/range；必须保存工具版本和scope。官方源版本/字段见本地 [runtime report](../../../../tooling_survey/runtime/REPORT.md)及 pinned [PyTorch source](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/standalone/execution_trace_observer.cpp)。 |
| Kineto/profiler CPU/runtime/device activities, `correlation`, `linked_correlation`, external IDs, stream/device/timestamp | 跨 host/runtime/device work的动态 occurrence/work correlation候选；可关联资源队列/host action order。 | correlation scope/version/timebase不天然全局唯一；不能自动变成完成/就绪/alias/external effects完整证明。官方：[Profiler](https://docs.pytorch.org/docs/stable/profiler.html)。 |
| `torchview.ComputationGraph`: `TensorNode/FunctionNode/ModuleNode`, `root_container`, `node_hierarchy`, `edge_list`, Digraph; tensor IDs/shapes | 视觉核对模块层级与前向tensor flow、shape；可导出节点/邻接候选供人工审图。 | forward真执行，有模式/设备调整；unique edges会合并相同source/dest使用，非完整Python CFG/env/source relation。已读 pinned source、未安装运行，细节见本地 [visual/FX report](../../../../tooling_survey/visual_fx/REPORT.md)。 |
| `torchviz.make_dot` autograd `grad_fn`, `next_functions`, optional saved tensors and view `_base` | 对一个已执行输出的 gradient dependency诊断，可交叉核对反向路径。 | 不跑forward、不恢复源调用/参数环境/控制/全前向uses；Graphviz标签不是typed program records。未安装运行，source review见同上 report。 |

Adapter共通合同：每条输入保留 provider name/version/stage/run scope/raw anchor/hash/available-flag/error/drop count；转换时保持原始 occurrence与derived relation分层；tool缺项映射为 `UNKNOWN/UNAVAILABLE/GAP` 而非空操作/纯性；每个 provider 的 exact scope独立，不按名字或地址跨域合并。FX/Export/ETO现状与限制见 `docs/TOOLING_SURVEY.md`、`docs/MODELING_INTEGRATION.md`及本地工具报告。这里没有一个provider的adapter已因此自动建成。

## 5. 第一阶段剩余缺口及依赖次序

| 优先级 | 缺口 | 最小必须的 typed 接口/可核验规则 | 关闭前不得声称 |
|---|---|---|---|
| M0 | operation/value/location/region/resource的事实边界、static vs dynamic/unknown统一 | 统一声明来源、版本/occurrence scope、claim evidence、UNAVAILABLE与UNKNOWN语义；source/code/runtime identities分域。 | 已有四类图容器就是完整程序模型。 |
| M1-A | entry ports：explicit formals、环境、state与控制端口混排 | `FunctionEntryLayout(environment, parameters)` 对环境端口做一一映射；独立ValueID分类允许任意物理顺序；entry剩余项严格是全套StateVersion参数；source replay验证所有formal slots/order。CALL/INVOKE arity/state验证仍只使用canonical actual Uses。 | environment ref已正确进入函数signature或runtime actual；layout只声明端口，不证明runtime取值。 |
| M1-B | function env与动态callee对应 | 静态环境接口可声明；M4对应需一次 invocation的callee object/code/environment role/current state records、alias and identity evidence。 | code相同/qualified name相同说明闭包/globals/defaults相同。 |
| M1-C | globals/cells/defaults owner/selector/state | owned locations、逐key/element/cell-content selector、global-first/builtins fallback ordered read、cell identity与cell contents分离、defaults key/index mapping。unknown footprint仍保守。 | 整个 namespace/list无变化，或 omitted location=none。 |
| M1-D | Region control/completion/protocol | typed branch/backedge/exit, zero iteration, continue/break/else, cleanup pending completion, exception state, suspend/resume generation。 | unsupported内部用 `OPAQUE`后视作状态穿过不变。 |
| M1-E | Resource runtime | static ResourceDefinition/Requirement/Use/Location已在原core；尚需 ResourceInstance generation、handle→instance binding、work/ticket, event/completion, ready/visibility/ownership and ordering。 | static “需要queue/memory/file”即有实例、容量足够或已ready。 |
| M1-F | value/materialization/provenance与程序图连接 | occurrence→denotation (Data/Object/Binding/State/Protocol/Unresolved)、logical ValueVersion、allocation lifetime/materialization/validity、copy vs transform vs mutation、外部 alias write。复用 v2 records，不双存producer/use。 | Tensor ObjectID或storage ptr固定代表内容版本。 |
| M2-A | 完整 Python 3.14构造与执行phase | Definition/import/class/typealias/typevar/function/lambda/annotation expression、arg/default/decorator/keyword/starpack evaluation order、scope/name resolution/literal/comprehension/fstring rules。每构造标 phase、隐式 dispatch、state、normal/raise、gap。 | AST遍历顺序就是Python evaluation order。 |
| M2-B | operator/protocol与未知 native | arithmetic/truth/iteration/next/match-stop/descriptor/context manager/format/unpack/copy/serialization/IO/NumPy/Torch native adapters的inputs/results/side-effects/exceptions，versioned protocol。未知保留入口/出口+effects incompleteness。 | unknown op has no effects。 |
| M3 | 自动全程序范围+body-preserving lowering | import/discovery frontier，逐node phase coverage、internal/body/unsupported coverage守恒；能保留支持语法周边结构，逐Use计数/ordered actuals，与source replay独立验证。 | body/region数、AST行数、opaque enclosing tree等于理解覆盖。 |
| M4 | evidence/identity/occurrence全链 | real object/env/work/runtime operation per activation, hook availability/drops, same-code instances, recursion/reuse/callback lifetime, copy/view/alias/races/interference. 不持有app objects/tensors。 | 一次trace的 absence或same weak ref说明全运行相同/无别的consumer。 |
| M5 | observation dependency closure | return/frame exits、files/videos/logs、external writes, exceptions, RNG, control/resource completion，从每个观察root递归回溯价值/状态/side-effect。 | 只有tensor producer路径就是程序依赖闭合。 |
| M6 | 化简选择与修改指导 | 合同Q、合法替代/边界、成本+clean A/B、rollback与拒绝理由，自动指向具体Region/operation与source range。 | graph重复即纯/cachable/可删，或此报告本身证明加速。 |

M1 的结构层可以不等到 M4 collector 才有价值，但应将两层验收分开：record/core gate验证静态端口与Use/state布局；runtime bridge gate验证实际函数和每次环境。`FunctionInterfaces.bind_call()` 条件兼容 raw signature，不能因绑定计划正确就生成执行callee/body edge。环境端口也不应被 `FunctionSignature.parameters` 计数。

## 6. 推荐最小通用验收

### 6.1 静态 records/validator/query

- 同一 `FunctionSignature`/`code_definition` 构造两份静态环境 interface；别把静态 code ID当 env identity。
- exact entry Reference ports、formal refs、env refs、每个state domain分别分类；重复/缺失/跨Region/错variant/错cell slot或position、code-definition mismatch 必拒。
- explicit actuals 0/1/keyword/default/variadic pack与隐式 env/state Uses分开计数；`call_arguments`/`invoke_arguments` 仍是唯一事实来源；环境 role映射从它派生，重复实际值允许，多端口alias不拒绝。
- normal direct-call 与 normal/raise Invoke 验证每边的post-state/current-version；unknown environment effects不得标 `effects_complete`、`pure` 或“read only”。
- 查询分别断言 `DECLARED`, `NO_DECLARED_CALLEE`, `NO_DECLARED_ENVIRONMENT`；加载JSON重验结构，绝不声称JSON带运行authority。
- 严格历史codec：v1-v4 bytes/wire仍隔离重放；v5必须有真实environment capability；缺field/夹带field/空新capability拒。

### 6.2 Python语义反例

- 同code不同 factory closure；两个函数共享一个cell vs 两个独立cell；修改共享cell后调用。
- function with mutable positional default、kw-only default；修改容器元素、替换 `__defaults__`、删/改 `__kwdefaults__`。
- 两个 globals dict创建同code function；global命中/删掉后builtins fallback；自定义 `__builtins__` dict/module。
- decorator returns raw function/wrapper/callable instance/raises; descriptor and bound method receiver; `__code__`换新同code/异code object。
- function invocation binder TypeError时无body entry；成功entry之后 body raise；callback/closure逃出outer frame；recursive activation不串环境。
- lazy annotation访问的第一次执行/异常/缓存，3.14 type parameter and annotation scopes；不把 `__annotations__`静态读取当无效应。

### 6.3 工具adapter

FX adapter可用 `x+x` 检查两个 ordered argument occurrences虽有一个 unique consumer；导出图必须记录 symbolic vs make_fx vs Export stage及实际执行次数/guards。ETO/Profiler需小CPU+设备适配器分别验 rf_id/correlation scope、missing/partial trace、并关闭 tensor-data extras。`torchview`与`torchviz`仅candidate/visual cross-check，不成为SCAR canonical graph。所有缺失事件和工具source gap维持显式 unavailable。

## 7. 证据版本与复用材料

- Python语言依据：[3.14 data model](https://docs.python.org/3.14/reference/datamodel.html)、[execution model](https://docs.python.org/3.14/reference/executionmodel.html)、[compound statements](https://docs.python.org/3.14/reference/compound_stmts.html)、[expressions/calls](https://docs.python.org/3.14/reference/expressions.html#calls)。本机工作环境注明 CPython 3.14.7；网页路径标作 3.14，不可声称测试了全部 patch-level实现行为。
- PyTorch规范/API依据：[FX](https://docs.pytorch.org/docs/stable/fx.html)、[Export](https://docs.pytorch.org/docs/stable/export.html)、[Export IR](https://docs.pytorch.org/docs/2.14/user_guide/torch_compiler/export/ir_spec.html)、[Profiler](https://docs.pytorch.org/docs/stable/profiler.html)；实际安装版证据和 probe见 `artifacts/experiments/tooling_survey/export_dynamo/REPORT.md`、`tooling_survey/visual_fx/REPORT.md`、`tooling_survey/runtime/REPORT.md`。stable docs可能比本地2.13新；报告区分官方约定、源代码阅读与CPU probe观察。
- 当前模型入口：`docs/WHOLE_PROGRAM_MODEL.md`, `WHOLE_PROGRAM_MODEL_PLAN.md`, `CORE_GRAPH_MODEL.md`, `PROGRAM_TYPES.md`, `N2_FUNCTION_INTERFACES.md`, `M1_ENVIRONMENT_INTERFACES.md`, `M1_RESOURCE_INTERFACES.md`, `TOOLING_SURVEY.md`, `MODELING_INTEGRATION.md`。
- 代码映射审阅位置：`scar/ir/program/{model.py,functions.py,environments.py,queries.py,resources.py,source.py,validation.py,environment_validation.py,codec.py}`；`scar/analysis/{function_binding.py,function_interfaces.py}`；`scar/trace/{code_snapshot.py,call_edges.py,call_operands.py}`。

## 8. 新环境/entry-layout实现只读复核记录

此复核在上述初稿后进行；物理参数顺序的原建议已修正：**我没有发现要求显式→env→state物理顺序的语义理由，实际反序/interleaved反例通过。** 当前 `FunctionEntryLayout(environment, parameters)` 记录显式 Python formal 的逻辑顺序和值ID；环境成员保留 fixed role/cell 顺序；其余 entry `StateVersionValue` 按location取值。`environment_errors()` 以 exact ID集合验证 formal/env/state三类不交并覆盖entry，要求 formal/env 是当前 block 的 exact `ReferenceValue`；现有 core validator另外验证每个 state domain、call/invoke全entry arity/type、state currentness与完成边。`ProgramIndex.environment_call()` 先把物理 `entry.arguments` 与 canonical call/invoke Use位置配对，再按formal/member ValueID返回逻辑序的 `parameters` 和 role序的 `arguments`，state Use按 `LocationID`派生；没有靠固定物理分段。

已通过的通用反例包括：environment/formal互相冒充、遗漏formal端口、formal引用body result/state/member、scalar `DataValue`冒充Python formal、同一个 actual Python reference绑定到互不相同的formal/env entry port、同一location连续跨调用传入最新state、state stale输入、direct CALL与INVOKE、正式/物理序不同、物理位置把reference/state/env/cell任意交错、两种路径strict dumps/loads回读。严格wire tests检查旧v2/v3/v4 golden，拒绝v1—v4注入新环境字段，并要求v5完整env+layout capability。CLI报告 `WELL_FORMED` 同时将 `runtime_callable_verified`、`environment_realization_verified`、`environment_extraction_verified`、`python_signature_binding_verified`、`source_recovery` 与 `transformation_authorized` 明确置false；不是runtime authority。

审查运行：

```bash
/home/zyf/miniconda3/envs/lewm/bin/python -m pytest -q \
  tests/unit/test_program_environment_records.py \
  tests/unit/test_program_environments.py \
  tests/unit/test_program_environment_codec.py \
  tests/integration/test_environment_program_cli.py
```

结果 **148 passed, 1.57s**。另运行 `PYTHONPATH=/tmp/scar-structured-model-280qf4mi /home/zyf/miniconda3/envs/lewm/bin/python artifacts/experiments/b1_call_operands/model_environment_interfaces/review/adversarial_probe.py`：nested `object.__setattr__` 破坏 formal/env 分区和 bool cell position两项均被 `require_valid()` 拒绝；aliased actuals仍保留6个不同 Use但只对应一个 Value，结果为 `DECLARED`；JSON probe记录于同目录 `adversarial_probe.json`。初次未设置 `PYTHONPATH` 的probe启动失败（`ModuleNotFoundError: scar`），没有运行Python检查；设置repo root后成功。

精确复核source scope：HEAD仍为 `f80af0fedb20c20121707ee1aaf494844b7dcea5`，工作树dirty。以下SHA256是在上述测试完成后取值的工作树文件；它们不是提交SHA，也不代表未列文件冻结：

| 文件 | SHA256 |
|---|---|
| `scar/ir/program/environments.py` | `bc46be047812a9ca992ed920014b7d66dcbafef7b36397f5267ad7559f6bbf4f` |
| `scar/ir/program/environment_validation.py` | `a63089081e0c152f3519b8118310cdca62dd502cd000cb212aba71e04ed38d3f` |
| `scar/ir/program/model.py` | `5a989b8f07cb42003bee26b1c7757b5f61b6b0e3973807b49347ccd5785bc851` |
| `scar/ir/program/validation.py` | `3868b74b773593a1cf39a43d5819efc588fd55151d0af0e11683dfff56ddf03f` |
| `scar/ir/program/queries.py` | `749b9ce7b6234f13cf804737f8151901869bb3faa95f4fadf431f66bbb7c0d55` |
| `scar/ir/program/codec.py` | `c0cb4c5b7f359b46db3b898b35b19d79f6bdcbfb7a36313ac8ef931a41d9ce9c` |
| `scar/ir/program/__init__.py` | `c3d3dc7c1bbe6802c6a3d369589dce6c666aefb56f951871184312c99882f6e7` |
| `scar/cli.py` | `a41a45411338b7d15f23630578af3329514ee63b835df8d2f99e215130488790` |
| `tests/unit/test_program_environment_records.py` | `d9dd13426b6d4c99d6edf56baef600a4deab6a3686b3c3ed262e7aec9f54ede0` |
| `tests/unit/test_program_environments.py` | `eb20b9fd74733a816656096347decb897e33b45779e16c6f28b055f829ab4d01` |
| `tests/unit/test_program_environment_codec.py` | `d764a6862c7a397a77a7dfa6ed3305403359ef95e10e6a79043853ef1c1df07d` |
| `tests/integration/test_environment_program_cli.py` | `8e5e72ad6a6791d317c4601cdb2cbb9dd9c4adff9a938fbd37cc2316c84d0414` |

通过的静态record/layout/codec组件不关闭后续source adapter：当前旧 source profiles不生成 `ProgramGraph.environments/function_entries`，所以尚未证明从 AST/source `FunctionSignature` 自动产生这份映射；core只验证 caller输入与图上声明一致，不验证它们来自实际运行时 callable 的环境。这个是明确的下一步source/dynamic对应缺口，不是 entry物理排序问题。

**总体判定：** 当前环境表是已有 canonical ProgramGraph 上的、可验证的静态环境入口声明；它不是对象环境采集器。作为 M1 子组件，若 entry partition/validator/query 与函数接口和调用参数布局确实一致即可有结构价值，无需伪造普通 `Read`/`Invoke`。完整程序建模目前还被 owner/selector、环境动态绑定、scope/definition phase、未知副作用/控制、资源实例/readiness、occurrence-denotation/source coverage及 provider adapters多处阻断。只有显式保留这些gap并逐门验收，才不会把“能表达一张接口表”误称为“整个程序已建模”。
