# 完整 work 分母的 enclosing-native 关系（显式 v2）

Root确认session82912 **actual exit0**，outer798.596145s / worker797.271622s。完整24,082 work与原22,060 annotation frontier分母保留，6次普通关系查询及原Region静态membership通过。**整体程序仍OPEN；不是direct-call、Tensor ports、world/state/contents/ready的证明。** Root独立assert收据为candidate01/ROOT_VERIFICATION.json，未改原worker或manifest。

| 实际覆盖／欠账 | v2数量 |
|---|---:|
| work有exact native及exact source context | 11,541 |
| work有独立enclosing native及enclosing source context | 12,541 |
| exact与enclosing重叠 | 0 |
| work没有任何native context | 0 |
| work有retained source context及至少一条CodeVersion/source-definition binding | 24,082 |
| host本身仍无exact native occurrence | 12,541 |
| STATIC_BODY_MEMBER_UNREVIEWED | 14,932 |
| STATE_CONTENT_READY_UNPROVED | 24,082 |

exact/enclosing覆盖分别报告，不把祖先冒充原host身份。旧v1的12,541 source未接项现有了外层retained context；原v1产物/失败/producer guards不改。static body欠账由旧2,391增加到14,932，扩大连接范围显露的欠账不等于body恢复。Code/source绑定属于准确外层native context，不把其CodeID授给内部ETO host。

全量索引实际读取原461,242 instances / 1,170,339 edges，索引78,171 provider edges；native156 shards / 39,796 canonical INVOKE、current858 source79,592 retained rows和817 binding rows全部走访。10,823个distinct内部host的enclosing深度按work加权为1层10,047、2层2,208、3层256、5层30。

本次owned EEG pass已strict decode原row并核chunk SHA/EOF，同时保留原provider/node_id/ctrl_deps/parent_basis与ordinal/digest/process/ETO thread/parent/raw-reference。后续仅从**本次新建**的私有field projection核逐步parent链、同namespace/process/thread、终端canonical binding；23,655原字段记录用于证明，额外原chunk读取0。没有输入旧audit DB，也没有缓存成功bool。普通selected query重新读原parent端点及native binding，source context仍为RETAINED_SOURCE_CONTEXT。固定cf30153… observer合同是RecordFunction collector-stack嵌套，不是GPU时段、源码direct call或数据依赖。

4个新/改模块及baseline01d9准确SHA见SOURCE_RECEIPTS.json和FOUR_SOURCE_DIFF.diff；source_native_composition未在本轮改。v1仍封闭原14类型、原字段、默认writer和空新字段时的原ID/字节；非空enclosing仅显式v2。19项必要小检查通过，包括原实际v1字节往返、actual-qualified v2 codec、exact-ID不变量、原两record字段、坏ctrl_deps/跨thread拒绝。这些小检查不是完整运行模型资格。

六个正常consumer机械选原exact/static代表及depth1/2/3/5代表；均核原端点，public static_member正常得到原Region。该静态membership不授AST replay、动态body执行或优化。target executable compile、target exec、prepare、lower、subprocess尝试均0；non-target compile events实际1199，不能写成all compile0。没有新目标episode、raw collector、backend或body重lower。

实际计费输入8,640,110,167B = stored2,460,886,340 + decoded6,179,223,827，其中core8,609,014,703 / code-source31,095,464；含重复普通reader读取。source/runtime与producer SHA guards另列READ_PLAN，数值不是物理磁盘I/O。stored output814,554,885B含本地SQLite716,791,808B；RSS312,440KiB，GNU-time exit0。接受的新scope预算1500/1560s、9GBcore+512MBcode、1GBoutput/2GiB没有用于改写原900s失败。

规范transport为157 work、86 source、25 work-index、80 source-index chunks，共348个，stored97,637,392B、decoded1,931,349,022B；manifest125,607B，SHA e1afda35561c9a9095ad34311fac361dbdf88f3d567456666938bfa100a7b115。编码重复成本保留，不称高效或全程序完成。仅对新transport做stored SHA复核并入Git，不再次解全输出或原图；SQLite、EO/raw、大static graph输入不复制。

前置完整原因审计/原180s失败/精确suffix恢复/两个sample harness失败及两条真实parent样本保存在artifacts/analysis/fragment_relation_gaps_20261026，纳本次限定归档。原candidate01/02 v1失败与helper修正历史在此前f3a1c96/01d9，不覆写。

**main源接入已由root完成，fresh门未运行。** MAIN_READONLY_BASELINE是接入前的历史快照：4模块不存在、source_native为ec408独立类。root随后逐SHA复制4源，并仅对ec408应用既有SOURCE_NATIVE_MOVE.diff得到4ae4同class re-export，imports/same-class检查通过；见MAIN_APPLICATION_REFERENCE.json及main的APPLICATION.json。旧navigation producer guard不降、旧派生cache失效。后继main必须按自己的producer绝对路径/源码版本fresh全24,082验收，不能借iso旧producer receipts。本任务未编辑main生产或index；下一步仅准备main新门入口。
