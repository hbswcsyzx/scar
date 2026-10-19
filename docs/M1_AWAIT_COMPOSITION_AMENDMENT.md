# Await组合：获取与最终消费的合同边界

2026-10-19；本补充不改冻结D0/D1/D2，不新增producer、字段、profile、wire tag
或优化规则。原A–H及16组分母不变。

## 真实阻断

`model_await_composition/wrapper-fix-and-first-resume/` 在稳定748源码指纹
`68db135285f3c3e50e262c3b75a6a0a82ee107875c1e9595d29611f12d1eb874`
得到5P/1F。零cut程序的Create→GET_AWAITABLE→首NEXT→原Body RETURN→真实
StopIteration packet→caller RAISE→extract INVOKE(自己的N/R)→最终consumer
已通过core。附上已有 `OutcomeAdapter(AWAIT_STOPITER_TO_EXPRESSION)` 时，
唯一新增错误为两条 `protocol_rule`：正确的caller acquisition scope不能容纳
既有最终提取合同。不能用假的lookup/call或跨region driver scope绕过。

## 最小修改

把“profile必需的clause”与“可附加的clause”分开。新增只读
`PROFILE_OPTIONAL_CLAUSES`；仅 `AWAIT_ACQUISITION_V1` 允许已有
`AWAIT_RESULT_ADAPTER` + 唯一已有规则 `AWAIT_STOPITER_TO_EXPRESSION`。
`PROFILE_CLAUSES` / `required_clauses` 不改：获取helper本身不需要伪造最终消费。
旧profile准入、准确region、expected input、own N/R、state及consumer检查不放宽。
此关系属于原Operation/Value/Use，不是另一张producer图。

## 不可混淆的验收

此准入修复仅解决“正确关系无法表达”，不是整个await单位已闭合。完整resolver
还需从原source→advance→body outcome→caller packet/真实consumer派生末端义务，
再查adapter；删除整adapter不得把原末端consumer从分母删除。普通
`ProtocolResultConsumers` 只看到extract.input不能证明StopIteration.value语义。
完整consumer派生及零/多cut动态组合继续按原C/D/E核验，未验证部分保持OPEN。
声明图有效、语言适用性、实际执行身份与变换授权仍分开报告。
