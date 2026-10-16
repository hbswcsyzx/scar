# B1 调用窗口验收记录

日期：2026-10-16。**组件、历史重放、新 GPU、冻结全仓、真实 LeWM 采集及离线
inventory/link/query 均已结束。W4 的结果是条件引用来源；不证明完整参数/数据/效果链，
不授权变换。**

实现提交 `8a300eb068d992b3737eee0bdf43fa2bf8c8aea1`，源码指纹
`38dfe6c34545b405fa5e8f08e2828f7357c862527500a6a1f2b3d97072796574`。
本记录不授予变换权限，不代表完整程序建模或 LeWM 优化已完成。

## 已验证的有限范围

| 验收 | 实际证据与结果 |
| --- | --- |
| 组件 | 363 PASS，73.446 秒，源码前后不变。 |
| 冻结全仓 | 2,594 PASS，0 失败/跳过，3 条既有警告；364.788 秒，峰值 1,030,456 KiB；同一指纹。 |
| 历史重放 | 新 CLI 独立重建旧 LOAD_OCCURRENCES_V1 原始 GPU 报告；旧目录所有文件哈希不变。 |
| 新 GPU | 真实 CUDA leaf Tensor 与 backward；distinct/shared 输入的跨层引用查询保持正确调用与独立 Use，全部 14 条命令 rc0、stderr0；零 gap/drop/error。 |
| 新 LeWM 采集 | 原成功命令 rc0，episode success_rate=100.0；目标 Git/tracked Python 和 SCAR 源指纹不变。 |

上述 GPU 门继续保留 8 项条件及内容/环境/效果/world/transform=false；它只证明
声明范围内的条件引用来源。全仓及 GPU 验收耗时含并行资源竞争，不是优化加速比。

## 真实 LeWM 记录

- base：168,626 条事件、84,313 次入口、850 个 code descriptor，零 drop/error。
- windows：312,812 条记录；207,248 条 instruction、100,550 次 attempt、
  4,069 次 handshake、945 个 gap、17,037 次 load occurrence，零 drop/error。
- 945 个 gap 全部为 `PROJECT_FUNCTION_CALL_DID_NOT_ENTER`；最后记录到主入口
  结束前，采集已越过初始化并覆盖规划器。**零丢弃不等于零缺口或完整连接。**
- 插桩 wall 229.496 秒、峰值 RSS 2,177,108 KiB。没有 clean A/B 或变换结果。
- 3 个本次拥有的 raw call 文件经 decoded SHA/bytes/lines 核对，从
  274,432,007 字节无损压缩到 16,211,195 字节；只删除其已验证 plain 副本。

离线公共 `inventory-program --calls` 已 rc0：151 个源文件、2,217 个定义、
10,235 个源码调用；固定预算尝试 256 个 body，其中 50 个 LOWERED_WITH_GAPS、
206 个 UNSUPPORTED，另 1,961 个未尝试。425 个 eligible code group 中，32 个
CORE_LINKED、393 个 INDEXED_WITHOUT_BODY。它是自动清单，不证明 32 条动态参数链。

W4 原流程终态 `COMPLETED_CONDITIONAL_ANALYSIS`，driver rc0，elapsed 5,858.171 秒，
峰值 RSS 2,371,520 KiB。三个公共命令 `inventory-program --calls`、`link-operands`、
`query-operand-refs` 均 rc0、stderr 0。阶段耗时分别 597.257 秒、2,625.578 秒、
2,630.046 秒。SCAR 源文件清单前后字节相同（各自 SHA-256
`7bc72e628ce32d13ba4c516cde99289e29ee951576219954b82720e997fed0e9`），其中 source
fingerprint 始终为 `38dfe6c34545b405fa5e8f08e2828f7357c862527500a6a1f2b3d97072796574`。
目标 LeWM HEAD `f70fed80288462ca4d006cb3607ec6da6eaa851f` 与 clean status、tracked
Python files 均前后不变。

窗口采集 sidecar 共 312,812 条记录、100,550 个 call attempts、17,037 个 load
occurrences、4,069 个 handshakes、945 个 gap，零 dropped event / error。945 个 gap
均为 `PROJECT_FUNCTION_CALL_DID_NOT_ENTER`。读取前后 raw manifests 完全相同；8 个
捕获文件的物理 SHA/bytes 与留存的 gzip 输入逐个相符。压缩输入保持原格式和原 manifest，
未重复复制到本次 offline archive。

离线 `link-operands` 报告中 850 个 code descriptors 有 553 个 `VERIFIED`、297 个
`INCOMPLETE` source mappings；这些 descriptor status 不表示实际 body/environment
已完整。routing 汇总报告 27 个 argument routes、27 个 completion routes、4,907 个
invocation returns 和 471 个 template values，但所有路由均为 conditional。报告有
100,523 个 routing issues：96,481 `HANDSHAKE_BOUNDARY`、4,001 `SOURCE_CORE_BOUNDARY`、
41 `DISPATCH_BOUNDARY`。frame 报告有 84,313 entries/exits、4,943 target body
observations、2,013 core-call observations、8,927 verified normal exits，以及 83,392
issues；reference occurrences/routes 均为 0。不得将 code-source match 或事件顺序解释成
callee 参数内容、状态效果、函数环境或 world 等价的证明。

最终 `query-operand-refs` 的实际输出状态为 `CONDITIONAL_REFERENCE_QUERY`。选择规则选中
process `559598` / thread `132143864129344` / invocation `591`；它只有一个
`CALL_RESULT` root，`routes=[]`，`reference_steps=1`，并报告
`COMPLETION_BOUNDARY`（无唯一 observed attempt/entry/completion route）。因此这个选中
结果没有实际参数/返回的 route 闭环；该命令成功表示 query 正确返回了条件边界，不表示
查询到了完整引用链。完整结果见归档 `windows_lewm_analysis/query.stdout` 和
`query-selection.json`。reference route 不能推出数据内容、效果或变换正确性。

此 W4 仅完成调用引用候选及条件 route 审查。inventory/link/query 不是 clean A/B 或
变换，不证明 whole-program completeness、LeWM 优化或加速。

这次数据进一步确认 source/core 端点缺口。新结构模型门见
`codex/structured-program-model` 分支的 `docs/N2_STRUCTURED_BODY_PLAN.md`；
循环/绑定只是其中一阶段，完整加载、推理和视频输出仍需其他通用协议。

## 归档

相对仓库 `artifacts/experiments/b1_call_operands/`：

- `windows_full_regression/`：driver、前后源码哈希、JUnit、资源和 stdout/stderr。
- `windows_gpu/`：独立原始项目、公共命令、旧输入保护 manifest、raw/reports。
- `windows_lewm/`：原始命令、压缩 trace、资源记录、原始输出、采集及压缩校验。
- `windows_lewm_analysis/`：W4 的 inventory/link/query 压缩报告、原始终端输出、time-v、
  终态 JSON、输入前后 manifest 和逐文件 SHA 验证的
  `offline-copy-manifest.json`。捕获 gzip trace 已在 `windows_lewm/trace/`，未再复制。
- `windows-validation-copy.json`：主树证据到本归档的逐文件 verified copy manifest。

原 c91876b 的预算失败保持其原记录；本次结果不覆盖那次失败。观察、条件推理、
已实现采集规则、有限验证和未完成的模型门分别保留，不将其合并成“优化通过”。
