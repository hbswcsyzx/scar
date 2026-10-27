# Await来源与原A–H/F12/F13/F15结构验收

2026-10-19，基线7aee713c1b700f504ba3ebb8606fa2a4456c4e1c。
**Verified：原await A–H条件结构范围及F12/F13/F15通过；F17/F21/F23保持。**
最终同源1854通过、0失败/错误/跳过；全部原1845准确identities保留。
这不是整个P4、M0–M2或自动整程序建模完成。

## 1. 模型没有增加业务节点

五实体仍为Operation / Value / StateLocation / Region / Resource；本轮不改
Program23/Execution8 wire/codec。获取调用、原own结果、有序Use、状态post、
实际发生及精确内容声明保持各自身份。所有新例都用已有原端口与关系，不
需要LeWM规则，也没有新增backend/detector。

两个返回相同类型的结果不能凭类型互换。一个原producer的NORMAL结果可以
有精确内容声明，但原call、effects、allocation及状态仍在；已知内容也不
自动等于已知对象身份或可删除该call。这些是将来图化简所需的连接与知识
边界，尚未在本轮执行优化。

## 2. 新增九项及唯一产品修复

| 新增范围 | 节点 | 准确证据 |
| --- | --- | --- |
| self/direct资格 | 3 | GENCORO完整Get→Drive→final N/R；ordinary GENERATOR普通NEXT合法；同完整图误获self-await资格准确拒绝。 |
| 另一Drive结果 | 2 | 同原caller两个真实Create/B/Drive，经各自conversion和final OutcomeAdapter；foreign ownNRef支配current final。仅替换payload后core合法，foreign binding=True、current=False、full final_copy拒绝。 |
| native self/noW | 1 | native COROUTINE单Create零cut完整图；无W/getter，按新Program重建caller/D/B/E供应捕获，核准确packet、ownN与当前state/final consumer。 |
| general返回COROUTINE | 1 | 原method call ownN/handle→advance保留，仅known body kind变COROUTINE；core合法、准确return_qualification拒绝。 |
| general返回builtin | 2 | 同ownNORMAL端口的LiteralEvaluation与knowncallee literalReturn两种已有表示；各自分类完整NON_ITERATOR。opaque格同节点另核UninterpretedConstant保持UNKNOWN、全图合法。 |

前两文件首测分别3P/2P，现有产品正确，无需改代码。第三文件首测3P/1F：
native、knownCOROUTINE、knowncallee builtin通过；ownN精确builtin的分类器
已返回完整NON_ITERATOR、current=True，整图validate却无issue。

**Observed**：_legacy_qualification先按“非Create且无callee”跳过结果，导致
已有知识到不了资格规则。**Implemented**：仅扩此fast筛选，按完整原
result port查现有共享LiteralEvaluation索引，仅精确PythonLiteral可进入；
没有精确内容或UninterpretedConstant仍原opaque路径。其后must-copy、原
source classification、typed qualification/reject保护及共享预算检查全部
沿用，没有“见literal就全图报错”。四项复测4P，未知控制通过。

此改动共一个产品文件的小范围diff；不是把“模型没表示”与“检查没用到已有
表示”混为一谈。新源码需一次统一受影响回归后才能授原范围验收。

## 3. 原A–H逐条的证据入口

原依据为未修改的M1_AWAIT_ACQUISITION_PLAN、M1_AWAIT_COMPOSITION_PLAN
第2节；完整selector、实际参数节点和原合同SHA由机器审计JSON保存。root
与独立只读审查核关键断言，不以测试数量或source/native=False替代原要求。

