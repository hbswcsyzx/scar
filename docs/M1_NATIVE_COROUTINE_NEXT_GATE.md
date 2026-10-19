# F14 之后的原范围

2026-10-19。完整目标仍是 M0–M2 建模，不新增 backend/detector。
[本门计划](M1_NATIVE_COROUTINE_PLAN.md)、[结构验收](M1_NATIVE_COROUTINE_ACCEPTANCE.md)
和 [实际报告](M1_NATIVE_COROUTINE_PROGRESS.md) 保留本门的条件和范围。

## 1. 下一步先审 F16 的已有连接

原四类 request 创建、同 R/B 三次 HOLD/HOLD/COMPLETE 实际调用及后次 scheduler
THROW/CLOSE 当前来源桥已有证据，不能重做它们充当新进展。

下一门须从原 Operation/Use、state read/write、SessionUpdate、CallActivation
和实际 selected transfer 出发，先区分以下三件事：

1. 同 R 完成后重用：`test_program_async_completed_reuse` 已有两次真实调用、
   一个 Request Create、第二拒绝的 own NORMAL/RAISE 包及全状态，不再造
   同义图。`test_execution_request_state_history` 已列 post→READ 的四个
   blocker：adapter.construct、首 terminal 效果不完整、catch context
   未隔离 RW、后次 association primitive 效果不完整。它们继续保留；不能
   把 opaque primitive 改 pure，或借 F/no-reset 放通 P。
2. R1/R2 竞争同 B：现有三调用管线与 two-callers 都只有一个 R，仍缺独立两次
   AsyncRequestCreate、各自 latent 输入、同 B 来源、R1 HOLD→R2 当前拒绝→
   R1 继续的整链。B 此时可暂停在 AWAIT，不能拿 IS_RUNNING 或 R2.IS_COMPLETE
   代替 occupancy。RequestStateRule 只锚 initial/complete；联合占用关系的
   来源与 bool 锚应先冻结合同，不能只贴 CHECK_ASYNC_REQUEST 标签。
3. 初始 ASEND：R.initial、B.Created、实际非 None SEND 的联合控制，及拒绝后
   原 body/request 各自后态。不能仅因存在 enum 或某个观测 bool 就宣称完成。
   旧 request_creation 的 B 是外部 suspended；现有 async-profile
   AdmissionPredicate 又限定 RequestStateCondition，不能直接塞
   BodyStateCondition/ReferenceIsNone 假称联合条件已验证。

独立只读复核建议先补 R1 HOLD→R2 拒绝→R1 Resume，再单独补 Created/初始
ASEND 的零/非 None 路线；原 R3 内容缺口独立保留。此复核没有新增运行。

只在原条款确有缺口时增加准确供图和必要派生连接。已有 opaque 证据保持
Unknown 的原因必须逐项列出；若能由展开已知 callee 取得效果，则保留原
callee 内部操作，不用手写“安全”标签跳过它。

## 2. 验收方法

先冻结原条款与最小完整供应图；作者各写隔离的新 fixture/unit 文件，冻结后
root 串行执行。先解决真实首红和具体错误 True，再独立核原分母；相关回归
保全部上一门精确 JUnit 身份。归档含实际命令、源 SHA、失败前源字节、结果、
审查与版本信息。没有证据的条款不能用更小的新测试范围替代。

本轮库存扫描未声称总 CPU 严格有界：共享预算覆盖派生 copy/path/projection
工作，部分原 inventory/FK 扫描仍按图大小执行。这是成本边界，不授真假证明。
只有测得或审查发现具体必要性，才单独改索引或计费，避免无关重构。

## 3. 原剩余顺序

完成 F16 后依次按原要求核 F18/F19、F20/F22、F24、X25/X26/X27；已有部分
证据应复用，不能把族名当完成。随后 P4 完整组件/冻结全仓、P5 公共面及
M2 原113构造/196字段总清单各自验收。M0–M2 真正齐备后先向用户讲解，
再进入原 M3 自动 lowering 与 M4 实际执行证据对应；不以手工图冒充自动拆解。
