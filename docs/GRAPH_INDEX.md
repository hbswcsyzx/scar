# 原规范图的 SQLite 查询索引 v1

2026-10-23。**Verified**：已通过一次真实完整 inventory 索引构建和必要局部查询验收，
没有修复后重跑。151 source、2217 body、840 个原图经过公共 reader/codec；437,228
实体、1,172,205 关系。建库 418.65s，含验收 426.82s，主库 481,460,224 bytes，
peak RSS 192,992 KiB。SQLite integrity/FK、原分母和三类准确原 locator 查询均 PASS。
没有执行 LeWM/forward、fresh lowering、优化或测试套件；完整程序建模仍 OPEN。

设计依据：[GRAPH_STORAGE.md](GRAPH_STORAGE.md)。SQLite 是原图的可重建索引；规范
记录仍由已固定 receipt 的原始 checkpoint/分片负责。没有迁移 IR 权威。

## 1. PUBLISHED 的严格含义

```text
原 partitioned inventory / original construction checkpoints
  → hash/size/representation 校验
  → InventoryPartitions.typed_body → 公共 ProgramGraph codec 校验
  → 小批事务构建 SQLite（BUILDING）
  → 原 manifest 分母 + 外键 + 预算检查
  → 单次根事务发布（PUBLISHED）
  → GraphIndex 只读局部查询
```

**PUBLISHED 仅表示这个索引构建完毕。** 原模型的构建失败、NOT_ATTEMPTED、未索引
关系、缺失动态对应等仍然存在。返回报告及库内 metadata 始终保留：

```text
whole_program_graph_established=False
all_relationships_indexed=False
source_replay_performed=False
target_executed=False
transformation_authorized=False
```

不存在“数据库已发布，所以第一阶段完整程序建模已经完成”的推论。

## 2. 身份与精确原档位置

每个查询 key 与 `InventoryPartitions.qualified_reference()` 形状一致：

```python
{
    "namespace": {
        "artifact": {"uri": original_logical_uri, "decoded_sha256": original_sha},
        "representation": original_representation,
        "body": original_body_identity,
    },
    "kind": "Operation",  # 必须显式区分 Region/Block/Value/Use/...
    "local_id": original_typed_id_wire_record,
}
```

不能仅凭 local ID、源码路径、函数名称或文件序号查询/合并实体。同名 body 或不同
checkpoint 中相同的 local ID 是不同命名空间。namespace 原样取自公共分片 reader；
保存时不以当前物理文件路径替换 logical URI。之后移动原档不会改变库中图身份，
但恢复原记录需要独立、准确的 retention 映射；索引不会猜新位置。

每个实体和关系都带原 checkpoint receipt 和 `#/graph/...` JSON pointer。header/
body status 取 **source shard receipt + `#/file/bodies/j`**。原 checkpoint 的 graph、
metadata、overlay 分别位于 `#/graph`、`#/metadata`、`#/structured` 等。

`partitions.body_record(i,j)` 是 reader 的内存投影，磁盘不存在巨大的
`#/files/i/bodies/j/graph` 文档。本索引没有制造这种 pointer。

索引内部整数主键/游标只用于数据库定位，不是新的 canonical ID。

## 3. 核心 schema

| 表 | 责任 |
|---|---|
| `snapshot` | schema/version、BUILDING/PUBLISHED、原 manifest URI/physical+decoded SHA/bytes、预算与范围报告 |
| `artifacts` | 原 artifact 的完整 receipt；节点不重复塞完整来源记录 |
| `namespaces` | 原 artifact/representation/body 身份、graph pointer、原 graph schema version |
| `bodies` | source shard 原位置、原 BodyStatus、是否有图及是否公共校验；图为空也计入分母 |
| `entities` | 原 typed local ID、统一 kind、实际 record type、原 pointer、声明 wire 顺序 |
| `relations` | 明确 typed relation、两端已有实体、完整 ordinal path、原字段 pointer、有限语义限定 |
| `facts` | 无独立 canonical ID 的 StateAccess、selector、exit 等原嵌套记录 locator/有限标量描述 |
| `coverage` | 每个 ProgramGraph 顶层字段的真实记录分母、非空 body 数、显式保留 reference endpoint 数及覆盖状态 |

