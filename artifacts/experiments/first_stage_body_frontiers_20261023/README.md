# 原调用加权的 source/body 缺口

2026-10-23。**Observed / Verified：保存的 metadata 投影 exit0**。
这不是重新构图或语言语义验收，也不增加 opportunity detector。

`audit.py` 对原分片 manifest 的全部151 source shard核physical/decoded SHA和字节，
把原2217个定义/body metadata与已验收272038 source bindings逐项连接。
没有读 canonical body graph、prepare、compile、执行目标或进行优化。

| 原调用分类 | code groups | 调用次数 |
| --- | ---: | ---: |
| 已有 body 连接 | 74 | 5,624 |
| 仅 source，body UNSUPPORTED | 91 | 2,902 |
| 仅 source，body NOT_ATTEMPTED | 260 | 260 |
| 在原项目 composition 中 definition 未连接 | 392 | 91,652 |
| 合计 | 817 | 100,438 |

最后一行未连接包含正在接入的外部依赖，不能把它写成没有源码或完全不可分析。
本报告固定旧 schema2，不能和新 attachments 的 source-only 数重复相加。
静态787 UNSUPPORTED/590 NOT_ATTEMPTED是全源码分母；上表91/260是实际观察到的
code-group分母。二者不是同一统计单位。

原source-only理由按调用权重排序，其中：heap/global/destructuring writes缺口
涉及1,092次/12groups，GeneratorExp涉及900次/1group，Slice涉及150次/1group，
`ordinary local has no parsed slot: v`涉及111次/3groups。这些是原lowerer记录的
诊断，尚未重新审查为根因；不能直接据此编写业务函数规则。它们决定后续通用
语言协议和解析问题的审查顺序，而不是据重复次数直接授权reuse。

成本：wall1.56s，peakRSS68,496KiB，exit0。原输入receipt、完整各组归属、实际理由
及精确source shard/body pointer分别保存在`result.json`、`groups.jsonl.gz`与
`input-shards.json`；stdout/stderr/time保留。`first_stage_complete=false`。
