# 原图组合与递归查询

日期：2026-10-23。状态：已实现组合适配器；**第一阶段仍为 OPEN**。

### 分片输入与schema2

`compose-program --inventory`也接受已发布的partitioned inventory `manifest.json`。
旧monolithic输入仍生成原schema1；分片输入生成schema2，并使用原`CompositionIndex`
正规类型读取。规范图仍在原source archives和body检查点中，不重新prepare源码、
不拼装巨型inventory JSON。

新索引的body header locator指向source shard `#/file/bodies/j`；graph、metadata
及gap分别指向原CP `#/graph`、`#/metadata`、`#/metadata/gaps/n`。每条locator携带
原artifact URI、physical/decoded SHA和size；canonical namespace另含精确ProgramGraph
表示版本、原body身份和`#/graph`。不伪造旧`#/files/i/bodies/j`指针；新格式该legacy
pointer字段为null。source定义通过snapshot(path/fingerprint)+原DefinitionID限定，
裸local ID不充当全局身份。ElementReference仍由绑定的composition、file及body限定。

`CompositionIndex`新增`inventory_file_count`、`inventory_file(i)`、`inventory_body(i,j)`、
`inventory_component(name)`及对应`*_locator`访问器。分片body按需加载，最多保留有限
source/body缓存。源三图每file沿用原公共reader验证，canonical graph每body沿用原codec；
归档成功、代码来源匹配及图结构有效都不等于actual/formal、state或resource已闭合。

## 1. 本次补什么

已有 Source SemanticGraph、SourceSemanticsGraph、SourceControlFlowGraph 与部分
canonical ProgramGraph body 不能继续分别查看。`program_composition` 将它们按原
来源和 typed ID 连接为一个可查询的组合索引；不重新保存三张图，不复制 value
producer、state version、Use 或 successor，也不制造一个有正常返回的空 root。

这仍不是完整 `ProgramSnapshot`。跨函数实际参数/形式参数、返回值、环境和状态
尚未闭合时，索引必须留下 frontier。源调用的候选目标可以展开到目标的原 body，
但这条连接保持 CONDITIONAL；它不证明实际 dispatch 或数据等价。

## 2. 原身份与组合投影

| 查询部分 | 保留的原身份和事实 |
| --- | --- |
| module、function、class 与其它操作 | SemanticGraph 的 `OperationDefinitionID`、`parent_id` |
| branch、loop 与受控构造 | 原 `ControlRegionID`、owner、parent 和 operation.control_region |
| source 构造 | 原 `SourceAtomID`、完整 SourceReference、coverage owner 与 execution phase |
| source 控制 | 原 `ControlFlowSuiteID`、`ControlFlowNodeID`、原 edge，不自行补 fallthrough |
| 已恢复 body | inventory JSON pointer、原 canonical graph SHA、原 `RegionID`/`OperationID` |
| 候选调用边界 | 原 `CallInventory`、candidate witness/condition、目标 definition 与可用 body 引用 |
| 未恢复部分 | 原 body status/reason、source/control gap、缺失 module/class body 和其它 frontier |

`ElementReference(file_index, existing_typed_id, body_index=None)` 只限定原记录的位置。
canonical Region/Operation 必须带 body_index，避免不同原 body 文档的 ID 被意外
合并。它不是新的操作、值或资源身份。

包含、来源对应、控制归属、条件 dispatch、数据依赖各自查询：

```text
module initializer / function definition
  ├─ children：原 SG lexical operation children
  ├─ control_regions：原 branch/loop 区域
  ├─ control_suites：原 CFG suites → 原 nodes / edges
  ├─ source_atoms：coverage 所给的 source 构造及执行 phase
  └─ typed_regions：原 canonical body region
        └─ blocks → 原 operations
              ├─ 原 ordered Uses → 原 Values / producer
              ├─ 原 StateAccess / effects_complete
              ├─ 原 terminator / completions
              └─ 原 conditional CallTarget
```

SourceAtom/CFG node 的 `corresponding_operations` 表示来源对应，不混称 lexical
包含或执行因果。定义时的 decorator/default/annotation 与 body 的调用时执行
仍保留原 inventory phase，不因为层级相邻而当成同一次 activation。

## 3. 机械输入与运行

输入仅为已经自动生成的 inventory 和 source-layer archive，不提供业务函数名单，
不运行目标，不重跑 forward，不根据 LeWM 名称分类。

```bash
python -m scar.analysis.program_composition \
  --inventory <inventory.json.gz> \
  --source-layers <source-layers-directory> \
  --out <new-output-directory>
```

输出只有组合索引 `index.json.gz` 与 `summary.json`。索引绑定 inventory 的原始
字节 SHA 和 archive manifest 的原始字节 SHA。逐文件使用已有 source-layer reader
核验三图、snapshot/context 和 archive；逐 body 使用已有 canonical graph codec
与 validator。metadata 的原 operation/value/use 链接必须能在相应图中找到。
归档来自另一版 inventory 时，只允许逐文件 snapshot/context 完全匹配，不凭文件名
或行号匹配。缺失 archive 留在文件分母；相互矛盾的 graph/link 会报错。

