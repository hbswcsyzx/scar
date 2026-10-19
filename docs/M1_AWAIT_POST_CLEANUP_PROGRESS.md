# 完成值经过清理、调用与恢复：连接进展

2026-10-19；基线 `107ff11efd0d8369583b613282dfca5450692c48`。
[计划](M1_AWAIT_POST_CLEANUP_PLAN.md)与[查询合同](M1_COMPLETION_CONTINUATION_VIEW.md)
冻结字节保留。这是原 P4 建模连接的一段进展，完整 A–H、十六组、P5、M2 仍开放。

## Implemented：同一模型中的不同关系

实体仍为 **Operation / Value / StateLocation / Region / Resource**。没有增加
Program23/Execution8 规范记录或更改 codec。新增的是引用原 producer、Use、
CFG、状态槽和 occurrence 的查询收据，不另存第二份 SSA，不按 workload 名称推断。

1. **原来源与当前来源分开。** 清理可以保留完成值，也可以通过显式 Replace
   产生新的 Return/Raise。当前来源到终点的 copy，与原来源是否保留是两个
   独立问题；root=False 不使合法替换自动变错，current=False 仍是真正矛盾。
2. **token 与 payload 分开。** 原 CleanupRoute 可以按新 replacement token
   路由到 Replace，而 Replace 仍消费旧、新两 token。最终 PendingDispatch
   才投影当前完成的 payload，不能用旧 active port 阻止替换前的合法路由。
3. **状态正确与状态不变分开。** 清理写产生新 StateVersion；必要连接是终点
   当前 State Use 到调用方同 location/full result slot，不能要求旧版本不变。
4. **同步完成与未来恢复分开。** D 是普通同步调用，内部可以有 C1，但不能
   冒充可挂起主体。外层 P 调用完成的 H 后，才由自己三段执行及独立外层
   driver 形成两次 Suspend/Resume。原来只在同段寻找终点的约束继续保留。
5. **结构 copy 与证据完整分开。** 缺 pending payload Use 时，不允许仅凭
   外层 terminal→parent copy 显示整链成功。缺身份、关联或恢复采集保具体 gap，
   不借同代码另一实例，也不把 UNKNOWN 改成“不需要原最终提取”。

静态 `ProgramIndex.completion_continuations` 复用原 packet continuation 引擎，
按需增加 Reference 起始角色、当前来源/choices/context、terminal/transition
收据和显式 cross_resume。原 packet 查询默认行为和收费路径保留。

动态同名查询沿准确 anchor 所属 activation 的实际 CFG/ControlTransfer 投影，
共用原 copy ancestry 和 pending payload 查询，不另求可能路径。源先核准确
CallActivation 祖先；每个 P segment 要有唯一实际 Drive 与准确 outcome，跨段
要有本次 Suspend 对应 ResumeIngress。尚不扩展的后继 call、下一 Drive、不支持
的 source kind 明确停为边界，不能由 effects_complete 越过。原始内容仍未核实。

## Observed 与修复依据

证据目录：`artifacts/experiments/b1_call_operands/model_await_post_cleanup/`。
每次命令、失败、日志、JUnit 与前后源码注册表独立保留。

- 首红静态 0P/7F：新增夹具的 parent 与 LiteralOrigin Reference 声明错误。
- 连接首红 1P/14F：真实缺查询/收据及合法替换误拒；父 P 新夹具还复用了
  不允许复用的出口 Use。分别修产品与新夹具，不放宽验证器。
- 静态修复后 21P/4F：发现替换前路由误筛，以及新 host 多声明正常出口。
- 首次动态整链 19P/3F：缺 payload 仍显示外层 copy 成功；跨层返回 exporter
  的 edge-only seeds 未启用 pending payload 分析。实际父 P 六项当次已通过。
- 定向复验 **36P/0F**：22 个本轮新增项目与14 个既有 packet continuation
  项目，pytest36.02s，runner36.7851471118629s，831 个源码前后一致。

上述定向与首次全套受影响回归的源摘要：
`117fe2a2ae0be1e70db5f0690ed03df70051d35382204f1d2f7f99d783988e37`。
首次全套受影响回归 **1693P/0F**，pytest298.75s，runner299.76331656146795s。
收尾合同审查发现手工构建的四类 check 行遗漏补充 receipt 字段；独立作者增强
新9项的原 helper 后实际3P/6F，root 补齐字段、尤其是准确 candidate choices 后
9P/0F。没有改旧测试或用新状态掩盖首个回归；原结果保留独立目录。

字段修复后的冻结源：
`1c0c38b00f9ce7b510a9fc52640272e1178bd064e7410e163479865c7d7f68ec`。
最终受影响回归在 `verified-final-receipts/` 独立归档：
**1693 passed / 0 failed / 0 error / 0 skipped**，pytest300.30s，
runner301.3771510431543s，831 个源码文件前后摘要一致。
原1671个精确 case identities 全部保留，本轮新增22项，没有纳入其他旧用例
冒充新增覆盖。该结果属于 affected focused，不是完整组件/full 验收。

## Rejected：不能授予的结论

- 重复 node/module、copy=True 或 supplied graph 均不证明可缓存、纯或可删除。
- 失去来源证据不能被当作合法覆盖；交付为 False 不贡献该 outcome 的消费者，
  交付未知时保库存并明确 PARTIAL 与 delivery_binding。
- 原端口结构关系不是 native/runtime/value 身份证据。所有 source/runtime/
  value/transform authority flags 继续 False。
- 本轮没有 LeWM 自动建图或真实变换的验收，没有新增 backend、性能实验或加速比。

## 下一步与原验收分母

22 项新增用例包括同步 D 的 N/R、保留/Replace、opaque/错包、budget1，真实父 P
两 cut、depth1/2、两实例、缺 Resume/Use/H 关联和实际 H RAISE。另有两个受控
三值连接测试；它们核真实 typed ports 的连接逻辑，不声称独立恢复源码/原生事实。

这不是所有来源、资格、失败、共享 incoming、重执行和 C1 的完整组合。
`original-obligations.json` 将准确 selectors 填回原 A–H partial evidence，
八格仍未关闭，F12–F24/X25–X27 仍 OPEN。后续按原清单：

1. 对照原证据逐格补 native/self、general/W 的 BodyRaise 与获取/构造失败、
   当前状态/最终消费者连接；不能拿本轮 self/BodyReturn 的成功替代。
2. 合并共享 incoming、重执行、刷新和缺采边界，逐项记录原 A–H 反例与分母。
3. 原十六组真齐后做组件/full、P5，再核 M2 原113构造/196字段；完成 M0–M2
   后按用户要求停下来讲解。自动来源恢复和图化简仍在后续原路线内。

原仓库、旧 tests/fixtures、已有冻结合同、codec 与上一归档字节由 checkpoint
再核。新命令必须新建 attempt 目录，不得覆盖本轮或历史执行证据。

归档核验不启动测试或 workload，在 `conda activate lewm` 后执行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_await_post_cleanup/checkpoint.py --check
```
