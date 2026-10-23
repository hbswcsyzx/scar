# 原 source/body 分片接入参数、返回与环境路由

2026-10-23。状态：**Verified：原272038的实档接线与分表归档完成；完整模型仍OPEN。**
本项接回已有能力，不增加 detector/backend，不执行目标，不宣称第一阶段完整。

## 1. 补什么

现有 `link_call_operands` / `build_operand_routes` / `import_callable_environments`
已有原始 frame/operand/environment reader、精确 CALL window、入口 handshake、
formal/return/environment 端口及条件查询。旧入口要求整份 `ProgramInventory`，
`_link_call_model` 还用 `to_dict()` 检查版本并求 hash；`_Sources` eager 收集全部 body。
它们不能直接读取 840-body 分片 inventory。

已有 code/source witness 只保存 CapturedCode 与完整 pycode-v2 摘要，不持久保存
CodeType。摘要含 free/cell/position/exception 等结构的 hash，并不意味着这些字段
已经在原档中展开保存。稀疏 CALL window 的跳转/handler 排除不能由摘要或连续几条
动态观测恢复。本项因此按需求一次 compile，保留真实 CodeType 和既有 dis 消费者。

## 2. CodeWitnessStore

`scar.analysis.code_witness.CodeWitnessStore` 是编译证据存储，不是程序执行图。

```python
from scar.analysis.code_witness import CodeWitnessBudget, CodeWitnessStore

store = CodeWitnessStore(
    fresh_code_witness_directory,
    budget=CodeWitnessBudget(max_compile_keys=20),
    create=True,
    compile_missing=True,
    producer={"revision": recorded_revision, "modules": exact_module_receipts},
    progress=write_progress,
)
```

创建空 store 不读取目标源码、compile 或加载 CodeType。实际 `resolve` 才按需求工作：

1. 读取当前 source 文本，使用与 `tokenize.open` 相同的 encoding/newline 规则，
   精确核对原 SourceSnapshot fingerprint；归档 UTF-8 文本及原 raw SHA。
2. 用既有 `future_flags_for` / `compile_cache_key`，按原 optimize_levels 首选变体
   一次 compile。编译不执行 import、decorator、函数体或目标代码。
3. 遍历 nested code 一次，用完整 `describe_code(child) == encode(CapturedCode)`
   匹配，不按 qualname/行号挑对象。
4. 保存 owned、非 group/world writable 的 module marshal 分片；manifest 记录
   source snapshot、编译 filename/profile/flags/optimize、Python 完整 build、
   magic/cache tag/marshal version、producer、SHA/大小和完整 module descriptor。
5. 后续只 load：先核 owned 普通文件、独立预算和 SHA/大小，再 `marshal.load`，
   检查恰一个 CodeType、完整 module descriptor、选中子代码的完整 CapturedCode。
   不 exec、不 prepare、不重新 compile。

module 内代码索引按键只建立一次，保存真实 CodeType；不创建另一个字节码解释器。
精确匹配的 child constant path、descriptor、module artifact 进入最终 route 报告的
CodeWitness 引用。marshal 仅接受本工具 own producer 创建的私有归档，不接受任意
外来 marshal/pyc。新读入者必须与归档 Python build/magic 一致。

默认独立上限：20 compile keys、32 source files、16 MB 总 source、每 module
16 MB marshal、256 MB 总 archive、8 MB manifest、8,192 nested codes、128 depth。
编译预算耗尽是 `CODE_WITNESS_COMPILE_BUDGET` frontier，不触发无限重试。
`store.counts` 保留本次 compile/load/match/source-read 活动；`receipt()` 是稳定
归档身份，避免首次 compile 与只读 replay 的活动计数污染语义比较。

## 3. SourceBodyAccess

`scar.analysis.source_body_access.SourceBodyAccess` 是正规 storage accessor，
不是假装有 `.files` 的 ProgramInventory。输入必须显式提供原 CompositionIndex、
已发布 source-bindings schema2、共同 CaptureCoordinates 和 CodeWitnessStore。

- header/profile、signature 从原 component 取；不整图 `to_dict()`。
- compact composition header 建立 snapshot+definition+body namespace 索引，检查
  当前集合裸 DefinitionID 是否唯一；冲突显式列出并拒绝其 body，不覆盖 map。
- fresh operand reader 独立重扫原 frame；核 source report 的原 SHA/字节/路径/行数、
  metadata、captured descriptor、全部 code group/entry/exit 分母与当前 Run/process。
- 不重复消费巨大 `invocations.jsonl.gz`；报告明确
  `source_invocation_rows_consumed=false`。所有当前调用事实都来自本次独立 raw scan。
- 每个需要的 body 由 `InventoryPartitions.typed_body` 读取原 CP，保留原 graph、
  metadata、BodyEntryInterface、frame/structured overlay；核 namespace、root、
  canonical SHA、source snapshot/context，并沿用原 public validator。
- source AST 仅对已核同一文本 parse 一次；不重新 prepare 三图。当前目标是实际
  body-linked 的 74 body，其他 source/body/未知调用仍完整保留，不能补假 root。

