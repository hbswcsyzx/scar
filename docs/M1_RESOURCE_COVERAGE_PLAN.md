# R2.3-G：共享 storage selector 覆盖实施门

起点 `2d6f1d4`；完整义务见 [R2.3 合同](M1_RESOURCE_READY_CONTRACT.md)。本门是
消费者/生产覆盖的共同前置算法，不能替代 denotation、writer closure 或 ready。
继续保护 LeWM/SCAR 主工作区，不新建 detector/backend/lowerer、不跑重型 profiling。

## 1. 冻结接口及事实归属

新增 `scar/ir/execution/coverage.py`：

- `RegionRef(artifact: ProviderArtifact, region: StorageRegionID)`：强类型不可变
  外部引用，不复制 allocation/shape/stride/dtype，也不重建 producer。
- `CoverageStatus`：COVERED / INCOMPLETE / UNRESOLVED。
- `CoverageGap(code, region: RegionRef | None, reason)`：明确缺口。
- `StorageCoverageResult(status, required, offered, used, covered_intervals,
  missing_intervals, budget_used, gaps)`：保留原引用和有预算的半开 byte intervals；
  未能确定的集合用 None，不冒充空集。runtime/transform 授权恒 False。
- `storage_coverage(required, offered, *, value_graphs, budget=4096)`。

`ExecutionIndex.materialization_coverage(required: MaterializationRef, offered,
budget=4096)` 从原 mat.region 取上述引用，调用同一个算法。公开查询返回原物化/
版本/region 关系、几何结果与缺口；region=None 明确缺 placement/selector，
不把 core Footprint、device 字符串或无 region 物化自动当字节地址。

本门不增加 ExecutionModel 表或 wire capability；R2.3 其他关系以后按正式 schema
版本化。不是用另一套 region 结构先构造孤立模型。

## 2. 算法边界

1. 提供的 ValueGraph 必须校验原结构及 canonical bytes/hash/schema/size；不读 URI。
   一次查询每个精确 artifact 核对一次，不跨查询信任 mutable graph 旧缓存。
   缺图给 UNRESOLVED；本次访问的已供错误图/损坏 FK/快照不符则拒绝输入。
   低层 empty/identity 快路可能不访问其余 offer，used 只列已核对的支持，不将
   未访问引用视为有效；公开 MatRef 查询在预算允许时先解析全部原物化引用。
2. 相同裸 ID 不跨 artifact 合并。不同 coordinate/分配而无对应，不拿 shape/
   pointer 猜地址；未知 offer 不填 known holes，也不据此声称 holes 必然未填。
3. 先 guard layout、dtype/空集；strided empty/zero-stride 不产生幽灵字节。
   非空未知 dtype、未知 layout 保留 gap。每个 dtype 的 offset/stride 按各自
   元素宽度转换，负 stride 必须在原 allocation 内。
4. 复用原 `provenance._width/_byte_bounds/_byte_intervals`。bbox 不能证明覆盖；
   大 contiguous 地址集只在独立证明连续后使用 bounds 快路。稀疏 strided holes
   必须保留。exact RegionRef 快路只在支持的合法几何中证明相对声明地址集包含。
5. 几何预算共同约束引用/rank/枚举/intervals，不为每 writer 重置；巨大 size 在
   len(range) 前受控，不溢出或枚举完整 Tensor。artifact 结构/哈希验证成本独立，
   不假装受枚举预算覆盖。返回实际预算消耗及截断原因。
6. 已知 union 完全覆盖可返回 COVERED；已知缺字节且没有未知补全项时返回
   INCOMPLETE；缺图/映射/布局/预算等可能影响结论则 UNRESOLVED。没有纯 geometry
   结果可以证明内容版本、数值、来源、lifetime、visibility 或 ready。

## 3. 自主验收顺序

1. 三份独立关系审查；真实 CPU/OS bounded witnesses，只存几元素/字节及元数据。
2. 原 region union/holes、empty/zero/negative stride、dtype/scoped identity/
   allocation/预算正反例；公开原 MatRef 查询、mutable catalog 重校验及 no authority。
3. 独立复审、组件 gate；保存首次失败及改正，不为兼容重建旧 golden。
4. clean 实现提交冻结后一次 full，不并行其他测试或改源码/文档；原测试/fixture
   守恒、临时目录与受保护工作区、精确源指纹。归档报告及版本并推送。

验收后继续 D/P/V，不把 G 改称完整 R2.3 或完整程序建模。所有 testcase 都是
通用 storage/程序反例，没有 LeWM 业务规则；没有新的 LeWM 加速比。
