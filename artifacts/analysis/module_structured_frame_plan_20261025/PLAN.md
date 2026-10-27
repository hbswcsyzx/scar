# 通用 frame root 与 module 递归展开（仅设计）

不编码、不运行gate/fixture/目标、不compile、不读大图/raw。仅重读586B归档（SHA f838ded2da95e6689bf437c9435367200d3d9ccc4c1244f17f205d89858e7c1b）及相关类型/producer。Root最新指令已撤销“core28固定”限制：不能为兼容旧实现而把Try上下文塞入opaque再称完整。

**真实类型断口。** `control.py:81–110` 的ControlScope.source只收SourceReference，唯一无parent根为FUNCTION；`control_validation.py:128,148,188` 要求每个启用Region有FUNCTION根，RAISE exit也只认它。MODULE没有SourceAtom，不能造Root SourceReference或改叫FUNCTION。C1本身以BLOCK/CLEANUP、pending、saved context和已有state location工作（`cleanup_validation.py:96–111`），没有必须复制的模块版pending机制。当前source层只有Assert/Raise helpers，没有通用Try producer。此前“普通world context替代C0/C1”的备选不采用。

**严格最小模型：core29 + 一次性的 SourceProgram8。** 保留旧core1–28/旧source1–7的闭合解码、能力与默认策略，不让新enum/union被旧版本静默接受。

```
ControlScope(kind=FRAME, parent=None, source=ModuleUnitSource)
         ↑ scope ID
FrameRoot(kind=MODULE, code=既有 CapturedCode, entry=MappingFramePorts(L,G,savedB,cells,W))
         ↓ 同一Region中的真实词法scope/port
BLOCK / LOOP / CLEANUP → 既有ExceptionPacket / PendingCompletion / C1 context保存恢复
```

- source subject与root frame种类/ABI分开：ControlScope新增通用FRAME根；FrameRoot关联同scope、现有完整CapturedCode身份和entry binding。MappingFramePorts仅命名已有ValueID/State端口，不创建Value或第二环境图；FUNCTION ABI只引用既有EnvironmentInterfaceID（由它唯一找到已有FunctionEntryLayout），不在FrameRoot再复制BodyEntryInterface/FunctionEntryLayout；MODULE用mapping端口；CLASS可用同端口形状但source为准确ClassDef reference，未有合法entry adapter时拒绝生成，不伪装MODULE/FUNCTION。frame kind是静态code/source主体类别，不证明经import/exec/FunctionType哪一种进入，也不证明实际ModuleObject或namespace身份。
- **只保一份入口权威**：新SP8 overlay引用core FrameRoot scope ID，ABI存在core记录；不再同时复制旧MappingFrameEntry字段。旧SP6/7维持原overlay。把既有ModuleUnitSource原类下移到一个无model依赖的公共source-subject文件，module_entries仅re-export同一类，字段/旧wire不变，避免control→module_entries→source/model的循环。CapturedCode沿用原pycode-v2完整descriptor；不能把legacy `ir.ids.CodeID` 的marshal `pycode-sha256` 键当同一身份强转。Root witness仍由正常CodeWitness reader核whole unit，不制造statement CodeID。
- root可有BLOCK/LOOP/CLEANUP后代，直接块所有权完整分区、nearest-loop、pending目的地、清理顺序全部沿现C0/C1。MODULE正常结束走FALLTHROUGH landing→None+world→Region normal exit，不能伪造源码return语句；RAISE携既有ExceptionPacket。原source6/7的reference+world异常接口不改；SP8 primitive的RAISE completion统一为`(exceptionRef, propagationTracebackRef, world)`，两引用属于**本次传播**，随后用既有ExceptionPacketDefinition包装；不能猜exception.__traceback__快照或填None。正常路径上已构造/归一化的异常对象（如assert失败）须经明确PROPAGATE_EXCEPTION协议取得传播载荷，再接同一raise-sink。新builder的payload/raise-sink hook把完整传播载荷路由到最近Try，for的StopIteration分流保留原载荷，未命中不能丢traceback再构造；旧函数completion/failure callback不变。
- Try使用现ExceptionMatcher动态handler operand、ExceptionPacket、PendingCompletionDefinition、HandledContextDomain、CleanupEnter/Resume/Replace与saved handled-context协议；不再定义另一套pending/exception结构，不用whole-world UNKNOWN隐藏可表达的捕获/恢复/替换关系。源码`ValueError`按真实LOAD_NAME求值，不能凭拼写固定为builtin。except-as绑定正常/异常出口都接原compiler隐式STORE/DELETE，custom mapping清理失败可替换pending。原source CFG的Try gap原样保留；新core控制从原AST/whole-root CodeWitness与异常表恢复，不把旧gap改PASS。

