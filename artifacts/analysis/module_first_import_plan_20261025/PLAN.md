# 原 module 首个 Import 的有序细化（设计，未实现/未运行）

输入固定于已通过入口门的原 ModuleUnit `opdef:init:2d91d50cf13f1e1f61014373`、原 namespace/context 和 whole-unit CodeWitness。此次只读了586B归档UTF8、既存小收据与相关源码/类型；未打开SP6/大source层/raw、未重candidate04、未compile或执行目标。

**自动选择与原控制范围。** 取同一原归档 AST 的 `module.body[0]`，要求是单alias、非dotted-name的 `ast.Import`（可有普通asname；首门不支持 ImportFrom、多alias、dotted、future/docstring跳越）。不按模块名筛选，不从后续挑一个方便语句。本例机械结果是 `import json`，原span `1:0–1:11`；剩余严格为 `module.body[1:]` 的10个原statement refs，起于 `2:0–2:9`、终于 `16:0–18:59`。由各原SourceAtom/span与module lexical owner唯一核回原SG Import定义及binding/output；原kind保持（不造CALL枚举或改OPAQUE种类），不能把不存在的计算Opcode记录冒充SG定义。`frontend_v2.py:357–392` 已把同一Import操作与原bind/output相连。

新增最小typed主体 `ModuleStatementSlice(unit, context, statements: tuple[SourceReference,...], suite: ControlFlowSuiteID, before: InsertionPointID)`：stmt成员必须恰好等于该原root AST的连续suffix，顺序不变、不遗漏、不重复；suite必须为原initializer的MODULE suite，before必须为首剩余stmt的原BEFORE insertion，anchor/source/version逐项匹配。normal/exception边界从同一原suite读取，不复制另一套CFG；原loop/try child suites及gap仍属于这些成员的控制范围。若原控制入口/归属不唯一，给准确frontier，不手造boundary ID。原95 atoms/92 **SG definitions**/45 CFG nodes/56 edges全集保留对账，不能改成prefix计数。

**连接与效果合同。** 保留现mapping entry及同一body Region；只细化该body内部：

```
unit entry (L,G,B,W) → 原body coordinator Region
  → prefix Import Region (L,G,B,W) ─NORMAL(import_ref,W1)→ STORE_NAME(L,key,import_ref,W1)
               └RAISE(exc,Werr)→ body RAISE                         ├RAISE(exc,Werr)→ body RAISE
                                                                  └NORMAL(W2)→ remaining Region(L,G,B,W2)
remaining ─NORMAL(None,W3)/RAISE(exc,W3)→ body completion → 外层原frame completion
```

共4个计算Region（entry、既有body、Import prefix、remaining），均为原core Region/callee/invoke，后三者不是额外Python frame。原entry→body关系保留；SourceProgram里的source links仅索引原source/SG与这些core端点，不建第二套读写图。

- `IMPORT_NAME_314` 是明确的**复合opcode协议**：输入saved builtins、globals、locals、由原AST/编译器核回的name/level/fromlist及world；覆盖从saved builtins取 `__import__` 与实际dispatch。绝不从locals/globals查同名函数，或重读当前globals['__builtins__']替代saved builtins；builtins lookup可能进入mapping行为。default-importer快捷路径与custom callable分派都属于该协议，不能把它简化成固定Python函数调用或只有IO。协议用现invoke的NORMAL(ref,post-world)/RAISE(exc,post-world)，effects_complete=False；可以不完成。importer的内部lookup/call/import/cache/sys.modules行为继续有展开债务，normal结果是**任意引用**，不据名称断言ModuleObject、sys.modules成员或新activation。
- 首门plain import的绑定key取 `alias.asname or alias.name`；无dotted-name时无需编造“取顶层包/属性链”步骤。STORE_NAME仍索引原Import/alias reference及原binding/output slot，不造ast.Name或SourceAtom去套赋值lowerer。level0/fromlistNone/name及IMPORT_NAME→STORE_NAME序列须在实际门从同一readonly root code核回，不只据AST猜编译器；不另造prefix CodeID或编译prefix。whole-unit CodeWitness仅提供原root资格，不能声称已捕获运行中的importer/namespace。
- `STORE_NAME_314` 接locals、准确key、import_ref及W1；NORMAL仅post-world，RAISE为exception+post-world。custom locals的写入、旧绑定释放/终结器与任意回调都保持保守，不套fast-local SSA或“纯绑定”。StateAddress复用 `InvokeStateOperand + ReferenceOwner + NamespaceKey`，至少索引builtins['__import__']的已知read和locals[key]的write，coverage=PARTIAL；其他global/locals/importer访问由整个coarse world承载，不伪造精确footprint或no-alias。
- import失败没有返回引用；import成功引用必须在进入STORE_NAME时活着。**STORE_NAME完整opcode边界**与其内部mapping调用边界须分开：按固定CPython合同核两completion的输入消费/临时引用顺序，再由producer/validator检查正常及异常pending集合；不能在store失败后悄悄继承一个已消费的import_ref，也不能提前丢引用。若这条边界不能从既有primary合同/readonly compiler定位核清，保具体consumption frontier，不填UNKNOWN来掩盖已知矛盾。复用现conditional FrameRules；不要求为所有Python primitive重建生命周期证明，不升级outer cleanup/runtime/effects。首次实现无需将lookup拆成假已观测callee或捏造__import__调用记录。

