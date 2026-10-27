# 原 inventory SQLite 索引：真实验收 PASS

2026-10-23。一次真实构建与必要验收，Python PID 382595，exit 0，无修复/重跑。
使用 `conda activate lewm`，没有目标执行、fresh lowering、forward、GPU 或测试套件。
**PUBLISHED 仅表示可重建索引发布，完整 ProgramModel/第一阶段仍未完成。**

## 实际入口与固定来源

在仓库根目录执行的实际相对入口：

```bash
bash artifacts/experiments/first_stage_graph_index_20261023/run.sh
```

默认 tag 为 attempt01。已有输出不应覆盖；恢复/重建应使用独立新输出位置。
脚本调用原 `index_inventory` / `InventoryPartitions` 公共 reader，逐 body 经公共
ProgramGraph codec 校验；不调用 lowerer。

输入：
`artifacts/experiments/first_stage_full_inventory_restored_20261023/result/manifest.json`。
原 manifest 63,577 bytes，physical/decoded SHA256 相同：

```text
1443fedcbd8882e86dee392339a5ea51fd29ea102068a65d9e51e06b347de09e
```

## 实测成本与分母

| 项目 | 真实结果 |
|---|---:|
| 建库 wall | 418.647045s |
| 含必要验收 wall | 426.824078s |
| 外层 `/usr/bin/time` wall | 7:07.20 |
| user/system CPU | 379.47s / 4.50s |
| peak RSS | 192,992 KiB（约 188.5 MiB） |
| source files | 151 |
| bodies / original checkpoints | 2,217 / 1,627 |
| 原 graph / public validated graph | 840 / 840 |
| LOWERED_WITH_GAPS | 840 |
| UNSUPPORTED | 787 |
| NOT_ATTEMPTED | 590 |
| entities / relations / facts | 437,228 / 1,172,205 / 289,298 |
| SQLite integrity | ok |
| SQLite FK violations | 0 |

所有 manifest/body status/graph 分母守恒。逐 file/body 累计进度保存在
`progress.attempt01.jsonl`；没有静默等待全部图结束才记录。

本地数据库：`graph.attempt01.sqlite`，481,460,224 bytes（459.2 MiB）。SHA256：

```text
5e9a7461b68268a630cf926d59ecfb1e7e498549d8500534f7d309fa81a32fbe
```

数据库本地保留，**不加入 Git、不额外压缩/复制**，可从固定原 manifest 重建。

## 三类真实原 locator 验收

完整机器记录：`query-proofs.attempt01.json`（75,007 bytes）。每个结果实际从其原
namespace 的 source shard/checkpoint reader 回取，核 receipt/hash/pointer 和 ID。

1. **包含**：Region→Block，原 `#/graph/regions/0/blocks/0` 的 block ID 与两端一致。
2. **producer + 重复 Use**：原 Value origin `#/graph/values/9/origin` 指向真实原
   Operation；两个不同 Use 的 `.value` 分别在
   `#/graph/operations/10/uses/1/value`、`#/graph/operations/13/uses/1/value`，同 Value
   保留两个独立 Use ID。没有去重，也没有把它称为可优化的重复计算。
3. **状态访问**：`#/graph/operations/0/accesses/0/location`、mode/full_overwrite 和
   before-state Use 均准确匹配原记录。

这些 locator 必须与各自完整 artifact/representation/body namespace 一起使用，
不能因 pointer 或 local ID 文本相同跨 body 合并。

## 真实覆盖与仍未索引的关系

`coverage.attempt01.json` 逐项列出全部 **57** 个 ProgramGraph 顶层字段及实际分母。
四类非空扩展记录尚未生成语义边；保留原 locator/typed reference endpoints：

| 字段 | 原记录数 | reference endpoints |
|---|---:|---:|
| binding_definitions | 3,875 | 7,067 |
| binding_reads | 6,588 | 19,764 |
| environments | 840 | 10,472 |
| function_entries | 840 | 5,464 |
| 合计 | 12,143 | 42,767 |

42,767 是已实际保留的原字段引用，**不是已连接的语义关系数**，也不是所有未来
endpoint 的分母。复杂未支持关系保留 NOT_INDEXED；零记录字段也明确保存 0。
跨 body composition、dynamic actual calls、原 global components 和 runtime physical
resources 不在此 source index 中。原 source graphs 的 resource collections 为 0，
不能把它解释成整个 LeWM 执行没有 CPU/GPU/文件/内存等资源。

索引没有补齐 787 unsupported 或 590 未尝试 body，仍明确：

```text
whole_program_graph_established=False
all_relationships_indexed=False
source_replay_performed=False
target_executed=False
transformation_authorized=False
```

## 可版本管理的运行证据

- `run.py`、`run.sh`：真实入口和三类验收代码。
- `modules.attempt01.json`：builder、reader、codec/model 模块的实际 SHA/bytes。
- `artifact-receipts.attempt01.json`：脚本与日志/报告/query/coverage 的 SHA/bytes。
- `build-report.attempt01.json`、`summary.attempt01.json`：发布状态、成本和完整分母。
- `query-proofs.attempt01.json`、`coverage.attempt01.json`：原 locator 证据和未索引范围。
- `run.attempt01.log`、`progress.attempt01.jsonl`、`time.attempt01.txt`：实际过程和退出码。

脚本 SHA256：

```text
fdfd61f03f5d0ae17885ed51b4190fcfceb53f80f5504972226690cafe84d90e  run.py
a7f27aa0583dafbded8be1035f5d51763473092105bacc50f68b7c0b20f85160  run.sh
```

没有向数据库写入另一套可修改 IR、完整大 JSON 或 Tensor 数值快照；查询返回原
身份和原证据位置。验收通过仅用于第一阶段依赖核查，没有启动 detector/backend。
