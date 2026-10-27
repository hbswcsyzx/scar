# 自动前端首批12项：真实边界与下一最小协议

## 实施进度（2026-10-23）

下文为原只读诊断与设计。其三文件tuple修正已在隔离proposal完成，并在原runtime/
compiler门均终态后应用到生产；准确字节与proposal一致，AST通过。新增focused guard
独立核原CFG/ordered Use/FRAME_HOLD/FRAME_EXIT，已在原65ops归档揭示tuple分配失败
提前丢element refs的缺口；旧artifact不改写。局部retention检查不证明normal/outer
lifetime，Slice/INDEX等中间consumer未证时保留具体frontier。

确切补丁、原producer及四项隔离IR检查在 `first_stage_tuple_key_proposal_20261023`，
应用收据在 `first_stage_tuple_key_applied_20261023`。

真实两body window已完成：`first_stage_tuple_key_bodies_20261023` exit0，wall26.71s，
其中原65ops body在新producer下恢复并公共回读，源码与完整编译见证独立核对；另一个
按原12attempt的准确AST/SG条件机械选出的body越过tuple来源缺口后，在正式地址校验
失败，保留FAILED_RETAINED与未知emitted cost，不能称UNSUPPORTED或成功。

失败暴露的是通用heap-source子图恢复器已有两处接线遗漏：恢复INDEX缺少对应原
receiver/key/world Uses的PARTIAL READ地址，key的SourceUse顺序也与既有0/1合同不符。
仅在SLICE_KEYS能力下用原Uses补该地址并恢复key ordinal1；不造Use、State、实际读写
或完整effects。新独立 `first_stage_tuple_key_heap_attempt02_20261023` 只重跑失败body，
没有再lower65ops body；exit0、wall17.49s，恢复218ops新图，两个SG-only tuple key的
准确源码/code/ordered Uses及raise element retention均通过。25个中间消费/控制join
frontiers保留，normal/outer/full lifetime仍未Verified。

新65ops artifact SHA `828a11c5bd201886a52bae68e83df490ae9199e546666af6de9bbfb66181e945`；
218ops artifact SHA `605c15aae03d100df6bd1ba63fb5c1507cbdd4d9ff177a6ba6bd058b2dc1d4f3`。
各门compile0/prepare0/target0，原20-key archive全部字节不变。现有842 composition仍
引用旧图，须经显式body revision/新snapshot修订后统一接线；未正式publication或增加
当前Run覆盖率。无新的detector/backend/优化。第一阶段继续OPEN。

## 原诊断与设计

2026-10-23。**Observed / 只读诊断；没有修改冻结生产代码或再次派工。**
本轮12次均为源码前端UNSUPPORTED，不是优化候选被拒。原返回/失败及零新图事实保留。
来源为 `first_stage_source_frontend_automatic_20261023` 的实际attempts/returned metadata、
原source locators和4份owned UTF8快照。AST解析不生成CodeType，不执行目标。

## 精确边界与当前调用权重

所有12个待恢复definition均为FUNCTION，源码span而非函数名决定下列分类。
每项的原work/body key、source span、归档source收据、group/call weight与diagnostic
原文在 `exact-ast-frontiers.json`；原结果JSON和ready/return记录均未覆盖。

| 原首个边界节点 | bodies | 当前calls | 当前缺口 |
| --- | ---: | ---: | --- |
| Tuple，位于Subscript(Store)的key | 1 | 25 | heap-target child无旧computational overlay；有完整SG定义 |
| ListComp /DictComp | 2 /1 | 3 /1 | 已分词法/compiler locals，但未有comp执行/保存恢复接口 |
| Call含**mapping | 4 | 5 | 当前固定argument adapter显式拒keyword.arg=None；四例均无*positional |
| dynamic two-bound Subscript | 1 | 2 | BINARY_SLICE lifetime/输入消费尚未映射 |
| Try | 1 | 1 | exception handler/control-state路由 |
| nested FunctionDef | 1 | 1 | definition-time defaults/closure/decorator/annotation/function object状态 |
| ImportFrom | 1 | 1 | import initialization/namespace/module cache/异常状态 |