**版本与≤5源边界。** 当前v6明确是whole-unit opaque：`ModuleBodyOverlay/UnexpandedModuleBody`没有suffix主体，validator又固定2 Regions、5 protocols且source links全为unit（`source_module_validation.py:90,116,174`）。不能改标签后把整段body再接在prefix后，也不能放宽v6 guards使旧artifact换义。建议新增非默认body profile `ModuleBodyExpansionProfile.IMPORT_PREFIX_314_V1` + **SourceProgram7** 显式分支；entry ABI仍复用原 `ModuleEntryDeclaration/EXEC_MAPPING_314_V1`，旧v6 profile、typed codec、wholebody REQUIRED及普通reader路径逐字段不变。v7新 `ModulePrefixOverlay` 复用现correspondence/frame/census类型；增加原Import source/SG/region/core op索引和 `UnexpandedModuleSlice(subject=上述typed slice, region, operation, required_expansion=REQUIRED)`。残余op的ModuleUnit source仅作provenance；新 `UNEXPANDED_STATEMENT_SLICE` 协议与slice主体明确其执行范围，绝不重用v6 whole-body协议改义。core28/原SourceAtom和SG/CFG均不改。

| 生产文件（预计4，最多5；现在未改） | 最小变更 |
|---|---|
| `scar/ir/program/module_entries.py` | 新body profile、typed stmt slice/prefix overlay及严格v7 codec，旧v6记录保持 |
| `scar/analysis/source_module_lowering.py` | 首句机械selector、原body内prefix→store→remaining的ordered emission，whole-unit evidence复用 |
| `scar/analysis/source_module_validation.py` | 独立v7来源/原CFG范围/接口/状态/pending检查，原v6 validator不放宽 |
| `scar/analysis/program_lowering.py` | lower_entry显式非默认body profile，v7序列化/读回分流；旧v1–6/default3–4不变 |

现有 `StructuredBuilder.invoke_results/frame_exit_references` 与core callee已够用；不预先改第5文件。worklist/sourceentryv2、publisher、backend、runtime binder不在本次改口。Main未来只能语义merge，不能用隔离旧worklist整文件覆盖。

**唯一下一门（Root授权后再准备/运行）。** 同586B source unit、同原正常CompositionIndex/source层、readonly whole-root witness，机械首句选择1项，不运行旧candidate04、不读raw/77MB根、不执行import/torch/目标、不compile/fresh prepare。沿旧预算：1unit/1prefix、4000ops、retained stored+decoded含重复32MB、record/context/root4MB、source1MB、output+owned readback16MB、worker180s/outer240s、20s heartbeat/GNU/SELF，源码/runtime SHA guard各32MB/pass；任何新增输入须先给Root准确receipt/预算，不静默增限。可在同新门只消费原v6 artifact一次以证兼容（其83250/933492B纳入预算），不重lower它。

验收：首句由原AST/SG/CFG/readonly compiler唯一核回；import结果reference确实进入STORE_NAME，post-world只沿正常成功路径进入准确remaining slice；lookup/import/store任一raise不得执行tail；两completion pending消费正确；callee/Region和original source links在完整普通v7 roundtrip中保留，v6原artifact及wholebody REQUIRED原样通过；残余正好原10 statements，原95/92/45/56及9 groups/271 calls分母不变。仅允许声明“首Import/namespace store接口已展开”，其importer内部、10句残余、runtime namespace/alias/ModuleObject/sys.modules、outer effects仍OPEN；绝非完整module数据流。阴性只覆盖实际新增合同：篡改suffix成员/控制入口、乱序world或丢raise、错消费pending应拒绝，不增全语法矩阵。现在没有新Gate、数据或实现结果。
