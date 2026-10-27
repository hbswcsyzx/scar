# C1 activation-local forwarding helper

2026-10-16；基线 `588ca84`。本子任务仅编辑：
`scar/ir/program/cleanup_forward.py`、`tests/unit/test_cleanup_forward.py`。
没有修改其他产品文件，没有运行 full、LeWM、GPU、采集、安装或 commit。

## 实现

- 冻结 API：`CleanupForwardFacts(slice_blocks, pending, context, fresh)` 为 frozen/slots
  dataclass，四个结果都是 frozenset；`derive_cleanup_forward` 使用约定 keyword 参数。
- slice 从 entry 沿真实 CFG 在整个 cleanup 子树中可达，切断重新进入 entry 及离开子树。
  直接从 canonical terminator 的每条 successor 和实际参数位置派生临时 incoming；
  不去重不同 successor，也不新增 producer、业务 graph 或持久 facts。
- pending 锚为当前 entry.pending_argument，context 锚为该 scope 唯一 Enter.saved_context。
  其他 entry 参数不参与传播；非锚 OperationResult 不构成 copy seed。
- slice 外前驱为 False，即使 actual 恰好引用 anchor；INVOKE 本地 UseID 可以转发，
  CompletionResult 与 PendingPayload 不复制。
- 先算 OR 最小固定点；其外保持 False，再求逐 incoming AND 最大固定点直至闭合。
  孤立无种子环与受无种子环污染的 phi 均排除，anchor/self-backedge 正例保留。
- fresh 只从 slice 内、有 PendingCompletionDefinition 的 pending OperationResult 取种子，
  并额外要求 entry 支配 producer block；entry 参数和外部来源不是 fresh。
  不检查 completion port 目标；目的地离开当前 cleanup 的义务由主 validator 检查。

## 定向验证

命令（conda lewm 的 Python，不 import Torch）：

```sh
PYTHONPATH=. /home/zyf/miniconda3/envs/lewm/bin/python -m pytest -q tests/unit/test_cleanup_forward.py
```

最终：**18 passed in 0.27s**，exit 0。增加两个剩余来源正反例之前的初次检查为
16 passed in 0.28s，exit 0；本子任务没有失败测试或省略的重跑结果。

测试覆盖：无种子/污染环、锚定互递归 loop、外部边界污染；分支合流、同 port repack、
不同本地 producer 的 fresh 合流、无构造定义的普通结果；同一 BRANCH 两边落同一块的
actual/formal 对调；pending/context/fresh 的自回边；旧 visit 的相同静态 Enter/result
经 entry 其他参数回传；外部前驱即使命名 anchor 仍为 False；fresh entry dominance；
INVOKE NORMAL/RAISE 的 UseID 与 CompletionResult 区别；PendingPayload；nested cleanup
分别锚定；canonical record 顺序不变性；返回结果不可变。

纯固定点反例单独调用内部 `_must_forward`，避免把抽象无种子环冒充 core-valid SSA。
其余测试使用实际不可变 ProgramGraph/Operation/Value/Use/terminator records，仅隔离
helper 的接线行为；它们不作为完整 state/routing/C1 graph 的验收证据。

`git diff --check -- scar/ir/program/cleanup_forward.py tests/unit/test_cleanup_forward.py`
返回 exit 0（两文件当前为新增未跟踪文件）；完整产品门由 root 统一执行。

## 前提与权限边界

调用前由 root 保证 core、scope、唯一 entry/首项 Enter、操作点 LIFO 和全出口覆盖。
本 helper 不替代这些 validator；它不证明 source/runtime context 或 payload 求值语义，
不证明回调 effects，不授予优化或 backend 权限。全 CFG AND 保守保留未证分支相关性。

SHA256：

```text
60d76f1173c6351f2f1b61f866cd12433612c17f1034a8113b76487c4d312b96  scar/ir/program/cleanup_forward.py
41a713d09d636dacc7682793b483a546df0d5927025d02f3f31661fef3b9bd82  tests/unit/test_cleanup_forward.py
```
