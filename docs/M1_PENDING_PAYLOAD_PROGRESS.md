# Pending payload：通用来源与真实两cut C1验收

2026-10-19。基线 `cd25456357ec3e569d32ad246bd5890ef8fc628f`，依据
[冻结计划](M1_PENDING_PAYLOAD_PLAN.md)。这是原P4的一个连接检查点，不是完整
X25或M0–M2验收；F12–F24/X25–X27原16组仍全部OPEN。

## 1. 原缺口与此次修正

**Observed:** 原图已具有payload、pending构造、C1动作、dispatch和投影formal。
`ProtocolFlow._edges`将PendingPayload当非普通copy边；`input_origins`只能报告
动态pending未选中。结果是原图合法、两个分支都保存同一输入值，既有公开
`ProgramIndex.source_binding(expected, actual)`仍返回False。
`red-original-projection/`真实1F保留这个缺连接，没有用新API缺失冒首红。

**Implemented:** 不新增canonical实体或wire。仍是Operation / Value /
StateLocation / Region / Resource，以及原有Use、state SSA和控制边。

```text
原payload Use → 原PendingCompletionDefinition(token, port, payload)
  → 原token的Use/formal/SavedInput
  → 原C1 Enter / Resume或fresh Replace，另保context/current state
  → 原CleanupRoute
  → 原dispatch selector + selected ControlPort + PendingPayload位置
  → 原landing formal → 原RETURN/RAISE或后续真实helper
```

pending token不是其payload；同port不表示同payload；裸PendingPayload()没有
owner/edge/slot，不能作为独立expected source。图中的条件投影关系现在由共用
来源查询解释，不靠某个workload或函数名称，也没有新建producer/state图。

## 2. 两类派生事实各自表示什么

`pending_payload_flow.py`在同一query context中派生原carrier/ControlPort关系：

- **possible**：该原pending carrier在此原位置/边是否可能携带此port。原
  constructor为种子，原边同时rename，Route/Dispatch按准确selector/port过滤，
  用带bottom边的最小固定点。无实际来源不产生“空成功”。
- **support**：相对于本次独立expected source，此carrier的该port case所持
  payload是否来自当前source。构造时核原payload OwnedUse；同port的所有适用
  incoming必须支持，不同port先分开。must与may分别求解和缓存，may不授证明。

source再求值会清旧source-relative support，但不删除旧token的possible；旧token
仍可能活着，不能冒本次新值。constructor再求值只kill自身result；另一个carrier
持有的旧token可以继续保存一个未改变的独立payload。这两种情况不是同一规则。

这些是查询临时事实，不是新逻辑Value/producer或静态epoch。Reference/whole
exception packet才可作为语言Return/Raise payload；state、Data及pending-token
本身保原快速路径。新增节点/边/pair的工作使用原共享预算，准备索引数量另记。
既有known-call return、caller/guard和source reset语义继续使用同一fixed point。

这里的来源关系不证明Reference所指对象的内容不变，也不证明操作pure；原state
读写/effects和后续优化合法性仍须另核，不能因此直接cache。

## 3. Origin与跨helper闭环

`input_origins`追真实dispatch selector的原token recipes，再按准确selected
port取对应原PendingCompletionDefinition.payload Use。它保留：

- 原selector、port、edge/argument ordinal、landing formal；
- 原definition/constructor和准确payload OwnedUse；
- 原token、SavedInput、CFG及caller路径；
- `PENDING_PAYLOAD_PROJECTION` witness及其静态token current-copy诊断。

同port多个来源不任选一个；另一个port的来源不混入本case。静态cycle、非构造
来源、缺payload或预算截断仍进入缺来源分母和cursor。token_match不是运行时
身份授权，原动态cut/visit缺口仍保留。所有source/runtime/native/transform
权限位保持False。

真实三Region用例验证：root CALL H1（原pack→dispatch→RETURN）之后CALL H2，
来源继续连接到H2内部真实consumer；换成另一个同型输入不能通过。private pending
仍禁止作为CALL/INVOKE实际参数，没有为跨调用伪加token参数或新copy边。

## 4. 两次挂起究竟验证了什么

新文件复用旧fixture，不修改其原字节，并分别构造一个连通两cut图：