没有把整个 ProgramGraph 或任意大记录 JSON 塞入单元格。事实表只存有限类型、
索引/模式/路径等查询描述，不存 Tensor 数值、源码全文或 literal payload。需要
原完整记录时按 receipt/pointer 回取；本模块不会循任意查询 URI 打开文件。

## 4. 明确支持的关系

| 原规范字段 | 索引投影与语义 |
|---|---|
| `Region.parent/blocks/entry` | `REGION_CHILD/BLOCK/ENTRY`，保有序 containment |
| `Block.arguments/operations` | `BLOCK_ARGUMENT/OPERATION`，保原 ordinal |
| `Value.region` | `REGION_VALUE` |
| `Operation.uses[j]` | `OPERATION_USE`，Use 是实际独立节点，保原 role 与 j |
| `Use.value` | `VALUE_USE`，同 Value 出现多槽仍逐项保留 |
| `Operation.results` | `OPERATION_RESULT`，不改 Value 的 canonical origin |
| `Value.origin` | `VALUE_OPERATION_ORIGIN` / `VALUE_BLOCK_ORIGIN`，或 literal-origin locator |
| `StateVersionValue.location` | `STATE_VERSION_LOCATION`，不等于内容 hash/version |
| `ReferenceValue.targets` | `DECLARED_POSSIBLE_LOCATION`，仅 possible target，绝不当 actual alias |
| `Operation.accesses` | 原 location/before Use/after Value/reference Use，mode、full_overwrite、footprint 同 access index 关联 |
| `Operation.callee` | `DECLARED_CALLEE`，仅原静态声明，绝不变成 observed call |
| `call_arguments/invoke_arguments` | 原 Use 的有序引用 |
| `ordering` | `EXPLICIT_ORDER`，只有原声明，不推断其他同步 |
| `resources` | 明确 ResourceDefinition 与 ResourceRequirement；原创建/外部来源、owner、约束、use、handle、resource-location |
| `state_address_refinements` | ExistingAccess/InvokeStateOperand，Reference/Resource/Unknown owner，各 typed selector 的真实 Use 字段及 ordinal path |

`ObjectField.name` 可作为小型路径描述保留；NamespaceKey/DynamicField/Element/Slice/
StorageRange 等动态部分只引用原 Use。UnknownOwner/UnknownSelection 的 operands
保留“未理解”的角色，不改写成已知地址。完整路径与 provider 资格仍取原记录。

### Control/completion 必须保持类型

只读取实际 `terminator.successors` 数组，构建 canonical static successor 关系。
这表示原图真实存在的静态边，**不是动态上该分支已发生**。

- BRANCH：ordinal 0/1 保 true/false。
- INVOKE：保原 NORMAL/RAISE completion kind、successor index、CompletionResult slot。
- Pending/Cleanup：保原 control port；pending payload projection 与普通 Use 传参分开。
- SUSPEND：later resumption ingress，不冒充同一 activation 的立即跳转；saved Use 与
  external resume input 分开。
- BODY_DRIVE：保原 outcome source operation；BodyDriveResult 指向原 outcome 来源，
  不把 drive 或 landing position 发明成普通 Value 的 producer。

`producer(Value)` 始终返回原 origin。落地 BlockArgument 的 producer 仍是原 block
argument；completion/saved/pending/resume 的条件投影只能通过独立关系查询。不会
沿投影静默覆盖 canonical producer，不按位置相同推断 alias。

## 5. 未支持关系也保留真实分母

每个 body 的所有 ProgramGraph 顶层字段都参与 coverage 计数；不是只数已支持类型。
未支持的 extension record 保存 `NOT_INDEXED_RECORD`：原 pointer、record type、字段
及明确 reference-field 白名单。

