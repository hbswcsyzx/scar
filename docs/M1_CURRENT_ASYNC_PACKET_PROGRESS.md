# 当前scheduler异常包与同请求重用：证据报告

有限范围与原验收分母见 [冻结计划](M1_CURRENT_ASYNC_PACKET_PLAN.md)。起点
`9293836d75e9c1d9a64849749d1b8b92529908b1`，上一门1854相关测试和旧档案保留。

## 实际首测

`model_current_async_packet/first-scheduler`：7例，4失败/3通过，无error/skip；
858源码运行期间稳定，hash
`f5e91daf76adbc900d0dc47f73ede5a75933e8bcdaab2bbb2d640d2bf0df8b6f`。

- **Observed**：两条完整core有效后续THROW/CLOSE供图，S producer到当前
  scheduler及normalizer raw、ownN到实际THROWN_PACKET、ownR到自己的RAISE、
  两个出口完整poststate逐槽绑定均通过，公共delivery却仍为None。
- **Observed / test-oracle defect**：两错L反例首先停在独立跨region
  `source_binding(S producer, L raw)`返回None的断言，尚未到公共拒错。不同
  producer不能自动推出不可复制。修正仅使用独立的原interface S entry
  BlockArgument→raw同region绑定核错源；公共拒错要求和原core图不弱化。
- **Implemented**：保首次L路径；后续S联合核entry S→helper raw、entry
  S→本Drive S、独立原recipe origin→本Drive S、recipe上下文和ownN→当前
  packet。不能从future Drive Use向前绑helper，也不能取多route任一成功。

## 第二次实际失败与局部修复

`first-combined`：11例，10通过/1失败，无error/skip；858源码稳定，hash
`8ebba57711dc1d920fe95341355053082948cd40c995bfb11e21cbbc8a3c4e3f`。
两条S正例、两条错L拒绝、两条删除附件、tiny budget及三条完整reuse供采通过。
唯一失败是新的候选扫描预算反例：N候选已True，下一R候选扫描扣费失败后，
整体仍True。反例保留完整原N/R图，不伪造第二normalizer。

**Implemented / Verified locally**：共享budget截断时保留已查局部收据，
整体降为None；原budget gap/cursor保留。`corrected-local`的62例全通过，
858源码稳定，hash
`1855d15c876ec76e2992abe27dfe8bcc58de2852c5f0b57692d278952f47047b`。
旧首次L归一化、后续NEXT/SEND、request admission包括在这次局部回归内。

## 同一R实际调用记录验证到哪里

NEW三例使用一个R Create、一个外来且已suspended的B。首次实际BodyDrive
产生COMPLETE post，经host RAISE/catch/context RW将最新状态送入第二call。
同一静态READ在两个activation内有各自bool occurrence和选择的边。第二call
分别覆盖拒绝helper自己的NORMAL/RAISE，准确packet和全部状态送到自己的
caller RAISE，不建第二BodyDrive。删除第二CallActivation时，其原call仍为
MISSING，首次COMPLETE收据不会借给它。两条正常链及缺采链实测通过。

这些是**人工构造的完整供图/供采**，用于核公共模型连接，不是自动采集到的
Python/native运行，也不把供采选中的第二True解释成推导所得。B的创建来源
保持Unresolved，没有造B Create来绕过缺口。

## 最终验收

**Verified，affected focused范围**：`verified-final` **1865通过 / 0失败 /
0错误 / 0跳过**；pytest723.66秒，wrapper724.6311825159937秒。858源码hash
`1855d15c876ec76e2992abe27dfe8bcc58de2852c5f0b57692d278952f47047b`
运行前后相同。原1854精确JUnit身份保留，新增仅S8和R3；原测试/fixture逐字
保持，全部原源码仅 `scar/ir/program/protocol_async.py` 变化，无新wire/schema。

| 尝试 | 通过 | 失败 | 源码稳定 | 用途 |
| --- | ---: | ---: | --- | --- |
| first-scheduler | 3 | 4 | 是 | 来源真实缺口 + 独立oracle错误 |
| first-combined | 10 | 1 | 是 | 完整S/R子证据通过；预算前缀真实失败 |
| corrected-local | 62 | 0 | 是 | 修复及旧L/NEXT/SEND/admission局部回归 |
| verified-final | 1865 | 0 | 是 | 同源码全相关回归，非组件/冻结全仓 |

**S1–S3通过**：准确S来源及ownN packet可连接；同kind L替换在core合法图上
由公共validator拒绝；缺normalization附件保delivery/definition和unknown；
tiny budget保原inventory，末候选扣费失败保局部收据而整体None。
**R仅连接子证据通过**，下一bool的内容推导未通过也未实现。

root独占串行解释器；所有协作者在每次运行前冻结。独立只读复核的产品/测试
SHA存于 `independent-review.json`。环境为既有 `lewm` conda，无安装/升级。
本表耗时是建模测试时间，不是LeWM性能数据。

归档在 `artifacts/experiments/b1_call_operands/model_current_async_packet/`：
每次原command、stdout/stderr、JUnit及前后源码表保留。三份历史变更源码文本
逐字对应当次已存hash，其余源码对应最终版本，四次运行858个原路径均核对。
`checkpoint.py --check` 不启动测试，核原1854身份、旧源码/档案、原完整台账、
精确历史源码重建、独立审查SHA与受保护仓库。该报告本身不把原条款缩减为
本轮子测试：原16组及P5/M2台账保留，已核子条目在本报告单列。

## 仍然不成立的结论

完整供采的COMPLETE→同R第二call拒绝链，不能自动证明native状态真值。当前
session post和局部predicate之间还缺跨调用状态内容派生关系，详见
[下一有限门](M1_COROUTINE_PHASE_NEXT_GATE.md)。F14/F16原完整族、其余八族、
P4组件/冻结全仓、P5和M2原113构造/196字段仍OPEN。A–H和原已验六族保留。

本门没有backend、LeWM特例、自动全程序恢复、可信TRANSFORM或新加速比。
