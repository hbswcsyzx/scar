# N4：获取结果发生、真实流程回边与当前来源

2026-10-19；基线 `2dd97caad70884a8224427aed15614b71d6491c7`，开始时工作树
干净、远端同步；上一节点1807受影响定向通过、原1793 identities保留，归档
前后核验与推送完成，是verified progress。原G/F17/F21/F23结构验收保持。
本轮承接[下一门审查](M1_AWAIT_REEVALUATION_NEXT_REVIEW.md)；完整目标仍是
原A–H、其余十三组、P5、M2原113构造/196字段，不以本轮局部矩阵代替全阶段。

## 1. 模型决定连接，不按时间选来源

五实体保持 Operation / Value / StateLocation / Region / Resource。同一静态
Operation可以多次执行；不同ValueOccurrence可复制同一B。对象身份、共同
copy root、一次获取的own结果端口及本次消费者的实际数据路径分开。

当前源码把候选先追到共同B root，可能让两个Get发生都匹配一次advance；
这是Inferred，必须先由完整public API例复现。优先复用原copy recipes和准确
selected completion/ordinal/landing，沿actual iterator找其获取结果边界，
不能穿过该边界把前一获取也当本次来源。不给任意同B或“最新时间”来源许可。
qualification输入和WrapperHeldBody保各自语义；不把本门改成全局root算法。

## 2. 同caller、同B、同static Get两次发生

A仅新增tests/unit/test_execution_await_source_visits.py，helper同文件。复用
原zero-cut/self Create→Get→Drive→constructor→真正E/F→最终consumer主体，
一个Create、一个B activation、一次Start/Return。Get用真实NORMAL-only
identity callee，按其实际签名供调用，不制造callee RAISE。

Get在原caller里经真实回边执行两次，每次独立CallActivation和own结果；所有
当前state从其准确fullslots回header，不能用旧state制造core非法图。首批：

1. latest：actual iterator来自Get1 own结果，只匹配Get1；原source库存仍2。
2. earlier：Get1较晚执行，但iterator来自Get0 own结果经previous carrier的
   原copy，必须匹配Get0。稳定ownerB种子不能冒充Get0结果，state仍用Get1。
3. 缺Get1 operand Use或selected transfer：保原keys/两source/advance及最终
   consumer库存；不借Get0填补缺证。Get1结果本身仍可见时可保候选，但不能
   把其输入/独立B桥当完整证明。

随后补Get1 call association和callee Return Use的局部缺采，必要的预算、
detach/fresh检查复用本图。所有缺采先保canonical/full/capture合法；更早的
core拒绝单列，不能伪报新协议能力。

earlier必须明确声明原carrier来源，不能伪称它是Get1的新结果。现静态
freshness刻意在同producer重执行时reset，保其方法lookup当前性规则。若
真实首红显示carrier被误当current Get结果要求，先修独立declared输入、原
历史copy与dynamic occurrence的准确桥，禁止整体松掉freshness、删earlier
例或捏造第二static Get。真字段阻断先写明，再讨论wire，不能先扩schema。

## 3. 真whole-pipeline循环，不用多个caller替代

C仅新增tests/unit/test_execution_await_pipeline_reexecution.py，helper同
文件。原含Get的caller Region本身加prologue/header及真实backedge；一个
caller activation/segment内重visit Create/Get/全部Drive/E/F/consumer。每轮
新Create对应新B activation；general acquisition helper、wrapper、driver、
E/F各轮有独立实际调用。原root外加loop CALL只会新建多个旧caller，不验收。

原terminal不能先执行再继续：把其原ID/UseID/kind/fullslot移至准确exit
landing，本轮own结果先由真实非terminal observer消费，再分支继续或退出。
continue传外部captures/sent/A及本轮current states回原header；不把旧B/W
送下一轮Start。exit传本轮payload/state到原terminal。原E/F N/R、B主体、
constructor保留；observer作为准确OwnedUse消费者，保HostTerminal库存。

先最小self/zero-cut/N完整例核供图和capture，再扩原self/general/W、零/两cut、
E/F own N/R的有限对照；不靠labels/ObjectID猜身份。两轮的Get、Create、B、
conversion、child、最终consumer全端口分别核，不只断列表非空。第二轮
局部缺Get/child或payload/state Use时不得借第一轮；错前轮Create/Drive/
Resume或过期SSA应归准确拒错层。H的shared budget1/中段、全缺采、detach/
fresh按原全链要求逐项合账，不以一个预算例宣称整个H完成。

本门C的有限主体矩阵为self/general/W × 零/两cut × BodyReturn/BodyRaise。
BodyReturn时两轮分别选真实E/F own N、R，不能用child R代替BodyRaise。
BodyRaise走B原packet→D/W→本轮consumer，没有构造/提取E/F义务。先验证
self零cut/BodyReturn最小供图，随后沿同一local构造器补其余有效格；某格若
存在真实规范阻断，保具体阻断与原义务，不能从分母删去它。

这不是direct布尔值乘三来源：self现图为GENERATOR_COROUTINE，two-cut已是
direct NEXT→Get→await SEND×2；general B为ordinary GENERATOR，全await，
其direct拒绝保原例；W为native COROUTINE，全wrapper，不能把W当B直接驱动。
native/self无W或B direct/W mixed若未供准确图，仍是各自原格，不改kind或
profile冒充。未采Ref identity时原final链可带body_reference_identity_unproved，
但准确selected/copy/fullslot端口可True；不为求整体DECLARED捏造身份事实。

原三来源/BodyRaise/失败/C1等组合若尚未齐备，保具体剩余selector缺项；本
节点不自动关闭E/H或其余家族。native/source/runtime权限False不能撤销已测
M1结构能力，也不能由供应图授真实源码自动恢复或优化权限。

## 4. 顺序、责任与验收

- 先独立只读审查原端口、原分母和schema，再冻结计划；A/C不交叉写。
- B只读复核原矩阵和具体产品差异，不写代码或执行解释器。
- root独占产品、文档、所有Python/pytest/probe/compile、归档和Git。每次
  作者全冻结后串行执行，保不可覆盖command/log/JUnit/源码前后清单。
- 最小完整例先实测；作者构造错与公共关系红分账。只修真实关系问题，不
  按case label/变量名/LeWM名称选择规则，也不改旧测试/fixtures/codec合同。
- 两作者有限矩阵齐备、独立复核后，一次原1807准确identities加新增的同源
  affected focused；核旧字节/合同/codec/归档和两原仓库HEAD/status，再
  checkpoint、commit/push及远端精确SHA。充分验证后停止可选复跑。

证据目录artifacts/experiments/b1_call_operands/model_await_reevaluation/。
不新增detector/backend，不跑native/GPU/LeWM实验，不存Tensor逐轮数值或
产生新加速结论。原M0–M2真正齐备后按用户要求先停下来讲解模型。
