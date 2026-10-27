# C1 主集成独立审查

2026-10-16；基线 `588ca84` 及 C1 工作区。范围为 root 编写的
`scar/ir/program/cleanup_validation.py`、C0/core validator 与 queries 接线，
对照 `docs/M1_CLEANUP_INTERFACES.md`。本轮不审查本人 helper 的实现正确性。
未修改产品，未运行 full/LeWM/GPU/install/commit 或新 capture。

**终态结论：有限范围复审通过。初审发现的一项合法图错拒已由 root 修复，正式新增
6项定向回归通过；其余有限核验符合冻结合同。** 原始失败证据保持，不因修复覆盖。

## F1：纯发散 cleanup 无法声明其截留的 Return/Raise 目标

严重性：阻塞 C1“发散无出口允许”合同（冻结文档 §4，原第81–82行）。
这是现有 core 不变量与新增 pending completion/cleanup 能力的组合缺口，
不是已证明的运行时错误，也不是本轮新写的 cleanup 栈代码单独引入的问题。

最小语义机制（本轮未执行该 Python）：

```python
def f(x):
    try:
        return x
    finally:
        while True:
            pass
```

实际 IR 复现从已通过的 `resume_multistate_graph()` 出发：保留 protected Return/Raise
构造、Route、entry Enter/read/write，删除 Resume、post-pop route、最终 dispatch 和
exit shims；添加只在 cleanup 子树内部自回的独立 loop block，逐域转发当前 state。
移除被删 blocks/operations 的 values，保持所有剩余 blocks 可达及规范所有权。

验证唯一结果：

```text
unbound_exit at program_region:shared.region
declared exits must be bound to actual control exits
```

原因：`validation.py` 原第313–314行要求声明的 ExitPort 恰好有实际 RETURN/RAISE
站点；但 `control_validation.py:172–180` 又要求 Return/Raise ControlPort 引用已有
region exit。cleanup 截留 pending 后始终发散时，这两项无法同时满足。
同样的类型矛盾也可能发生于旧 Return 被 cleanup Replace 成 Raise、旧目标从无完成站点。
本次已实跑复现的是纯发散 IR；后一个场景在此只作机制推论，不冒充第二次实测。

原始复现与 source SHA256：`integration-probe.divergence.initial.json`。
可重放构造：同目录 `integration_probe.py::fully_diverging_cleanup(graph)`。

已采用的最小 v9 约束（由 root 实施）：旧无 C1 图保留原 unbound_exit；v9/C1 延后此检查，
完整 C0/C1 结构、stack、route、copy/fresh 通过后，未绑定实际站点的 exit 只能是
被某个同 region cleanup 捕获的潜在语言目标。支持必须来自该 interface **指定的
pending_argument** 的完整派生 facts，并有真实 ControlPort/PendingDefinition 来源。
闲置 exit、死 pack、entry 其他 pending 参数均不能提供支持。它不证明目标实际完成；
`ProgramIndex.exit_port_uses` 应返回空 tuple，不能伪造 producer/UseSite。

## 已实跑的其他有限正反例

命令：

```sh
PYTHONPATH=. /home/zyf/miniconda3/envs/lewm/bin/python artifacts/experiments/b1_call_operands/model_cleanup_interfaces/review/integration_probe.py
```

`integration-probe.extra.json`：13项 IR/query 核验符合预期，exit 0。
这不是完整组件门或 runtime/source 覆盖率。原先6项、随后11项结果分别保留在
`integration-probe.initial.json`、`integration-probe.final.json`，没有失败被覆盖。

