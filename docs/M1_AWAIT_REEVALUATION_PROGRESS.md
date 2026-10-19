# N4：获取发生与流程重求值的验收记录

2026-10-19。基线 `2dd97caad70884a8224427aed15614b71d6491c7`，开始时工作树
干净、远端同步；实际重核上一1807项归档及保护仓库。整个开发目标仍为active。
[冻结计划](M1_AWAIT_REEVALUATION_PLAN.md) SHA
`ac705fa754012e4c42422503cbe19d9701899a4bc8fd885af6051a6762dfc46a`。

## 1. 本轮解决的模型问题

五实体仍为 **Operation / Value / StateLocation / Region / Resource**。
Operation是静态操作定义；一次执行有独立occurrence。共享对象身份不合并
两个获取结果；原数据copy路径、own结果端口、状态版本及动态访问次数分别保留。
这是前后端都应遵守的连接规则，不按LeWM/变量名/测试标签选择例外。

**Observed**：同一static Get实际执行两次，结果均指向同B时，原实现可能
同时匹配Get0/Get1。另一完整反例保存Get0的结果，即使Get1较晚执行，实际
iterator仍来自Get0，而state来自Get1；按“最新一次”选择同样错误。

**Implemented / Verified（局部）**：沿actual iterator的原copy ancestry，
找到该source的准确own-result边界。不能穿过identity callee Return后仅按
共同B root选源，也不能把landing中的forwarded旧值当该Get自己的结果。
缺本次selected transfer/Use/call/Return时保缺证，不借另一获取补位。

原静态current-copy=False与可明确声明的历史carrier分开。仅对已有own
OperationResult/InvokeLiteralResult和独立Reference BlockArgument，原历史
recipe确实经过carrier且carrier到actual准确copy时，保条件None、原False及
全部recipe/freshness。它不证明动态visit，也不放宽method lookup当前性。

## 2. 循环条件与消费图

**Observed**：静态选中的后一次loop incoming会抹去初始entry；把同一分支
不同时刻的选择压成一个tuple，也会让真实已执行source从may库存消失。
这会丢掉实际final consumer和嵌套E/F，甚至误报payload/state错接。

**Implemented**：基于原CFG确认循环，保原choices、必要source prefix与原
binding。仅为条件may库存释放已确认的循环选择，保所有独立acyclic选择及
own completion edge；候选还必须恢复原source点。该库存不提供must seeds，
不能声明总库存/证明完整，更不能授变换权限。准确actual copy可以在实际
occurrence层单独验证，静态多visit适用性仍明确标为未证。

动态incoming guard只停在准确merge；不能被同一static branch较后的另一
successor抢先否定。同site wrapper constructor只接本次constructor的真实B
operand。选中Return路径的joint只排除准确selected=False目标；原未选目标
仍在库存，True/None目标继续承担证明义务。

## 3. 新增38项的准确分母

两作者只写两个新unit文件；root独占产品修复及所有解释器。每次运行前作者
冻结，不并发修改。旧tests/fixtures/contracts/codecs逐字节保留。

| 新文件/范围 | 节点数 | 实际检查 |
| --- | --- | --- |
| source_visits：两次Get | 2 | latest/earlier各选择准确own结果；一个Create/B/Start，Get1状态保持当前。 |
| source_visits：局部缺采 | 4 | 缺Get1 operand/selected transfer/call/Return Use，不借Get0。 |
| source_visits：预算、detach | 2 | budget1与实际完整成本一半；保anchors/分母/cursor，重查不受修改影响。 |
| source_visits：历史桥边界 | 3 | 原False及history保留；port预算耗尽；unsupported OwnedUse不进入历史搜索。 |
| source_visits：控制反例 | 2 | 确认loop历史歧义为None，独立acyclic冲突仍False。 |
| pipeline：完整主体 | 12 | self/general/W × 零/两cut × 真BodyReturn/BodyRaise；每格两轮同caller/newB。 |
| pipeline：第二轮缺采 | 8 | Get/helper/W inner/E/F/observer payload或state/Resume/terminal，不借第一轮。 |
| pipeline：旧Create拒错 | 1 | 原core错误body_creation_reused；不能冒称协议层新拒错。 |
| pipeline：共享预算 | 2 | 固定budget1/128的有限截断，保anchors和原outcome分母；128不冒称实际一半。 |
| pipeline：detach/fresh | 1 | 结果修改与新external catalog分离。 |
| pipeline：删除links | 1 | 删全部AwaitBodyLink仍保两轮advance与原outcome义务。 |