**一次通用body overlay，不再每句升SP。** `StructuredFrameBodyOverlay(root_scope, namespace_policy, stmt_expansions, correspondence, protocol_indices, required_expansions)`统一表达多种语句。每个slice以准确unit/context、lexical owner、闭合AST序列字段（BODY/ORELSE/HANDLER_BODY/FINALBODY）及有序原SourceReferences标识；有旧suite/BEFORE anchors则绑定，无旧完整CFG时保准确源控制gap并由core作用域/port建立新控制，不捏造旧CFG ID。展开关系只索引已有core scope/entry/normal/raise ports与原source成员：子slice有序、不重叠、完备覆盖父成员；未展开者保持原精确subject+REQUIRED。递归展开通常在**同一个实际frame Region**内产生BLOCK/LOOP/CLEANUP，计算子Region不冒充新的Python frame。协议能力集合显式版本化，后续支持新AST族只加受控producer/capability与validator，不换overlay字段或每句发SP9。

**namespace策略与可复用点。** 采用固定typed策略MODULE_MAPPING / FUNCTION_FAST_LOCALS（class prepared mapping暂为债务），不能任意callback或借STRUCTURED_ENV标记绕guard。`StructuredBuilder:118,152,239,304,495`的named BlockArguments/LocalBindingValue、define/read_local、store和build_function均强依赖function slot/symbol-table/formal ABI；`environment_lowering.py:51–69,95–112,258–284`还强制五项函数环境前缀和require_definition。它的expr/condition分发（113–143）可提成共享helper，Name/const/store仍由固定typed namespace/root-evidence策略实现；不能为了少改一文件而复制dispatcher或借EnvironmentBuilder构造假函数环境。入口/namespace策略须抽出，旧function adapter继续原样。

- MODULE的Name读取是独立LOAD_NAME协议：L miss才到G，再到savedB；mapping的未找到与其他异常分开，任一lookup可调用Python/raise/改world。STORE/DELETE_NAME是mapping访问/尝试，顺序world/normal/raise完整；地址复用ReferenceOwner+NamespaceKey+PARTIAL，**normal不授StoredValueWrite/内容已存证明**。不得根据刚才store把随后Name读取替成已知SSA引用。显式global声明按原compiler分类路由G，不能看变量名字。
- mapping策略不把namespace名字放cursor.env当fast locals；loop只携world、iterator及必要表达式引用，名字状态经namespace world回路。复用现GET_ITERATOR/ADVANCE_ITERATOR/MATCH_STOP_ITERATION、branch/merge/loop ports；不unroll256，不假定range/type/ValueError等builtin身份。
- 复用现source_heap的SG+真实source恢复、普通有序Call/Attribute/Index/BinOp、conditional短路、mapping/字符串协议及Assert/Raise helper；不能照搬function专用AnnAssign语义。`() `等compiler常量从同whole-root CodeWitness通过现CodeConstantSource/READ_CODE_CONSTANT索引，不新造任意scalar evaluator。helpers中带function require_definition的入口不能靠假函数调用，改由明确root-evidence hook或模块adapter核回。
- future模块FunctionDef必须把新函数的globals接G，builtins按函数创建协议从G解析并保存（未必等于当前module savedB），不是捕获L；L只是最终绑定函数对象的STORE_NAME目标。默认值/装饰器按源码有序求值，3.14 annotation/code/cell环境另验。现仅有有界genexpr函数创建，没有通用def producer；本真实11句没有def/class/closure，所以这些不阻塞本unit，但必须列类型/producer债务，不能伪函数对象/defaults/cells。

**原11条机械清单与完整展开路径。** AST索引不是业务白名单；全部保原95 atoms/92 SG definitions/45 CFG nodes/56 edges，循环/异常的嵌套成员另递归，外部callee/primitive内部仍可有具体效果/展开债务。

| index / source行 | AST类型 | 数据/控制连接与所需补口 |
|---|---|---|
| 0 / 1 | Import | 已有import→mapping store接口；按通用dispatcher复用，不专判json |
| 1 / 2 | Import | 同族自动推进，不发新wire |
| 2 / 3 | ImportFrom | IMPORT_NAME(fromlist)+IMPORT_FROM→STORE_NAME；attribute/circular-import fallback与container消费保持may_raise，不推ModuleObject |
| 3 / 4 | Import | 同族，torch仅原源字面量，目标不执行 |
| 4 / 6 | Assign | Name torch→attribute ones→`() `/keyword cpu→call→STORE_NAME x，callee/effects保守 |
| 5 / 7–8 | For | iterator/stop分流/回边，STORE_NAME `_`；body LOAD_NAME x→加法→STORE_NAME x；不按256展开 |
| 6 / 9 | Expr | 有序cat/list/两次reshape与x namespace读取；discard结果，calls非pure |
| 7 / 10 | Assign | None→mapping store exception_type，不能把后续读取当已存内容 |
| 8 / 11–14 | Try | call失败packet→动态except匹配/handled context→STORE_NAME error→handler赋值→隐式None-store/delete→C1 restore/replace；未匹配向外传播 |
| 9 / 15 | Assert | compare与and短路/动态truth；失败走内建AssertionError构造与raise，不查同名namespace |
| 10 / 16–18 | Expr | Path/os/json读取、environ下标、dict各项和getpid/序列化/write_text按源码顺序，所有call/heap/namespace后world连接 |