对于已阅读类型定义的显式字段路径，额外保存 `NOT_INDEXED_REFERENCE`，包括实际
typed local ID、精确字段 pointer、是否能定位已有 canonical endpoint。这里使用
固定字段路径，如 `binding_reads.operation` 或 `cleanup_resumes.continuation.operation`，
**不通用扫描 dataclass 的所有 ID**。这些只是“原记录引用了这个 ID”，不授予协议
关系、实际调用、结果、alias、lifecycle 或效果含义。

白名单是部分覆盖；尚未映射的复杂 contract/port 的 endpoint 仍按原 record locator
回取。`coverage.declared_reference_endpoints` 给已实际投影的数目，不把它当全部
endpoint 分母，也不把 NOT_INDEXED 行当“没有关系”。

当前不索引 inventory 全局 components、source-call candidates、跨 body composition、
动态实际调用、provider/canonical 对应、alias/物化/完整生命周期与 ready 推断。
相同 local ID 不会因此自动跨片连接。后续必须从原有准确 qualified correspondence
补桥，不能从名称或邻近关系猜测。

## 6. API

```python
from scar.store import GraphIndex, IndexBudgets, index_inventory

report = index_inventory(
    "/absolute/archive/manifest.json",
    "/absolute/fresh/graph.sqlite",
    IndexBudgets(max_database_bytes=4_000_000_000),
    progress=write_progress_record,  # 可选：FILE_BEGIN/BODY_COMPLETE 标量进度
)

with GraphIndex("/absolute/fresh/graph.sqlite") as graph:
    node = graph.entity(qualified_reference)
    children = graph.region_children(region_reference)  # 默认 REGION_BLOCK
    nested = graph.region_children(region_reference, relation="REGION_CHILD")
    incoming = graph.incoming(qualified_reference)
    outgoing = graph.outgoing(qualified_reference, relation="STATE_ACCESS")
    origin = graph.producer(value_reference)
    uses = graph.ordered_uses(operation_or_value_reference)
    paths = graph.facts(operation_reference, kind="ADDRESS_SELECTOR")
    coverage = graph.coverage()
    omitted = graph.unindexed_records(namespace)
    endpoints = graph.unindexed_records(namespace, references=True)
```

`ordered_uses` 返回原 Use、其原 Value、拥有它的 operation；重复 Value 保持多个 Use。
顺序是原 graph/operation/use wire order，不是 runtime execution order。

列表查询默认最多 1000 项，返回 `next_cursor`。下一页把它传入 `after`；不依赖大
OFFSET，也不把整图加载到查询进程。每个结果保 qualified identity、receipt/pointer。
`entity` 不存在返回 None；BUILDING、错误 schema/version 的库在打开时直接拒绝。

数据库 `mode=ro` + `PRAGMA query_only=ON` + 一个读取事务；API 没有图写入入口。
本机 readonly index 本身不是抵抗外部恶意篡改的签名服务，保管方仍需保存返回的
数据库 SHA/bytes receipt。数据库索引改变不修改其原图证据。

## 7. 构建边界、预算与失败

- 自动遍历 manifest 的全部 source/body，不需要业务名称或人工标注。
- `InventoryPartitions` 保留两个有限 LRU shard，逐 body 使用公共 codec；不会构造
  单一巨型 ProgramInventory。没有 source replay、fresh lowering 或目标执行。
- 一个 writer，小批事务（默认 2000 行）。显式 IDs 保原顺序，可以按表批量写入。
- 可选 progress 回调按 file/body 返回累计计数，真实构建脚本可写阶段日志；不把整个
  graph 或 Tensor 数据传给回调。回调失败会中止构建并保留 BUILDING。
- 使用 DELETE journal，不因并发需求在未知文件系统上直接启用 WAL。构建期间
  GraphIndex 拒绝 BUILDING；发布后允许多个独立只读进程查询。
- 有 max_bodies/entities/relations/facts/shard_bytes/record_bytes/database_bytes 等
  预算。SQLite max_page_count 限制主库大小；临时 rollback journal/已解码原 shard
  与公共 codec 的运行内存另有成本，不能冒称整机硬资源预算。
- 原 source_files/checkpoint_returns/graph_bodies/not_attempted_bodies 分母需与 manifest
  完全一致，所有已索引关系/owner 外键实际核验通过，才发布。
