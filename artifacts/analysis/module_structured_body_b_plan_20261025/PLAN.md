# B：module 根与 mapping namespace 策略（原设计历史及验收状态）

本文件下面保留原设计及边界；原文另存PLAN.original.md（SHA256 19f993994c9ad4bc0ac105f66b8bccd702248b11086fbd460643be9cea3220e9）。B现已获准实现并由Root实际验收；只代表前缀与reader资格，完整module/runtime仍OPEN。

A 已由隔离树 `548b112d70249d6b3711641396903a6b0da256d2` 交付；Root 报 main71621 旧SP7/6/5正常回读actual0。本计划只接 source producer 到 A 的真实根类型，不实现Try/传播traceback/C1 source producer，不改变现有function默认能力或旧SP1–7。

**入口及唯一权威。** `PreparedSource.lower_entry(selection, code_evidence=..., profile=新显式STRUCTURED_MAPPING_314_V1)`仍是入口（program_lowering.py:384–391）。selection必须原ModuleCatalog的ModuleUnitSource；原`module_unit`、`require_root_evidence`继续核MODULE initializer、准确snapshot/namespace与exec-mode whole-unit readonly CodeWitness，不能仅凭`<module>`名称。新builder不进`StructuredBuilder.run/build_function`，不调用`definition(ast.Module)`，不造RootSourceReference、FunctionObject/ENV/defaults/formals。

```
原ModuleUnitSource + whole-unit SourceCodeEvidence
  → ControlScope(FRAME, source=该unit, region=实际module frame Region)
  → FrameRoot(scope=上项ID, kind=MODULE, code=evidence.captured,
              entry=MappingFramePorts(L,G,savedB,原ordered cells,W))
  → 同Region的顺序stmt/loop CFG → 精确remaining slice计算接口
```

SP8 overlay只引用`root_scope`，不复制MappingFrameEntry。core29 named端口允许准确ValueID映射，source validator还必须核其entry角色、whole-root code及closure顺序；本profile沿原source-root证据仅支持empty closure，不能据此让core/CLASS继承该限制。不同L/G/savedB端口仍允许实际对象alias。FrameRoot不等于动态activation/import或已观测namespace绑定。

**builder精确接点。** `StructuredBuilder`的new_block/define_binding/read_local/store（109/152/239/304）及build_function（495）绑定fast-local/slot ABI；`record_loop:349`在names为空时已有合法空bindings，不必造module SG slot。保旧function adapter，把中性Region构造/statement循环与固定namespace策略分开：mapping策略的cursor.env始终不存Python名字，只携world及必要iterator/临时引用；`new_block(named=())`、jump/branch/merge、for迭代/stop分流、frame_exit_references及assemble_region可直接复用。原module的emit/link_value/use/protocol已支持ModuleUnitSource与原SourceReference（source_module_lowering.py:98–127），继续使用这些typed对应。

`environment_lowering.py:113–148`的expr/condition分发提成共享helper，由原function builder和module builder共同调用；Name/store由固定策略钩子处理，不复制该dispatcher、不继承其五项function ENV构造。函数free/local/global与captured-cell分类继续只走原adapter。module的普通Call/Attribute/List/BinOp等复用原StructuredBuilder与source_heap真实SG恢复；不得从namespace刚store过的SSA值替换下一次Name读。`() `须走原whole-root witness的准确LOAD_CONST/co_consts路径，复用source_slice_lowering的现有CodeConstantSource/READ_CODE_CONSTANT helper；module显式传入同root的typed SourceLanguageOptions（仅所需既有能力），不借它生成function ENV/language wrapper，也不扩大module profile的可支持族。此unit不涉及child-code常量。

**namespace合同。** 新SP8封闭enum `NamespacePolicy.MODULE_MAPPING_314_V1` 与独立`FrameBodyProtocolKind`，不扩旧ModuleProtocolKind或旧PythonProtocolKind以暗开SP6/7。

