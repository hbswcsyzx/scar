# 开发与用法

使用现有 `conda activate lewm`，只在 `~/AAA/scar` 的 `main` 开发。
不创建 worktree、日期版源码或历史实验副本；正常提交 Git，不 reset。
不修改外部 LeWM、数据/权重、CUDA/driver 或整套环境。删除实现前先查引用。

## 当前形式前端入口

```bash
python -B -m scar.cli source-bytes --file /path/to/program.py --out /path/to/fresh-material
python -B -m scar.cli source-bytes --model /path/to/model --out /path/to/fresh-f0 --jobs 4
python -B -m scar.cli source-bytes --model /path/to/model --out /path/to/fresh-check --verify
python -B -m scar.cli source-tokens --model /path/to/model --out /path/to/fresh-f1 --jobs 4
python -B -m scar.cli source-tokens --model /path/to/model --out /path/to/fresh-lexical-check --verify --jobs 4
python -B -m scar.cli source-syntax --model /path/to/model --out /path/to/fresh-f2 --jobs 8
python -B -m scar.cli source-syntax --model /path/to/model --out /path/to/fresh-syntax-check --verify --jobs 8
```

F0只保原始bytes与编码结果。解码失败仍存原bytes；文件不可用/预算停止准确报错，不给后层授权。
现有模型只追加每源raw/token分片；旧源码和IR保持。F1也可用`--file PATH`独立采集（先执行F0）。
`--max-tokens`是每源上限；verify按原工件预算重放，原预算超过本次上限则拒绝，不会静默忽略限制。
F1只转录词法，不证明语法有效；原生错误保prefix，预算停止不发布partial模型。
F2默认exec，也支持eval/single/func_type；--file先经过F0/F1，--max-nodes是每源AST上限。
源码始终只解析为AST；语法成功不证明作用域/控制合法。大literal超固定预算准确报frontier，不标UNKNOWN。
F0至F3及F4-A已在声明材料域验收；当前F4-B操作签名和产生规则尚未完成，前层未验收不新增后层功能。
当前profile固定本机CPython及tokenizer源码/静态解释器二进制指纹；内置tokenizer的shared Python暂不接纳。

F3-A：

```bash
PYTHONHASHSEED=0 python -B -m scar.cli source-symbols --model /path/to/model --out /path/to/materials --collect-only --jobs 8
PYTHONHASHSEED=0 python -B -m scar.cli source-symbols --model /path/to/model --materials /path/to/materials --out /path/to/check --verify --jobs 8
```

固定seed只用于分析进程；实际hash上下文写入profile，worker不一致时拒绝。每源scope/symbol上限可配置，
F1/F2及原材料的replay预算也受本次上限约束。默认capture会向可写模型只追加source_symbols；
collect-only是独立材料store，fresh核验绑定必需源码收据。PUBLIC_COMPILER_VIEW/UNJOINED不授AST绑定或scope完整性。
/home已恢复可写，同一main的只读期间提交已合并，普通入口可直接使用。
已验F3七层已按原收据登记到当前模型；`/var/tmp/scar-f2-recovery-7w7nd_0z/`仍保历史材料，canonical查询无需传外部store。

F3-B（只分类字段角色，不执行symtable或目标）：

```bash
python -B -m scar.cli source-roles --model /path/to/model --out /path/to/roles --collect-only --jobs 8
python -B -m scar.cli source-roles --model /path/to/model --materials /path/to/roles --out /path/to/check --verify --jobs 8
```

每store只保存一份`source_roles/catalog.json.gz`，每源为稀疏原槽ports和484条计数；
`--max-ports/--max-slots`限制本层，`--max-nodes/--max-tokens`同时约束上游重放。
默认capture向可写模型只追加source_roles；collect-only不改模型，verify重新计算角色与计数。
纯API以`read_source_syntax_material`取得验证后的不可变F2材料，用`SyntaxRoleView(material)`复用索引查询。

C1源码上下文（不求词法存储或建立真实frame）：

