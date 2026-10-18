# Storage byte coverage：有限实施报告

状态：Implemented；专属 CPU 定向测试 Verified。不是 R2.3 ready/consumer 闭环验收。

## 接口与归属

- 仅新增 `scar/ir/execution/coverage.py`、`tests/unit/test_execution_coverage.py`。
- 公开 `RegionRef`、`CoverageStatus`、`CoverageGap`、`StorageCoverageResult`、`storage_coverage`，字段按冻结 API。
- root 查询复用私有 `_ValueCatalog(value_graphs).graph(artifact)` 与 `_storage_coverage(..., catalog=..., budget=...)`。resolver 仅每次查询存活，每 distinct hash/schema/size 核一次 caller ValueGraph，再从已核字节经现成 v2 codec 解出 detached snapshot；URI 不读。
- 不改 ProgramGraph、ExecutionModel、wire，不复制 geometry 或 producer；RegionRef 仅引用既有 region。

## 已实现边界

1. 仅同 scoped artifact hash/schema/size + AllocationID 坐标系合并；不同 backing 保留 `allocation_correspondence_unresolved`，不作物理无 alias 断言。
2. 复用 provenance `_width/_byte_bounds/_byte_intervals`。在入口守住 layout、empty、known width、共享 cardinality/range 预算。empty/zeroStride 无幽灵点，负 stride 服从原 ValueGraph 边界验证。
3. dense 快路按 abs(stride) 排序，只有 stride <= 当前连续 span 才扩展；重叠维可为 dense，bbox 不填洞。supported exact RegionRef 反身包含可跳过枚举，`covered_intervals=None` 表示未展开而非空。
4. 对 exact 半开 byte intervals 合并 union，再沿 required intervals 单调比较；INCOMPLETE 必须 required 和所有可能提供者均可解析。已知子集足够时可 COVERED，即使额外 offer 缺失，并保留其 gap。
5. 非 empty 未知 layout/dtype、缺 snapshot/mapping、预算不足返回 UNRESOLVED。已提供 wrong family/hash/schema/size/region FK 或 invalid graph 是 ValueError。
6. `used` 是原 offers 中纳入所算 union 的非空支持，或 exact identity witness；不是最小必要集，更不是实际写入内容列表。
7. 所有结果 `source_runtime_verified=False`、`transformation_authorized=False`；不证明 logical version、当前内容、allocation lifetime、production、visibility、ready、free。

## 预算的精确定义

共享逻辑工作单位包含 visited refs、rank、整数 64-bit words、每枚举点的 rank 运算与排序估计、interval sorting/merge/comparison。预算不逐 writer 重置，超限不能据未完成枚举报告 INCOMPLETE。巨大 shape 在 legacy len(range(...)) 前 guard。

严格输入 record/type 检查，以及 ValueGraph validate、canonical serialize/hash、strict snapshot decode 是单独的 snapshot/input 验证成本，不宣称被 geometry 预算硬限。未访问 offer 不核 catalog 事实；result 保留原 offered refs，不补造其有效性。

## 真实测试

命令：conda activate lewm；PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_execution_coverage.py。

- attempt001：26 passed / 0.43s / exit 0；源码前后 hash 一致。
- 有界自查将 per-point rank 乘积加入预算计价；未改语义/API；attempt001 保留。
- attempt002：26 passed / 0.43s / exit 0；源码前后 hash 一致；最终版本。
- 覆盖：halves union、strided holes 与补洞、required holes、empty zeroStride、巨大 broadcast、overlapping dense、负 stride/越界、dtype element→byte、未知 geometry 禁 identity 升级、巨大 exact identity、巨大 dense、超大 range guard、累计预算、known subset + unknown offer、scoped allocation、URI 不读、per-query once hashing、detached snapshot、跨调用拒 mutablegraph 旧 digest、malformed external graph、strict/frozen/嵌套篡改/禁止 fake authority。
- 没有运行 full、LeWM、GPU、provider capture，没有安装环境依赖。
- 报告落盘首个 shell 遗漏 conda，python command-not-found，未写文件；已保存 report-write.attempt001.log 后在 lewm 环境重做。这不是测试失败。

## 后续仍缺

EndpointPlacement/selector 单位、consumer denotation/current state、生产贡献覆盖及来源完整性、每贡献 AND/支持 OR、Completed 与 conditional order_path、失败部分产出与 visibility 均未由本组件实现。Core Footprint 不是 byte selector；Materialization.region=None 不是文件声明。root 的 MatRef 查询接线/独立 witness 与整体门验收另记。

## 最终源码 SHA256

- `scar/ir/execution/coverage.py`: `f818c78087d2855162868aaaf81420fdfe89038a2ddba6e7f2773744e58b55d5`
- `tests/unit/test_execution_coverage.py`: `c790c80c7acb80a77870043f37483b1b5e867963c73d8c67d30597f66aaf66cf`

## 窄输入契约复审修正（最终 attempt003）

父代理指出两个与既有 catalog 合同不一致的边界：所有 key 应 exact str；已有 sha key 值 None 是已提供 wrong-family，不能降成缺图。已仅加两项检查及同一参数化反例（integer key、str subclass key、present None），未扩大 geometry scope。

attempt003：同一专属测试文件 29 passed / 0.43s / exit 0；源码前后 hash 一致。attempt001/002 均保留，最终版本由以下 SHA 取代上节旧 SHA：

- `scar/ir/execution/coverage.py`: `e674cc01a0115f3d71a245a3878438969bdfa74953dff87a99cd89d63575687f`
- `tests/unit/test_execution_coverage.py`: `88ce27c32fc0280d09e9fe3cf3c429c3d4f8c016806a20b9af3655a5407d58ec`