12格真实重执行都在原Get caller内形成backedge；不是外层循环反复调用新
caller。每轮有独立Create/B activation、source/driver/child调用和observer。
原terminal ID/Use/fullslot移至真实exit，第一轮不能先执行terminal再继续。
BodyReturn两轮E/F各选own N、R；BodyRaise走B的真实packet，不要求假E/F。
self两cut为direct NEXT→Get→await SEND×2；general为ordinary GENERATOR
全await；W为native COROUTINE、W≠B的wrapper路径，不能按三个布尔标签
当作相同控制图。native/self其他完整来源格仍按其原A/D/F等合同单独合账。

## 4. 原始失败与诊断

证据根目录：
`artifacts/experiments/b1_call_operands/model_await_reevaluation/`。
每次保command/stdout/stderr/JUnit及source before/after；不覆盖失败。

| attempt | 实际结果与解释 |
| --- | --- |
| c1-first | 1F；本轮已选child全部copy为True，准确未选HostTerminal的None却污染joint。 |
| c1-target-fixed | 1P；仅排除准确未选目标的joint贡献。 |
| a4-first | 2P/2F；真实Get0/Get1混选；earlier静态拒绝。另核出两项新测试metadata不适用。 |
| a4-metadata-corrected-boundary | 3P/1F；纠正RAW NEXT与真实save consumer后，earlier余currentGet硬要求。 |
| finite36-first | 13P/23F；历史桥进入实际查询，但loop入口与部分作者API/denotation假设仍错。 |
| finite36-guard-entry | 21P/15F；two-cut规范图有效；原case多项库存与动态incoming/constructor错接继续诊断。 |
| finite38-occurrence-guards | 28P/10F；准确source已能匹配，final consumer仍被静态loop选择删掉。 |
| finite38-inventory-bridge | 37P/1F；全部25 pipeline通过，earlier实际一半预算误报final state矛盾。 |
| budget-join-repaired | 2P/1F；控制收据存在仍不足以修复candidate内部耗尽的分支。 |
| budget-candidate-cut-fixed | exit4/0执行；root写错CFG selector，不能记为通过。 |
| budget-candidate-cut-verified | 3P；原failed预算例与两个acyclic控制反例通过。 |

首红后作者修正仅新文件中的不适用假设：primitive BodyRaise无terminals字段、
wrapper B operand需独立denotation、旧Create有准确core错误、缺operand不
抹掉仍可见own结果、多个static case应按实际selected occurrence选取。
不改旧fixtures、不删失败分母、不捏造缺少的引用身份。

三个diagnostic exit1保留：join-inventory记录真实静态hard rejection；
mid-budget先输出真实issue后其打印器遇ValueID键报TypeError；budget-scopes
先输出收据后误取未使用cache报KeyError。它们不是验收通过。后两项新的
state-budget-exact/membership诊断均exit0，确认真正剩余bug：candidate flow
内部耗尽预算，返回conditional=True/before=None却无pending；上层遂回退原
False。不是“scope不存在”，只读审查此前的另一假设不得当成本例实测根因。

修复只在candidate返回后转unfinished；只有本query已建立的精确
(operation,phase,edge,originalguards)控制收据可保pending None。收据不含
Value、seed、membership、bounds或flow；原flow仍执行并保原cache hooks。
原False嵌套保留；未证明的预算工作不授True、完整性或授权。

## 5. 最终受影响回归与原范围

**Verified**：`verified-final`实际1845通过、0失败、0错误、0跳过；pytest
706.87秒，命令包装总时707.8808秒。853份源码前后SHA一致：
`908182cfa79d2fb0609c6747fb4b96fe83a202949af3cb5dbd3e940a1b97da92`。
最终归档另核全部原1807准确JUnit identities保留，新增38项仅来自两个新文件。
这是affected focused，不冒称新组件/全仓或LeWM性能数据。

本门不改变Program23/Execution8 wire/codec及冻结合同。G/F17/F21/F23原结构
验收保持。完整回归后另按原条款逐项核对selector、关键断言、同源JUnit，
经[独立E/H原范围验收](M1_AWAIT_ORIGINAL_SCOPE_ACCEPTANCE.md)关闭这两条
M1条件结构行；不是因新增38项都绿自动关账。预算1、真实reexecution、当前
state、旧来源拒绝、snapshot/fresh/detach已有准确证据，不再扩成无穷乘积。
原A/B/C/D/F、其余十三家族、P5与M2原113构造/196字段仍为剩余工作。
F15仍明确缺普通generator被误授direct/self await资格及另Drive adapter结果
替换的两个准确反例，不能用反向general资格拒绝或错误O关联冒充。

阶段口径保持：M2是分解合同，M3是自动建图，M4是实际采集对应。供应图上的
结构连接既不能代替自动整程序恢复，也不因自动采集尚未完成而重开已证M1。
本轮无新detector/backend、native/GPU/LeWM实验，无新TRANSFORM或加速比。
完整M0–M2齐备后，按用户要求先停下讲解模型。
