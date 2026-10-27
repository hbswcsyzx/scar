# P3 production 查询有限实施报告

状态：Implemented；专用 CPU/手工 IR fixture 查询验收 Verified。不是自动运行时恢复、完整 writer inventory、Ready/V 或优化权限的验收。

## 接口与职责

仅新增 production_query.py、专用 fixture/test；未编辑公共 wrapper、ProgramGraph、ExecutionModel、codec、source/write/produced validator、LeWM 或 backend。

production(ctx, read_id, *, budget=4096) 返回 detached dict。公开 ExecutionIndex wrapper 由 root 集成，重新构造严格 external snapshots 后调用本模块。

顶层字段：read、demand、lineage_prerequisites、candidates、current_production、possible_invalidators、unresolved_relevance、pending_sources、gaps、budget_used、budget_costs、truncated、budget_scope；source_runtime_verified/readiness_verified/transformation_authorized 恒 False。

candidate.id 是 ('edge', original InventoryID, stream, edgeID) 或 ('raw', InventoryID, stream, physical line, canonical SHA)。不含 Write/Produced/Work ID。先枚举原 consumer run 的所有 inventory 来源，后作可选关联。run 不可解时保留全部 inventory 并给 gap。

候选保留 PRODUCES/MATERIALIZES/OBSERVED_WRITE/OVERWRITES/ALIASES/USES_STORAGE/ESCAPES 与全部原 raw 行。raw_native_result 只是原 payload 含 scar_native_result；其它 raw_record 保留当前 normalizer 未展开的效果，不捏造 alias/overwrite/escape 图边。

同 bundle 从原 EEG endpoint 查回 VG；独立范围仅显式 bridge，多目标全部保留且不证明相等。source stage/evidence 只按准确 SourceEdgeRef 或物理 RawRecordRef line+SHA 连接，不以同 host/work parent 推配对。

current_production 是准确 scoped version、Mat、selector 相符的声明关联子集，非闭合 AND writer 集合。其它 write 保留在候选 write_associations。原 parent_versions/provenance.inputs 仅列血缘前提。同 allocation 的不同版本/边界盒可能重叠列 possible invalidator；边界盒不填洞、不证明写入。

仅相同物理 raw stage、相同 production/placement 且相同 writer 的声明才归为一个关联组。不同 stage 或未证明同一原生工作保留分组/重复未决 gap。匹配 produced 保留原 Outcome、实际 frontier/selector 和部分结果，不从 COMPLETED 扩大范围，也不抹掉 FAILED/CANCELLED 的实际前缀。

## 预算

positive exact-int（拒 bool）。共享预算计 VG lineage node、每 parent/provenance 引用、每源 EEG edge/raw 行、检查的 endpoint/bridge/write/produced/group join 和 selector rank。来源枚举在关联前，删除关联不能改变已经扫描的候选前缀。截断明确给 production_budget 与 pending/unresolved；不能推 independence。

snapshot 严格校验、normalizer 重放使用自己的 byte/line/artifact 预算；返回原 metadata 的 deepcopy/序列化不计作图遍历。因此 budget=4096 不等于总内存/总耗时上界。未保存 tensor 数值。

## 原始执行证据

所有测试均 conda activate lewm，PYTHONDONTWRITEBYTECODE=1，PYTHONPATH=.；准确命令、Python 版本、源 SHA、stdout/stderr、退出码保存在 attemptNNN。

- attempt001：20 passed / 5 failed / 2.06s。五个失败均新 fixture 将 OccurrencePoint 错传给要求 EvidencePoint 的 Unresolved.point，未进入查询；原始失败保留。
- attempt002：修 fixture 坐标并加不同版本同 allocation 反例后，26 passed / 2.33s。
- attempt003：budget fanout/placement/grouping 复核后，26 passed / 2.17s。
- attempt004：按独立审查保留 ESCAPES 为未决来源后，26 passed / 2.27s；exit 0。当前冻结 hash 对应此轮。

测试包含：D 原读取/Observation root；真实 replay 的 PRODUCES/OBSERVED_WRITE；删除 Produced/Write/Work 的来源候选不变；缺 inventory/index；raw opaque native；准确部分前缀下 COMPLETED/FAILED/CANCELLED；跨图桥及多桥不选首项；同 allocation 的其它版本不列 current；相同 raw stage 组与不同 stage 不合并；血缘前提非当前贡献；catalog 后变重新核验；返回 detached；严格预算和截断。

当前 normalizer 不生成 ALIASES/OVERWRITES/ESCAPES 关系，未伪造 graph fixture 来冒称其 runtime 捕获已验；这些已有 schema 关系在查询枚举中保留。未知原始 alias 行只保留原 raw 候选和具体缺口。未跑全仓、GPU、LeWM、安装或真实采集；完整 component/full 由 root 统一执行。

## 冻结源码

- scar/ir/execution/production_query.py: `3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab`
- tests/fixtures/execution_production_queries.py: `92539d2c4d65c1b7a33e6623144c6c2ee5e2234bcb41b9370cdb9300f85ba22b`
- tests/unit/test_execution_production_query.py: `5f1790a3b16caefccab0c071dcbbabf0589fb9c6ee00ce069b312ecbec307acf`
