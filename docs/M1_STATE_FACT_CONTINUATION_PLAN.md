# 原状态事实到当前读取：有限实现门

2026-10-19。基线 `fa7b769e34adf5ef39c27103c11b6cb75f796f7b`，上一门为
verified progress：1865相关测试、原1854身份保留、858稳定源码；本轮起点已复核
其checkpoint。原M0–M2范围、16族/P5/M2原113构造/196字段不变。

## 1. 模型合同

Operation / Value / StateLocation / Region / Resource不变。不新增canonical
state、producer、identity、codec或优化backend。查询收据属于派生证据，不是
另一套程序图。现session_flow局部must固定点、原SessionPublication、准确
CallActivation、canonical effect、copy recipe和host flow均复用。

必须分开：原post在某点成立、主体引用copy、状态版本端口传递、内容保持、
READ自己的bool与实际分支。不能用后一项反推前一项，也不选“最近同名节点”。

首版事实域为原SessionPublication.support全部域，合并目标READ全部实际
StateAccess域。不能取交集、丢辅助READ或凭field/Location名称缩小依赖。
不同LocationID不证明隔离；WRITE/RW无独立隔离证据均是可能clobber。
地址DECLARED_COMPLETE不升级operation.effects_complete。未知写保None，
不推出内容已False。现无post→physical selector对应，不授跨字段/域写豁免。

CallActivation只关联callee；body展开不免除outer effects_complete=False。
完整boundary也不免除child内部未知效果。N/R与全部state actual/formal、出口
ordinal、选中transfer必须准确；host-order先后不能替代每个中间操作的效果清单。
无已证whole-boundary及state保持语义的primitive INVOKE仍是阻断。

## 2. 公共派生接口

`ExecutionIndex.state_preservation(start,end,*,locations,budget=4096)`：
start是准确AFTER或实际EDGE，end是这次操作BEFORE，locations为非空唯一原
LocationID tuple。遍历原static block位置与actual visit/transfer，展开准确
同步call并从已知completion返回parent。逐原操作列effects、缺采、call边界和
状态端口；不凭endpoint相同跳过区间。缺完整路线/未知效果/任何未排除写或预算
截断时preserved=None；False连接与False字段值不是一回事。返回原operations、
calls、transfers、state_bindings、blockers、reached、cursor、共享budget与权限False。

`ExecutionIndex.request_state_history(readOccurrence,*,budget=4096)`：
自动枚举原SessionUpdate及其实际发生，保未观察原来源分母。核准确post点/实际
NORMAL或AFTER、原全部support、同R的独立copy、原READ/ownbool/branch，再调用
上述generic query。仅原COMPLETE→IS_COMPLETE合同可产生条件expected_bool=True；
不由HOLD/ABANDON推出False，不用实际选中True边充当证明。每个来源及其阻断
均保留；同一共享预算贯穿枚举、copy、路线及效果。不授source/native/transform权限。

## 3. 真实压力图的预期结果

上门R3必须仍为PARTIAL：post之后的adapter.construct、effects不完整terminal、
无隔离证据的catch context RW、第二association primitive INVOKE都要具体列出。
完整SSA/packet/call记录不修复它们。原fixture不能被标pure或改位置以制造通过。
正例使用另外明确完整效果的通用getter图；若为新语义正例构造独立post/READ图，
必须保其真实接口而明确是供图，不宣称修好了原R3或自动LeWM恢复。

## 4. 自主验收节点

| 节点 | 证据 |
| --- | --- |
| H0 | 三方只读审查、上述事实域/调用/别名边界冻结，旧合同和原分母保留 |
| H1 | 完整getter跨callee原N/R端口与状态保持正例；每个中间操作可审计 |
| H2 | outer incomplete、child opaque、同域/不同Location写均不获保持；缺entry/completion/Use/transfer不借别次 |
| H3 | 原R3准确来源及全部阻断；COMPLETE/READ逻辑连接有正例，错R/未成立post不成功 |
| H4 | budget1和中段截断保库存/游标，不能把已证前缀作为全部；原1865身份及旧源码/fixture守恒 |
| H5 | 独立复核、冻结相关回归、逐节点报告、版本提交与远端核验 |

只补这些有限原关系，不铺参数笛卡尔积；首测、构图错误与产品错误分别归档。
本门不关闭F14/F16：native Running/完成后reuse整链、请求竞争/初始ASEND与原
其余八族仍要自己的证据，之后P4组件/冻结全仓、P5/M2完整验收，再按用户要求
讲解模型。M3自动lowering/M4采集对应和LeWM优化/新加速比仍待后续。

## 5. 写入与运行责任

root拥有旧文件公共API、history实现、文档/归档/Git及全部串行解释器。A可在
root明确授权后仅写NEW generic模块，C仅写NEW generic测试，B仅写NEW history
测试。所有源码作者每次解释器运行前明确冻结；禁止协作者Python/pytest/probe/
compile，禁止改旧tests/fixtures/codec。原LeWM和原SCAR checkout保持。
