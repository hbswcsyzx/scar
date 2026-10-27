# D2.4 公开条件 scope / CLI 实施报告

## 交付与边界

**Implemented / Verified（定向结构接口）：** LifecycleScope、LifecyclePosition、带
scope/原操作/位置的 LifecyclePoint 及 publication.point；CLI 的逐 scope 机器记录。
只修改授权四文件：queries.py、scar/cli.py、test_lifecycle_scope_queries.py、
test_lifecycle_scope_cli.py。不改 ProgramGraph、schema14、canonical producer 或 E/F/T/P 引擎。

- LifecycleScope 保存原 DriverLifecycle / DriverInterface；rule 为原 interface.rule
  派生属性，applicability 为恒 ProofStatus.UNKNOWN 的不可构造属性。无显式 scope
  不凭 D1 interface 推导新 scope。旧 raw getters 保持原记录接口。
- LifecyclePoint 保留原 terminal/session 后追加 scope、原 Operation、typed
  BEFORE/AFTER/EDGE 与 successor_index；EDGE 的真实 successor 由原操作直接派生。
  拒 bool/负数/越界或 BEFORE/AFTER 附带 index；不创建第二份 edge/actual/producer。
- SessionPublication.point 精确是 metadata AFTER 或 helper 实际 NORMAL EDGE；
  TerminalReleasePublication.point 是真实 release BEFORE。detached view 仍能回到
  原未证 rule 的 artifact+locator，不按同名 artifact 猜 ProviderEnvelope。
- CLI conditional_lifecycle_scopes 含 region、rule_profile、原 implementation
  FactReference 的严格编码、UNKNOWN、conditional_facts_derived 与逐 Region 五表
  实际计数。old v11 无 scope 时数组空且推导标志 false；显式 old v12/13 scope 可
  显示条件事实，不因此获得 session/drop 结构能力。失败 report scope 为空。
- 原 lifecycle/source/runtime/transform 权限保持 false；不声称 refs held/free/ready。

## 实际证据

先真实 import 并检查四文件 AST/单一终止 LF，`compile-ready.json` 记录源码指纹；
随后首次且唯一 focused 运行 **16 passed in 1.15s，exit0**。

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_lifecycle_scope_queries.py tests/unit/test_lifecycle_scope_cli.py
```

CPython3.14.7；`initial.log/json` 保存完整 stdout/stderr、精确命令、版本、耗时、
四文件 SHA。没有首跑失败或重跑。用例覆盖原对象 is、immutability/no status 参数、
无 caller-facts 方法输入、detached rule 链、helper NORMAL 改为实际 index1、callback
后 P失效/F保留但条件仍 UNKNOWN、11/12/13/14 当前 graph wire 选择与查询前后
字节不变、predicate-only 和 invalid/same-output report。

此处11–14是相应既有 factory 的当前序列化回归；未将它们冒称独立历史 v14 golden。
immutable v14 golden 由 root 后续生成与集成，不阻塞本首次接口运行。

## 后续与不声称事项

根代理负责真实 C1/C2B 组合fixture和独立 gate。本任务另只读审查该组合，不把本
四文件自测作为独立审计。既有 strict ProgramGraph/codec 保持 derived view 不可
成为 canonical 字段；依 root 指示不再添加重复构造器测试。

没有 full、LeWM/GPU、新 capture、安装、git、前端自动建图或性能测试。没有证明
实际 native/source/guard 条件或完整 D2/C2/M0–M2。首跑后四文件冻结，仅追加 ignored 报告。
