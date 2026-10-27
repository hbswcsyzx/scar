# 同步 try/finally：canonical pending completion 独立设计审查

状态：**Proposed；仅 M1 类型/接口与 validator 设计，不是源码规则实现或验收。**
基准：`618cf83fff4e82ed0e873db0d2f4e9a14d6e4ab5`；未执行测试、目标程序或新语言探针。
依据：`WHOLE_PROGRAM_MODEL.md` §5、`model/PYTHON_CONTROL_PROTOCOLS.md` §4–5，
以及 `model_environment_interfaces/review/NEXT_CONTROL_INTERFACE_SCOPE.md`。

## 1. 唯一建议：协议 Value SSA；不再保存 per-edge completion 副本

采用 `PendingCompletionValue`，由既有 Operation producer、有序 Use、BlockArgument、
Successor 承载。构造表只解释 OperationResult；合流不另造 definition。与现有
LocalBindingValue/BindingDefinition 模式一致；不能同时在边上再写 kind/target/payload。
边上的 dispatch case 是筛选谓词，不是另一份值内容。静态 token 不是 Python 对象，
不等于 Exception Reference、bool 或 world，也不授予 runtime identity/纯性/变换权限。

```text
PendingCompletionType()                         # 全局统一协议型，不接受手填 union
PendingCompletionValue(id:ValueID, region:RegionID,
                       origin:OperationResult|BlockArgument)
UseRole.PENDING_COMPLETION
PendingDefinition(value:ValueID, completion:CompletionConstructor)
CompletionConstructor =
    Fallthrough(target:FallthroughTarget)
  | Return(target:ReturnTarget, payload:UseID)    # exact ReferenceValue use
  | Raise(target:RaiseTarget, packet:UseID)      # exact ExceptionPacketValue use
  | Break(target:BreakTarget)
  | Continue(target:ContinueTarget)
```

每个 OperationResult pending 恰一构造行；producer.results 必须精确引用该 ValueID，
payload/packet 必须是 producer 自己拥有且可用的 Use。其他三类无 payload 字段。
BlockArgument 无构造行、无 LiteralOrigin、无 UNKNOWN 构造器；不可从普通 call 获得
无协议的 pending 值。本门只允许本 Region 的内部 CFG 传递，不作为 Python formal。
Return 无表达式仍显式持有 None 的 ReferenceValue；不能以“无 payload”代替。

## 2. 静态 scope/目标：索引既有 CFG，不再建一张控制图

新增 typed ID `ControlScopeID`、`ControlPortID`；scope 不是另一种执行 Region。

```text
ControlScope(id, region, parent:ControlScopeID|None,
             kind:FUNCTION|LOOP|PROTECTED|CLEANUP,
             source:SourceReference|None, blocks:tuple[BlockID,...])
ControlPort(id, owner:ControlScopeID, protocol:PortProtocol,
            landing:BlockID|RegionExitReference)
RegionExitReference(region:RegionID, exit_name:str) # 查验现有 ExitPort；不复制 signature
PortProtocol = FALLTHROUGH | FUNCTION_RETURN | EXCEPTION_PROPAGATE
             | LOOP_BREAK | LOOP_CONTINUE
FallthroughTarget(port:ControlPortID) / ReturnTarget(port:ControlPortID)
RaiseTarget(port:ControlPortID) / BreakTarget(port:ControlPortID)
ContinueTarget(port:ControlPortID)
```

目标 wrapper 与 port.protocol 必须一一相容；Return 只能落到所属函数正常边界；
Raise 指异常传播端口（本门只实现函数边界，未来 handler 用另一个明确协议变体）。
Break/Continue 的 port.owner 必须是当前活动 LOOP，分别指 after/test-or-advance。
Fallthrough 指确定正常后继，不能借它越过仍需执行的 cleanup。
scope 树同 Region、无环；每个参与本协议的 block 恰有一个直接 owner；parent 表示
词法活动关系，不能从 dominance 猜。LOOP 包含活动 header/body，不含该 loop else；
内层 loop else 的 break 可因而属于外层。嵌套函数是不同 Region，不能跨函数跳转。
当前 `LoopInterface` 无 LoopID 且在 source overlay：未来 adapter 将其 source/ports
对齐此 core scope/port，不把 LoopInterface 复制为另一组 CFG edges。
端口的 block/exit 身份、签名和 state 域从 core 查询，不存第二份 signature/world。
source=None 是未验证声明；有 SourceReference 也不自动证明 scope 来源真实。

## 3. 合流与专用 dispatch：不能重释 INVOKE

```text
Operation.terminator: Terminator | PendingDispatchTerminator
PendingDispatchTerminator(pending:UseID, cases:tuple[PendingCaseSuccessor,...])
PendingCaseSuccessor(case:CompletionCase, block:BlockID,
                     arguments:tuple[UseID|PendingProjection,...])
CompletionCase = 对应五个 constructor 的 (kind, typed target)，不含 payload
PendingProjection = RETURN_REFERENCE | EXCEPTION_PACKET
```

