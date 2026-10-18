# R2.2 event/order 验收

## 状态与证据范围

**组件已通过；本次冻结全仓回归待运行。** 起点 R2.1 `9c7a913`，
按 [计划](M1_RESOURCE_ORDER_PLAN.md) 实现 [接口](M1_RESOURCE_ORDER_INTERFACES.md)。
没有新增 detector/backend/lowerer，也没有新的 LeWM profiling 或加速比。

Verified：组件 **497 cases / 7 criteria / 9.382s**，零失败；登记 **489** 个
源/测试/gate 文件指纹前后一致：
`10e12c818eb8c8adaeb3a4e0e4cf4dd4927137f568da590b02f648e013c4a3e5`。
报告保留组件运行前的基线 HEAD、dirty status 和实际 tested-files hash；
后续 clean full 将另绑定完整实现提交，不能把组件基线 HEAD 当成实现版本。

## 已实现和验证的连接

- 原 queued work/persistent prefix→有限 FIFO profile；WorkStart、WorkEnd、
  PrefixEnd、EventSignal 分开，没有 ConsumerEnd→ConsumerStart 的倒推。
- 同一 event 实例上的每次 record 有独立 ID，marker/capture 引用准确前项；
  event 原 ResourceUse/StateAccess 与 wait 原 state Use 相接，r1 不浮动到 r2。
- pending 工作无 Outcome 也能建立条件顺序；不宣称已完成或产出成功。
- 合并 dependency/FIFO/frontier/event/wait 后检查联合循环；错误队列、run、
  实例、代次和原端口拒绝，未知传递/协议/进程对应保留具体 gap。
- 查询保存 detached 原行/规则支持、预算与缺口；无路径不证明 independence。
  runtime/source/order verification 与 transformation authority 始终 False。
- execution v3 按能力显式编码；历史 v1/v2 字节不变，不能降级丢工作/顺序。

## 独立审查与原始失败

scope 复审发现 ExternalRealm queue 的 prefix/FIFO 可能绕过跨 run 检查，
以及 `(run,None)==(run,None)` 被当成同进程。已在 member/frontier/FIFO/capture
统一检查 scope，缺 process 身份不会闭合对应；两个有效反例纳入组件。
其第一次 fixture 测试因 InitialEntry 仍属旧 process 失败 **0P/2F**，修正
fixture 后 **2P**；原日志保留，不将构造失败当成验证器反例。

另发现 INVOKE bare state argument 可能被误用为 event read；已限制为 work 中
经 R2.1 验证的准确 InvokeBoundaryStateEffect。该路径做了静态复审，未声称
新增真实 INVOKE/native wait 实验。普通 wait 的原 READ/RW 路径由组合测试验证。
requirement-only 资源 Use 能经本 activation 的准确 realization 对应 location；
缺映射是 gap，不能把缺少固定 definition 当成不同资源的已知矛盾。

首轮记录 **13P**、codec **108P/1.55s**、graph **28P/1.82s**、query **12P/0.71s**；
增加 requirement-only 组合检查后 query **13P/0.73s**。这些 focused 指纹与最终
组件分别保存。旧 work-codec 的 version-3 case 保留原身份，随 v3 实现改为
正向 roundtrip，新增 version-4 非法反例；不是更名抹去旧 case。

v2 golden 从不可变 `bb1b402b498e9ce80a701658a59c1471e8ec32ce` 的隔离 archive
独立生成，assert 实际导入路径均属 archive、旧 codec 最大版本为 2：
**56,435 bytes**，SHA256
`b03a304a582a662d71ebdbe4685776aef9ec4fc357142f0fa2e6656cdae03234`。
旧 v1 golden 没有重新生成，原 fixture 与 case 守恒将在 full 单独核对。

## 保留的缺口及下一步

协议引用/路径是条件模型，不是 native enqueue/context/错误传播实证；不授
host read、其他域可见、ready、free、persistence 或变换。FAILED/CANCELLED
不会靠 order 路径升级为成功内容。R2.3 仍需原消费者→denotation、每必要贡献的
AND/替代支持 OR、实际 produced coverage 与内容/分配/域匹配；然后才到 R3。
整个 M0–M2 未完成，不将子门验收重定义成完整程序建模或 LeWM 自动优化。

原始证据目录：
`artifacts/experiments/b1_call_operands/model_resource_order/`。