查询示例：

```python
from scar.analysis.program_composition import CompositionIndex, ElementReference
from scar.ir.v2.ids import OperationDefinitionID

model = CompositionIndex("<output>/index.json.gz")
ref = ElementReference(file_index, OperationDefinitionID(original_id_value))
region = model.expand(ref)
dependencies = model.dependencies(ref)
for body_ref in region["typed_regions"]:
    body = model.expand(body_ref)
    for operation_ref in body["children"]:
        operation = model.dependencies(operation_ref)
        # Uses、Value、StateAccess、Terminator 为原 canonical records。
```

`source(file_index)` 返回原 SourceLayerView；`typed_body(file_index, body_index)`
返回原 ProgramGraph 和 LoweringMetadata。只做有限 LRU 缓存。调用方可以继续使用
原 graph validator、def-use 查询和状态分析，不维护第二套连接事实。

## 4. 哪些缺口必须继续补

组合索引的结构可展开不等于依赖完整。至少仍分别报告：

1. `BODY_UNSUPPORTED`、`BODY_NOT_ATTEMPTED` 与 body 内原始 gap；
2. 没有 canonical body 的模块初始化和 class/comprehension 等 definition；
3. 原 SourceSemantics/CFG gap，以及既无 coverage owner 又无 operation 来源对应的 atom；
4. 每个调用的条件目标与 `actual_formal_return_connected=False`；
5. canonical operation 原 `effects_complete=False`，不把未知当作无副作用；
6. 本模块尚未连接动态 activation、Tensor provenance、native work 和 OS/CUDA resource。

这里不将 coverage status 重新改成 CONNECTED，不将候选 CallTarget 改写成 CALL，
不把 `LOWERED_WITH_GAPS` 当作纯函数，不把 source CFG 当作实际运行轨迹。

## 5. 下一条实质连接

用 source/call recorder 的实际 callable、entry handshake、参数与返回证据，连接
这里给出的原 definition/body 边界；使用公共 Run/Process/Thread 坐标。证据不足的
端口留为具体 frontier，并直接统计原必需分母。之后接 Torch/native/OS 数据与资源
关系。只有依赖、状态、完成和资源接口均闭合后，才可能组合成完整 ProgramSnapshot
及其 ExecutionModel；本索引不代替这项工作。

## 6. 首次真实自动组装（历史 54-body 输入）

使用未修改 LeWM 的既有 environment inventory 和 source-context 三图归档，
自动组装 151/151 个文件：122,323 个 source atoms、114,560 个原 semantic
operations、6,916 个 CFG suites、65,880 个 CFG nodes 和 78,691 条 CFG edges。
2,217 个 body 中，54 个引用已恢复的原 canonical body；201 个源调用候选目标
保持条件连接。产物位于 `artifacts/experiments/first_stage_program_composition_20261023/result`。

未恢复项仍有 1,961 个 NOT_ATTEMPTED、202 个 UNSUPPORTED、151 个 module
initializer canonical body 缺口，以及原语义/控制/效果与跨函数绑定缺口。
这里的全文件结构索引不代表完整数据、状态或资源依赖，第一阶段仍未通过。

一次当前查询入口的真实查询已从自动选中的 `run_inference.py` definition 展开到
原 typed region 和 23 个 operation，再取回原 operation 的 9 个有序 Uses 与
1 个 StateAccess；`effects_complete=False` 被保留。查询脚本按数据自动选取
示例，不是产品对 LeWM 的特殊规则。组装进程启动后完善的查询投影和 coverage
frontier 只在当前查询中使用；当前模块的更严格 metadata 检查不冒充已重跑全部
151 份旧图。后续全量重建应使用当前模块与最新 inventory。

## 7. 分片 full inventory 的实际组合与调用连接

`artifacts/experiments/first_stage_partitioned_composition_bindings_20261023`
已完成一次新的 151-file compose 与同 capture 绑定，exit 0。输入为
`first_stage_full_inventory_restored_20261023/result/manifest.json`，不使用上节
54-body inventory，不构造巨型 JSON，也未重新 prepare/lower 原源码。

151 个原 source archive 均逐份核对 snapshot/context，840 个 canonical body 沿用
原 public codec 校验；组合保存 2,217 个 definition/body header、122,323 个 source
atoms、114,560 个 semantic operations 和 263 个条件调用目标。source CFG 的
6,916 suites、65,880 nodes、78,691 edges 均引用原图。787 个 UNSUPPORTED、
590 个 NOT_ATTEMPTED 和 151 个未恢复 module initializer body 明确保留。

compose 阶段 wall 662.44 秒；连同独立坐标核对及 100,438 次实际调用绑定，全过程
wall 14:26.32、peak RSS 814,720 KiB。5,624 次 invocation 关联原 body，3,162 次
仅关联 source，91,652 次未解析。具体原档 SHA、schema2 locator、producer 与计数见
实验 README、`summary.json` 和 `bindings/report.json`。这验证分片来源与实际 entry
的正规接入，不证明 actual/formal、状态、effects、资源或完整执行模型已闭合。