新 dataclass 用独立 wire discriminator；保留旧 Terminator 全部字段和编码。新增类型
不具有旧 INVOKE 的 `completions` 或 `CompletionResult`，不能混用。普通 INVOKE
仍只表示该次操作 NORMAL/RAISE；其异常经过明确 packet/语言完成 adapter 后才 pending。
`pending` 是 dispatch 自有唯一选择 Use；每条边另有独立的实际 Use occurrence，
即使同一个 Value 被多边转发也不能复用一个 UseID 冒充多个端口。
每条 projection 只能出现在相应 case 的边上，并只注入该边私有目标 BlockArgument；
不能在 dispatch 前定义，也不能从 RETURN case 投影异常或在 BREAK case 取 payload。
同一 case 的 payload slot 恰绑定一次；引用精度不得凭投影创建新的 known target/identity。
正常后续合流可用普通 CFG；只有 projection 落点要求单一真实 incoming edge。

从 constructor 种子及真实 CFG 入边求最小固定点 `cases(ValueID)`；dispatch 转发自身
pending 的边按该 case 过滤。不同路径同 case、不同 payload 合并时必须保留关联来源，
不能分别收集“所有 return targets”和“所有 payload”再任意配对。类型相同不等于值相同。
每个 dispatch 的 keys 必须恰等于推导集合，无漏/重/额外 case；静态 CFG 未证明不可达
的路径不能按运行样本剪掉。没有构造来源的循环 token 不能凭空产生可分派值。
新分派只选择既有控制边，不生成状态；全部 state 实参沿旧规则使用当前版本。

## 4. Cleanup 接口及异常上下文是必要部分

```text
CleanupInterface(protected_scope:ControlScopeID, cleanup_scope:ControlScopeID,
                 entry:BlockID, pending_argument:ValueID)
CleanupAction(operation:OperationID, cleanup:ControlScopeID,
              transition:Enter|Resume|Replace)
Enter(pending:UseID, saved_context:ValueID)
Resume(pending:UseID, saved_context:UseID)
Replace(pending:UseID, replacement:UseID, saved_context:UseID)
SavedExceptionContextValue(id,region,origin); SavedExceptionContextType(cleanup_scope)
UseRole.SAVED_EXCEPTION_CONTEXT
ExceptionPacketValue(id,region,origin); ExceptionPacketType(); UseRole.EXCEPTION_PACKET
ExceptionPacketDefinition(value:ValueID, exception:UseID)
```

这些 action 只绑定现有 operation 的 Use/result；before/after 世界只在 StateAccess。
Enter 读取当前 handled-exception context，产出 saved-context token；pending 为 Raise
时在 cleanup 期间安装该异常，否则保留原 handled context。Resume/Replace 恢复之前
的 handled context，**不恢复旧 world**。saved token 保存该上下文而非复制整个共享状态；
必须按 cleanup 静态作用域类型匹配，并由同次 Enter 的 SSA 路径传来。
ExceptionPacket 保存异常对象的规范 Use；traceback/cause/context/suppress 等可变属性
仍在当前 state。传播来源是 producer/source；不能另外放一份可独立修改的属性快照。
INVOKE 异常捕获、显式 raise normalization、bare raise 是不同 producer 协议；本批
至少声明捕获来源及 packet projection，未实现的 normalization 不能被空 constructor 代替。
packet 的异常引用不证明是有效 BaseException，需语言 adapter/evidence；结构层仅查类型。

context 的保存/安装/恢复、旧 payload 保留/丢弃均可能影响 frame/对象寿命与可观测状态。
action 的 ordinary StateAccess 至少连接承载这些效果的当前域：READ_WRITE、
full_overwrite=False、effects_complete=False；不添加独立 world，不宣称 free/total。
普通 cleanup 调用可能抛异常或不完成，仍用原 INVOKE 各自 post-state，不能一律非抛出。
动作的 context 子字段规则是本接口的规范语义，validator 只能核验所声明连接；
对应具体 Python 操作/异常链维护的真实性仍待 source adapter，不是 this-batch 自动证据。

## 5. 恢复、覆盖及嵌套的校验规则

- 从 PROTECTED 离开的每条控制路径，按源/目标 scope 路径选择最近尚未运行的 cleanup；
  必须先进入其 entry，传原 pending 和当前完整 state 域，不能直接到最终目标。
- cleanup 自己完成 Fallthrough 时 Resume 原 pending；不重新计算 Return 表达式，
  不新造同 kind 但不同 payload 的 pending。随后 dispatch 到下一层 cleanup 或最终端口。
- 只有**离开该 cleanup 作用域**的新 Return/Raise/Break/Continue 才 Replace；
  新构造 token 与旧 token 都必须是 action 的 Uses，旧 payload 丢弃效果不能消失。
- `try: return x; finally: for _: ...: break` 的内部 break 不离开该 cleanup，
  不 Replace；循环结束仍恢复 Return(x)。finally 内嵌 try 的正常 Fallthrough 同理。