- 预算或构建失败抛 `IndexBuildError`，携带 report；保留 BUILDING 检查点。旧产物不
  覆盖，原 graph/manifest 不修改。初始无效输入/无法新建文件可在建库前直接拒绝。

## 8. 真实验收：一次构建，全部必要检查 PASS

原分片 manifest 发布后，已完成一次真实运行（2026-10-23），详情见
[实验 README](../artifacts/experiments/first_stage_graph_index_20261023/README.md) 与其中
固定 receipt、summary、coverage、query-proofs、time/progress。Python PID 382595，
退出码 0；未修改模块、未触发失败重跑。

| 项目 | 实测结果 |
|---|---|
| 已发布原 manifest | `first_stage_full_inventory_restored_20261023/result/manifest.json` |
| 原 manifest SHA256 | `1443fedcbd8882e86dee392339a5ea51fd29ea102068a65d9e51e06b347de09e` |
| source/body/checkpoint/graph | 151 / 2217 / 1627 / 840，全部守恒 |
| 原 body status | 840 LOWERED_WITH_GAPS、787 UNSUPPORTED、590 NOT_ATTEMPTED |
| entities/relations/facts | 437,228 / 1,172,205 / 289,298 |
| build wall | 418.647s |
| 含必要验收 wall | 426.824s；外层 time 7:07.20 |
| peak RSS | 192,992 KiB（约 188.5 MiB） |
| DB bytes | 481,460,224（约 459.2 MiB） |
| DB SHA256 | `5e9a7461b68268a630cf926d59ecfb1e7e498549d8500534f7d309fa81a32fbe` |
| SQLite integrity/FK | ok / 0 violations |

三类真实查询分别核对原 checkpoint receipt、exact JSON pointer、两端 ID：

1. Region→Block containment：`#/graph/regions/0/blocks/0`。
2. 原 Operation producer 和两个不同 Use 对同 Value 的引用：origin
   `#/graph/values/9/origin`，Use.value 分别位于
   `#/graph/operations/10/uses/1/value`、`#/graph/operations/13/uses/1/value`。
3. StateAccess：原 `#/graph/operations/0/accesses/0/location`、mode/full_overwrite、
   before-state Use 均一致。

这些 pointer 分别属于 query-proofs 内准确 namespace/artifact，不是跨 body 全局 ID。
多个原 Use 的存在不是 redundant computation 证明。

全部 57 个 ProgramGraph 字段均有真实 coverage。当前四类非空扩展记录只保留
locator 和显式字段引用，**语义关系仍 NOT_INDEXED**：

| 未索引关系字段 | 原记录数 | 已保留 reference endpoints |
|---|---:|---:|
| binding_definitions | 3,875 | 7,067 |
| binding_reads | 6,588 | 19,764 |
| environments | 840 | 10,472 |
| function_entries | 840 | 5,464 |
| 合计 | 12,143 | 42,767 |

42,767 个 endpoint 不是 42,767 条已闭合语义边；部分只是未资格化的外部 typed
reference。global inventory components、跨 body composition、动态实际调用和 runtime
资源桥不在此 source index 的覆盖内。原 source graphs 的 resource collections 为零，
不能解释为整个程序没有软硬件资源。UNSUPPORTED/NOT_ATTEMPTED 也没有被补成图。

SQLite 原库本地保留，可由固定原 manifest 重建；不加入 Git、不再额外压缩成全量
副本。代码、脚本、SHA/日志、分母/coverage 和 query receipts 用于版本管理。

### 本轮冻结收据

lewm 环境仅以标准库 `ast.parse(path.read_text())` 解析两个新模块，进程 exit 0；
没有 import store 模块、建库、执行目标或运行测试。冻结模块 SHA256：

```text
019e9754352facfb195c6f6bf1b768f7c9ad0dfa6b2712d4a3342021a79d08ed  scar/store/__init__.py
e59746ae82fe4d3d397222521721d26646a634d48a17e88bc32a05752314c5b8  scar/store/graph_index.py
```