推进分三小段但**同SP8**：A先严格frame-root/ABI/source与C0/C1类型门（不假函数）；B复用source adapter恢复imports+Name/Assign/Expr/For，精确Try slice仍REQUIRED；C接真实Try/except/清理、Assert/最后Expr，使这11条及嵌套源码成员都有有序core数据/状态/控制路径。完整source拓扑不等于importer/torch/native/OS资源执行或效果证明，scope总状态仍由独立义务判断，不能只清unknown计数。source858/runtime843与原动态分母不变。

**实际最小实施面12生产文件，不能硬压到6而少建关系。** 六处core/source-subject类型与codec/validator是跨层闭环必需；另六处负责overlay、入口分流、共享builder/表达式、module producer/验收和Try source连接。

| 文件 | 必要理由 |
|---|---|
| 新`ir/program/source_subjects.py` | ModuleUnitSource单一定义下移、FrameKind/MappingFramePorts/FrameRoot；打断model依赖环 |
| `ir/program/module_entries.py` | 旧类re-export、一次通用SP8 body/slice overlay；旧6/7 types/wire封闭保留 |
| `ir/program/control.py` | FRAME根与typed source-subject union，旧FUNCTION根兼容 |
| `ir/program/model.py` | 唯一frame_roots索引关联core scope/code/ABI，不复制pending/state |
| `ir/program/codec.py` | core29显式能力与严格field/tag；旧≤28拒新root，不默默升级旧图 |
| `ir/program/control_validation.py` | 通用根/ABI/subject/code/端口验证，保全部旧C0根所有权/转移约束 |
| `analysis/program_lowering.py` | SP8 closed dispatch/codec与explicit capability；旧1–7不放宽 |
| `analysis/structured_lowering.py` | 中性root/namespace/exception-payload/sink hooks和复用loop/expression验证；旧function adapter不变 |
| `analysis/environment_lowering.py` | 提取已有expr/condition共享分发，保function环境/快局部adapter原合同；module不复制分发或伪造五前缀 |
| `analysis/source_module_lowering.py` | mapping策略、递归slice、ImportFrom、code constant与有序source producer |
| `analysis/source_module_validation.py` | 同一通用overlay的source成员覆盖/策略/控制关系检查，接正常core29 C0/C1 validator |
| `analysis/source_statement_lowering.py` | 新通用Try/except-as source连接器，复用现C0/C1与既有Assert/Raise，不再atomic Try冒充恢复 |

`cleanup.py/cleanup_validation.py`已有关系可直接复用，当前未见必须改的FUNCTION特判；若实际API复核发现额外文件需要改，先报具体关系。此范围不含自动class/通用FunctionDef producer、backend、detectors、原planner/发布/运行binder，也不借范围限制伪造这些能力。下一授权应先审core29实体/codec小门，再做同586B逐步source gate，不能直接再跑一条全body opaque窗口当推进。

**一份实际source-only窗口的验收入口（设计，未执行）。** 授权后按现ModuleCatalog机械选唯一exec-mode root及whole-unit witness，同一586B原文/95/92/45/56上下文；不按文件名、import字符串或函数名选择。A的类型/codec定向检查通过后完成B/C，再由root持有一次真实窗口：input≤32MiB、source/runtime guard各≤32MiB、output≤16MiB、4000 construction ops、outer≤240s；不自动提高预算，不重lower旧SP6/7。窗口用普通SP8结构+AST/原CodeWitness验证及同一archive的旧SP6/7只读兼容消费；compile/target/prepare计数须guard为0，AST解析单列。实核全部11条及嵌套成员的slice覆盖、顺序data/world/control、normal+raise与Try handled-context/except-as cleanup关系，源成员缺失/传播载荷丢失/FrameRoot与code或ABI不匹配均失败。仍缺任何语句连接就保精确slice REQUIRED、body OPEN，不称完整unit；importer内部、call/native/OS、runtime activation、conditional frame效果继续独立OPEN。
