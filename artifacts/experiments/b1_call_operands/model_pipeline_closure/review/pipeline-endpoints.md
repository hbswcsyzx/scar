# R3.3 pipeline ↔ endpoint 有限源码交叉复审

结论：**PASS_WITH_SCOPE（静态复审）**。在下列读取版本中，未发现这次限定连接范围内仍阻断交付的具体错接。此结论不等于重跑测试、真实 native 协议证明、整个 R3 完成或自动恢复 LeWM。

## 范围和证据

- 仅只读 endpoint/P/V 当前源码，以及本人已冻结的 pipeline fixture 与 integration assertions；本轮没有运行 pytest、probe、workload 或采集。
- 本人此前发现的 mixed-selector 崩溃与 C 的两项发现分别保留原始报告/日志，不覆盖初始失败。
- pipeline 矩阵历史结果是 11 个独立用例通过，后续 empty-buffer 的 3 个通过是同一矩阵内 3 个用例复跑，不能相加为 14 个用例。
- 历史 `115848/131072` 是修复 endpoint 标签计费前那次实际查询数据；本轮不将其冒充新源码预算用量。新成本由 root 最终组件记录。

## 已知问题的有限关闭

### 1. Work OutcomeProduction 的 actual selector 转接

C 的原问题：`resolve_actual_range` 返回的新 `actual_selector` 没进入 `resolved_produced`，而 V 统一读取此字段，导致原 Work storage selector 或新 endpoint selector 变为 None。Host EstablishedProduction 的 `**ranges` 路线不能替它提供覆盖。

当前 `production_validation.py:242–251` 明确保留 `ranges['actual_selector']` 和 `ranges['placement_match']`；`production_query.py:419–424` 保留同一 resolved association，`validity_query.py:64–87` 从原 Work/Host 两类 production 取相同 selector 字段。此项按当前源码**静态关闭**，不创建第二 producer 或用 request 代替 actual。

本人的 pipeline 文件输出使用 Host EstablishedProduction；11 个 pipeline 用例不能单独宣称已经实测 Work→endpoint 分支。该分支的组件证据仍归 root/A 的实际测试。

### 2. Endpoint coverage 后半段标签扫描预算

C 的原问题：边界构建/排序及每 portion 重新扫描 accepted offers 未计共享预算，最坏 N²。

当前 `validity_query.py:199–224` 在构建、排序、每个完整标签扫描之前分别扣 `endpoint_boundary_build`、`endpoint_boundary_sort`、`endpoint_portion_labels`；不足时不生成貌似完整的部分标签。`:233–258` 保留 UNRESOLVED、pending offers/portions 与 truncation gap。此项按当前源码**静态关闭**，本轮未重新测成本或性能。

### 3. Storage / endpoint selector 分流

本人初轮矩阵的产品错误：同一 logical version 的 storage buffer 与 endpoint 贡献混入另一种几何解释器，产生类型崩溃。

当前 `validity_query.py:115–152` 仅将 RegionRef 送 storage geometry，仅将 endpoint-byte-range descriptor 送 endpoint arithmetic；异族原 offers 保留于 `unmatched_offers` 和具体 gap，不删除原 source candidates，不按相同逻辑版本授权跨 placement 覆盖。此项当前源码与历史修后通过矩阵一致。

这不等于声明物理不别名：`validity_stability.py` 对 storage/endpoint 混合以及不同 endpoint target 仍保留 POSSIBLE。覆盖不能互换与 alias 已排除是不同事实。

## 端点范围与原输入连接

- `endpoint_protocol.py` 仅解析 whitelist 六字段、root locator、exact UTF-8 JSON 与受限 bytes；READ / WRITE_REQUEST 非空，WRITE_ACTUAL 可为零。它不打开 URI 或执行 provider。
- `source_byte_input:237–320` 从原 writer-owned UseRef → ContentRead → DataIdentity → scoped VersionRef / StorageContent Mat 派生唯一字节输入。多个候选不择首；Reference 不冒充内容；source/destination Mat 可不同，但需同 exact VG 与逻辑版本，仍保留 native consumption 未证条件。
- `production_ranges.py:141–168` 将 WRITE_REQUEST 与独立 WRITE_ACTUAL 对照原 raw requested/written counts、同 endpoint incarnation、同 destination MatRef。它不从 actual4 把 read8/request8 缩为4。
- `validity_validation.py:559–643` 再核 READ selector/interval/visibility 的 exact FactRef、独立 read extent、read/request/actual target 与 MatRef、source extent、placement_match；不只比较 shape、值、名字或文件路径。
- `:645–737` Work endpoint 需要本 ticket 的 COMPLETED 与准确 quiescence，并有到实际 read begin 的顺序；Ordered 本身不能满足 endpoint completed-write 可见性。失败/取消的部分 storage 写能力不被悄悄推广为此窄 endpoint 协议。

## Empty buffer、flush、close

- `execution_io_pipeline.py:429–453` 定义独立 empty-buffer LogicalVersion 与 shape0 Mat；容量8不等于已有8字节内容。
- `:549–557` 未执行 save 的路径明确不生成 close.flush 的 byte-write stage，后续 write/establishment 也不凭空产生。原 close.buffer_read / flush / close 控制和状态操作仍在；`:642–664` 的原 DataDenotation/ContentRead 选择 empty Mat 及其版本。
- integration `:88–99` 保留 empty identity、shape、无假 write/establishment 断言。WRITE_ACTUAL0 即便可解析也不能覆盖非空 read；这与“伪造 requested8/native0 来解释未写缓冲区”不同。
- 正常路径保留 serialized → 独立 CPU buffer → flush 原 Data Use/ContentRead → file endpoint，buffer accepted8 不直接授 file visible8。flush 缺失、观察早于 flush、partial4/read8 都不由最终 root 放在 close 后而掩盖。
- close/end-handle 不推导 target retirement、对象释放、flush 或 durability；本文没有把 `fsync` 返回视为掉电持久性证明。

## 本次读取指纹

```text
4b9cf7163c498ce85e654c3c1ff2ac863dab8efb9fae471bf07398535ed037fb scar/ir/execution/endpoint_protocol.py
2ee63f5d74cb9e75d3c7991318ca6fdcc125f2b9b3b09cfc0912726ce952ed17 scar/ir/execution/production_ranges.py
63f55ef4c4270f137d62799874ee51b783f562fc5086005e3f1769e8571158aa scar/ir/execution/production_validation.py
48cceaa0878db98508f4700ad24eb1b02b889219a8531aee0d7e69e3ca21c703 scar/ir/execution/production_query.py
e67c42294ca912fc425669e64523e8d52802ded17187980fb8ccca8b94157f15 scar/ir/execution/validity_query.py
81edc6774599ff508bcd55de10ba000a2e51f504f0b4bf3cd4e5823e82a9f564 scar/ir/execution/validity_validation.py
ef78805eba6be300dcc222836b8920910720b811ce19c15f1f327ac2000adea6 scar/ir/execution/validity_stability.py
42723a1144309cc544a39a71c78d364de922cd757a0fc0364fc7a8af3cc89c97 tests/fixtures/execution_io_pipeline.py
54ac956439232e9cffaa006485b248fa26a1a45003cd168ef70ffe5c4764fdf7 tests/integration/test_execution_io_pipeline.py
```

上述是共享树读取时版本，不宣称作者随后无修改或全局源已冻结。协议 applicability、真实 byte copying / capture completeness、未知 alias 与 persistence 仍保留原条件；没有新增 detector/backend 或优化授权。
