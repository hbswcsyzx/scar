# 独立异常来源与 lookup fallback：有界验收

2026-10-18，基线 `8585d7f2aa013896fa58c3759d540338b78d43a5`。
依据[冻结计划](M1_LOOKUP_FALLBACK_PLAN.md)。这是原 P4 的连接补充，原
F12–F24/X25–X27 共 16 组全部仍 OPEN；不是整个建模阶段完成。

## 1. 从模型到代码

核心实体仍为 Operation / Value / StateLocation / Region / Resource。
方法查找、异常类型匹配、分支、pending 构造和 cleanup 都是原 Operation；
数据与状态通过原端口及 OwnedUse 连接，不新增第二份 producer、状态或 CFG。

```text
独立注入包 E0 ─────────────────────┐
iterator → lookup 自身 RAISE EL → matcher
                                  NORMAL bool → 原 BRANCH
                                      true  → E0 → 实际消费者
                                      false → EL → 实际消费者
                                  自身 RAISE EM → 实际消费者
```

**Observed:** 原公开 continuation query 只连接 EL 到 matcher，没有三种包的
独立 fallback 路径。`red-three-packets/` 是真实 1F：原 core 和完整模型合法，
已有 query 返回缺失连接；不是调用未定义的新 API。

**Implemented:** 复用 `protocol_bindings` 闭合类型集合：

- `NormalizedThrowSource(raw, packet)` 分开保留原 RAW OwnedUse 和独立整包。
  名称不表示规范化已证；不能扫描唯一构造器或从实际 true 消费者倒选 E0。
- `DelegateLookupFallback(lookup, matcher, request, guard)` 关联准确 lookup
  RAISE 与原 matcher。自然键包含原 lookup 完整 scope/clause/operation/slot、
  matcher 和 guard。lookup 仍是零参数、无 request trigger 的原查找。
- E0/EL/EM、三腿和各自 selected edge 从原来源/结果/branch 派生；调用不能
  以用户提供的“正确 routes”代替实际 consumer 分母。only-RAISE 没有假 bool/N。
- 相同 packet 类型不代表相同包。wrong E0、lookup NORMAL、同种 sibling
  lookup、EL/EM 互换、未来产生的 EM 冒作先前 E0 都保具体错误。

