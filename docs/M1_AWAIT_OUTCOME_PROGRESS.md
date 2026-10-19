# Await失败与资格检查：进度验收

2026-10-19；基线 `2fc957192e710d1db1210c7b7a1073313f2e16d6`。
本轮延续 [完整单位计划](M1_AWAIT_OUTCOME_PLAN.md)，状态为 **PROGRESS**。
完整A–H、原F12–F24/X25–X27十六组、P5、M2原113构造/196字段及M0–M2
全部仍OPEN。以下是供应IR的连接验收，不是任意Python或LeWM自动恢复全图。

## 一、模型上的决定

Operation / Value / StateLocation / Region / Resource五类实体未变。
获取、资格检查、分支、推进和异常构造仍是原Operation；候选、bool、iterator、
body handle和whole exception packet仍是原Value的角色。所有连接沿原Use、
state SSA及CFG边派生，没有新增producer、可写控制边或第二份数据身份。

原完整CFG可以同时保留接受和拒绝分支。对某个准确来源，在固定资格检查的
声明合同下，接受分支可能不可行；这不使整个静态Program非法。若实际capture
选择了不合格输入的接受分支，则是合同矛盾。这一决定见冻结
[D3补充合同](M1_AWAIT_QUALIFICATION_CONTRACT.md)，没有宣称验证native实现，
也没有赋予优化权限。未知来源仍未证明，不按不可行处理。

## 二、Observed：真实失败与最后回归

每次独立命令、全日志、JUnit和前后源码清单保存在
`artifacts/experiments/b1_call_operands/model_await_outcomes/`。以下attempt
属于各自源码指纹，不能相加为当前源码的全仓结果。

| attempt | 实际结果 | 说明 |
| --- | --- | --- |
| first-failure-paths | 2P/4F | 两处新测试API错误；另两处在同一旧Program的合法false→TypeError capture前被静态拒绝，暴露合同/oracle冲突。 |
| first-qualification-contract | 15P/0F | 第一版D3与准确失败capture的定向结果；不属于最终字节。 |
| red-declared-bool-conflict | 1F | 原core合法，自己的bool literal与固定检查结论相反；临时实现没有报矛盾，修复前证据保留。 |
| red-unrelated-qualification | 1F | 无调用关系的旁支检查错误掩盖原不合格返回的硬拒绝；临时实现缺口，修复前证据保留。 |
| qualification-boundaries | 24P/0F | 三值判断、literal、旁支及失败路线的边界验证；在最后一处过滤顺序修复之前，不归给最终字节。 |
| accepted-focused | **1454P/0F/0E/0skip** | 原1437精确caseID全部保留，新17；768源前后固定。受影响定向，非组件/full。 |

最终源码SHA为
`f72dfd47d874a1e1927966bb12a384577f9b3325ccc17b09f573a0be1312eac6`；
pytest118.86s，runner119.87133851740509s。这些是测试时长，不是workload性能。
新17项为failure静态/执行6、qualification静态/执行10、无关旁支边界1。

## 三、Implemented / Verified：本门连接

- 静态qualification视图按独立expected→本次input、原来源case、own bool与
  branch polarity派生True/False/None；自己的准确bool literal若相冲突仍拒绝。
- 已知坏候选只有被准确检查、准确调用返回、准确iterator及原控制边共同保护时，
  才能保留为条件下不可行的成功腿。用原入口删接受边后的可达性核旁路；不能
  先假定接受再证明它控制成功。相关原正常出口不能为空。
- 无调用关系、已知不匹配或有旁路的检查不能提供豁免；相关未知输入/路径保
  具体gap。原case和成功/失败CFG仍在库存中，未按某次实际选择删除。
- Execution独立从本次候选input与准确Create lineage核资格，从own bool的
  实际branch或own INVOKE N/R核选择；不靠后续Drive反选expected。实际错误
  接受即使没有捕获advance/BodyDrive也报矛盾。缺采仍是gap/未查计数。
- 新真实capture覆盖lookup RAISE、方法call RAISE及资格false→TypeError；保持
  原正常CFG、Get RAISE、精确callee调用与实际无advance/BodyDrive的事实。

查询使用同一context/shared budget，原raw索引只准备一次，结果经原公共接口
分离返回。Program23、Execution8记录与codec未变。没有新增detector/backend。
有限独立只读复核的风险、修复及最终SHA见证据目录 `independent-review.md`。

## 四、唯一旧测试输入迁移

`test_general_await_known_generator_coroutine_cannot_continue_as_iterator` 保留
原caseID及“坏返回无合法检查不能继续”的issue断言，输入改为准确去掉typed
qualification附件的图。原candidate、正常CFG及advance没有删。
这是D3合同下的显式迁移，不宣称所有旧tests字节未变。

旧文件完整字节存档为 `original_test_program_await_general.py.txt`；归档门逐字
复算这一处替换，并要求其余所有已有tests/fixtures与基线一致。新独立测试验证
qualified静态有效、实际拒绝合法、实际接受矛盾，以及untyped/错bool/bypass
仍拒绝。原D0/D1/D2合同和上一门归档字节保持不变。

## 五、原验收仍缺什么

1. **失败packet/state/consumer。** 本轮证明实际失败能保留和准确选择，不等于
   qualification bool false对应的完整whole packet、各slot状态及caller consumer
   都已连接。该路径不能被简化成“看见TypeError标签即正确”。
2. **最终结果链。** 从原BodyReturn到已有StopIteration适配NORMAL、whole packet、
   本advance RAISE及准确caller最终提取/consumer的独立库存尚待完成。删除整个
   final adapter仍须保原consumer义务；构造自己的RAISE、BodyRaise及中途handoff
   必须分开，不能统称completion。
3. **原组合与分母。** 三路source、零/多cut、W/B、同B direct/await、跨caller、
   当前state、mixed来源、INVOKE检查及反极性bool、缺整附件与budget1的原总数/
   checked/pending/cursor仍需按原A–H逐格验收。新17测试没有替代这些格。
4. 原16组全齐后才组件与冻结full；之后P5和M2原清单。历史5822 full只归于
   `81389862ee3f1dfe88c59f74ca1bfeff732779ff`，不移用到当前768源。

下一步仍按原计划补失败完整端点与source-first最终consumer视图，先冻结合同、
保真实首红、有限独立审查，再串行验收、归档及commit/push。没有新LeWM
profiling/benchmark、变换或加速比；两个受保护原仓库保持原HEAD及干净状态。
