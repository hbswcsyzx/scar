# C2B root 集成独立反例审查

2026-10-18；审查 `resumption_validation.py`、`validation.py`、`queries.py` 的新增集成，不修改这三个产品文件。
本轮新增运行只有人工 IR 最小探针及专属回归；没有采集、应用 LeWM/GPU 或全仓运行。五个 forwarding 产品文件的实施证据另见 `body-forwarding/report.md`。

## F1：同一 FRAME_CONTEXT 保存槽绑定多个 formal 被错拒

**已实测并修复，有限复审通过。** 冻结 API 允许 SavedInput 同槽多 formal 显式复用；唯一的是 FRAME_CONTEXT 保存槽，而不是该不可变私有片段的所有别名 formal。caller token 的唯一参数规则不能直接用于 frame 片段。

最小机制：在 `resumption_program()` 的正常恢复 case 追加一个 FRAME_CONTEXT BlockArgument，并在该 case arguments 追加 SavedInput(0)。既有 FRAME_CONTEXT 槽/owned Use/Detach/result 均不变；Attach 可以消费原 formal 或新 alias，另一 formal 未消费。没有复制 producer、增添动态 activation 或把 caller token 保存起来。

修复前 `resumption_validation.py:199–200` 要求 `len(frame_formals)==1`，`:230–232` 又要求 landing 只有一个 FRAME_CONTEXT 参数，故拒绝这一合法 alias。最小探针对照结果：

- 原始 fixture：通过。
- 同一个保存 Reference 槽追加 alias formal：通过。
- 同一个保存 FRAME_CONTEXT 槽追加 alias formal：拒绝，码为 `resumption_landing_attach`、`resumption_frame_parameter`。

复现：`PYTHONPATH=. /home/zyf/miniconda3/envs/lewm/bin/python artifacts/experiments/b1_call_operands/model_resume_interfaces/review/body-adversarial-repro.py`。
源码/初始输出分别为 `body-adversarial-repro.py`、`body-adversarial-repro.log`。
专属回归位于 `tests/unit/test_resumption_forwarding.py::test_one_saved_frame_slot_can_bind_two_formals_and_attach_either`，参数化原 formal/新 alias 两种 Attach 选择；修复前两例均失败，完整日志为 `body-forwarding/frame-alias-before-fix.log`。

建议的限定修复已由 root 接受：frame-formals 非空且 Attach 输入属于该组；landing 所有 FRAME_CONTEXT 参数都必须来自同一个指定 FRAME_CONTEXT saved 槽，不能按类型接受其他来源。非 landing frame 参数、caller 唯一参数与私有使用限制继续执行。

有限复查确认：`resumption_validation.py:193–202` 改为非空组及精确成员检查，`:225–232` 允许 landing 多个 frame 参数但仍禁止非 landing frame 参数，caller 的唯一参数条件未放宽。core 的 SavedInput 逐参数类型校验、唯一 FRAME_CONTEXT slot 与 saved-role 校验共同排除其他 frame 来源；并非按类型凭空接入额外 formal。主 body 合同 `41–43` 也明确同源 aliases 合法。

root 修复后精确选择该回归：**2 passed / 11 deselected in 0.30s**，完整日志 `body-forwarding/frame-alias-after-fix.corrected-selector.log`；我已核对日志和上述源码，没有重跑 suite。root 首次使用 `-k frame_alias` 未匹配测试（exit 5，13 deselected），原日志 `frame-alias-after-fix.log` 保留且不计为成功。

## 其他读取结论与界限

- logical CFG/availability roots 已分开使用；所有 operation Uses（含再次 saved）通过 cut 可用性，C1 仍用 logical dominators。
- private caller 的普通逐边转发核验具体 ValueID，Detach 核验当前 token；额外 invoke/call operand 不能仅靠同构造来源获得许可。
- Query 的 saved-source 指向 canonical owned Use，ResumeInput 只给出声明 signature；producer 仍沿 Value.origin，未发现它把恢复参数改成 OperationResult 的接线。
- 未从这些静态声明推断真实 caller inheritance、完整 source capture、driver 对应或实例/generation 单次恢复；这些仍不在本组件验收范围。

以上不是对全部错误图的穷尽证明。当前确认的实质问题只有 F1，已按未收缩的合同修复且保留修复前后证据；本次有限复审没有剩余阻塞项，也不据此宣布整体 C2 完成。
