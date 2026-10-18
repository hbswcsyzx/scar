# C2B body 结构组件验收

2026-10-18；最终组件 **499项PASS / 7.077s**，7项标准全部通过，测试前后源指纹
相同。**冻结全仓回归待完成，尚未完成发布验收。**
字段依据：[body 合同](M1_RESUMPTION_BODY_COMPONENT.md)。完整
[C2](M1_RESUMPTION_INTERFACES.md)与 M0–M2 第一阶段仍未完成。

## 实施与模型的对应

| 模型关系 | 本组件实现 |
| --- | --- |
| 操作与唯一输入 | Suspend 的 exported/saved/handoff 是原 Operation 的独立 owned Uses；SavedInput 索引规范保存槽，不复制 actual。 |
| 控制与定义可用性 | temporal 边保留逻辑 CFG/cleanup activation；entry 与每个 landing 另作 availability root，禁止直接读未保存旧定义。 |
| 引用与当前内容 | 保存引用不保存可变内容；ResumeInput 逐 location 提供当次实际恢复前最新共享状态。 |
| 状态和私有上下文 | Initial/Attach/Detach 作用于声明 context 域；frame fragment 可以同源 alias；caller token 只在当前 drive 沿真实端口传递。 |
| 局部绑定与清理 | 同 slot/BOUND、原 pending/context 的 copy/fresh 沿规范 SavedInput 推导；暂停不 pop 或重 Enter。 |
| 来源和权限 | query 保留 BlockArgument producer；wire v10 及 CLI 只报告静态结构，不声明 driver、source、runtime、exclusivity 或 transform 已验证。 |

保留现有 producer/Use/state 和旧 v1–v9 合同。未新增 ID 命名空间、第二份 SSA、
source lowerer、Tensor tracer、detector 或 backend。

## 验收范围与已定位的问题

- 正例包括值/packet 恢复、多 state 域、BOUND 局部、普通循环、第二 cut 后的合流、
  `finally` 暂停后 Resume、fresh-before-yield Return Replace，以及恢复后实际异常
  INVOKE 构造新的 PendingRaise 并 Replace。手工 IR 不算源码自动恢复。
- 反例定位缺保存、旧 world/context/caller、无依据的 reference 精化、错误保存角色、
  不合法 private escape、错误 binding slot 与直接 CALL/INVOKE resumable body。
- 独立复现 F1：一个 FRAME_CONTEXT 保存槽传给两个 landing 参数被首版错拒。
  保留最小复现及两个原失败，修复允许同源 aliases 和 Attach 精确选择其中之一；
  caller 唯一参数规则不放宽。修复后的两个回归通过。
- 其余初始失败为新测试/脚本接线错误（helper 名、字段名、guard 隔离和未匹配
  selector）；原始日志保留，不把它们算产品误判或成功测试。

最终 gate 使用 [manifest](../gates/m1_resumption_body.json)逐标准映射；冻结实现
后再以同 HEAD/source/fixture 指纹跑一次完整测试。组件与 full 的报告必须分别
保留，旧 C1 的 3,330 项结果不能代替这次新代码的验证。

最终组件源指纹：`5ad7f47129a81b79c036dd46c458ecf603687546fa6e77bb4b7d2630b133d5a2`，
覆盖403个源/测试/脚本/gate文件。原始报告位于
`artifacts/experiments/b1_call_operands/model_resume_interfaces/body-component/final.json`。

## 后续顺序与权限

1. 完成本组件的独立复核、gate、冻结 full、归档和版本推送。
2. 冻结完整 Create/driver/body ingress/host outcome/release 字段合同，区分 drive
   epoch 与 body generation，处理 delegate-only 与无 body 的 drive。
3. 落实例/代次、专用 ingress、生命周期与 adapter 的 typed 组合，沿既有 C0/C1/
   body/state 接线，不复建通用 Python 编译器或 native TreeSpec。
4. 按完整性矩阵继续 location/literal、resource instance/work/ready、occurrence/
   denotation 与协议规则；全部 M0–M2 完成时按用户要求先停下来讲解。

未新增完整“上一 cleanup visit → 再 Enter → 再 yield”交叉路径枚举；旧 C1 对应
回归与本次跨 yield 测例分别记录，不冒称穷尽证明。没有 Create/driver/runtime
generation 实测，没有 LeWM 自动变换或 clean A/B 加速比。