- LOAD_NAME协议输入(L,G,savedB,key,W)，NORMAL(ref,W')、RAISE(exceptionRef,W')；L未找到才G，再savedB，最后NameError，其他mapping异常立即传播。该协议把fallback规则明确写入类型profile与validator，custom mapping可调用Python/改world/raise；不把命名operation当effects完整。未展开mapping内部路径仍保相应协议扩展债务。
- STORE_NAME输入(L,key,value,W)，NORMAL(W')、RAISE(exceptionRef,W')；沿已固定opcode合同消费栈输入，StateAddress为ReferenceOwner+NamespaceKey的PARTIAL协议尝试。正常不授StoredValueWrite或内容已存。DELETE_NAME语义同样是mapping尝试，但本首段不出现，producer明确暂不支持；C处理except-as隐式清理时再接，不能默认成功。
- IMPORT_NAME继续从savedB解析可能自定义`__import__`，携G/L/level/fromlist原端口；不固定callee、effects或ModuleObject。IMPORT_FROM增加独立明确协议：真实模块返回对象/符号→结果/raise，attribute及circular-import fallback行为留协议合同与内部扩展债务；再准确STORE_NAME别名。任何一个失败都携本次post-world，不能跳到后续stmt。
- source库/内建名字无特殊分支；range、torch等全部是原源码literal key。for目标经STORE_NAME，循环体重新LOAD_NAME；不unroll256，不假定range/type/builtin身份。module显式global按真实compiler分类接G，unsupported分类保frontier。未来FunctionDef捕获G及函数创建时保存的builtins，不捕获L；本profile不生成def/class/非空closure。

**一次SP8，不逐句升版本。** 新`StructuredFrameBodyOverlay(root_scope, namespace_policy, completion_profile, stmt_expansions, correspondence, protocols, loops, constants, required_expansions)`仅索引core实体与原source事实。typed slice包括unit/context、准确lexical owner、AST序列字段及有序SourceReferences；有原suite/BEFORE/CFG anchor则核回，原Try source CFG gap不伪造ID或改PASS。各子slice有序、不重叠、覆盖准确父成员。计算子Region不是新Python frame；只实际frame Region声明FrameRoot。旧SP6/7 class/wire/reader原样封闭，SP8必须有自己的明确分支，排在A的历史writer guard之前。

B的completion_profile明确为RAW_EXCEPTION_REF_314_V1，复用原(ref,W)失败路径。根先严格分区CFG/LOOP，**不伪造需要ExceptionPacket的C0 RAISE control port或pending**。原for的StopIteration分流与未命中ref转出仍保原层资格；只有C的显式PROPAGATION_PACKET profile才能加入(exception,本次traceback,W)、C0语言ports/pending和C1 caught-context/cleanup，不发SP9，也不拿coarse world替代这些将来要建的关系。

**真实首段及边界。** 对原586B AST，递归按已声明producer/原SG/readonly compiler能力机械选择最大连续prefix（不是手写本unit名单）：0 Import；1 Import；2 ImportFrom；3 Import；4 Assign(call含empty-tuple constant/keyword)；5 For(内含Assign/BinOp)；6 Expr(call/list/attribute)；7 Assign(None)。第8 Try首遇当前未支持族，剩余`module.body[8:]`为Try/Assert/Expr共3条，保准确subject/context/源码范围与全world normal/raise接口，不删Try/展开其else冒充完成。若某前序表达式无法准确核回，就在其完整原stmt边界停，保更长真实suffix，不能填8条成功。原11顶层/嵌套source成员及95/92/45/56分母全部保留；8条prefix也不代表primitive内部effects/namespace内容已证。

**B实际6源（Root随后批准实施并已验收，原设计范围如下）。**

| 文件 | 改口 |
|---|---|
| ir/program/module_entries.py | 一次SP8通用overlay/slice/namespace及completion profile；旧6/7记录不变 |
| analysis/program_lowering.py | 明确SP8 writer/reader与新profile入口；历史1–7守卫保持，正文producer不混函数replay |
| analysis/structured_lowering.py | 中性root/namespace接点，复用CFG/loop/frame与现raw completion，保function adapter |
| analysis/environment_lowering.py | 提出并复用现expr/condition dispatcher，原function ENV和分类不变 |
| analysis/source_module_lowering.py | typed真实FRAME/FrameRoot、mapping策略、import族、机械prefix和精确slice producer |
| analysis/source_module_validation.py | 独立原AST/SG/CFG/witness对账、端口角色/profile/覆盖与正常core29 reader连接 |

不改A其余core5源、原planner/default3–4、native/backend/binder，也不现在改source_statement_lowering。若现有constant helper实际要求改其原文件，先报具体API关系，不复制一套常量解释器。

原设计的同586B source-only窗口已由Root持有并完成（session63369 actual0）；原预算为：沿32MB实际stored+decoded（含重复）、record4MB、output16MB、4000ops、worker180s/outer240s；机械prefix、SP8普通完整读回及原SP6/7兼容消费，module lower仅该unit一次并实计，target executable compile/exec/fresh prepare均guard为0，AST分析另计，不重lower旧图。实际118ops/2Regions、8顶层接口/9stmt records、remaining3；新SP8与旧SP6/7正常回读通过。报告见 ../../experiments/module_structured_prefix_g1_20261025/REPORT.md。C仍需另行审传播payload/Try/except-as清理接点；B未填packet/traceback，不称完整module或runtime成功。
