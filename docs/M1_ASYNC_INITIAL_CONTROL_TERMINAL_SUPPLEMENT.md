# 本门补充：同一 async session 的自然 Return 到 host

2026-10-19。冻结计划后的 `first-joint-authored` 实测 34 通过、4 失败。
其中 `yielded-new-nonNone-resume` 的第四次 Drive 已到原 Body RETURN、
原 COMPLETE、实际 constructor own NORMAL 和 exception packet/host，但
`execution/resumable_sessions.py::_hosts` 对非 SuspendTerminator 提前返回，
未检查已有 `ASYNCGEN_RETURN_TO_STOP_ASYNC_ITERATION` 合同。

这是动态派生视图遗漏，不是缺少一种核心实体或需要再造 adapter。
root 负责窄改这一旧产品路径：复用原 adapter 的选定 own N/R、原输入、
实际 exception component 和 host 绑定；仅接受准确 DriveResult/source/rule。
自然 Return 与 ASYNC_YIELD 仍是不同输入种类，AWAIT handoff 保留原逻辑。
其它未知 terminal adaptation 保留准确 gap；不由规则名证明 native 实现。
Execution8 和旧 wire 均不修改。

C 原 NEW 动态正例保留每个 session 恰有一个 host 的原断言，补显式原
constructor/packet/host 端口核对。root 在同一 NEW 文件补真实缺采反例，
不改变旧 fixture。原相关回归已包含 async pipeline/session edges；最终
仍保全部 2016 旧义务，不另以小范围通过替代。

本补充的所有权为 root：`scar/ir/execution/resumable_sessions.py`；
其它所有权不变。原四项首败和此前源码快照均保留，不重写历史收据。