```bash
python -B -m scar.cli source-contexts --model /path/to/model --roles-materials /path/to/roles --out /path/to/contexts --collect-only --jobs 8
python -B -m scar.cli source-contexts --model /path/to/model --roles-materials /path/to/roles --materials /path/to/contexts --out /path/to/check --verify --jobs 8
```

外部B输入只允许只读采集/核验；B已注册model时可省`--roles-materials`并使用默认增量发布。
C1只存scope/region/private策略与稀疏原槽边界，catalog共享一份；同源F2/B各只fresh一次。
`SourceContextView(syntax, roles, contexts).resolve(slot)`或`.port_context(port)`复用父槽索引；不复制端口或逐槽context。
`--max-scopes/--max-regions/--max-boundaries`限制本层，`--max-slots`及其余输入预算同时约束重放。

C2a名字投影和整scope声明：

```bash
python -B -m scar.cli source-declarations --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --out /path/to/declarations --collect-only --jobs 8
python -B -m scar.cli source-declarations --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --materials /path/to/declarations --out /path/to/check --verify --jobs 8
```

外部B/C1输入只读、全收据固定；全部canonical时才允许默认append。每原B port一disposition，名字只intern一次。
`SourceDeclarationView(...).port/scope/contribution/name`查询原引用账本；`--max-names/--max-contributions/--max-conflicts`约束本层。
投影阶段固定`SYMBOL_VISIT_PROJECTION`；源码操作意图、visit flags、visibility和C1抑制分别保存，不授运行值或物理地址。

C2b条件化namespace接口与捕获（仍不授C3编译器投影）：

```bash
python -B -m scar.cli source-bindings --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --declarations-materials /path/to/declarations --out /path/to/bindings --collect-only --jobs 8
python -B -m scar.cli source-bindings --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --declarations-materials /path/to/declarations --materials /path/to/bindings --out /path/to/check --verify --jobs 8
```

三个上游store固定原收据；全部canonical时才允许默认append。每store一catalog、每源一类型化绑定分片。
`SourceBindingView(roles, contexts, declarations, material).port/scope/binding/interface/plan/capture/relay`查询原引用，`.verify()`核引用与逆边。
八项本层预算超限不发布部分表；源码冲突保端口与原因。namespace为源码模板，未观察运行字典、物理cell或地址。

C3-T编译器拓扑（需要固定分析进程hash上下文；不运行目标）：

```bash
PYTHONHASHSEED=0 python -B -m scar.cli compiler-topology --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --symbols-materials /path/to/symbols --out /path/to/topology --collect-only --jobs 8
PYTHONHASHSEED=0 python -B -m scar.cli compiler-topology --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --symbols-materials /path/to/symbols --materials /path/to/topology --out /path/to/check --verify --jobs 8
```

`CompilerTopologyView(roles, contexts, native, material)`查询`.scope/.region/.block`，传原SourceContextView后可查询`.port`。
模板保原construction parent/children；PUBLIC引用原F3-A行，INLINED/FUTURE_DETACHED保模板和规则，不伪造公开行。
`--max-blocks/--max-rewrites/--max-visit-steps`约束本层；只验拓扑与scope元数据，符号来源/参数仍未投影。

C3-S符号来源与参数投影：

```bash
PYTHONHASHSEED=0 python -B -m scar.cli compiler-symbols --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --declarations-materials /path/to/declarations --symbols-materials /path/to/symbols --topology-materials /path/to/topology --out /path/to/compiler-symbols --collect-only --jobs 16
PYTHONHASHSEED=0 python -B -m scar.cli compiler-symbols --model /path/to/model --roles-materials /path/to/roles --contexts-materials /path/to/contexts --declarations-materials /path/to/declarations --symbols-materials /path/to/symbols --topology-materials /path/to/topology --materials /path/to/compiler-symbols --out /path/to/check --verify --jobs 16
```

