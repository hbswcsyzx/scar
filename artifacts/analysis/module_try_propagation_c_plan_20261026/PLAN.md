# C：同 SP8 的传播载荷与普通 Try/except-as（Root已授权实施）

B 已交付 `8078ffdecff2734c5baeac3d6bdf7a6c436c0b55`；本轮不改其六源/50902…冻结与原门。C 首切口是原 unit 的第8条 Try（11–14行），不是解释器重写；先接普通单handler、可选as绑定、无else/finally的通用形状，按AST/SG/whole-root CodeWitness选择，其他Try/TryStar形状保精确frontier。预期扩到9个顶层接口、remaining为Assert/Expr两条，但必须由实际producer决定，不能预填成功数。namespace/import/call内部、runtime与完整模块仍OPEN。

**闭合能力与来源。** 保source8/core29，增加显式非默认 `FrameBodyProfile.STRUCTURED_MAPPING_PROPAGATION_314_V1` 与 `FrameCompletionProfile.PROPAGATION_REF_PAIR_314_V1` 的固定配对；B的旧profile仍只允许RAW，SP1–7/默认3–4不放宽。overlay仍引用唯一core FrameRoot，沿原constants/expansions/child_slices/protocols，不复制入口ABI/pending。原frontend_v2.py:304–310确实给ExceptHandler建SourceAtom，所以handler body可用其原SourceReference+HANDLER_BODY精确定位，不造Name/Module原子、裸业务ID或另一张CFG。

```
每个 C-profile INVOKE:
 NORMAL(existing results..., W')
 RAISE(exceptionRef, thisPropagationTracebackRef, W')
   → 现 ExceptionPacketDefinition（纯CONTROL、两个真实Reference Uses）
   → 现 PendingCompletionDefinition / ControlPort / 实际CFG
   → 原 C1 Enter / Resume / Replace / route / C0 dispatch
```

这里traceback是该opcode错误传播边界的显式结果；不得读取`exception.__traceback__`旧属性、填None/Unknown、或把B的ref-only错误静默适配成C。opaque remaining计算Region也必须保同一paired RAISE接口，frame root最终RAISE出口携现ExceptionPacket+当前world。packet只是本次传播的引用聚合；cause/context属性、traceback对象变化和其他effects仍在当前world中，不由pack快照或回滚。原C0 packet/pending唯一constructor与C1 must-forward/must-fresh均保持。

**builder接口最小改口。** structured_lowering.py:204–235目前固定单exception ref，for_statement:405–433又有自定义failure callback。抽固定payload/profile hooks：`raise_payload_types()`、`route_failure(cursor, source, operands)`；旧function/B仍收一ref，C接一个私有construction-only `PropagationOperands(exception ValueID, traceback ValueID)`，只命名已有core结果，不序列化第二权威。for的StopIteration消耗与未命中重传都必须保原pair；不能在callback只留下exception再假造traceback。program_lowering.py:682–707的new_block须能创建已有ProtocolValueType对应的真实ProtocolValue BlockArgument，module use须用UseRole.PROTOCOL。原函数/RAW行为不变。

新source协议只补明确的dynamic exception-match、DELETE_NAME与pending-preserving frame-exit等索引，不重定义旧FRAME_EXIT/现C0/C1。终态frame释放接受同一pending token与真实namespace/临时引用，按原FrameRules保守更新world，再交现PendingDispatch投影已有payload；protocol token不是Python对象，不作为假的ReferenceValue。适用条件/回调/不完成/实际释放仍未证。要供handler代码使用的exceptionRef直接沿原core Use→BlockArgument传递，并在source validator核其与packet构造输入同源；不新增packet投影权威或parallel pending表。

**Try的实际控制/状态拓扑。**

