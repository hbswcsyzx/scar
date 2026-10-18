# P4 中间检查点：不接收 RAW 参数的 helper 来源查询

2026-10-18，基线`d507a16`。这是P4共享来源查询的中间检查点，**不关闭P4**，
不替代原F12–F24/X25–X27分母或最终组件/冻结全仓门。

## 1. 从模型推出的具体缺口

```text
caller: 原RawRequest的operand[i] → 原Reference值
                                  → call actual[i]
                                  → helper formal[i]
                                  → 下一层call → 实际consumer Use
caller: 原raw anchor → 第一层call之前仍是当前来源
```

RAW是caller中的协议值；helper可能只需要普通Reference参数。不能为了查询
方便在实际helper签名中添加一个不存在的RAW参数。实际Use/Value/call/CFG
仍唯一，额外查询结果只是这些事实的派生recipe。

**Observed：**旧`request_input_binding`只额外接受“raw本身被该call传入callee”
的一层consumer_forward。原caller raw锚与只接Reference的helper之间，即使
确有准确原参数传递，查询也返回空binding。新原图通过ProgramIndex/core，
定向`helper-inputs/red001`真实1失败，原日志保留。

## 2. Implemented：补哪条关系

在原raw、raw operand、实际input三条recipe之间：

1. 保留相同完整caller context的原行为和旧consumer_forward字段。
2. 允许input的原caller链严格扩展raw caller链；第一下游call必须在该raw锚
   所属region，后续每层call/actual/formal均来自原input recipe。
3. 用同一ProtocolFlow检查该raw anchor在准确第一call之前仍fresh，缓存原
   `(raw OwnedUse, call OperationID)`的结果；缺预算不产生成功extension。
4. 原operand leaf、raw/input的同caller与CFG选择、evaluation freshness继续
   联合检查；不按None内容或同类型拼接。
5. 新view的`raw_context_extension`保原anchor/call/context suffix；不新增
   ProgramGraph表、producer/SSA、实参或schema，且request身份/变换权限为False。

这只表示**可能的静态参数来源**。同一组原参数被两个call使用时，查询保留
两个context；不能由此确定它们属于哪次request。P4的独立trigger/完整输入
tuple和实际P3发生对应仍须另核，不能把bindings非空当成运行请求身份。

## 3. Verified：必要定向结果

证据根：`artifacts/experiments/b1_call_operands/model_remaining_protocols/`。

| 检查 | 结果及意义 |
| --- | --- |
| 修前正例 | `helper-inputs/red001`，1失败；合法原graph，binding缺失。 |
| 修后本批 | `helper-inputs/green001`，22通过/1.00s。 |
| 新10例 | 1–3参数×1/2层helper；错ordinal、future pack、两可能caller；prepared index与真实预算截断。 |
| 旧12例 | 原request_inputs 6例与input_origin_pairs 6例；旧caller、内容不等于来源、预算及公开ledger保留。 |
| 独立只读审查 | `design/helper-review.md`有限PASS_WITH_SCOPE；未另跑测试。 |

上述22项检查的670注册源在测试前后均为：
`f69b01db0a09dbfe18fad36971f2f0a965edaad4859ec04f266ae0ecb248cb7f`。
随后只把必需leaf相等判定移到较昂贵helper检查之前，跳过必败候选；语义不变，
预算和诊断前缀可改善，原22项证据不冒充新指纹。最终必要影响范围包含新旧
input/request、generator admission、路由及先前预算确定性回归，实际
**112通过/10.09s**，`helper-inputs/final-focused001`，源码前后稳定为：
`57f379702ce1efc59ad9a19ed6530f05a80304c1959267f315cd46047b226d2b`。
独立复审保原记录并追加此移动的范围说明，未自行运行测试。
此前99 fixtures未改，新增一份通用helper原图，共100；测试数不表示模型覆盖率。

## 4. 尚未验收与后续

- 当前不是整个P4的组件/冻结全仓结果；按[P4计划](M1_REMAINING_PROTOCOL_PLAN.md)
  在三组协议集成后统一验收，不为单个函数重复完整回归。
- 原scope/provider库存、native语义、动态request身份和数值内容均未由此证明。
- P4共享合同继续收束精确expected来源、完整tuple分支、parent resume、async
  association/session与cancel target；不新建调度器或任意图约束语言。
- 不增加detector/backend、LeWM规则或重型profiling；没有新的LeWM加速结论。