CodeType 缺失不改变已有 VERIFIED source correspondence。callsite、return 和环境
记录分别保留 `CODE_WITNESS_UNAVAILABLE`。没有共同 process membership 的调用仍
保留原观察，但不产生当前 Run 的路由。retained ancestor 不升级为 direct caller。

当前版本消费已验收的原 source-bindings schema2；新 source attachment 的统一
SourceDefinitionReference 尚不在本次接入范围，不伪造外部 source 的 file_index。

## 4. 新入口与旧入口

旧入口/v1 replay 保持原调用方式和字段。新入口：

```python
from scar.analysis.call_operands import link_call_operands

report = link_call_operands(
    original_trace_directory,
    original_project_root,
    composition=original_composition_index,
    source_bindings=verified_source_binding_directory,
    coordinates=same_capture_coordinates,
    code_witnesses=store,
    frame_budget=independent_frame_budget,
    operand_budget=independent_operand_budget,
    route_budget=independent_route_budget,
    include_environments=True,
    progress=write_progress,
)
document = report.to_dict()  # scar.call-operand-links / schema2
```

inventory 与新输入互斥。reader/model/routes/environment 的原算法不重写：

- 固定位置 Name actual、exact function/layout、唯一真实 direct entry handshake；
- 原完整 LOAD window、jump/handler 排除、hook epoch/gap、原 code/site/offset；
- 原 FormalPort / ValueID / UseID / RegionID / EnvironmentInterface；
- 原 source normal-return/FRAME_EXIT 对应及 world port；
- defaults 保持未证实，环境身份不升级为内容/状态版本证明。

新 `entry_parameters` 是已有 `ReferenceOccurrence`，将实际 entry 捕获的参数按原
signature/formal port 关联。它不等于 caller actual 的来源路由。只有原严格规则
通过才产生 ArgumentRoute / CompletionRoute。report2 的 `source_body_access`
收据提供每个原 body 的 CP namespace 和 locator；不能将局部 ValueID 跨 body 合并。

v2 公共 replay 使用同样显式输入及 **只读** CodeWitnessStore：

```python
readonly_store = CodeWitnessStore(existing_code_witness_directory)
rebuilt = CallOperandReport.from_dict(
    document,
    composition=original_composition_index,
    source_bindings=verified_source_binding_directory,
    coordinates=same_capture_coordinates,
    code_witnesses=readonly_store,
    frame_ceiling=independent_frame_budget,
    operand_ceiling=independent_operand_budget,
    route_ceiling=independent_route_budget,
)
```

不消费 report 声称的 route 代替原档核验；重建结果须精确一致。重复 operation、
多轮 loop、不同 predecessor、挂起 frame 等原 occurrence/control 边界仍拒绝猜接。

## 5. 首次有界实档验收范围与实际结果

固定 272038，输入为已验收的 partitioned composition/source bindings；不混 369749。
只读已有产物的统计为：74 body-linked code groups 分布在 20 source files，首选
编译键恰 20；全部已录制 optimize 变体 53。首次只给 20 键，按需求编译；缺失变体
明确保留，不能声称全部 855 CodeID 都已获得 CodeType。

原 frame 分母 817 entered groups / 100,438 entry/exit；operand 312,812 events，
含 207,248 instructions、100,550 attempts、4,069 handshakes、945 gaps；environment
16,403 events，含 12,334 dispatches、4,069 entries。所有分母守恒，不预填 route 数。

已保存 revision/module SHA、脚本、progress/time/RSS并执行上述范围：首次完成20键
compile和74原CP读入后，在既有issue列表线性去重处耗764.42s仍未完成。root明确
中止自己的分析任务，shell exit130；SIGINT原栈位于该成员比较，原归档未删除。

修正只增加保序set成员索引，全部路由条件保持。独立attempt02只读复用20个源文本/
marshal模块，compile0/current-source-read0，完整descriptor匹配224次；74CP保持原
namespace。100,438调用、312,812operand与16,403env events全部守恒。

实际输出：13,872入口参数occurrences，27条argument与27条completion条件路由，
5,173 invocation return roots；3,347entries接10,087env ports。100,523 route issues
（96,481 handshake、3,294 source/core、748 dispatch）与6,694未定defaults保留。
这不证明完整的function environment、内容、状态、effects或world等价。

routes阶段2.04s，整体time5:26.17、peakRSS1,833,420KiB；序列化5.73s后按原表分块，
没有再保存一份99,289,131bytes完整report JSON。原文档canonical SHA为
`0197eff9d76e8673efd1ef639eab5d1b61e70fcb2aab4eae02d0d02fbaea3abd`。
这属于SCAR自身吞吐修正，不能报LeWM加速比。

记录在`first_stage_partitioned_operand_routes_20261023`（原中止及CodeWitness）和
`first_stage_partitioned_operand_routes_attempt02_20261023`。本次未新执行目标或测试
套件。`first_stage_complete` / `transformation_authorized` 仍为 false。