1. try.body继续复用现有ordered call/list/attribute/namespace规则；normal直接到after-Try，不为normal路径虚构一次PUSH_EXC_INFO。任一raise边把pair送exception-only gate BLOCK，在此pack原packet/pending Raise，经既有CleanupRoute进入handler CLEANUP（gate与cleanup同parent）。
2. 复用 `HandledContextDomain(region, 已有world LocationID)`，不造context world。C1 Enter以原Raise pending保存ambient并安装packet.exception；这是现合同（M1_CLEANUP_INTERFACES.md:52–58），并非新推断。随后真实LOAD_NAME求handler type；不把`ValueError`拼写固定为builtin。用现ExceptionMatcher+ExceptionHandlerOperand索引dynamic matcher的原exception Use、handler正常结果端口、bool分支、raise及全部state sites；input/source可用现BlockArgument，类不匹配/匹配本身raise均保真实分支。
3. 未匹配：Resume原pending与本次saved_context，不重新pack同一token。type lookup/match失败：在旧context仍活跃时由新pair形成fresh Raise pending，走Replace恢复ambient；新的cause/context处理必须在restore前体现于传播协议后态。匹配后STORE_NAME as绑定仍是L的PARTIAL尝试；handler里的该名字重新LOAD_NAME，不能直接换成caught ref。
4. **as清理不能合并顺序。** CPython3.14.7的正常路径先恢复ambient，再做隐式None-store/delete；handler异常路径先清名，再由外层恢复/reraise；绑定STORE失败发生在清名保护建立前。见[固定版本codegen_try_except](https://github.com/python/cpython/blob/v3.14.7/Python/codegen.c#L2311-L2380)。因此正常handler构造fresh Fallthrough pending，C1 Replace先restore，经post-pop corridor到normal清名块；handler-body失败先在同一活跃cleanup内普通CFG去exceptional清名块，**不再Enter一次**（否则会把新raised exception错误安装成handled context）。清名成功再Replace原fresh Raise，清名失败则Replace更新的fresh Raise；绑定失败直接Replace，不误跑清名。STORE/DELETE可忽略写、调用Python、raise，不授内容/清除证明，也不覆盖已发生的world写。
5. Resume/Replace严格直接归属cleanup、紧邻真实JUMP→parent的route-only corridor，再到C0 dispatch；private saved context不传普通callee/exit。source_statement_lowering里的新try connector只产这些既有记录。C1原栈/LIFO/全部INVOKE边覆盖、pending原锚、replacement freshness负责拒绝绕路；source validator另核原AST/CodeWitness异常表与上述正常/异常分流。原source CFG Try gap保原样，不能伪造旧CFG anchor或把接口内部债务算PASS。

**尚未决的验收边界（不等待全解释器调研）。** 传播pair的抽象端口已能表达，但其source adapter仍须把同版本opcode error-site/异常表边界核回；CodeWitness本身不观测live traceback。首次新错误与compiler RERAISE必须分开：未匹配分支保原packet/token，不二次补frame/traceback；不足时拒该profile/保具体frontier，不用属性读取或None补口。正常/异常清名走廊已由固定codegen确认，实际artifact的opcode/exception-table匹配及FrameRules适用条件仍由后继门分别核验，不能靠协议名称自证。pending frame-exit与原conditioned retention的精确输入形状也需在实施前API核定；若现关系不能安全表达，先报具体接口，不新造traceback语义或平行pending权威。

**最小6个生产文件；core模型/codec/cleanup不改。**

| 文件 | 必要改口 |
|---|---|
| ir/program/module_entries.py | SP8新显式profile/paired completion、源协议kind；旧RAW固定配对不变 |
| analysis/program_lowering.py | source8新cap分流与现ProtocolValue BlockArgument支持；不变旧wrapper guards |
| analysis/structured_lowering.py | 固定failure payload hooks、for原pair保持；旧function/B默认不变 |
| analysis/source_module_lowering.py | C opt-in adapter、actual scopes/ports/C1记录、paired suffix与pending frame-exit；同一FrameRoot |
| analysis/source_statement_lowering.py | 通用单handler Try连接器及as正常/异常清名走廊；不现在扩Assert/Raise/finally/except* |
| analysis/source_module_validation.py | 独立paired-port/source/handler/clean名顺序与CodeWitness检查，调用现C0/C1完整validator |

若发现还缺core可表达关系，先报准确字段/producer-validator点，不靠metadata或whole-world UNKNOWN冒充。C不修改B frozen artifact以补traceback；新门构建新profile的同一unit，旧B只消费不重lower。

**一次真实原source Try门（原实施计划；现已获Root授权并执行，见文末实际状态）。** 沿原586B/95/92/45/56/context/readonly compiler root；仅该qualified module一次C lowering，机械prefix→准确suffix，普通完整source8/core29读回及同原B artifact一次兼容消费。验收exception pair每条边不丢不猜、动态handler/normal/raise、as绑定失败不清名、两种清理context顺序、全world当前性、C0/C1原authority及RequiredExpansion。保32MB actual stored+decoded含重复/owned readback、record4MB、output16MB、4000ops、worker180s/outer240s；超预算保终态，不静默放大。target executable compile/exec/fresh prepare0、readonly witness/AST分析分别实计；不target、不raw、不新episode。不扩大微测矩阵或重lower三个function成功图。

## 实施前接口核定续段（2026-10-26；无core改口）

Root已批准本文所列六源实施；原265099b1…稿保存为PLAN.original.md。先按实际API修正/封闭两个接点，再编码：

- **paired invoke**直接用既有CompletionSignature的RAISE `(REFERENCE,REFERENCE,STATE)`，各CompletionResult索引0/1/2生成该次错误边的BlockArguments。私有PropagationOperands只引用这两个现有ValueID。仅纯ExceptionPacketDefinition聚合它们；RERAISE经原pending Resume/dispatch保持原packet，不再读异常属性、重填None或添一份trace。它是静态协议结果端口，不是live traceback观测。CodeWitness/固定opcode合同定位源错误边，actual identity/effects保OPEN。
- **不能让ordinary frame-exit读PENDING_COMPLETION。** control_validation.py:345–359的pending_escape只允许既有typed控制/cleanup Uses。改为先由现PendingDispatch/PendingPayload选择language payload，再在raise shim用`UseRole.PROTOCOL`读取真实EXCEPTION_PACKET，配namespace/retained Reference Uses及当前world；新source kind `FRAME_EXIT_EXCEPTION_PACKET`只做原FrameRules下的world/retention过渡，然后RAISE终结器继续使用同一个packet和post-world。packet不是Python ReferenceValue，也不投影/重pack。普通packet Use没有pending_escape限制，pending token仍只在原C0/C1合法端点流动；normal shim仍用原reference payload。不存在新增pending authority/core表。此前草案“frame释放接受pending token”的直接输入方案由此替换。
- **ExceptionMatcher的既有RAISE attachment要求packet，不能把paired refs硬塞进去。** 不改core matcher：按现缓存Python_bytecodes.c:2847–2859，将CHECK_EXC_MATCH分成type-validating may-raise协议（C paired completion）、借用两个Reference的normal-only readonly matcher（既有ExceptionMatcher/ExceptionHandlerOperand，raise_result=None）及随后原conditional release。实际bool仍供真实BRANCH；释放可能回调的world变化单列，不把整个opcode标pure或漏掉TypeError边。旧function/B/RAW和matcher合同不变。

两接口都在现core可表达，不需第七生产文件。handler normal/exceptional清名的两走廊和绑定失败不清名仍按正文；B六源冻结/旧SP8 artifact不变，C在新profile/新窗口验证。

## 实际交付状态（2026-10-26）

六源实施完成。Root6695原窗口exit1，原因仅末次runtime参与者缺uuid/_uuid；保留原失败与当时freeze，不重建未记录的construction/runtime资格。Root59038独立normal-reader postflight exit0（14.691772119s），同一C-SP8普通读回、source/C0/C1及最终source/input/runtime核通过，lower0。当前静态图354ops/2Regions、9顶层接口/12expansions、remaining Assert+Expr共2条REQUIRED；不是模块完整。精确artifact及原/新资格分离见 `artifacts/experiments/module_try_propagation_g1_20261026/REPORT.md`。

实际frame-exit使用RAISE.block选择的普通landing：先PendingDispatch投影既有packet，再FRAME_EXIT_EXCEPTION_PACKET更新world，最后转发到原单操作exit shim；不是往exit-type RAISE shim插入额外操作。core/pending/cleanup authority未改。
