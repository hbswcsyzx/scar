# P2 amendment：调用具有哪些实际 completion

2026-10-18，发现于两次 close/retry 的真实仅 RAISE callee 构图。
本轮 Program18 尚未发布；本 amendment 与
[AdmissionPredicate](M1_ADMISSION_PREDICATE_CONTRACT.md) 合并为同一能力版本。
它不重写冻结的 P1 文档，也不把新构造写回 v1–17。

## 问题

旧一般 INVOKE 构造器同时要求 NORMAL、RAISE；已知 callee 的出口签名又必须
与它完全相等。因此，一个只抛异常的真实函数无法被调用：添加 NORMAL 会造
不存在的出口，不添加则构造器拒绝。用另一个真实双分支 fixture 可以检验 retry
连接，但不能修复这个表达缺口。

## 规范规则

- 一般 INVOKE 的 completion 是 **非空的 NORMAL/RAISE 子集**，每种恰一次。
  每条边使用不同 landing；不存在的 completion 不要求占一个虚假位置。
- Operation 的 completion signature kind 集合必须与实际 successor kind
  集合完全相等。每条边的有序结果、state、forward 与已知 callee 的准确出口
  继续受原 validator 检查，不能只放宽两个构造器而留下错误签名。
- raw successor ordinal 与 completion kind 不同。单 RAISE 的 ordinal 是0；
  任何读取都要看原 edge.kind，不能把“第0条”硬当 NORMAL。
- `normal_result` 在没有 NORMAL 或没有对应产出 landing 时明确报 ValueError；
  不泄漏内部 `StopIteration`，也不返回旁支或旧结果。
- 特定协议可以有更强要求。FinalBodyGate 继续独立要求 NORMAL+RAISE，
  NORMAL private landing 继续只能连接配对 BodyDrive；缺边返回明确 issue。
  Create 等请求 NORMAL 结果的接口仍逐项验证其真实 NORMAL 端口。

completion inventory 是 supplied model 的声明。只有一个 completion 不证明
未展开的 native/opaque 实现绝不会返回或抛异常。source/site inventory、外部
效果与适用性仍须另证；不能据此自动删除异常处理或授权化简。

## Wire 与回归

Program18 的触发为 AdmissionPredicate **或** single-completion INVOKE。
没有二者的图保留原 capability family 和旧 bytes；18 也不能用空 envelope
冒充新能力。强行放入 v1–17 必须拒绝，Execution 仍为7。

旧 constructor 测试的身份保留：原“只给一条边必错”断言调整为新 capability
正例；重复 kind、同 landing、signature/edge 不相等仍拒绝。新增真实 callee
单 RAISE/单 NORMAL、当前 N/R state/result、codec/查询与特殊 gate 反例。
原失败与独立源码审查保留；最终状态以本批组件/冻结报告为准。
