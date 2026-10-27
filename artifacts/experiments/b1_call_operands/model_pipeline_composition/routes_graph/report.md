# R3.2 P2 原端口组合实施记录

有限范围 **Implemented / focused Verified**；不代表整个 R3.2 或 M0–M2 通过。

## 所有权与接口

仅新增产品 `scar/ir/execution/composition_routes.py` 与测试 `tests/unit/test_execution_composition_routes.py`，未改旧 fixture、canonical graph、validator、model、wire、P/V 或公开 wrapper。设计另见 `design/routes.md`。

`routes(ctx, *, budget: ValidityBudget) -> dict` 内部不 detach，供公开顶层一次复制。返回：

- `operations/values/transfers/calls`：原定义/动态 occurrence/Use/StateAccess/producer/actual successor/call association 的视图。
- `gaps/status/visited/pending/cursor/budget_used`：DERIVED 仅表示扫描已给 observed rows，不是完整捕获/纯性/身份/可删除证明；预算截断为 TRUNCATED。
- 四项 source/runtime/value identity/transformation 权限恒 False。

operations 的 `scan_complete` 仅表示本行原端口扫描完毕。缺 Use 保留原端口+gap；缺 call link 保留 MISSING。entry formal 无 transfer 时仍保留原 ingress/ordinal。typed marker 投影与原 copy Use 分开；BodyDrive 只回查原静态 outcome Use，不伪造动态 body activation。

预算消耗原 operation/value/transfer、各 Use/result/access、各 marker argument、全部 caller scan 与各 call input/output joins。所有阶段共用传入预算；`budget_used` 是该共享对象累计用量，不要求 caller 再扣。结果 tuple 组装只重排已访问项；外部验证/最终 copy 和原全量 inventory 由 root 的顶层组合负责，不声称 bounded traversal 等于全部 CPU 成本。

## 实际执行与首败保留

命令（两个 attempt 均相同）：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_pipeline_composition/focus.py routes_graph tests/unit/test_execution_composition_routes.py
```

- attempt001：**9 passed / 1 failed，0.79s**。失败在测试 fixture 构造阶段：给 direct CALL 添加未绑定的 Use，被原 core `call_binding` 正确拒绝，未进入该项 query。原日志/source.before/after/junit 保留。
- 修正仅测试：直接使用 shared_calls 既有 `twice.left/twice.right` 两个同 actual、不同原 Use 端口；未放宽 core 或 query。
- attempt002：**10 passed / 0.69s**；子进程 returncode 0，driver wall duration 1.3850775193423033s。精确 Python 版本、命令、stdout/stderr、junit、运行前后源码 hash 均在 attempt002。owned 临时 basetemp 已在子进程退出后清理。

通过范围：两次同 callee 不同 activation 与当前 state；相同实际值双 Use；缺 call/缺 Use；实际 NORMAL/RAISE 且 CompletionResult 顺序反排；INVOKE 无 common AFTER；SavedInput 与 ResumeInput current state 分开；C1 CleanupRoute/PendingPayload；BodyDriveResult 静态原 outcome；loop incarnation；跨阶段共享预算/截断 cursor。通用声明图不等于 native/source 自动恢复，没有运行 LeWM 或 GPU，没有新的性能结论。

## 冻结源 SHA256

```text
4218b52b7f2d7f9b775011127dbca54015303ae17d062d465cc687f93a36e7ca scar/ir/execution/composition_routes.py
f26b56470eeced476769fdefbc15f5f2939cff0f5d9380d78a7b68fe0ed1138e tests/unit/test_execution_composition_routes.py
```

两文件均有单一 LF EOF。此后停止 owned 产品/测试编辑，等待 root 联合验收；本文不替代独立复审或冻结组件/全仓。
