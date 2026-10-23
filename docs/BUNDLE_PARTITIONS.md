# IRBundle 原记录分块归档

2026-10-23。状态：**Implemented；真实CPU原档全部记录核验PASS，完整LeWM导入进行中**。
新增独立 `scar/store/bundle_partitions.py`；`import-capture --bundle-partitions`
显式选择该路径，旧JSON路径仍兼容，旧provider原档不变。存储验证不重跑目标/forward，
不运行额外测试套件，不代表第一阶段完整程序模型通过。

## 目的与权威边界

原 `IRBundle.to_dict()` 会先构造全部 SG/EEG/Value/Correspondence 的巨大嵌套文档，
随后再生成单份大 JSON。真实 native bundle 的未压缩体积已超过 2GB，这种重复
物化不适合作为主要保存路径。

本 writer 直接遍历**已有原记录**，逐条调用其 `as_dict()`。不调用
`bundle.to_dict()`、任一 `graph.to_dict()`，不先拼全图列表，不重跑程序、不读
Tensor 内容、不生成额外节点/边。已有 canonical metadata 原样保存，已有数值型
measurement 不被删除；不会为保存模型额外取 Tensor 的元素、clone/hash/_version。

这是原 IRBundle 的分块存储，不是另一个可以独立修改的 IR，不授予优化权限。
raw ETO/Kineto/call/OS 等 provider artifact 仍保持原格式。

## 1. 公开 API

```python
from scar.store.bundle_partitions import (
    BundleBudgets, BundlePartitions, publish_bundle,
)

report = publish_bundle(
    existing_bundle,
    "/absolute/fresh/bundle-partitions",
    budgets=BundleBudgets(),
    progress=write_progress_record,  # 可选
)

archive = BundlePartitions("/absolute/fresh/bundle-partitions/manifest.json")
for envelope in archive.iter_records("evidence", "instances"):
    original_record = envelope["record"]
    original_ids = original_record["id"]
    actual_source = envelope["locator"]
```

`fresh_out` 的父目录必须已存在；输出目录通过独占 mkdir 创建，不能覆盖旧产物。
调用方必须在 validation/export 期间持有稳定的同一 bundle 和 record metadata，
不得并发修改；writer 核对 table 数量，但不冒称能证明任意外部并发写入不存在。

只支持现有 `IRBundle` 精确类型，要求 `optimization is None` 且
`source_semantics is None`。即使这些图为空对象但非 None，也拒绝，防止悄悄丢字段。
本次 native bundle 满足此范围。以后要支持它们，需显式增加格式/表及验收。

## 2. 明确的原表集合

| 原 graph | 原 collection |
|---|---|
| semantic | packages、modules、source_atoms、definitions、slots、controls、contracts、effects、resources、edges |
| evidence | instances、observations、provider_references、measurements、control_events、external_references、edges |
| values | logical_values、versions、provenance、allocations、regions、materializations、objects、bindings |
| correspondence | records；原 graph 为 None 时完整保留 None |

绝不只保存“节点和边”而漏掉 control_events/external_references/bindings 等原字段。
字典/list 内每个 record 使用原 `as_dict()`；control_events 是原字符串，
external_references 使用原 `{kind, wire}` 字段。原 graph 实例出现额外未处理表时
拒绝，不能把未知字段忽略。

开始输出前仅调用**一次公开 `bundle.assert_valid()`**。manifest 保存该次完整验证
报告与各 graph 实际 schema/version。Evidence/Value 的版本随原能力变化，不能用
类的最高版本常量假装该次实际版本。每张表完成后和全部输出结束时都核对 live
collection count，并与公开 validation 的原 counts 核对；旧格式省略的空可选表以
明确的零记录保存在分片目录描述中。

## 3. Chunk 与 locator

```text
bundle-partitions/
├── manifest.json
├── semantic/definitions/000000.jsonl.gz
├── semantic/edges/000000.jsonl.gz
├── evidence/instances/000000.jsonl.gz
├── evidence/instances/000001.jsonl.gz
├── values/regions/000000.jsonl.gz
└── ...
```

每个 decoded JSONL 行：

```json
{"ordinal":0,"record":{"id":{"kind":"...","value":"...","wire":"..."}}}
```

ordinal 在**该 archive 的 graph/table 内**从 0 连续计数。遍历顺序是原 live
container 的 iteration order；set 本来没有语义顺序。本实现不为排序而拷贝全表。
ordinal **不是旧 `to_dict()` 排序后单 JSON 的数组位置**，也不是执行时间。

真实 locator 是 `chunk URI + line(1-based) + /record`，没有生成虚构的旧 JSON
数组 pointer。record 内所有 cross-graph IDs、provider 原 locator 原样保持。