`CompilerSymbolView(declarations, topology, native, material)`查询slot/fact/source/port/symbol/parameter，`.why(scope,ordinal)`返回有界来源引用。
source slot、compiler slot与native行分域；scope code不是低位flag；varnames只是有序参数，不冒充runtime locals布局。
五项独立本层预算与原D.max_contributions分开；超限不发布部分来源表，外部五store均固定原收据。

F3-D只读组合验收（不复制程序图，不运行目标）：

```bash
PYTHONHASHSEED=0 python -B -m scar.cli frontend-check --model /path/to/model \
  --roles-materials /path/to/roles --contexts-materials /path/to/contexts \
  --declarations-materials /path/to/declarations --bindings-materials /path/to/bindings \
  --symbols-materials /path/to/symbols --topology-materials /path/to/topology \
  --compiler-symbols-materials /path/to/compiler-symbols --out /path/to/fresh-check --jobs 16
```

全部材料已注册到model时可省略对应sidecar参数。只写验收summary，固定输入/实现收据并重验原Q/S及父层。
`read_frontend_bindings(F0,F1,F2,B,C1,D,Q,A,T,S)`返回原表组合view；
`.port/.implicit/.endpoints/.parameter/.why`分别查询原引用，不合并源码namespace与compiler分类。
endpoint中的KEEP路径显式标记association；query预算耗尽返回incomplete与最多一条frontier及remaining，不当成无依赖。

已接受材料的登记（原字节复制，不重新授予语义结论）：

```bash
PYTHONHASHSEED=0 python -B -m scar.cli frontend-register --model /path/to/model \
  --acceptance /path/to/accepted-f3d/result.json --acceptance-sha256 ORIGINAL_ACCEPTED_SHA \
  --verifications /path/to/seven-verification-reports.json --out /path/to/fresh-registration --jobs 8
```

verification映射的键是七种artifact名，值为各原fresh报告的绝对路径。SHA须来自先前已接受的F3-D记录；现场重签不是验收。
登记核source/父层收据、原报告、实际DTO、catalog及当前profile；字节、实现或输入域变化时拒绝。`jobs`控制复制并发。
保持原ID和证明范围，报告标`HISTORICAL_FRESH_ACCEPTANCE_REUSE`；正常语义reader仍执行原strict检查。
每层独立持久化；中断可留下已登记前缀，重新使用同一输入和新的输出目录可复用完全相同的已登记层。

F4-A共享结构目录（不执行目标、不构造程序实例图）：

```bash
python -B -m scar.cli program-types --out /path/to/type-materials
python -B -m scar.cli program-types --materials /path/to/type-materials --out /path/to/fresh-type-check
```

`program_type_catalog/read_program_type_catalog`保原记录类型、字段语法和实现收据；
`validate_program_shape(graph,max_visits=...)`核exact名义类型与构造约束，返回cross-record/opcode语义未核标记；完整图仍须后层核验。
类型图递归用REF表示，值对象循环拒绝；原图和输入目录不改，不存每次迭代数值。
当前已恢复的共享目录位于`artifacts/current/type-grammars/`；独立fresh记录在`queries/type-grammar-restoration/verification/`。

F4-B接口查询：`ProtocolSignatureIndex(graph, structured, interface, metadata, language=language).match(original_operation_id)`，
入口在`scar.ir.program.protocol_signature_context`。规则来自typed protocol，world/ABI等从原接口绑定；缺原参数返回带字段的
`MISSING_SIGNATURE_CONTEXT`。显式补参仅供诊断，不能覆盖自动绑定或授予源码/变换许可；当前还不是规范图发布入口。

源码产生规则的结构入口在`scar.analysis.source_productions`：`production_type_catalog/read_production_type_catalog`核共享类型目录，
`validate_production_plan/production_plan_document/read_production_plan`核有界记录、原引用类型、区域归属和有序端口。
`ProductionSourceIndex(F0, SourceContextView, FrontendBindingView).match(plan)`复用已严格读取的父层；输入SHA只计算一次，不重parse或复制F2。
源码role port与namespace access分开；属性/keyword标签不能被接成变量读写。输出明确保`source_rules_replayed=False`，当前不能发布canonical新图。

