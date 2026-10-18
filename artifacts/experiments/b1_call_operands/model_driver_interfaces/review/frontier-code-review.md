# C2F frontier 独立代码复审

2026-10-18；只读复核 `resumption_flow.py`、`queries.py::body_outcomes` 和
`tests/unit/test_body_outcome_frontier.py`，并核对 C2F 文档及现 core/C2B 的相关前置条件。
本次未改产品/tests/docs，未新增 probe，未运行测试或重复 suite/full。

## 结论

**有限范围通过；未发现须阻塞 C2F 的实质错误。**
结论只覆盖已验证 resumable body 的首 terminal 结构查询；不签核 BodyDrive、D0
字段、动态 activation/session/epoch 关系或完整 C2D。没有新 runtime 证明。

## 核对依据

- `scar/ir/program/queries.py:90`–108：ProgramIndex 初始化先完整 validate，非法图
  不进入公开查询；`:122`–127 为每个规范 Use 建立唯一缓存 UseSite。
- `scar/ir/program/queries.py:224`–246：准确 ID、未知端点、跨 Region 和普通内部
  block 分别检查；只接受已声明 body 的 entry 或 C2B facts 中真实 temporal landing。
  未声明 body 返回 None，与已声明 body 无首 terminal 返回空元组分开。
- `scar/ir/program/resumption_validation.py:220`–221：roots 来自原 entry 和该 body
  的真实 landing，没有从名称或全部 blocks 猜恢复入口。
- `scar/ir/program/validation.py:196`–207：validated block 必须以唯一最后 terminator
  结束。因此 `resumption_flow.py:45`–50 只读最后 op 是成立的共享前置条件；helper
  另对空 block、末 op 无 term 和跨 Region successor 显式报错。
- `scar/ir/program/resumption_flow.py:36`–58：worklist/visited 只沿实际 successor
  走；遇 Suspend/Return/Raise 收集后立即停止，不跨任何 Suspend temporal successor。
  INVOKE、C0/C1、普通 branch/loop 不作值推断。visited 终止静态循环遍历，不推导
  动态总终止；可得空 frontier，也可在含发散回边的图上得到候选 terminal。
- `scar/ir/program/resumption_flow.py:60`：OperationID 排序仅稳定展示，不存新 CFG、
  actual 或 producer，不把多个可达 terminal 排成运行时间顺序。
- `scar/ir/program/queries.py:248`–260：Suspend 只暴露 exported 和 handoff；saved
  frame/binding/pending/context 不列入结果。Return/Raise 直接取实际 terminal values；
  不扫描 ExitPort 声明，故不会为被 C1 永久截留的语言目标发明 terminal。
- 同处 values 从 `self._uses[use_id]` 取原缓存 UseSite，无新 Use/Value/Operation
  producer；多个查询可创建新的只读 BodyOutcomeSite，但仍引用同一规范 UseSite。

## 定向测试的源码覆盖

`tests/unit/test_body_outcome_frontier.py:118`–224 实际断言包括：原 entry 与 value/
packet landing、连续两 cut、INVOKE 加 C1 的两条 outcome、普通分支/自回边、完整
合法纯发散 body、错类型/未知/跨 body/内部 block、wire 不变及 origin 对象 identity。
`:27`–30、`:139`–140、`:219` 的 `is index.use_site(...)` 明确检查规范 UseSite
身份；Suspend 私有保存值排除另有明确断言。上述为测试源码阅读，本轮不冒称实跑结果。

## 可信边界

共享 helper 接受调用方已验证的 Region/operations/start；它不重新执行完整图验证，
也不独立限制 start 为 landing。公开 ProgramIndex 已提供该限制，未来直接复用 helper
的 driver validator 必须保留同样前置条件。当前没有因此接受错误公开查询的路径。
空集仅表示该入口没有结构可达的指定终端；非空不保证任何分支实际发生、所有路径完成、
无 effect 或资源 ready。现代码/文档均未把这些结论升级为执行许可。

## 审查快照 SHA-256

- `scar/ir/program/resumption_flow.py`：`c7c6b5c8e6d84d568fa87e52f71f9b66a6c1a50930633d0e97ea8613ce014cbc`
- `scar/ir/program/queries.py`：`7cb8fe59dee3bff30030ecf96ba05015c14f4d3c62530d0f2a51a9474ab7a05e`
- `tests/unit/test_body_outcome_frontier.py`：`375bbb7a561058a2c73394042676d16f4de9cd2d1ae00f7daf2ae4c5facede27`