| 机制 | 实际结果 |
| --- | --- |
| 合法多域 Resume；nested Fallthrough 与新 Return；局部 Break/Continue | 完整 `validate` 均无 issues。 |
| 普通 user operation 消费 private saved-context | `cleanup_context_escape`。 |
| Resume 使用 cleanup user write 之前的 world | core `stale_state`。 |
| protected→entry 改成普通 JUMP，保留真实参数 | `cleanup_protected_bypass`、`cleanup_entry_edge`。 |
| 去掉 pop 动作、保留 state/pending 接线后离开 cleanup | `cleanup_stack_entry`、`cleanup_exit_bypass`。 |
| 将合法 Resume 拆到独立首项 block，改为 Replace 同一个旧 pending | 精确 `cleanup_replacement_fresh`，未被更早 core/C0 门遮挡。 |
| inner Resume 恢复 outer context | 精确 `cleanup_context_forward`。 |
| outer Replace 用新 pending 冒充 saved original | 精确 `cleanup_pending_forward`。 |
| inner Return route 的 actual 偷换成 outer old pending | 精确 `cleanup_route_pending`。 |
| ProgramIndex 的 entry stack/copy/context/route 查询 | 与当前 canonical facts 一致；nested Fallthrough 为 FINAL_DISPATCH，Return 为 outer REPLACE。 |

nested fixture 初期的 protected→entry 普通 JUMP、Fallthrough 直接去非 dispatch block
均按合同被拒；fixture agent 修正后正例通过，未将搭建中的 fixture 错误报成 validator 缺陷。

## 代码审查边界

操作点栈覆盖全部真实 CFG/invoke 边；protected 物理出口、post-pop parent 走廊与
route selector/actual 绑定均已接通。state 仍由 core 当前版本规则检查；pending/context
分别证明，不能用端口集合替代。C0 无 C1 图仍走原解释，queries 复用 validator 派生结果。
本次未找到可复现的错误 graph 被接受，也未发现合法 nested/local control 的额外错拒；
该结论限于上述检查和探针，不穷尽一般 Python 控制或声明接口对应真实执行的事实。

## F1 修复后限定复核

root 将延期限定在同 region 的 handled_context_domains；C1 所有结构、LIFO、路由、
copy/fresh、private-context 检查无错之后，仅收集各 interface 指定 pending_argument 的
complete facts 所对应的本 region 函数 exit。该 gate 不把未消费的其他 pending 位置当
支持。审查未发现此限定需要额外的终止性假设；它也允许旧目标被新转移替换。

本人按新授权仅新增 `tests/unit/test_cleanup_nontermination.py`，没有编辑主 fixture。
正式命令：

```sh
PYTHONPATH=. /home/zyf/miniconda3/envs/lewm/bin/python -m pytest -q tests/unit/test_cleanup_nontermination.py
```

**6 passed in 0.34s**，exit 0；包括纯发散 validate/v9 确定性 roundtrip、全部声明出口
槽位的空 UseSite tuple；旧 C0 仅 CLEANUP 标签仍拒 unbound_exit；C1 ghost exit 仅闲置、
闲置 pack、或只作为 entry 额外参数三种来源均拒 unbound_exit。初次定向执行同6项为
0.37s通过；正式 pytest 文件是在 root 修复落地后建立，修复前证据是上面的独立 IR
复现，未声称正式 pytest 在旧代码上重跑过。Return→ReplaceRaise 在此仍是规则推论，
未声称新增该场景的专用正例。

相同原始 `fully_diverging_cleanup` 构造修后也无 issues，所有 exit-use count 为零：
`integration-probe.divergence.after-fix.json`，含修后产品与新测试 SHA256。
因此 F1 在本报告范围内 **CLOSED**；没有收缩“纯发散允许”的合同。

另对 root 自行发现并修复的新 CleanupRouteTerminator 子类/codec 缺 tag 问题做独立
限定确认：普通 Operation 构造拒 TypeError；绕过 frozen 构造注入后 validate 返回 schema
错误，见 `route-subclass.after-fix.json`。未将该发现归为本人初审的新缺陷，也未扩大旧
ID 子类规则；旧 schema/ID 的完整兼容门仍由 root 统一执行。

本报告不代替完整组件、公开 CLI 或冻结验收。第一阶段及 source/runtime 权限仍未关闭。