- Replace 后不同时恢复旧 pending。新目标重新计算仍需经过的外层 cleanup；不能重进
  当前 finalbody。嵌套 cleanup 各有自己的 pending/context token，不能拿外层 token 结内层。
- validator 在既有 CFG 上推导活动 cleanup 栈、当前 pending/context 路由；Enter 入栈，
  Resume/Replace 出栈。逐边检查且按实际 Use 识别，禁止全局“token仅能用一次”规则，
  因互斥分支与循环会合法重复静态 Use。该推导不是第二套持久化控制边或世界状态。
- 函数出口只能在应运行的 cleanup 都完成后到达；同步 Return/外传 Raise 由显式
  边界 adapter 投影到既有 RETURN/RAISE 接口。Host NORMAL 不是新的语言 Fallthrough。
- 若 finalbody 发散或自身未完成，则没有 Resume；不能为使 dispatch 完整而造退出边。

## 6. 必须拒绝的错接与剩余语义边界

1. 合流 Return(x)/Raise(e) 后，把 e 送正常出口或把 x 送异常出口；覆盖后复活旧 x。
2. cleanup 修改对象/异常后，exit 携带进入 cleanup 前的 StateVersion，或回滚上下文时回滚 world。
3. 将 inner-loop else 的 break 绑到已经不活动的 inner loop；内部局部 break 却丢弃 outer pending。
4. 用同名函数/相同 code 选择另一 Region 的 ReturnTarget，或省略中间 outer cleanup。
5. 删除一个 incoming constructor/dispatch case 后以手填 union 掩盖；借 shared projection block 泄漏另一 case。
6. 将新的 invoke RAISE 直接作为旧 pending 的恢复，漏掉新异常覆盖/链及旧 payload 释放。
7. saved-context 来自另一 cleanup/较早回边、bare raise 用 pending 的异常代替当前 handled context。

尚需在实施前锁定：packet producer/投影的精确 records、context state 域的声明约束，
以及 scope/action validator 对非终止 CFG 的栈固定点算法和预算。上述字段与不变量
给出最低合同；不能省掉它们却声称已覆盖同步 try/finally 的全部语言效果。
本门不实现 except/except* 匹配、with 抑制、Suspend/Resume、async、runtime occurrence。
用户/native/interposition 任意副作用不因 typed action 变成已知；现 frame 条件仍保留。

## 7. 文件与版本落点

- `model.py`：三种 canonical Value/type/UseRole，独立 dispatch terminator 联合及 graph 表。
- 新 `completions.py` / `completion_validation.py`：constructor、scope/port、cleanup/action，
  固定点 case/cleanup 路由及错误码；`ids.py` 加静态 scope/port ID。
- `validation.py`：扩展精确 owned-use/type/dominance/CFG/private projection/state 检查；
  不修改 INVOKE NORMAL/RAISE 含义，不让新 token 逃进既有 Python formals/host exits。
- `codec.py`：ProgramGraph 新能力用 v6；v1–v5 exact fields/旧 wire 原样保留。
  只增空表不得把历史文档自动升 v6；出现新 Value/terminator 也必须触发能力检测。
- `structured.py`/source profile、SourceProgram/inventory 本批不改；以后自动源码 adapter
  再建立 source-exact scope/protocol 对应并单独升级历史 profile，不能靠 M1 声明冒充 M3。

## 8. 本轮最终分批决议：C0 接口可先落，C1 才验证 cleanup

采纳 root 的 C0 编码细化：用闭合 `ProtocolValue/ProtocolValueType(protocol=PENDING_COMPLETION|EXCEPTION_PACKET)` 代替上述两个类；`PendingDefinition(value,port,payload)` 由 `port.kind` 唯一确定类别。此为同一 canonical 模型的编码收敛，不保留两套 records；Protocol enum/组合须 exact 校验，Packet 不能冒充 Pending。
`PacketDefinition(value,exception:UseID,traceback:UseID)` 足以声明本次传播引用；两个字段各有独立 owned Use，均是 Reference，None 只能是明确传播值。traceback 是传播 payload，不断言它永远等于异常对象当前 `__traceback__`；不知道时不能填 None。可变属性和 handled context 仍走 state，捕获/重抛/正规化的正确来源与状态约束留待 C1/adapter。
C0 必须完整执行 scope/port 类型、producer/Use、真实 CFG case 固定点、精确 dispatch/projection 和当前 state 校验；`cleanup_verified` 等若出现在 wire 必须严格固定 False，优先派生属性。拒绝未实现的 executable CleanupAction/cleanup adapter；静态 CLEANUP scope 仅是声明，不能据此认可遗漏 finalbody 的程序等价性。
C1 再落实 §4–5 的 context token、Enter/Resume/Replace、活动栈及全部词法 unwind 约束。C0 不叫 finally 支持完成，不关闭本报告列出的 context/异常链/生命周期义务；同期 SourceProgram/历史 profile 均不升级或获得新自动恢复权限。