权重是这些body在既有Run的实际调用数，不是新增调用，也不是可节省耗时。节点在同一
span有Expr/Call包装时保留两个原AST候选，Call形状由确切ast.Call字段核定，不猜变量名。

## 下一项：SG-backed固定tuple index-key

选择依据是范围小且证据明确，并非某个业务函数更重要：25次调用的实际首阻塞已有
完整source/SG与compiler witness，只缺跨现有source表示的适配，且能一并修正tuple
失败ownership。这是tuple**表达式建键**，与前轮Tuple(Store)解包不是同一协议。

`tuple-key-source-witness.json`已核：原Tuple atom有唯一SG operator/output slot，parent
是Subscript(Store)，再上是Assign；对应SourceSemantics operations数量为0。当前
`source_slice_lowering.lower_key`在已匹配BUILD_TUPLE后无条件调用old_operation，报
“expression needs one source computational record”。旧computational overlay有意不展开
assignment-target children；不能因该表无记录就说源码/SG缺失，更不能伪造StaticValue。

最小适配复用 `source_heap_lowering._source_definition/_associate`：在旧overlay存在时保
原路；缺失时只接原SG准确Tuple atom/唯一operator/output slot，按真实AST顺序恢复child
Uses。child可用现有heap expression recovery读取Name/Constant等；若child也无正规规则
则保留它的frontier，不造producer。外层tuple仍复用原Operation/ReferenceValue、
Opcode.BUILD_TUPLE、normal/raise world与原source correspondence。

constant key仍走CodeWitness确证的LOAD_CONST，dynamic固定arity key须有准确位置/arity的
BUILD_TUPLE；Starred key与另种compiler lowering保持拒绝。不得生成global tuple()调用，
不得从index key推导NumPy/Tensor view、copy、consumer纯性或物理读写。

## 必须同时核的异常与ownership

