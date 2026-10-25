# G1 exec 根代码的 mapping-frame 入口（仅设计）

状态：`DESIGN_ONLY`。不改生产、schema 或验收合同；不运行 lower/compile/target/raw。实际输入与 SHA 见 [SOURCE_RECEIPTS.json](SOURCE_RECEIPTS.json)。先前三图成本方案已独立归档并 push `72f2a580e185ec597fe38350a3f3337f6e71d166`，本设计不授权该 ADD。

1. **真实断口与复用。** G1 的 586B 源码已有 `MODULE` initializer `opdef:init:2d91d50cf13f1e1f61014373`、95 atoms、92 semantic operations、45 CFG nodes/56 edges；function/class definitions 和 canonical bodies 均为 0。原 CodeWitness 的 `mode=exec`、root constant path `[]` 与完整 CapturedCode 已核回，但 `CodeSourceLink.definition/source=None`，故不能进入要求非空 definition/source 的函数 worklist。复用原 initializer、SG/CFG、core28 的 Region/Block/Use/world、completion、FrameRules；不另造 module 定义或 producer/use/state 图。依据：`frontend_v2.py:320–338`、`program_inventory.py:470,643,679`、`call_edges.py:300–309`、`source_frontend_worklist.py:195–223`。

2. **最小类型/API 草图（拟议，当前不存在）。** `ModuleUnitSource` 只引用准确 snapshot、namespace root 和已有 initializer，解决 AST.Module 没有原 SourceAtom、不能伪造 SourceReference 的问题。自动 selector 从原 `module_roots` 与准确 exec/root CodeWitness 生成 `ModuleRootSelection`；不能只凭 `co_name='<module>'`。

```python
ModuleUnitSource(snapshot: SourceSnapshot, namespace_root: str,
                 initializer: OperationDefinitionID)
MappingFrameEntry(unit: ModuleUnitSource, region: RegionID,
                  locals_namespace: ValueID, globals_namespace: ValueID,
                  builtins_namespace: ValueID, closure_cells: tuple[ValueID, ...],
                  world: ValueID)
# 拟议调用；selection/evidence 由正常原档 reader 构造，非 caller trusted token：
prepared.lower_entry(selection, code_evidence=readonly_root_evidence, max_operations=...)
```

这些引用是 entry BlockArguments；不同 ValueID 不证明 Python 对象不 alias。只有进入协议的实际证据才可把 locals/globals 接成同一值；G1 尚无该证据。builtins 是实际 frame 输入，不能一律重读 globals['__builtins__']。本例 co_freevars/co_cellvars 均空；非空 closure 必须按真实 co_freevars 顺序传 cell 引用，未接能力明确拒绝，不能提前读内容。FunctionEntry 仍保原参数和 function-object/globals/builtins/defaults/kwdefaults ABI；ClassEntry 的 prepared namespace/metaclass/decorators/__classcell__ 是另一个协议，不在本轮。依据：`functions.py:18,80`、`environments.py:26,101`。

3. **namespace 与外层协议分离。** 本例真实 compiler 使用 LOAD_NAME/STORE_NAME/DELETE_NAME：locals→globals→builtins 查找和 mapping 写/删均可调用 Python、raise、改 world，不能套 fast-local 纯绑定；只有真实 LOAD_GLOBAL/STORE_GLOBAL 才复用已有 global 协议。新 module 协议 overlay 可索引原 core operations/ordered Uses，state 地址复用 `ReferenceOwner + NamespaceKey`，该地址注解不证明 effects_complete。IMPORT_NAME/FROM 保守接口连接 world/normal/raise，导入内部仍欠展开；不把 OPAQUE 算完成。VERIFIED exec 根不证明它经 import 执行，也不证明 ModuleObject/sys.modules 成员：同 code 可经 exec/FunctionType 进入。import、__main__、exec 的进入/返回及 sys.modules 插入/失败移除须由各自协议和 provider 另证；不把原 `$module_namespace` 输出当作已证的借入 namespace。依据：`structured.py:19,64`、`state_addresses.py:79,117,234`。