局部表达式规则（F4-B，尚未闭合全域）：

```bash
PYTHONHASHSEED=0 python -B -m scar.cli source-expressions --model /path/to/model --source /original/source.py --out /path/to/materials --jobs 2
PYTHONHASHSEED=0 python -B -m scar.cli source-expressions --model /path/to/model --source /original/source.py --materials /path/to/materials --out /path/to/fresh-check --jobs 2
```

`--source`可重复；省略时处理声明源码全集。每源流式写一个`expressions.jsonl.gz`，共享目录只存一份，fresh逐记录重新产生并比较。
规则目录绑定recipe类型目录摘要；输入语法或记录构造契约变化时拒绝沿用原材料。
材料v2逐原表达式分区为局部recipe、父属表达式、已知不单独求值的源码、规则前沿，计数必须精确覆盖原分母；SUPPRESSED_SOURCE保C1原因/原槽，不冒称缺失规则或删除源码。
`SourceExpressionRules(ProductionSourceIndex, world=…, exception_abi=…).build/verify`不parse目标；按原字段定义顺序，保持state流与短路对象身份。
显式rule frontier保原occurrence/构造/用途；child接口、效果和state来源仍是义务。不能用这个入口宣称完整CFG/SSA或执行图已生成。
调用/显示使用已有PythonProtocol签名，item/pair数量由原字段分组导出；父属描述符另记`PARENT_SOURCE_DESCRIPTOR`，不计作缺失的独立表达式规则。
容器、格式化/模板规则分别在`source_display_rules.py`、`source_string_rules.py`；代码SHA和精确字面值输入类型均进入共享规则目录。
推导式在`source_comprehension_rules.py`；同步/异步子句共用循环模板，异步advance复用已取得的await iterator，按StopAsyncIteration耗尽。原C1求值归属决定eager/惰性异步传播。
`source_suspension_rules.py`按原C1执行owner产生Yield规则，区分普通／异步yield和bare None；normal／raise恢复入口显式接收新world，不能保存旧STATE。
`source_delegation_rules.py`产生Await/YieldFrom共享循环；recipe v3显式保存delegate端口，4种协议强制核签名。采集仍不展开driver/native，准入、close规范化及frame/context保活另验。
`source_callable_rules.py`产生Lambda及GeneratorExp的创建/延迟body；参数、初始默认值和活跃转交cell沿`source_deferred_interfaces.py`接原F3，不在创建时读取cell内容。v5分别表示异步generator的AWAIT推进及ASYNC_YIELD。
语句入口：`python -B -m scar.cli source-statements --model /path/to/model --source /original/source.py --out /path/to/materials --jobs 3`；保相同`--source`选择，加`--materials /path/to/materials`并换独立输出即可fresh核验。当前28类：Expr/Pass/Assign/Delete/Return/Global/Nonlocal/If/While/For/AsyncFor/Break/Continue/AugAssign/AnnAssign/Assert/Raise/Import/ImportFrom/FunctionDef/AsyncFunctionDef/ClassDef/TypeAlias/With/AsyncWith/Try/TryStar/Match。两入口复用collector但保独立domain、catalog和分片，不互认收据。
v6语句suite保normal/return/raise/break/continue端口，循环跳转由原F2 occurrence定位并由对应模板消费。`source_statement_interfaces.py`只给保守child接口，不授child实现、路径可行或清理证明；未来组合须检查实际child出口是该接口的子集。升级须重采集并fresh核验，不改旧材料的version冒充迁移。
v7原子语句在`source_statement_atoms.py`；compile option、inplace operator及annotation publication都有强制接口检查。target和声明地址中的slice/tuple按原父槽分类，避免多生成一次普通写入或容器构造。DEFERRED annotation另计`ANNOTATION_REQUEST` child义务；编译选项未解析和请求body未降低分别保false，不冒称已完成。
v8导入规则在`source_statement_imports.py`；保原alias/module/level引用和已知名字投影，正常路径按原序请求、取成员、绑定。`alias`作为父属描述符单独记账；不能将from-list、成员查找及绑定名字混为同一字符串，也不以一次静态请求证明module body已执行。
v9函数创建在`source_statement_functions.py`；defaults与退出路径复用`source_callable_rules.py`。docstring为父属metadata；函数注解另计`FUNCTION_ANNOTATION_REQUEST`义务，调用准入、请求body和native frame仍未证明。
v10的`source_type_parameter_interfaces.py`接原F3 scope/声明/resolution/capture，`source_type_parameter_rules.py`生成工厂激活和三类type parameter的顺序动作。lazy evaluator另计bound/default request义务；其body与native factory布局仍未降低。v11的`source_definition_interfaces.py`和`source_statement_definitions.py`接类及类型别名，复用泛型工厂与调用参数组装；class callback保独立namespace入口，类型别名另计`TYPE_ALIAS_VALUE_REQUEST`。class namespace初始化/收尾是待展开的typed边界，不能当作纯操作。
v12的`source_statement_contexts.py`接同步/异步with，复用完成路由和await推进；`withitem`为父属描述符。`restore_handled_completions`在所有完成上恢复先前异常状态；不能用未绑定的普通attribute lookup代替type-special方法查找，也不将正常exit结果用于抑制return/break/continue。当前只授局部规则与端口一致，native派发、frame/lasti及引用清理仍未证明。
v13的`source_statement_exceptions.py`接普通try；ExceptHandler为父属描述符，`suite_at`复用原字段列表调度handler body。MatchExceptionType保验证及匹配异常，DeleteExceptionBinding只接受原清理声明；finalbody为一份SHARED模板，通过显式完成路由保留/覆盖pending结果。所有调用须在同一词法activation内，不能借共享访问另一函数的参数或world。
v14的`source_statement_exception_groups.py`接TryStar，clause在同一dispatcher按序构造，不递归复制后续clause。分开body异常收集与分派失败，复用原异常名清理和共享finally。PrepareReraise输入改为异常引用/world，输出仍依明确异常ABI；旧材料须重新生成并fresh，不直接改version。
v15的`source_condition_rules.py`接条件上下文，`SourceExpressionRules.build(occurrence, ProductionPurpose.CONDITION)`返回BOOL/world。材料v3自动遍历CONDITION child请求，在原occurrence分区之后追加`LOCAL_CONTEXT_SOURCE_RULE`记录；`condition_recipes`单列，不冒充新增源码。fallback用同occurrence的VALUE模板，键必须含purpose；`DELEGATED_VALUE_RULE`保留被委托字段。更新后须重新生成并fresh，旧v2材料明确拒绝。
v16的`source_pattern_interfaces.py`从原F2/F3导出捕获、分支一致性和native操作端口；`source_statement_patterns.py`接Match，八类模式由父语句拥有，不单独当表达式求值。匹配失败不输出假捕获，成功后写入再判断guard；失败/后续case用共享模板。局部规则不授native内部实现、引用清理或全图证明。
v17的`source_root_interfaces.py`及`source_root_rules.py`接三类执行根：`python -B -m scar.cli source-roots --model /path/to/model --source /original/source.py --out /path/to/materials --jobs 3`。同源选择加`--materials`并换独立输出即可fresh；根、表达式和语句各保独立domain。FunctionType为非执行语法，不编造入口。入口仅在外部namespace准入之后建模，scope注解函数保留待展开请求，不能据此宣布完整依赖图。
v18的`source_evaluation_interfaces.py`导出原请求环境并做受控编译器字符串化查询，`source_evaluation_rules.py`生成函数注解及类型求值器的共享body；创建操作必须引用真实body ID。材料v4增加`evaluation_request_templates`和`stringized_annotation_values`，原入口/命令不变，须重采集/fresh，旧v3不互认。内核不parse或执行目标；仅字符串化查询恢复原F2子树并静态编译wrapper。模块/类汇总请求仍待展开，全部native/准入证明不由模板存在替代。
v19的`source_class_namespace_interfaces.py`从原scope/resolution/role推导隐式访问及编译metadata，`source_class_namespace_rules.py`展开有序prelude/finalization。旧InitializeClassNamespace/FinalizeClassNamespace类型已删除；按现有三入口重采/fresh即可，不改旧recipe版本。logical name/cell、未知native捕获传递及class注解汇总仍分别保留，不据普通namespace动作已展开宣称全层完成。
v20的`source_capture_interfaces.py`复用原F3活跃hop，并从原C3 FREE证据补充源解析可定位的共享捕获父链；`CaptureReference`明确区分旧整数ID与新复合键。`owned_cells`只是原binding的逻辑cell要求。三入口和材料外壳仍相同，旧实现pin不能直接fresh；须重生成v20 recipe，不改旧header。模块/类注解汇总体、准入和物理frame仍未闭合。
v21的`source_scope_annotation_interfaces.py`为模块/类请求导出原scope、共享捕获和三种目标优化策略的登记表；不parse或执行目标。BuildScopeAnnotations/BuildClassAnnotations现在必须带annotations及body ID；ReadAnnotationRegistration保环境/新world和异常出口。材料v4新增两种request计数，不再把它们记作SCOPE_ANNOTATION_REQUEST整块义务。沿原入口重生成即可，原F2/F3材料不变；源码模板与原编译单元是否保留该代码分开记录。
v22的`source_annotation_state_interfaces.py`导出namespace/cell来源、原投影key和编译参数域；`source_annotation_state_rules.py`展开写入。PublishAnnotation保留为描述符，已退出instruction union；无条件class字段只留metadata。原三入口不变，重生成/fresh读取新recipe；不重签旧版本。绑定编译上下文与完整状态/引用证明仍待完成。
星号/keyword的失败顺序参考固定版本[CPython codegen](https://github.com/python/cpython/blob/v3.14.7/Python/codegen.c)；本机stack guideline从header读入并固定SHA。

源码身份桥（按unit分片，保持输入模型和旧ID）：

```bash
python -B -m scar.cli source-anchors --model /path/to/model --out /path/to/materials --jobs 8
python -B -m scar.cli source-anchors --model /path/to/model --materials /path/to/materials --out /path/to/fresh-check --jobs 8
```

两入口均重验F2上游；身份生成本身只读原occurrence字段，不再解析或恢复AST。无旧SG的unit明确保留source-only处置。
`SourceAtomAnchorView.atom/occurrence/field`按原ID/字段查询；None只表示非旧Atom域构造，低层view不自授fresh源码证明。

## 已有建图入口（前端形式验收尚未完成）

```bash
python -B -m scar.cli static /path/to/program --out /path/to/model --phase bodies --jobs 4
python -B -m scar.cli static /path/to/program --out /path/to/model --expand --jobs 4
python -B -m scar.cli static /path/to/program --out /path/to/model --link-calls --max-call-bodies 80
```

`--phase sources/graph` 为材料目录/源码图，`--phase bodies` 继续构建规范主体；
`--expand` 增量补主体。显式预算仅限本次工作，不缩小完整性分母。
依赖材料可用 `--inventory-dependencies --dependency-root PATH` 定位，
再用 `--expand-dependencies` 送回同一前端；这些命令均不执行目标。

## 动态采集及离线连接

```bash
python -B -m scar.cli trace --calls-only \
  --capture-plan /path/to/plan.json --capture-plan-sha256 PLAN_SHA256 \
  --capture-transport snapshot --project-root /path/to/program-root \
  --out /path/to/fresh-trace -- python /path/to/program.py
python -B -m scar.cli observed-calls --model /path/to/model \
  --trace /path/to/fresh-trace --out /path/to/fresh-bindings --expand-missing
python -B -m scar.cli observed-graph --model /path/to/model --expand-missing \
  --trace /path/to/fresh-trace --out /path/to/fresh-observed-graph
```

采集计划由 `scar.trace.lean_capture.LeanCapturePlan` 对原源码/代码身份生成；具体接口以源码为准。
采集不额外执行用户 repr、descriptor 或 hook 来探测对象，不保存每次 Tensor 的完整数值。
优先复用已保存 trace；`observed-calls` 只离线连接，缺主体按完整代码身份请求原前端补建。
`--expand-missing` 先核完整Code/profile及已有plan文件指纹；无历史指纹时可补当前源码候选，
再按匹配Code作用域补body并fresh接线，不将父模块/环境认作历史事实；
不执行源码、不猜import名，旧分片保留但覆盖仍限旧basis。文件/字节预算用`--max-source-files/bytes`。
已有graph=None诊断按当前静态规则判是否可重试；成功补建保留旧收据，已有规范图不覆盖。
尚缺static adapter时明确报告形状/入口需求，不能把artifact文件当已建图。
采集仍含 frame profile hooks，不能宣称零干扰；性能测量与建图采集分开。
需要实际 callable 类型/owner/ABI 时加 `trace --native-callables`：仅在新 trace 内隔离编译小 C probe，
不安装环境依赖；当前限 CPython 3.14.7/GIL/Linux x86-64，不执行用户 getter 或读取 Tensor 数值。

## 共享图查询

```python
from scar.analysis.program_dependency_session import ProgramDependencySession

with ProgramDependencySession('/path/to/model') as session:
    ns, = session.select_bodies(file='program.py', entry='function_name', kind='FUNCTION')
    body = session.load(ns)                 # 原共享函数图及 index
    loops = session.loop_constructs(ns)     # 原成员 ID、嵌套、初始/回边端口
    if loops:
        operations = loops[0].expand(session.graph())
        boundary = session.loop_boundary(ns, loops[0])
```

不存在的 structured/主体信息保留准确缺口，不当成空子图。`ProgramDependencyBudget`
控制时间、输入、缓存和关系读取；边界查询完成仍须检查前沿和字段覆盖。
CLI 的 `static-query --program-graph` 使用原 typed ID，不按名称制造依赖。
动态接口用 `session.attach_observations(trace)` 接入，再由 `session.graph().observed_incoming/outgoing(port)`
查询；作用域与端口由返回的provider提供。原trace重验后才授边，DTO读回不是证明。
`graph.observed_layouts(scope)` 返回条件ABI布局；v2显式保存布局，v1读回为NOT_RECORDED而非空布局。
`graph.observed_native_callables(scope)` 查询附着原 CALL/Use 的实际类型、owner、self、flags 和地址事实；
未对应静态 CALL 的记录保留 frontier。导出为v3，v1/v2的这些字段读回为None=NOT_RECORDED。
类型名称只是描述标签，地址只适用该进程事件；它们不单独证明源码实现、kernel、copy 或效果。
有native采集时，`observed-graph` 自动生成共享协议分片并导出v4；`--native-protocols DIR` 重放已有分片。
API以 `provider.build_native_protocols(fresh_dir)` 生成、`attach_native_protocols(dir)` 核验接入；
`provider.native_protocols` 返回可展开的原canonical模板。协议输入/声明出口没有实际Invocation，witness仅为原CALL。
旧v1/v2/v3读回的协议字段为None；异常引用包未适配时仍保已知world，不把整个出口丢掉。

## 维护

当前任务及验收结果只更新 [STATUS](STATUS.md)，结构变化更新 [MODEL](MODEL.md) 或
[ARCHITECTURE](ARCHITECTURE.md)；不新增专题、版本或 gate 文档。
先定位缺失的识别事实、端口、连接或推理规则，再修改负责层；只运行相关检查。
生成图仅发布到 `artifacts/current/static/`，查询只引用原 ID/收据，不另建权威程序。
