# 第一阶段：同次 Python 与原生执行证据

日期：2026-10-20。状态：**CPU 采集共存有限验收；完整模型和 LeWM 全覆盖未通过。**

## 为什么实现这一项

[自动化审计](FIRST_STAGE_AUTOMATION_AUDIT.md)确认，calls/operands 与旧 inject
互斥，原始证据不能在同次运行中共同采集。此改动只解决该集成断点，不新增
Tensor tracer、detector、backend 或优化实验，也没有修改规范 IR 的实体类型。

```bash
conda activate lewm
python -m scar.cli trace --call-operands --execution-evidence \
  --project-root /path/to/program --out /path/to/new-trace -- \
  python /path/to/program/entry.py
```

`--execution-evidence` 需要 calls-only/call-operands。默认采集模式保持原行为。
部署时从当前 worktree 执行或将其加入 PYTHONPATH；未重装用户 conda 环境。

## 模型职责与真实行为

- call recorder 继续独占 Python profile hook，operand sidecar 使用原 monitoring。
- 新 `trace/execution_evidence.py` 是薄 provider collector。延迟到目标实际完成
  Torch import 后才启动，不提前 import Torch、不重跑 forward、不包裹 Tensor。
- 复用单个 `torch.profiler.profile` 与 ExecutionTraceObserver，保存 nonce 命名
  原始 ETO/Chrome 文件及每进程 manifest，保留 provider 配置、窗口、版本和缺口。
- ETO 提供 shape/stride 等原字段；Kineto `record_shapes=False`、`with_stack=False`、
  `profile_memory=True`，不重复采 shape、不采 Tensor 数据。不声称有 memory DFG。
- 本机 provider 的注册所有权行为按固定 Torch source revision 核验；外部 ETO
  存在时 native API 可能只 warning 并返回 true，不能据此作清理。新 collector
  要求本次独有随机路径确实创建才取得窄注册收据，否则不注销外部 observer。
- 未验证的 provider revision、外部 profiler、额外 Tensor 数据采集环境等使该
  provider 显式 UNSUPPORTED；目标仍原样执行。不会覆盖现有 profiler 或旧产物。

## 实际自验

命令和原始 JUnit/stdout/stderr 在
[`first_stage_native_evidence_20261020`](../artifacts/experiments/first_stage_native_evidence_20261020/)。

**38 passed，109.68 秒 pytest；exit 0，无 stderr。** 其中 5 新项、33 既有 CLI
回归。这里只运行直接受影响的采集路径，没有重跑整个仓库，也不是性能 benchmark。

5 个新测试均使用真实 CPU 子进程：

1. 同次 calls/operands/ETO/Chrome；3 次目标函数对应实际 3 次 add/add_，目标状态
   和结果符合预期，无提前 Torch import、profile hook 变化或额外 forward。
2. 非 Torch 程序不被强制加载 Torch，不产生原生执行文件。
3. 未启用 call recorder 时，CLI 在执行目标前拒绝该组合。
4. 已有 ETO 在 SCAR install/close 后仍实际记录后续 sin，不只检查局部布尔标记。
5. 已有 profiler 仍保持 active，且实际记录后续 cos。

独立只读代码审查未发现声明范围内高/中风险阻塞。旧测试和 fixtures 未修改。

## 未完成的必需工作

这是 EXECUTION_EVIDENCE，不是静态 DEFINITION_GRAPH；manifest 明确
`whole_model_established=False`、`canonical_graph_imported=False`。接下来的实际
LeWM 采集、原始字段导入、准确 Python→Torch occurrence、state/LogicalVersion、
resource lifetime/ready、文件/环境/视频闭包仍需实施。不能把文件齐全称作完整模型。

采集只覆盖 owner 进程和 provider 窗口；Torch 初始 import 过程、其它进程/线程
和绕过 builtins import hook 的全部 loader 不保证覆盖。host 返回不等于 GPU
完成；provider 原始 buffer 没有 collector 强制的硬内存上限。仪器开销和潜在
引用生命周期影响明示，不用于 clean benchmark 或变换证明。

## 后续真实 LeWM 验证

同配置真实 LeWM 已正常完成，见 [当前状态](FIRST_STAGE_MODEL_STATUS.md)：
151,228 ETO 节点、151,226 ETO/Kineto 唯一 RF 对应及 GPU/OS 活动均有原始证据。
首次 OS 采集失败与 seccomp-BPF 重试分开保留。此结果验收采集共存，不改变上述
canonical model、逻辑身份、资源与全部路径仍未恢复的范围限制。
