# C2B body graph fixtures / 定向验收与有限读审

2026-10-18。基于 `b4bc1a4` 后 root 并发实施的 C2 工作树；本报告不是冻结产品全仓
报告。只新增三个授权测试文件，没有修改产品、其他 agent 文件或执行 commit/push。
没有运行 LeWM、GPU、capture 或 full suite。

## 实施内容

- `tests/fixtures/program_resumption_graphs.py`：统一手工 typed IR fixture。
  `resumption_program()` 为 wire/CLI 稳定入口，3 blocks、world/context 两 state 域，
  SENT_VALUE/THROWN_PACKET 独占 landing，signature 与 formals 故意错序。
  `resumption_binding_program()` 保存并恢复 BOUND LocalBinding，再产生新读取结果；
  `resumption_loop_program()` 覆盖 Attached ordinary branch/self-loop caller forwarding；
  `resumption_two_cuts_program()` 覆盖第二 cut 后间接 merge（可选故意漏保存）；
  `resumption_cleanup_program(replace_pending=False/True)` 保持单一 CleanupEnter、
  原 pending/context 锚，含 fresh-before-yield replacement；
  `resumption_invoke_program()` 覆盖 unknown INVOKE 两路径 fresh state 与本地 caller。
- `tests/unit/test_program_resumption_graph.py`：C2B 状态、availability、精化、保存角色、
  私有 context/调用边界与 derived queries。query 保留真实 BlockArgument producer，
  检查错 ID 类型、缺失端点、非 Suspend 和 bool/out-of-range case。
- `tests/unit/test_resumption_cleanup.py`：C1 Resume/Replace 跨 yield、保存锚与 freshness、
  使用旧 context/world 的拒绝。没有用新增 detector、backend 或业务规则构造 fixture。

这些 fixture 是声明组合，source span 仅占位；不证明源代码、Python runtime 的实例/
generation、实际 context switching、driver 或任何变换。

## 实际运行及保留的首次失败

在已有 conda `lewm` 中，`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.`：

```text
python -m pytest -q tests/unit/test_program_resumption_graph.py tests/unit/test_resumption_cleanup.py
```

| 日志 | 实际结果 | 含义 |
| --- | --- | --- |
| construct.initial.log | 4 个基础 factory 构造成功 | 只构造，不是 validate |
| construct.cleanup.log | 两个 C1 factory 构造成功 | 只构造，不是 validate |
| pytest.initial.log | 28 passed / 2 failed，0.61s | 原样保留 |
| pytest.corrected.log | 31 passed，0.56s | 隔离目标 guard 后通过 |
| pytest.invoke-review.log | 3 passed / 25 deselected，0.32s | 逃逸疑点正反例确认 |
| pytest.final.log | **34 passed，0.49s，exit 0** | 三个最终测试文件组合的有界终态 |

首次两项失败不是无效图被产品接受：

1. 保存 LocalBinding 时把 role 改 VALUE，先被 `binding_edge_slot` 等既有绑定规则拒绝，
   尚未进入 switch validator。现断言精确的前置 guard；另加普通 Reference 冒充
   LOCAL_BINDING 的反例，精确命中 `resumption_saved_role`。
2. Replace 输入改旧 pending 时，post-pop jump 尚转发原 fresh replacement，先命中
   `cleanup_corridor_pending`。同步 selected jump actual，保持走廊一致后，现准确命中
   `cleanup_replacement_fresh`。没有弱化合同或改产品绕过。

## root body validator 的有限独立读审

审读 `resumption_validation.py` 与 core `validation.py` 的模式/循环、private context、
多状态和 availability 连接。未发现新的实质漏洞。重点核对的是共同约束：

- 每个普通 Attached block 恰一个 caller formal；每条普通入边精确转发当前 caller。
  Detach 必须邻接 handoff/terminal，避免 Detached 路径继续普通用户操作。
- 初始和恢复 Attach 唯一产生 caller；frame 只由 Initial/Detach 产生，Suspend 保存
  邻接 Detach.frame；普通调用/完成不能伪造 private context。
- logical CFG 与追加 availability roots 分开；两个 cut/间接 merge 的旧值受检查，
  保存操作自己的 Use 也没有豁免。C1 copy/fresh 用 logical CFG，不在恢复时重建锚。
- shared state 的恢复由 typed ResumeInput 逐 Location 接入；world 写及 context Detach
  后不能用早期 state。unknown INVOKE 的两条 completion 必须分别提供两域后态。