1. **RAISE路径**：原delegation cut → helper准确RAISE → 新packet进入fresh
   pending → 第二次Detach/Suspend/Attach → 原CleanupReplace → Route →
   PendingPayload → 实际host RAISE。packet只由pending保存，没有塞进VALUE
   slot；旧pending/replacement分别保存，context/frame/delegate另用其原role。
   Rpacket在首cut之后产生，因此只声称该packet跨第二cut；active C1跨两个cut。
   共host还可接close NORMAL的E0，所以只有准确helper RAISE guard才给True，
   unconditional不得True。
2. **正常路径**：第一次cut之前产生的原Return pending/payload → 两次真实
   cut → 原CleanupResume → Route/Dispatch → 原RETURN payload Use。这个用例
   才验证同一个旧payload确实穿过两个cut，而非把两个旧fixture并列相加。

每次world/context取新的ResumeInput，Attach重建本次caller；不保存旧caller
冒充当前，也不回滚到pre-detach state。原C0/C1/C2仍核词法栈、active entry、
context、副本、fresh Replace和当前state。查询没有绕过它们。

错误context/state/把旧Return当新Raise replacement由原core更早拒绝，不写成
新来源算法发现。专用同型错packet来源反例显式去掉原conditional close协议附件，
避免其已有pack-source规则先拒绝；原C1、两cut和dispatch仍完整，再验证通用
source_binding不能把另一packet当helper自己的RAISE。

## 5. 逐门证据与失败归属

| 记录 | 实际结果 | 说明 |
| --- | --- | --- |
| red-original-projection | 1F | valid原图的公开source_binding缺连接 |
| first-connected | 20P / 4F | 新fixture复用edge Use、猜错formal位置和预期过晚错误码 |
| repaired-core-fixtures | 25P / 1F | normal fixture将Value record误传到ValueID字段 |
| repaired-normal-two-cuts | 1P | 修ID后只重跑这一必要selector |
| final-focused | **1018P / 0F / 0E / 0skip** | 三路复审、所有作者冻结后的统一受影响验证 |

失败均保留，未修改core以接纳错误fixture，未放宽语义断言。多个小定向不累加
冒充一次整体通过。最终1018由原965义务不变、26个新增测试和27个原有相关测试
组成；后27项覆盖pending INVOKE转发、SavedInput、cleanup当前性，是扩展的
受影响覆盖，不能说成新写的测试。

归档首检另发现：首败中新引入的旧Return冒Raise用例在纠正core归属时改名，
从 `test_second_cut_cannot_present_the_old_pending_token_as_fresh_replacement`
改为 `test_second_cut_cannot_replace_raise_with_the_old_return_pending_token`。
输入仍是同一second.suspend replacement Use换成second.input.pending；更正的是
被提前拒绝的错误码与用例名称。原始失败ID不删，checkpoint单列attempt映射并
要求目标仍为新增用例，不能用于迁移/隐藏原965义务。首检失败与修正原因保留。

最终718-source前后指纹：
`1b92351bac44522b6cbe84afeee1f3ed32eab4deed679c6260dec6da81df00fa`。
pytest41.83s；runner42.680510396137834s；这是验收成本，不是workload性能。
使用原conda lewm / Python3.14.7，没有环境重装、CUDA/PyTorch升级或重型LeWM。

**Verified:** 本门供应IR的projection/source/caller/guard、两cut组合和回归范围。
Program1–22/Execution8不变，无新schema；原codec/model源码和所有旧fixture、
冻结计划、历史证据由checkpoint与基线逐字节核对。归档脚本只核验、不启动测试。
原LeWM及受保护主checkout保持不动，源码/失败收据/报告独立commit并推送。

证据：`artifacts/experiments/b1_call_operands/model_pending_payloads/`。

## 6. 保留的边界与后续

**Rejected:** 错同型来源、错guard、旧source/token冒当前、无种子来源、错误私有
role与state/context由各自core或source门拒绝。**Unproved:** 自动源码恢复、真实
native/source解释、实际activation/segment/本次resume的动态对应及变换权限。
本轮没有新backend/detector、LeWM-specific rule、自动LeWM变换或加速比。

原packet_frontiers仍诚实标为frontier-only；通用source_binding现在能证明后续
端口来源，不等于该frontier查询已穷尽所有handler、override、opaque call、C1
continuation和P3发生组合。下一步应把这些共享证明接入原各family的完整义务
清单，补缺来源及动态桥，保持16组分母，再执行统一组件/一次干净frozen full，
而不是继续添加孤立detector。P5/M2及完整M0–M2仍OPEN；旧full仍仅属于8138986。
