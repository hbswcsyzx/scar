# R2.3 合同与 G 前置边界：有限只读 closure

结论：**BOUNDED_PASS（修正后的关系合同及本报告限定的 geometry/query 源审）**。
不是 D/P/V 产品签核、G 完整测试验收或完整 R2.3 通过。未运行 Python、pytest、probe、native/GPU、LeWM 或全仓；未改产品、tests、docs。仅新增本报告及独立 `consumer-review.md`。

## 1. 发现及合同修正历史

### 1.1 直接 Host/Q 观察被字面要求伪造 work 的关系缺口

初读 `M1_RESOURCE_READY_CONTRACT.md` SHA
`f964b6d9b1dce09d3bda7a2bba8624437117581a27cc251c097f2004eee5af62`。
旧 §3 字面要求所有读取端口连接 exact ticket，且读取区间一律至少 WorkStart..WorkEnd；它遗漏 R0 允许的直接 Host read、真正外部 ObservationRoot 没有实际 consumer work 的合法分支。
本代理源审提出；root 认定为真实关系缺口并修改正文，**旧合同不记 PASS**。没有执行错误图或 runtime 复现。

修正后 §3（`:47–54`）明确：存在实际资源/native work 才要求 exact ticket/原 effect/native 输入槽；直接 Host read 连接原 OccurrencePoint/协议区间，真实 Q root 连接观察点/区间。无实际 work 不伪造 ticket，未知消费方式单列 gap；WorkStart..WorkEnd 的保守区间只适用于实际资源 work。当前 SHA：
`b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f`。

### 1.2 geometry 的“全部输入已验”文案与提前返回范围不一致

初读 `M1_RESOURCE_COVERAGE_PLAN.md` SHA
`27679e4343a4cac722478055e4eaf39c5ce8398b5b8c9a732ff375d8f966a2c1`。
其旧 §2.1 对“已提供错误图/损坏 FK 拒绝输入”未限定访问范围；低层 coverage required-empty 或 exact-ref 充分支持快路会提前 COVERED，不访问其余 offered graph/FK。代码头部已明示 unvisited offers 不 catalog-verified。
这不否定充分子集的几何包含，却不能同时声称整份输入 catalog 已核验。此为源审文案/范围不一致，**未运行 probe，不声称已实测输入漏拒**。

root 已修 §2.1（`:32–34`）：仅“本次访问的”已供错误图/FK/快照矛盾拒绝；低层 empty/identity 可不访问其余 offer；used 只列已核对支持，不授未访问引用有效性；公开 MatRef query 在预算允许时先解析全部原 MatRefs。当前 SHA：
`ce09b76000644522f21b90c697c644897de1fc75631aaf8dc85f4b41f8917704`。
范围现与源码相符，不要求为几何 OR 充分子集遍历无关 offer。

## 2. G 没有替代必须关闭的 D/P/V

| 必须关系 | 修正后合同锚点 | 核对结论 |
| --- | --- | --- |
| denotation、当前 mutable 内容、原 selector | READY §3 `:40–46`，§4 | Use 旁附 logical ID 不算对应；原 Mat→version/backing 派生，未知不默认 whole/disjoint |
| actual consumer work/实际输入映射 | READY §3 `:47–51` | 同 host occurrence 不足以从多个 work 选中 consumer；直接 Host/Q 分支保留 |
| actual read interval | READY §3 `:52–54`、§8 | enqueue 点 current support 不替代资源读区间；无 work 的准确观察区间有独立表示义务 |
| 真正 Q root | READY §2、§3 `:55–58` | 精确 semantic artifact/现存 ContractID/输出或端点要求/观察点/协议；不由 EXTERNAL facet、路径或 close 猜根 |
| 贡献 universe 与 actual produced | READY §5–6 | source endpoint→ticket/effect/selector、inventory/边界、类别及去重必须对账；删 contribution/work 不缩小宇宙；partial FAILED/CANCELLED 不扩大 |
| 每贡献 AND/替代支持 OR | READY §7 | 允许混合 Completed/Ordered；不能独立 union 内容/consumer/domain；严格到实际 consumer Start |
| 有效性与 visibility | READY §8 `:141–156` | current state/alias/读区间/分配 retirement/端点选择；Host/Queue/Endpoint 不自动包含；retention 不证明内容稳定 |
| 实施与最终验收分母 | READY §9 `:161–168`，COVERAGE 末段 | G 只是几何前置，D/P/V 继续必做，完整 R2/R3/M0–M2 不因 G 关闭 |

