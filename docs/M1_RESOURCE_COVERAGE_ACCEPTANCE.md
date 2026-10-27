# R2.3-G scoped storage coverage 验收

**状态：组件及一次 clean 冻结全仓通过。** 基线 R2.2 `2d6f1d4`。
[完整 R2.3 合同](M1_RESOURCE_READY_CONTRACT.md)保留 D/P/V 全部义务；
[G 计划](M1_RESOURCE_COVERAGE_PLAN.md)只实现共享 selector 几何及原 MatRef 查询。

## 已实现及验证

Implemented：`execution/coverage.py` 的 scoped RegionRef、预算内精确 byte-set
union/containment 和三值结果，以及 `ExecutionIndex.materialization_coverage`。
它从原 MaterializationRef 解析版本/region，不添加 producer/state 表、不改 wire。
既有 provenance helper 和 ValueGraph strict decoder 被复用；hash 后的实际查询
使用与 bytes 一致的 detached snapshot，每次查询重新核对 caller 的可变图。

Verified：最终组件 **432 cases / 6 criteria / 9.768s PASS**，所有 **493** 个
登记文件前后不变，指纹：
`b2e1bcdb11b4d1df31832f4b7c2a77aa6d3d3b0f2ef45afb77df6db717460e48`。
组件报告保留实际 dirty status/基线 HEAD 与 tested-files hash；full 则另绑
clean 实现提交，不能拿组件基线 HEAD 代表本次实现。

冻结 `aa2b9178e7a23ccfd86695b68524bf3817fe1673` 的一次 full：**4,427 PASS**，
0 failed/error/skipped、三条 warning；wall **473.15876185987145s**、pytest
**470.96s**，最大 RSS **1,026,340 KiB**。所有493登记文件、50 fixture及clean
HEAD/status前后一致。旧489文件除query.py扩展外488个不变，新增4个；全部
旧4,387测试身份和50 fixture保留，新增40项仅属本几何/原MatRef查询。
独占basetemp已在子进程终结后移除，LeWM及SCAR主工作区仍干净且HEAD未变。
这些是验收成本，不是LeWM或其他工作负载的A/B性能。

- union 覆盖及 stride holes；bbox 只在独立证明 contiguous 后使用。
- strided empty/zero-stride、negative stride、各 dtype 元素到 byte 的转换。
- 大 dense/exact selector 快路不枚举整个 Tensor；巨大非 dense size、累计 region/
  rank/位数/枚举/interval 工作预算不足返回 UNRESOLVED，不触发 len(range) 溢出。
- scoped allocation/不同 artifact 不按裸 ID 或 shape 合并；未知 layout/宽度和
  缺图不给假覆盖，也不给假 disjoint。
- 原 Mat.region=None 保留 endpoint/selector 缺口；未知 offered 不能被静默删除
  以证明缺字节；足够 known subset 可给几何 COVERED，但不证明这些 bytes 已产生。
- 每查询共享 resolver；旧 Index 的 caller graph 改变后不复用旧 hash 结果；
  返回原物化记录的副本不污染 source catalog。

低层 empty/identity 快路可能不访问其余 offer。used 只列核对的支持；未访问引用
不因结果 COVERED 就获得有效性。公开 MatRef 查询在预算内先解析全部引用，
明确提供的坏图/快照/FK 拒绝；访问预算不足是 UNRESOLVED。

## 真实有界见证与审查

Observed：一次真实 conda `lewm` CPU/OS 运行 **3/3 PASS**：

1. 同 Tensor 对象/data pointer、Torch `_version` 仍为 0，NumPy 改写后延迟线程
   实际读到新标量 73。retention/host 状态不等于读取区间内容稳定。
2. 8-byte 文件只写前 4 bytes 后发生受控异常，关闭后部分内容仍可读。
   异常不回滚；本次没有 fsync/durability 实验。
3. dense 与 stride-2 视图有相同 `[1,4)` 包围区间，后者仍缺偏移 2；实际
   empty zero-stride 视图的元素数为 0。

这是手写语义反例的真实执行，不是 SCAR 自动 source/native recovery。只保留几
个标量/字节和元数据；没有 GPU/LeWM profiling 或环境修改。脚本 SHA256：
`542a80628e5c1046a06e23970bbd387f5f7f00a0e95a8a873510330e887f56da`。

独立审查区分 logical lineage 前提、当前物化贡献和潜在 invalidator，不将所有
祖先 writer 平铺为 AND。合同修正了“无实际 work 的 host/Q 观察不造 ticket”，
以及低层未访问 offer 的验证范围。catalog 输入修正 exact-string keys、缺 key
与 present None/wrong-family 的区别；None 不能被当成尚未提供的图。

原 focused 证据保持：geometry 26P 后收紧枚举预算仍 26P，再补三项 catalog
检查 **29P/0.43s**；原 MatRef query **11P/0.60s**。没有失败被改写为通过。
这些源指纹分别记录，不拿旧 focused hash 代表最终组件。

## 尚未完成

Rejected：从顺序路径直接授 ready、从 retention 推稳定、从 bbox 填 holes、
从 mat.region=None 造 storage、从 UNKNOWN offer 推空集，以及凭 COMPLETE/FactRef
关闭缺失 writer inventory 的捷径。

Proposed / pending implementation：D 的 denotation/exact read/host-Q interfaces，
P 的 scoped evidence↔value/work/output bridge、来源派生贡献及 Produced frontier，
V 的读取区间有效性/visibility/每贡献 AND-OR。G 不能代替其中任何一个。
完整 R2.3、R3、M0–M2 与 LeWM 自动化简仍未完成；没有新的 LeWM 加速比。

证据目录：`artifacts/experiments/b1_call_operands/model_resource_ready/`。