语言规则核对采用 [PEP 380](https://peps.python.org/pep-0380/#formal-semantics)
及 [Python generator methods](https://docs.python.org/3.14/reference/expressions.html#generator-iterator-methods)。
本实现检查供应模型中的关系，不宣称自动恢复了真实 native 操作。

## 2. 连接、上下文与边界

复用 prepared ProgramIndex、ConnectionContext 的 current-copy、caller/CFG
关系和独立 consumer ledger。每个兼容 receiver case 内核整个
raw/E0/receiver/EL/handler/bool tuple，再保留所有 case；互斥 case 不作一个
必须同时成立的 tuple。已有原输入库存继续负责全部 incoming 的分母。

`protocol_packet_routes.packet_frontiers` 是共享预算的原 CFG 查询：

- 逐原位置/边找到 host RAISE、parent packet slot 或真实 C1 action。
- 原 source、lookup、matcher 再求值、CFG 回边、不透明调用/未完备 effect、
  suspend、缺 consumer 和截断都保具体 gap，不把未看到 consumer 当空成功。
- C1 只检查 action 实际消费 pending token 的来源。死 pack 既不解除义务，
  也不因 payload 不同而污染 active pending。
- 合法 cleanup replacement 可以覆盖旧控制结果；fresh pending + Return/Raise
  不能单独证明其源程序适用性。报告 override support 的 applicability=False，
  并保 override/continuation 未证条件，不强迫 finally 后永远传播旧 E0。

所有新 route 都明确 `frontier_only=True`。C1 frontier 正确不等于准确投影了
PendingPayload、恢复了 saved context 或最终到达 host。原 X25 完整闭环未关闭。
既有 close route 查询的历史 DECLARED 也不能升级解释为完整 C1 dispatch 证明。

**Inferred/Proposed:** 类别测试为 AttributeError、注入为 GeneratorExit、原 RAW
规范化为 E0 都还需要源适用性/真实边界证据。FixedBuiltinHandler、FactRef 或
同型值不授运行时身份。所有 native/runtime/source verified 及 transformation
authorization 标志保持 False。没有增加优化 detector、backend 或 LeWM 特例。

## 3. 真实失败与修复

| 记录 | 实际结果 | 处理 |
| --- | --- | --- |
| red-three-packets | 1F | 实现缺失三腿连接 |
| first-connected | 23P / 1F | sibling 错接补精确 site 错误分类，保原断言 |
| repaired-packets | 24P | 当时源码的小定向，非最终结果 |
| red-raw-and-case-review | 1F / 1P | 普通 Reference 冒 RAW 被漏检；本地 OR 正例本来通过 |
| boundary-and-codec | 81P / 3F | 补 nested E0 局部 gap；修两项测试对原 fixture 的错误假设 |
| final-focused | 965P / 0F / 0E / 0skip | 初次冻结后统一受影响定向 |
| final-focused-repair | 965P / 0F / 0E / 0skip | 仅修新测试末尾空行后，绑定最终源码 |

RAW 修复先核已知原 operand 的真实 role，再解析 RAW 来源；真正外部 RAW 无
本地定义仍保 gap。OR 的本地正例没有复现语义误拒，不声称已复现并修复跨 callee
混合 caller 的全部情形；逐 case 实施及完整覆盖断言是结构保证，后者仍需组合验收。

边界首败中，两项是测试假设错：C1 actual 是原 pending 的转发 formal，不是相同
ValueID；原 failed-block JUMP 的 effects_complete=False 不能无条件穿过。修后
测试核准确 copy、直接从实际 C1 action 检查 frontier，并保原不透明路径边界。

只读审查还关闭了两个实现风险：bindings 一次按 lookup/matcher 建准备索引并
报告准备数量，避免逐 lookup 全表扫描；port 查询预算耗尽先截断，不能伪造
不合法 site。direct budget=1 回归验证此区别，没有提高原预算。

## 4. Wire 与自主验收

Program22 仅由新 fallback binding 能力触发；Program21 的字段和旧 tags 不变，
没有新图表。删除新 binding 回到原 family。旧 envelope 装新记录、去 tag 绕过
union、假升级、错误 namespace/shape 均拒绝；Execution8 未改。

独立旧21 oracle 使用基线 commit 的旧 encoder 子进程，归档仅 scar/tests/
pyproject.toml，临时提取目录已删除，source tar 保留。生成的 24,222-byte golden
SHA256 `59ef85f4b1d2c1981d15f0b1f4ce8987a026c95ca5e9dd37f666091334d184ff`。
旧2–21 golden 的原编码字节通过；旧 fixture 与历史证据另由 checkpoint 逐项核验。

三路只读复审后，所有作者冻结。最终结果：

- **965 affected focused**，旧880义务全部保留；878个原 case ID 不变，两个
  future-schema 参数 `[22]→[23]` 迁移；新增85。
- **713-source** 前后指纹
  `d98ca13fc57cbd97185ecdbf45ece875918d26f1b1dd7b8068e7b9d97805179e`。
- pytest **40.32s**；runner **41.12096674647182s**；0失败/错误/跳过。
- conda lewm，Python3.14.7，环境/LeWM 仓库不改。

证据目录：`artifacts/experiments/b1_call_operands/model_lookup_fallback/`。
`checkpoint.py --write/--check` 只校验档案、不启动测试；保存全部失败 case、旧880
义务、历史 fixture、旧计划、旧证据与两个受保护 checkout 的守恒关系。
初次965P及原 `checkpoint-initial.json` 保留；最终提交只采用修整后的新源码指纹。

**Verified:** 本门有界模型/连接和兼容性。**Rejected:** 已知错源、错包、错类别、
错 site/guard 和不兼容 tuple。**Unproved:** native/source、完整 C1/caller/组合
适用性、自动全程序恢复。原16组、P5/M2与完整M0–M2仍OPEN。没有新组件/full、
LeWM TRANSFORM、A/B或加速比；旧 full 仍只属于 `8138986`。

## 5. 下一步

继续原16组中的来源规范化、完整 packet/C1 projection/context/override、跨 caller
及各协议 family 的组合连接；逐组保分母与反例。全部就绪后才进入独立复审、
统一组件、干净 commit 和一次 frozen full，再推进 P5/M2 的自动建模验收。