本合同没有将 geometry COVERED、source FactRef 存在、COMPLETE 声明或条件 order path 当 ready/native authority。也未把字段尚未冻结的 D/P/V 冒称已实现。

## 3. 追加的 bounded geometry/query 源审

只读 `coverage.py`、`ExecutionIndex.materialization_coverage` 及实际复用的 provenance 三个几何 helper；未扩大 graph fixture 或独立运行算法。

- `_ValueCatalog` 按 exact hash/schema/size 检查本次访问图的 canonical bytes 和 FK，显式 dict key 为 exact str，present-None/wrong-family 不是缺图；不读 URI。每次 query 重建 resolver，实际用于几何的是经严格 decoder 解出的已核对 bytes 快照，不信任长期 mutable catalog cache。
- `RegionRef` 只指原 ValueGraph region；allocation coordinate 包括 artifact 身份，不凭同裸 ID、device 或 pointer 合并。跨 coordinate 无显式映射为 unresolved，不能填 holes。
- describe 先检查合法 layout/empty/width；空 strided selector 在旧 zero-stride helper 前返回，避免幽灵字节。dense bounds 快路独立检查连续地址集；非 dense 走受限 exact `_byte_intervals`，不以 bbox 填洞。
- strided cardinality 在 `len(range)` 前检查剩余共享预算与 sys.maxsize；引用、rank/字宽、枚举和 interval 操作使用同一计数器。图结构检查/序列化/hash 是单独输入成本，本报告不把它们声称为 O(budget)。
- union 后只切分 required 地址集；已知 holes 返回 INCOMPLETE，未知 offer/预算等可能填补 holes 时 missing=None/UNRESOLVED；充分已知子集可以 COVERED。covered=None 表示未展开，而 `()` 才是已知空集。
- MatRef query 从原 mat.region 取 RegionRef，返回原 materialization/version/region；region=None 保留 endpoint placement/selector gap。未知 offered mat 不被悄悄删除以证明 INCOMPLETE；少预算不当独立性或无内容结论。
- 同一 allocation 字节几何可以 COVERED 而 logical version 不同；当前查询保留原版本并明确几何 scope，D/P/V 仍须检查内容。两个 API 的 source/runtime 与 transformation authority 保持 False，不增加 ExecutionModel 表或新 producer/state/materialization。

在这些具体路径中未发现剩余阻断；这不是对所有输入、并发 catalog 修改、性能上界或整个产品的穷尽证明。作者/root 报告的测试不计作本代理独立运行。

## 4. 最终读取源 SHA256

| 文件 | SHA256 |
| --- | --- |
| `docs/M1_RESOURCE_READY_CONTRACT.md` | `b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f` |
| `docs/M1_RESOURCE_COVERAGE_PLAN.md` | `ce09b76000644522f21b90c697c644897de1fc75631aaf8dc85f4b41f8917704` |
| `scar/ir/execution/coverage.py` | `e674cc01a0115f3d71a245a3878438969bdfa74953dff87a99cd89d63575687f` |
| `scar/ir/execution/query.py` | `1dd206368dba9a2ef9d3e3ed5bc15fce266ef3dd139d58874ab681c69dae892d` |
| `scar/ir/provenance.py`（width/bounds/intervals 相关段） | `f8f11d353a05c9b2ec893ae5ab3da7be747b4a2ea3b28a21eb1f7891237523c1` |

结论只针对修正后的关系边界与上述源码；source/runtime 对应、物理内容、producer/consumer 实际匹配、稳定读取、Host/Endpoint 协议及完整程序模型仍需各自验收。