4. **completion、cleanup、activation。** G1 根正常路径实际为 `LOAD_CONST None; RETURN_VALUE`，entry 返回 None 引用与 post-world，不返回 module 对象；异常返回 exception 与其 post-world。异常不会自动回滚 namespace。原 exception table 有 4 entries，except-as 的 error 有正常/异常两条隐式 clear/delete；custom mapping 的 cleanup 仍 may_raise/替换 pending。复用既有异常 packet/handled-context/cleanup/Frame retention，不将当前未接的 Try/import 内部当已证。函数专用 AnnAssign 规则也不能搬给 module（`source_statement_lowering.py:99–106`）。CodeID 是静态 code，动态 activation 必须另外用 Run/process/原 enter anchor 区分；本例 1 次 module activation 的 namespace/进入模式未观测，不能因 code 匹配声称已绑定。

5. **必要版本与最小改口。** SourceProgram5 不能准确表达：reader 只解函数 BodyEntryInterface/STRUCTURED_ENV，EnvironmentInterface 强制五项函数前缀，StructuredBodyModel.source 又强制 SourceReference。建议 SourceProgram6 显式 entry-kind/interface 与 source-origin union；v1–5 原路径逐字段不变，旧 reader 明确 unsupported；core28 无需变化。首个 source-only 接线预计六文件：新增 `ir/program/module_entries.py`（类型与严格 overlay decode）、`analysis/source_module_lowering.py`（正常 root-witness/自动 selection/namespace 协议）、`analysis/source_module_validation.py`；改 `program_lowering.py`（v6 codec/entry dispatch）、`structured_lowering.py`（抽出入口无关 emit/loop helpers，函数 guards 保留）、`source_frontend_worklist.py`（独立 module-unit 候选，不伪 DefinitionInventory）。这是实现提案，须 Root 再授权。entry profile 即显式 v6 能力，旧 library3/main4 默认不增长。现 inventory8 无 MODULE DefinitionKind 且 definition.source 必填，不能塞假 function；先返回独立 typed module-entry catalog，保原 function/class 分母，再由后续显式 inventory/catalog 版本纳入。CP2 admission 固定 SourceProgram5，未来发布需明确新版本/reader capability，本轮不绕过。依据：`program_lowering.py:164,182,265`、`inventory.py:13,91,164`、`structured.py:141`、`inventory_partitions.py:375–385`。

6. **唯一真实 source-only 验收入口。** Root 授权后，新单次 runner 机械选 G1 `module_roots[0]`；输入为收据内 586B archived UTF8、1455B readonly marshal/准确 manifest、现存单文件 source-layer archive（840089B decoded）与小 inventory/composition metadata，不开 raw/77MB roots，不 compile/exec，不改源、不剥掉 import/try。首先检查完整 source fingerprint、exec compile key/root code descriptor、原 namespace/initializer 归属和 namespace/world ports，再做普通 SourceProgram6/core28 roundtrip与独立原 AST/CodeWitness 校验。原 0 function/class、1 module root、9 code groups/271 calls 的独立分母全部保留；module 的 1 次调用仅保留原 activation anchor，不声称已建立缺失 runtime namespace 连接。若全体 statements 不能返回完整 graph，保存准确 partial/frontier，保留 MODULE_INITIALIZER_BODY_NOT_RECOVERED 及相应 required-expansion debt；入口可表达不等于整个 body/程序完成。G1 现有 81 semantic/2 control gaps 与外部源、frozen/native/运行效果欠账须逐项保留；不通过重复造图或逐 primitive 生命周期证明来拖延入口，也不把未展开接口提升为完成。本次设计实际新建图 0、lower/compile/target/raw 0；源码读取保守上界 968485B，小 metadata 上界 1600000B。