已下载固定CPython v3.14.7 primary原文件并留SHA，路径见实验 `primary-source/receipts.json`。
[BUILD_TUPLE](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L1986)
使用success-only steal，分配失败走ERROR_NO_POP；
[tuple helper](https://github.com/python/cpython/blob/v3.14.7/Objects/tupleobject.c#L413)
在分配失败时尚未转移parts，随后由解释器unwind消费它们。不能与
另一ArraySteal helper的失败语义混淆。

当前 `source_slice_lowering._invoke` normal和raise均_transfer；对BUILD_TUPLE会在failure
FrameExit前去掉仍在stack的parts，缺少正确的failure pending引用。这是具体建模缺口。
已发布body26验证覆盖source/ports/结构，不曾证明实际lifetime，不能因此说该分支已正确。
前轮保留的lifetime/finalizer/noncompletion UNKNOWN条件也不能替代明确输入消费关系。

最小helper改动应显式区分normal与raise的consumed集合：tuple正常转移parts给tuple；
tuple失败保留parts并交failure FrameExit/unwind；其它slice/index协议按各自固定版本合同
沿原规则，不用一个全局消费策略替代。不能将tuple allocation失败当pure或无world变化。

独立义务：

- RHS先于target receiver/key；tuple children左到右，前child effect/后child失败的post-world保留。
- tuple失败尚未执行该target store；先前chain/loop targets若已提交不可回滚。
- 成功completion发布一个tuple ref和world；失败exception/world及pending parts/外层RHS/
  receiver/iterator归属正确，不重复release、遗漏release或假造实际allocation/free事件。
- 原source/code位置、arity、ordered Use/alias关系独立校验。elements仍为原refs，不clone。
- finalizer/termination/actual implementation仍未证明处保持显式条件，不能升为NONE。

## 最小改口与后继有界验收（原设计；现已实施）

| 文件/接口 | 所需变化 |
| --- | --- |
| source_slice_lowering.lower_key | SG-only source-backed tuple与child recovery；保exact CodeWitness/ordered holds |
| source_slice_lowering._invoke | completion-specific input consumption；tuple raise不提前transfer |
| source_heap_lowering | 只复用原recovery API，若需hook保持原SG与source角色，不新增业务节点 |
| source_language_validation | 对index-key BUILD_TUPLE的原AST/SG、ordered ports、两种completion pending集合独立检查 |

准确复用的现有接口是 `_source_definition(builder,node, binding=False)`、
`_associate(builder,operation_id,node,definition,Opcode.BUILD_TUPLE)`、
`expression_for_heap_target(builder,node,cursor)`、`_hold(builder,cursor,node,reference)`、
`_transfer(builder,held,node)`、`builder.invoke(...,failure_handler=...)`及
`builder.finish_exit(failure,node,exception,ExitKind.RAISE)`。前三者连接已有SG与core操作，
后四者保留现有typed world/Frame协议；无需引入另一套producer或runtime事件。

`_invoke`的内部参数需分别表达normal_consumed与raise_consumed；它们是原ReferenceValue
的有序持有实例序列，不得把相同ValueID出现两次合成一个集合。对本次BUILD_TUPLE：

| completion | tuple elements | 外层RHS/receiver/iterator | 后继 |
| --- | --- | --- | --- |
| NORMAL | interpreter向tuple转移；从active_temporaries移除elements的末尾段 | 保持原顺序/原持有次数 | 原normal result+post-world；调用方再持有tuple result |
| RAISE | 不转移、不提前release；仍在原stack位置 | 保持原顺序/原持有次数 | FRAME_EXIT持有exception、locals、全部pending；沿post-world进入原RAISE |

这里的失败规则依据`ERROR_NO_POP`及success-only steal，不能错误地套用
`_PyTuple_FromArraySteal`的失败清理。归档primary `bytecodes.c`中exception_unwind
5424起会关闭剩余stack entries；当前frontend不支持Try handler，因此本门只建模无已恢复
handler的frame exit，不凭这一规则假设将来的handler栈深、lasti或异常payload。

独立验证不能只检查lowerer报告的consumed参数或把normal与raise出口相减：当前
`_transfer`没有独立wire事件，必须依据原CFG、FRAME_HOLD/RELEASE和已明确的primitive
completion规则核持有实例。最小证明范围是所恢复tuple key及其外层evaluation上下文：
tuple前各child hold的ordered Use、tuple invoke输入、raise FRAME_EXIT的pending后缀与
外层prefix必须相等；normal沿tuple result继续，不得在后继failure中再次以独立持有
实例清理已转移elements。若遇未定义的中间primitive消费或不能唯一恢复的控制路径，
保留明确lifetime frontier，不以结构合法或自报UNKNOWN充当该局部义务通过。

优先沿当前已有typed Operation/Opcode与capability完成实现，不为存一个tuple另造规范图。
若需要新增来源记录/改变wire字段，必须先明确新版本，不能往旧overlay静默加字段。
应有一个独立的正常/中途child失败/tuple allocation失败关系审核；结构归档能核最后一种
pending形状，不必执行大模型或假造一场MemoryError来充当真实观测。

后继实际源case由该exact AST/SG条件机械选，不按本例名字；只在原已选file中恢复对应body，
检查新的第一frontier，不预言整个body必定成功。已发布tuple key来源可只回读验证受影响
failure边，不能将旧source/code proof冒称新lifetime实测。重新完成SourceProgram→CP2→
currentRun接线仍是独立门，不在本只读诊断实施。

其余优先队列是kwargs expansion（必须DICT_MERGE重复key错误，不能套dict display的
DICT_UPDATE覆盖语义）、comprehension完整scope/控制、combined slice、definition/import/
Try入口。原静态/动态分母、失败节点与重试key都保留；不扩大budget刷更多UNSUPPORTED，
也不通过cache/backend绕过程序表示缺口。
