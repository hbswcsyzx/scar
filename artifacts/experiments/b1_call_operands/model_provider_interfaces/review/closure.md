# P0 来源修复的只读闭环复核

2026-10-16；冻结实现 `35469f0cc608d46d21b75775c7ba69fe76619109`，读时工作树 clean。
**结论：原 CompletionResult 问题按规范化规则已修；PendingPayload 扩展仍有一项待修。**
本轮只读源代码、测试和文档，没有运行测试或重跑 probe；不能将此结论称为实测复验。
原 [review.md](review.md)、[probe.py](probe.py)、[probe.result.json](probe.result.json)
均保留不改；四个旧错误接受结果仍是修复前证据。

## 原问题关闭范围

validator 现在扫描实际 CFG 边，把 `CompletionResult` 注入目标参数的来源派生为
该 INVOKE 操作；随后检查对应 provider operation key 与非空结果 path。
core 在此前已验证 INVOKE 完成目标只有一条实际 incoming edge，因此这部分来源
唯一、不依赖代码标签或 dominance，也没有持久化另一份 producer。
正常/异常 reference、正常/异常 post-state 均进入这一逻辑。
普通入口参数和单纯 UseID 转发不因此增加 producer。

新增测试文件静态包含四类正常/异常 value/state 的正确与错误 key、空投影、
UseID 转发对照和单来源 PendingPayload 对照。没有在本轮执行这些测试。
docs §3 已说明这是规范化来源声明检查，不核实外部 locator 或其端口索引。
原生 provider CFG 参数来源、真实 completion 投影语义仍属 P1，不授予等价或优化权限。

## 新待修项：共享 PendingPayload landing 被错误认定单一 producer

当前代码对每条投影边执行 `edge_producers[formal] = operation.id`。
INVOKE 的唯一前驱约束不适用于 PendingDispatch：`control_validation.py` 允许
不同 dispatch 对同一 Return port 使用共享退出 shim，没有 private-target 限制。

最小结构反例（静态推导，未执行）：

```text
entry --true--> left:  make PendingReturn(x); dispatch_left  --PendingPayload--> exit(payload, world)
      --false-> right: make PendingReturn(y); dispatch_right --PendingPayload--> exit(payload, world)
exit: RETURN payload, world
```

两次构造使用同一个函数 Return port，各分支显式传当前 world，exit 参数是合流。
若 `graph.operations` 中 dispatch_right 最后，来源表只保留 right；交换两个操作
在全局元组中的存放顺序（各 block.operations 保持不变）就变成 left。
由此 provider key 校验随存放顺序变化；普通 phi 被误认为某一次投影的唯一结果。
一条 PendingPayload 边与一条 UseID 转发边合流时也存在同类误判。
现有新增测试只覆盖单 dispatch 来源，不能排除这一问题。

建议最小修复：按真实 CFG edge 数统计目标的 incoming edges，只有唯一 incoming
edge 且该位置为 CompletionResult/PendingPayload 时派生 producer；多前驱参数
保留普通 phi 身份。若要保留更多精度，必须证明每条前驱该位置都是同一个投影
操作，不能只收集投影边而忽略 UseID 转发。不要通过禁止合法共享 landing 规避。
本项已直接通知 root；本报告没有修改或要求中断正在进行的全仓回归。

## 被审文件 SHA256

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/program/provider_validation.py` | `6cc8392caae05758b0ecd855697875b52098f54a62e2161338604761eaff9c22` |
| `scar/ir/program/validation.py` | `16b96077b5eee8a15b134fa2d95e6117f2b21e7c70b102881cee863a47177d9c` |
| `scar/ir/program/control_validation.py` | `73415377dee70aca0f2f844b5e6bdcad6ec18cff44ca7859c77492db08643642` |
| `tests/unit/test_provider_completion_origins.py` | `d9da15b5501052aed0fbf0fdffe11935717c2d225a3d2de36216e7c1f7a2ce7e` |
| `docs/M1_PROVIDER_INTERFACES.md` | `8c1f3b254a39d70c8617918f74109493d39860aed3c3dec95abbea83e2168792` |

没有新增 artifact/runtime/source 验证、guard 求值或权限；P0 不关闭全部 T1/M1/M2。