manifest 每个 chunk 保存：

- 精确相对 URI、gzip 格式、physical SHA256/bytes；
- decoded SHA256/bytes、lines；
- 连续 first_ordinal/last_ordinal；
- table/graph counts、实际原 schema/version 和原公开 validation。

空表明确 records=0/chunks=[]，不会被误解为未处理。manifest 还保存总 decoded/
stored bytes、records、chunks、预算与范围，明确 whole_program_established=False。

## 4. 有界与原子发布

默认预算：decoded chunk 16MB、compressed chunk 17MB、单行含 envelope 4MB；
独立 total decoded 16GB、total stored 4GB、records 10M、chunks 100k、manifest 4MB。
它们都是可覆盖的正整数，没有因输入大而自动无限放宽。

逐记录 JSON 用有限深度/项目数预检查和 `JSONEncoder.iterencode`，防止先生成
完整大 record 字符串再判断预算。每次只保留单条有限 record 的 encoded buffer。
gzip 逐块写入，compressed/decoded 的独立计数和 SHA 随真实写入维护，不重新
生成一份大原图。原 bundle 和单条 `as_dict()` 内部已有分配不属于 exporter 硬内存
隔离；本实现没有进程级资源隔离的声明。

progress 提供 VALIDATION_BEGIN、TABLE_BEGIN、CHUNK_CLOSED、TABLE_COMPLETE 及累计
bytes/records/chunks。回调失败中止发布；不把完整 graph 或 Tensor 交给回调。

全部 chunk 关闭、counts/预算检查完成后，写入并 fsync 临时 manifest，通过同目录
`os.link` **原子且不覆盖**地发布 `manifest.json`。预算或 I/O 失败不会发布 manifest；
可能留下新输出目录中的 partial chunks，作为失败产物，不删除任何输入。没有
最终 manifest 的目录不可读作已发布归档。这里的原子性是发布可见性，不是跨多个
原 provider 文件的事务，也不是断电后所有文件自动可靠的承诺。

## 5. 局部 reader 的验证含义

`BundlePartitions` 首先验证 manifest schema/status/表集合/counts/连续 ranges 和
读入预算。不把 manifest 中 producer 的 validation claim 当成 reader 自己重做的
语义核验，也不拼回全 bundle。

每次选择 `iter_records(graph, table)`，只读取该表所需 chunk。chunk 必须位于
archive 下精确预期的相对文件名；禁止 absolute/`..`/symlink traversal。

**首条 yield 前**，有界读取完整 compressed chunk，核 stored SHA/size；随后有界
解压完整 chunk，核 decoded SHA/size/lines。最多同时保留一个 compressed 和一个
decoded chunk，默认约 33MB 加单条 JSON 解析成本。不会让首条局部查询冒称一个
尚未结束解压的 chunk 已完成 raw hash 验证。

之后逐行严格 JSON，核当前 envelope 和准确 ordinal，返回：

```text
record / ordinal
locator: 原chunk receipt + line + /record + manifest receipt
verification:
  whole_chunk_stored_sha_verified=True
  whole_chunk_decoded_sha_verified=True
  current_row_ordinal_verified=True
  record_semantics_revalidated=False
  whole_bundle_revalidated=False
```

未访问其他 chunk 时不宣称它们已核验。当前行合法也不代表所有 record 的语义和
cross-graph references 已重新通过公开 codec；需要这种证明时另做显式语义恢复。

## 6. 当前接线与待验收

本模块是新增可选存储路径，已接实际capture pipeline显式flag。既有 OS/native-memory 等
protocol snapshot 输出可保留兼容，本 writer 首先消除反复保存巨大 IRBundle 的
路径，不能误报“所有旧 JSON 输出均已迁移”。

实际验收见 `artifacts/experiments/first_stage_bundle_storage_20261023`：对已留存CPU
执行原档做一次native/dispatch/physical导入，25张表的786条原记录、原顺序、
locator和完整chunk SHA逐条一致。产物8 chunks，914,170 decoded bytes、52,977
stored bytes；manifest9,031字节。保存了producer SHA、脚本、原分母和逐表record摘要。
这是存储往返证据，不是新的目标运行或完整模型证据。

完整LeWM新采集的同路径联合导入位于 `first_stage_joined_physical_20261023`，
当前正在运行；结束后以真实manifest和联合报告更新，不能沿用CPU结论冒充GPU验收。

静态冻结收据：lewm 环境标准库 `ast.parse` exit 0；未 import 此模块、未 export
bundle、未执行目标或测试。模块 SHA256：

```text
eadc3e7ae116e4e47dad09aa842b5e33be48b39e49426c7e257efa3ad6b817b5  scar/store/bundle_partitions.py
```