| 原行 | 原要求及准确证据 |
| --- | --- |
| A | 三路来源/正确资格。新native self/noW补缺；GENCORO self与direct/await由resume及本轮qualification核。general的普通GEN允许、GENCORO/COROUTINE/builtin禁止成功推进分别有准确负例；unknown不当known bad。 |
| B | lookup→call→qualification的原正常与失败。general、outcome_failures及execution_outcome_failures核各stage own边、真实CallActivation、当前packet/state→Get R；wrong receiver/bool/bypass/parent slot、缺helper/删除/预算均有原selector。真实bool+BRANCH的Q不伪造不存在的INVOKE R。 |
| C | 零cut首advance完成、准确提取及异常。program_await_outcomes ownN/R与execution_await_outcomes的精确packet/final、extractor ownR/constructor failure；错同型输出、缺Use、删metadata仍留消费者。 |
| D | 两cut持续B、准确恢复及最终值/异常。program_await_outcomes的HANDOFF不冒final；execution_await_general_final逐三Drive/ResumeIngress/transfer及E/F全slot。四种原非state恢复slot、旧state/Resume、另一caller输出、缺transfer/child及预算均已有准确入口。 |
| E | 上一门原范围验收保持：同GENCORO B direct/await、多Create及旧Resume/Drive/state、真实重执行。 |
| F | program/execution_await_wrapper及wrapper_final核原constructor/getter、W≠B、独立expected B、准确Drive/ownN/R；错误scope身份/constructor/result/state、缺owner/call/getter与预算保原义务。构造器内部所有实现与C1无限乘积不是原F。 |
| G | 上一原共享输入、真实copy-loop、准确caller/全tuple矩阵保持关闭。 |
| H | 上一原shared budget/index/flow、分母/cursor、bounded copies、fresh/snapshot/detach/reexecution及无capture不假报预算不足的验收保持。 |

本轮是供应模型上的条件结构验收。native正例重新构造了准确capture，没有
执行真实native探针；没有由换kind/profile或引用名字宣称语言实际已验证。
原语言适用/来源、运行身份、值身份及变换许可分别仍为False。

## 4. 原家族F12/F13/F15与剩余范围

| 家族 | 完整原义务怎样合账 |
| --- | --- |
| F12 | A来源/资格与B lookup-call-检查、正常和各自失败；native self及精确bad返回补原缺项，错源/缺失/预算保义务，不要求每来源乘每cut。 |
| F13 | D的每次handoff→本次body恢复→最终表达式，以及C准确normal/raise slot；错state/其他child/漏转移与缺采反例齐备后才关。 |
| F15 | 同GENCORO准确direct/await结果、wrapper原B关系，加本轮两个确切负例：ordinaryGEN误资格和另一Drive真实adapter结果替换；不再用错误O关联/helper结果冒充。 |

F17/F21/F23保留；其他十组为F14/F16/F18/F19/F20/F22/F24/X25/X26/X27，
原16组分母不变。完整P4组件/冻结全仓、P5、M2原113构造/196字段仍需完成。
不能把这里的await A–H闭合写成整个M0–M2或任意程序自动建图已完成。

下一门只读审查已具体化F14/F16缺口：native coroutine的phase真实branch/
重入/完成后reuse/THROW-CLOSE当前结果与旧callback谓词；async request的
COMPLETE后复用、R1/R2竞争B、初始ASEND联合条件和后续scheduler packet。
同R/B三次真实stepping早已实现，不重新造这项基础图。详见下一门审查记录。

## 5. 运行与版本证据

证据根目录：
artifacts/experiments/b1_call_operands/model_direct_qualification_and_foreign_result/。
每次command/log/JUnit及源码前后清单保留，包括真实3P/1F首红。原1845
选择及全部旧test/fixture/codec/合同/归档字节由checkpoint逐项核对。原设计
与计划不改；F12补充/内容来源澄清有独立SHA和amended selection。

`verified-final`实际pytest713.98秒，命令总时715.0721124866977秒；856份源码
前后SHA一致：
fd1069cea62d96ed451b0cedc8ae8c644add212e5ec8f31a6982a8eac86bfed6。
`original-structural-accepted`实际exit0、0.2593秒，逐所有原条款匹配非空实际
green JUnit identities并保存structural-acceptance.json，没有启动新测试。
checkpoint重算这些匹配、核原1845身份、旧字节/合同/codec和保护仓库。

LeWM原仓库保持保护；本轮无GPU profiling、TRANSFORM或
新clean A/B加速结论。M0–M2真齐后按用户要求先讲解模型，再进入原M3/M4。
