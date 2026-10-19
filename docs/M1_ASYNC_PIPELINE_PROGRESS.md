# P4 连续 async source/consumer/occurrence 验收

2026-10-19；基线 a5ff0f937015c225ba5d46c71bdc4e75866316d4。
依据 [冻结计划](M1_ASYNC_PIPELINE_PLAN.md)。本门限定结论 **PASS_WITH_SCOPE_WIP**，
仅适用于下述供应IR/执行记录组合。原16组、P5/M2和完整第一阶段继续 OPEN。

## 1. Observed：首先复现真实缺连接

原公开 validation 接口没有拒绝把 AWAIT host RETURN 的 payload 改成另一个
ReferenceValue；删除整张 SessionUpdate 及其 AsyncSessionOutcome 后，原 AWAIT
仍在，但旧义务从消费者表出发，导致该 source 的消费者义务也消失。

首次测试错误地把 validate 的 tuple 当作 report.issues，属于新测试 API 错误。
修正为原公开返回合同后，两项均真正失败；不以缺少新字段充作产品首红。

| attempt | 实际结果 | 归属 |
| --- | --- | --- |
| red-original-async-obligations | 2F | 1项新测试API错误，1项真实来源分母缺失 |
| red-correct-public-result | 2F | 两项原公开接口的真实缺连接，723源稳定 |
| first-static-connected | 41P / 7F | 两首红转绿；7F均新fixture漏import OperationResult |
| first-pipeline-connected | 16P / 12F | 新fixture分支ID遗漏重命名及Suspend私有入口违反core |
| repaired-canonical-pipeline | 26P / 6F | main及初始执行组合通过；4项shared上下文夹具不合法，2项新测试API错误 |
| original-ports-and-session | 18P / 1F | shared/main/helper真实N/R通过；遗漏后缀变体误用InitialEntry.point |
| scoped-session-evidence | 4P / 0F | scope、R/B scoped identity、fresh catalog及缺实际update occurrence |
| final-focused | **1308P / 0F / 0E / 0skip** | 原1032项+本轮22项+254项相关旧P3/CALL/codec覆盖 |

上述各次原命令、JUnit、日志及源码前后清单均保留。夹具问题已按
原类型/控制/端口规则修正，不放松原 validator。不能把未到达产品查询的新夹具
错误写成产品 bug，也不能把一个测试首红的多次复跑累加为新增覆盖。

## 2. Implemented：同一模型中的连接

五类实体 Operation / Value / StateLocation / Region / Resource 保持不变。
静态 source inventory 从原 Drive/outcome 边派生，再核 first post、R/B 和当前
state 的相关 tuple；缺 update 不删 source，shared incoming 不任选成功路径。
AWAIT 原 export 到 host RETURN 按该来源的准确 choices 核对。旧 update 收据保留。

执行视图复用原 Drive occurrence、ControlTransfer、BlockVisit、activation 与
segment 定位本次 update 和 host。新增端点加入既有 CFG/CALL/body copy 祖先
闭包，再由 fresh scoped identity 校核，未复制另一份 SSA/phase 图或 Tensor 数值。
本地 state receipt 保原 State UseOccurrence 和准确前/后态，scope 逐项保分母。
只在准确 NORMAL 后授 helper 的声明 post，RAISE 保自己的 packet/partial state。

同R/B三CALL图中，R完成和B暂停分别表达；item adapter 可以最终 RAISE
StopIteration(item)，没有编造NORMAL。该图是供应 IR，不是已自动恢复的源码。

## 3. Verified：自主统一验收

root串行、conda lewm / Python3.14.7。最终1308项在728源固定指纹
`4d0da6cdd5537ae26a99e7da2945ce553395dd6cba350fc2009d9cc8a4e948e4`
通过；pytest90.09s，runner91.13712089322507s。前后指纹相同。1032项既有case
ID及原义务全部保留，无旧测试断言迁移；新增三个文件共22项，另254项旧覆盖。
这些是验收成本，不是LeWM运行时间或加速比。未继续做可选复跑。

已验：同一B/R、三个独立driver activation、一个B activation/三个segment，
准确ResumeIngress及host/item；共享HOLD的两条原incoming；missing whole update/
attachment/occurrence/state/role Use；错误旧Suspend/Use；helper实际NORMAL与RAISE；
scope缺一不借另一；原Use/Value/CFG不变的同artifact R/B ObjectID冲突；catalog
变动后的fresh查询和旧收据detach；budget1保分母并mask未核copy/compatibility/post。

独立源审发现的typed端口、缺采state、scope三项风险在首次动态验收前修正，不能
冒作旧产品实测bug。同ObjectID/protocolkind与source-copy证明分开：新增端点必须
有原CFG/CALL/body祖先连接；无连接保copy_unproved。准备及fresh比较次数另列，
使用原共享查询budget，不在新session层重置，public结果只在原出口统一detach。

### 自主关卡

| 门 | 限定结论 |
| --- | --- |
| D | 冻结计划、三路源审，原实体/端口/SSA/wire足以表达本组合，无新canonical record |
| R | 两项原公开接口真实首红已修；全部原失败证据保留 |
| S | source先于update、共享incoming相关tuple、AWAIT handoff、遗漏/预算正反例通过 |
| P | 同R/B三真实CALL供应图及item adapter/partial state通过，无假NORMAL |
| E | 原发生/activation/segment、session/host、N/R、identity、缺采、fresh正反例通过 |
| V | 独立有限复审后冻结所有作者，1308 affected focused同源通过 |
| A | checkpoint核原case/fixture/失败日志/合同/wire与保护目录，commit/push另保revision |

Program1–22/Execution8、原model/codec及全部旧fixture字节不变；没有修改旧测试。
归档checker不启动tests/workload；不能把本轮attached source收据当成新的full。
历史5822 full仍仅属于81389862ee3f1dfe88c59f74ca1bfeff732779ff。

## 4. Rejected / Unproved 与下一阶段

source/native/runtime/value identity/transform 权限始终分开。即使声明路径完全连接，
也不等于 native 源码等价、真实运行身份已证、纯函数、可复用或允许变换。
已知R/B scoped identity和准确Use/旧Resume冲突拒绝；合法图中的缺消费者/缺采保
明确缺口，不能因没有观察到后继而认定dead work。终止R不等于终止B。

未支持的 body terminal host adapter、源码/native分类、缺采和预算截断保明确 gap。
post receipt只描述原 update 点，不暗示其可跨后续call保持；原session_flow失效规则不变。
本轮不跑component/full或LeWM，不增加detector/backend，不产生新加速比。

所有F12–F24/X25–X27原16组仍OPEN。本门只闭合连续异步来源/消费者/发生的
组合单位；剩余wrapper iterator→body projection、native/source分类、各family
normalization/handler/cancel和caller组合继续逐项验收。原分母齐后才统一component/
frozen-full；随后P5、M2原113构造/196字段，完整第一阶段后按用户要求停下来讲解。

证据：`artifacts/experiments/b1_call_operands/model_async_pipeline/`。
