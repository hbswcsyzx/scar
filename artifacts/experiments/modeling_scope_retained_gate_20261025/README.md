本目录仅完成 metadata/header/stat 准备，真实门尚未执行。固定源报告为 `first_stage_source_revision_current_20261025/result/connections/source/report.json`；typed `catalog.json` 的 inventory 与 coordinates 均逐字段取自该报告并校验原 receipt。源 header 声明 2217 个定义，报告声明 100438 次 invocation；均尚未读取成员正文。

`freeze.json` 固定 4 个 producer、实际导入的非 native SCAR 依赖、runner、Python/GNU-time 和全部所选 small roots（112 个文件）。冻结校验通过；invocation 仅固定 stat 和报告中的 decoded receipt，尚未读取其 19564946 个压缩字节。native type implementation `scar/ir/program/native.py` 未纳入源冻结，原 native producer 不执行也不修改。

输入根为 catalog 中六个准确原 artifact：contract、coordinates、source inventory、source report、native bundle manifest、同 Run 的 OS fragment manifest。`native_capture_batch` 尚未发布，保持 null 和明确 debt；不猜 schema。

预算：输入 small root/shard 各 32000000 字节，invocations stored 128000000 / decoded 1000000000 字节，单行 1000000 字节；输入总 stored+decoded 2000000000 字节，200000 members，1000 source files；producer 1800 秒。账本单 chunk stored/decoded 各 8000000 字节、1000 行，单记录 1000000 字节，manifest 4000000 字节，200000 entries，10000 chunks，总 decoded 8000000000 / stored 1000000000 字节、1800 秒。外层 2100 秒，20 秒 heartbeat，GNU-time 与 SELF peak RSS 分开记录；RSS 为观测值，无虚构内存硬限制。

根审核准确 catalog、freeze、预算后持有会话运行：

```bash
PYTHONPATH=. python3 -B artifacts/experiments/modeling_scope_retained_gate_20261025/run_gate.py --execute --freeze-sha256 09949422bdf67dae6f4d9f24772a8af4b80e6745171187fec0798c72c1eb87d3
```

固定单次运行目录 `attempt01/`，固定账本输出 `attempt01/ledger/manifest.json`，完整门报告 `attempt01/result.json`。目录已存在即拒绝；不自动重试。`BUILDING.json`、阶段 progress、stdout/stderr、GNU-time 和失败 receipt 保留。若在 manifest 发布后只读查询或终检失败，失败记录明确保留 `manifest_exists`，不可把 launcher 失败误判为成功。

门只验收全部原 source/call 成员及其可定位索引，读完才核 rows/decoded bytes/SHA。只读样本 query 每次至多一个 index chunk 加一个 data chunk，无原档重放。source constructs (122323)、dispatch (39796)、native activities (461242)、native value tables (225630)、OS observations (1067768)、OS resource/lifetime/process/thread table entries (38307) 仅有独立集合声明与未访 debt；OS table 数不代表完整 OS 资源全集。所有语义轴与这六域保持 OPEN；不宣称全程序完整建模。

`metadata-preflight.json` 保存来源字段与同 Run 证据；`preparation-check.json` 仅保存脚本语法、默认不执行入口和 112 个 small frozen files 的检查。`descriptor-final-check-04.json` 与检查源码复制自隔离树既有小型必要检查，无新正文扫描；原 receipts 未覆写。