一个疑点经真实小 IR 排除：同一 caller UseID 若既为 invoke argument 又本地 forward，
core `control_binding` 已拒绝。用独立 UseID 将同一 caller Value 传给 opaque callee，
`resumption_private_escape` 拒绝；普通本地 forwarding 的 positive 仍合法。因此没有
要求 root 修改产品；三个回归明确保留这层共同防护，不将静态怀疑写成已发现漏洞。

## 初批34项终态时尚未覆盖的组合与权限

本批新跨 yield C1 fixture 覆盖原 Return pending Resume，以及 Enter 后、yield 前
构造的新 Return replacement。**没有新增前一 cleanup visit 再次 Enter 后携旧 token
的跨挂起反例，也没有新 Throw 在 C1 中构造 Raise→Replace 的专门路径。** 旧 C1
相关回归不等于这两个新增跨组合已经验收；root 如将它们列入本组件门，还须专门补齐。

没有验收 Create/driver、gate、动态实例/代次、host outcome adapter、finalizer、完整
request×state 家族、源码自动恢复、真实 runtime context 或转化权限。完整 C2.0/C2.4
仍 OPEN；最终冻结组件/full 验收由 root 单独归档，本次 34 项不替代它。

## 授权文件终态 SHA-256

```text
fd43f5bd3e35a2a1ed0ba59daff19ece444cf21f509c4fe753f1347a3a67bac6  tests/fixtures/program_resumption_graphs.py
386410a84cc7116a0ec746bbc503db33a361e2a598e8efa733a38429620cfe56  tests/unit/test_program_resumption_graph.py
a5a2bf33220dfaa45e5917638434d9be06be40ce9e680678d3dbf7ef3d3dbbe2  tests/unit/test_resumption_cleanup.py
```

文件/API 已冻结，等待 root 后续验收；未获新任务不继续扩展 fixture。

## 后续授权补齐：恢复后新异常真正走 Raise→Replace

root 随后明确授权扩展 owned fixture/cleanup test，保留以上初批证据和日志。
新增 `resumption_cleanup_invoke_program()`，从稳定的 Resume fixture 作增量：

```text
原 Enter → Detach/Suspend → landing Attach → unknown INVOKE
    NORMAL: fresh world/context → 原 C1 Resume → parent route
    RAISE: packet + fresh world/context → 新 Pending Raise
          → 独立 CleanupReplace → 同一 parent route
parent route → C0 Return/Raise dispatch → 各自 Detach + terminal
```

新 INVOKE 的实际 Python/native 实现仍 unknown；这是实际 IR normal/raise 结构，
不是 source/runtime 异常见证。NORMAL/RAISE 分别拥有完整 completion，使用两个
域的真实 post-state；新 packet 经 owned Use 构造 Pending Raise。C1 old pending/
saved-context 通过原 Enter 的 canonical local copies 保持，没有新造 Enter 或锚。
普通出口保持 Return，新增功能 scope Raise port、RAISE exit 与 Detach Raise shim。

新增5项首次运行：**5 passed / 6 deselected，0.34s**，
`pytest.raise-replace.initial.log`（首次即通过，无失败重试）。包括正例、3种旧状态
精确 `stale_state`、旧 Return 冒称被选中 fresh Raise 精确
`cleanup_corridor_pending`。后者检验真实选中 token 一致性，未把它冒称为单独
must-fresh 证明；隔离的 must-fresh 反例仍是初批已通过的
`test_old_entry_pending_cannot_masquerade_as_fresh_after_resume`。

最终两 owned 文件同命令合跑：**39 passed，0.61s，exit 0**，
`pytest.final-with-raise.log`。前一 cleanup visit 再次 Enter 携旧 token 的专门
cross-yield fixture 仍未新增；不将此次 Raise 组合当作所有回访路径枚举。
完整 driver/runtime/source/C2.0/C2.4 的 OPEN 边界不变。

扩展后最终文件/API 再冻结，SHA-256：

```text
fa6a5bc90cf6605f8498b07835ee68bddd3c043a1ae04263431d41a30af5d93e  tests/fixtures/program_resumption_graphs.py
386410a84cc7116a0ec746bbc503db33a361e2a598e8efa733a38429620cfe56  tests/unit/test_program_resumption_graph.py
2ea326f7a459416ed6df690e980871384058c98a1505508aee7a6f98cc353fda  tests/unit/test_resumption_cleanup.py
```
