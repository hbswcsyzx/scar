# 第一阶段余缺交接：完整 LeWM 自动建模仍 OPEN

2026-10-25。仅阅读主树三份阶段文档、本次 REPORT/result 共5个文件；无 trace 扫描、
重跑、代码修改或提交。合同的完成条件仍是固定 AnalysisScope 下，未修改 LeWM 原
完整入口自动产生模型，必需端口、状态、控制、资源/生命周期关系无未解释断点。
结构清单、接口表征、内部展开、运行对应必须分列；不可用 OPAQUE 或缩分母取得 PASS。

本次是**保存的 CPU 样例**，不是 LeWM：93681 exit0/38.890410046s，271次调用、
566个参数 occurrence，260个入口/520个既有 formal ports 局部映射，11个入口缺 body。
frame536684B+operand13285B，只一次完整 frame 流；唯一真实 port/source 交换独立拒绝。
520不是对象数或内容数。producer基线 bc139/core28；Root另确认 main66781兼容验收
exit0/3.53413s，接入0d5d7e10；该兼容消费不改写原 producer 范围。

| 实体/关系 | 已获证据及其范围 | 未解决接口/阻塞 | 下一最小实际门 |
| --- | --- | --- | --- |
| AnalysisScope、CodeIdentity、Run/Process/Thread、frame根 | 有范围化账本、归档/版本链；core29 FRAME/source ABI及旧格式守卫通过。未来collector注册/源码见证已有CPU门 | 旧LeWM只有collector HEAD label，不能追认执行源码/shared issuer；PID代次、实际frame/namespace进入未普遍闭合 | 收口现有namespace/source producer的真实frame入口消费；下次联合采集同时绑定实际code、issuer、actor与起止，保旧scope条件 |
| Region/Operation/Use、源码/依赖 body及出版 | 正式静态858 bodies/2217定义/151文件；完整runtime仍843快照，100438调用中6699 body-linked；新CPU外部28op body能正常出版/绑定 | 静态/运行快照不同；769 UNSUPPORTED、590 NOT_ATTEMPTED及module、Try/cleanup等余项；project/依赖出版需保各自parent/CAS/namespace | 消费现成产物完成project/dependency出版与原body/source普通读回；继续通用module/frame正文小门，不重新lower已成功图 |
| Invocation→callee入口参数→既有formal port | 本CPU520局部引用端口，name→slot→BlockArgument，原SourceRole/namespace/fact/point准确；缺FunctionObject不否掉该局部事实 | **不等于caller实际表达式→formal**。本CPU operand无load值/ENTRY_HANDSHAKE；旧五项未连接资格各271仍在。旧LeWM另有27条条件argument/completion路由，不能与本CPU相加 | 从已有实档中确有原Use/握手证据的有界窗口接caller→callee，保持求值顺序并独立错连拒绝；证据不足保持具体frontier |
| Return/Raise、控制与cleanup | 原profile可观察NORMAL/UNKNOWN；本CPU270 NORMAL、1 UNKNOWN。旧843有限返回roots已接线 | UNKNOWN不证明unwind/异常/None；normal observation不自动选中canonical Return或caller consumer；外层lifetime/cleanup未闭合 | 同一既有body/发生上核原return-site、准确完成端口与consumer；无法区分的路径继续UNKNOWN，不由缺日志补None |
| Object/Environment、globals/defaults/cells、namespace | 旧843已有3372入口/10162环境ports等有限连接；code/source/body对应已可查询 | 同code不同function/env；6744 defaults未定与大量route issues保留。引用token不是ObjectIdentity、内容或读写版本；环境前缀/world未被本次520补齐 | 用既有有来源的environment记录接一个具体binding/read；静态slot、实际owner、前/后态分别核，缺内容/写入证据列为需补采 |
| NativeBoundary、Tensor引用/geometry、逻辑值/provenance/materialization | 旧LeWM39796 dispatch/127接口/156片已接端口；111189 Tensor ports中held109288、未定1901，geometry107483、缺3706 | 接口已表征不等于native内部、值来源/state/alias/ready完备；native-only不要求也不能造Python对象。新metadata/标量CPU门不恢复旧LeWM缺采 | 复用现成canonical边界，做一个确有输入/producer/输出来源的有界版本链消费；真正未采的native metadata随统一采集合并补齐，保B/C/内容资格分离 |
| StateLocation/StateVersion、mutation/alias/RNG/world | core与部分provider合同可表达；实际引用、view和物理点可分开查询 | 仍缺真实读写前后版本、外部alias/escape、RNG与跨body状态传递；schema may-effect或相同world名不证明状态等价 | 一个实际mutation或状态操作闭合原输入/后态/别名与完成义务，使用原typed关系，不能仅接geometry或版本计数 |
| Resource/handle/work/completion、FD/OS/CUDA ready/lifetime | 大量OS/work及CPU/GPU scope来源、FD scalar回执已保存；接口库存可核 | FD selection不证明table连续性/OFD身份；旧unshare/close_range漏选已撤回相关资格，网络等全集仍有限。host返回不是GPU完成，内存birth/end、stream/wait和输出因果链未全接 | 先消费已有精确活动桥接一个work→completion/wait或FD生命周期；缺连续性/ready字段随同一联合采集补，不按时间邻近、fd/地址相同推断 |

优先顺序：先收口正在进行的出版/namespace与普通consumer，并消费已有证据能闭合的
caller/return或值来源断口；只把真正缺采的collector来源、native metadata、OS连续性及
异步完成字段合入**一次**后续完整LeWM联合采集，避免逐字段episode。可复用的接口没有
adapter与原档根本未采必须分开；完整Tensor值不默认保存，未观测的硬件内部细化单列。

最后仍须按合同S3→S4复建统一模型、保持源码/实际调用/provider/OS全部分母，逐项核
mandatory义务。仅当固定scope的必需OPEN=0，才可称第一阶段完成并按S5停止汇报；
本交接不新增profile/backend，不开始图化简、变换或性能结论。

依据：[合同](/home/zyf/AAA/scar-worktrees/structured-program-model/docs/FIRST_STAGE_MODEL_CONTRACT.md)、
[状态](/home/zyf/AAA/scar-worktrees/structured-program-model/docs/FIRST_STAGE_MODEL_STATUS.md)、
[执行计划](/home/zyf/AAA/scar-worktrees/structured-program-model/docs/FIRST_STAGE_EXECUTION_PLAN.md)，
及本树callee_entry_routing_20261025原REPORT/result。文档历史“下一项”按日期保留；
本交接不将旧路线文字或尚在收口的后继实现当作新增已验收事实。
