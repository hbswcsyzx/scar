# B1 调用窗口验收记录

日期：2026-10-16。**组件、历史重放、新 GPU 与冻结全仓通过；真实 LeWM 采集通过，
离线链接/查询仍在运行，W4 尚未关闭。**

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
后续 `link-operands` 仍运行；没有最终 route/query 数量或覆盖结论。待原进程结束
后按同一 handle 获取终态并补报告，不因观察超时重启。

这次数据进一步确认 source/core 端点缺口。新结构模型门见
`codex/structured-program-model` 分支的 `docs/N2_STRUCTURED_BODY_PLAN.md`；
循环/绑定只是其中一阶段，完整加载、推理和视频输出仍需其他通用协议。

## 归档

相对仓库 `artifacts/experiments/b1_call_operands/`：

- `windows_full_regression/`：driver、前后源码哈希、JUnit、资源和 stdout/stderr。
- `windows_gpu/`：独立原始项目、公共命令、旧输入保护 manifest、raw/reports。
- `windows_lewm/`：原始命令、压缩 trace、资源记录、原始输出、采集及压缩校验。
- `windows-validation-copy.json`：主树证据到本归档的逐文件 verified copy manifest。

原 c91876b 的预算失败保持其原记录；本次结果不覆盖那次失败。观察、条件推理、
已实现采集规则、有限验证和未完成的模型门分别保留，不将其合并成“优化通过”。
