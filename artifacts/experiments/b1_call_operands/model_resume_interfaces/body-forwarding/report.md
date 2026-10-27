# C2B saved forwarding 接线交接

2026-10-17。只修改授权五个产品文件和 `tests/unit/test_resumption_forwarding.py`；没有修改 root 的 model/core/codec/queries/C2 validator，未 commit。

- C0：通过统一 `saved_actual_use` 推导 pending case facts；外部 ResumeInput 不成为原 token 来源；保存 pending 只准 PENDING_COMPLETION role，包括未被 case 恢复的保留。两种 C2 frame/caller protocol 交专用 validator，EXCEPTION_PACKET 仍需 C0 scope。出口 shim 只新增已声明 body 的 Detach+真实 Return/Raise 二操作形状，实际 Detach 合法性由 C2 validator 检查。
- Binding：query derivation、same-slot/类型验证及 use authorization 全部接通 saved Uses。只准 LOCAL_BINDING role 保留；拒绝 ResumeInput 构造 binding history；旧 BOUND/UNBOUND 固定点不变。
- C1：must-copy/fresh 沿真实 logical temporal 边解析 saved actual；不改 entry-relative 算法。CLEANUP_CONTEXT 保留要求当前 active owning cleanup 和合法 lexical scope，所有实际恢复 formal 仍须留在所属子树；允许没有 case 恢复的合法私有保留。
- Provider：ResumeInput 可提供 canonical boundary-operation 的归属核对，值仍是 BlockArgument；没有新增 OperationResult、实际执行证据或 producer 存储。SavedInput 不被改认成新 producer。

## 定向证据

命令：`PYTHONPATH=. /home/zyf/miniconda3/envs/lewm/bin/python -m pytest -q tests/unit/test_resumption_forwarding.py`。

- 首跑：9 passed / 2 failed。失败是新负例测试直接索引“无来源 binding”的 facts key；旧 API 对这种非法 token 省略 key。改为 `.get(id, ())` 后不改变产品实现。
- 最终同文件重跑：**11 passed in 0.29s**；首跑和最终完整输出分别保存为 `initial-pytest.log`、`final-pytest.log`。
- 测试限定派生事实/边界许可：same-slot BOUND、错误 saved role、外部输入不造历史、未恢复的私有保留、同 port 新 pending 不作原 copy、C0/C2 constructor 分工、provider BlockArgument 归属。

未跑 graph suite、全仓、应用 LeWM/GPU/采集/安装。root 已独立报告其 smoke 正例通过；该报告不把 smoke、测试数或本批接线等同整体 C2/driver/source/runtime 完成。
上述五文件及 owned 测试已冻结；后续对 root 集成只做独立只读反例审查。

## 后续独立审查回归

root 明确授权在同一 owned 测试文件追加 FRAME_CONTEXT 同槽多 formal 回归（两种 Attach 选择）。修复前两个案例实测失败，记录 `frame-alias-before-fix.log`；root 修复其专用 validator 后两个案例通过，记录 `frame-alias-after-fix.corrected-selector.log`。root 的首次错误 selector 运行 exit 5 另存 `frame-alias-after-fix.log`，不计成功。
五个 forwarding 产品文件没有因该问题再改动；修复属于 root 的 `resumption_validation.py`。独立结论见 `review/body-adversarial-review.md`，owned 测试文件现含 13 个参数化案例；没有再跑整 suite。
