# D2.0：SessionUpdate / TerminalFrameRelease 可实施合同

2026-10-18，根代理指定基线 `8ee8d02`。**本文件冻结建议的声明语义和验收条件；
未实现产品。**只写本新 ignored 前缀；没有修改 scar/docs/tests/旧 archive，没有
pytest、LeWM/GPU、安装、git或新 probe。旧三组断言见证不重复运行。

## 1. 明确选择

1. SessionUpdate 支持两种强类型绑定，统一使用现 core 状态和控制边；不存第二份
   before/after，不存 sources tuple，不新增通用 request 历史状态机。
2. TerminalFrameRelease 是**窄的终态 owner-frame 引用放弃/转移阶段**，固定普通
   operation + FrameRules。它不保证仍持有引用、不保证耗尽/free，不授一次性权利。
   两个这样的 tag 不自动非法，更不自动构成冗余工作。
3. 真正会向外 raise 的宽 wrapper 保持普通 INVOKE；不借窄 FrameRules 吞异常。
4. “发生过真实 terminal completion”与“当前 session/occupancy post 仍成立”分开；
   前者是派生历史因果，后者绑定准确当前 state 版本。owner-frame 当前 ownership
   始终不由历史锚推出。

## 2. 冻结字段（不再添加方法名或任意 native 分派）

```text
LifecyclePostBinding = AFTER_OPERATION | NORMAL_COMPLETION
SessionPost = HOLD | COMPLETE | ABANDON

SessionUpdate(operation: OperationID,
              request: UseID,
              body: UseID,
              binding: LifecyclePostBinding,
              post: SessionPost)

TerminalFrameRelease(operation: OperationID,
                     owner: UseID,
                     rules: FrameRules = FrameRules())
```

均 frozen/slots；exact IDs/enums/records，递归重验 FrameRules，无 verified、consumed、
drop_once、native_name、state snapshot 或独立 producer。operation 同一记录角色唯一。
Use 必须为该 operation 的真实 owned Reference Use，两个角色 UseID 不同而 Value 可
alias。实际 primitive/source 关联与 DriverRule 条件不是由 tag 自行证明。

来自唯一 owning DriverInterface：全部状态域 D 从 entry state 参数派生，lifecycle
域 L 来自 interface，`∅≠L⊆D`；规则复用 interface.rule。不得新增 per-helper 函数名表。
这些 D2 操作只在显式启用 D2 的 driver scope 使用；其他普通 StateAccess/helper
继续能表示一般程序，并不被要求全部改写成 SessionUpdate/TerminalFrameRelease。

### 2.1 三个 post 的固定、有限含义

| post | 精确谓词（仅对指定 R/B） | 明确不推出 |
| --- | --- | --- |
| HOLD | R 对 B 的活动 session/占用关系继续，R 尚可按本协议继续本 session。 | 下一次 admission 已获准；B 此刻正在执行指令；其他原始请求是否合法。 |
| COMPLETE | R 协议终结，不能再以这个 R 成功继续其驱动；R 不再持有对 B 的活动占用。 | R 已不再强引用 B；B 续体结束；B 无其他 request 占用或可立即驱动。 |
| ABANDON | R 对 B 的本活动占用已撤回；R 的协议终结性不作保证。 | R 一定完成/一定可复用；B 结束、空闲或 frame 已释放。 |

COMPLETE 可比 ABANDON 更强，三个名称不是所有 Python request machine states。
哪一个实际 family/helper 满足哪个谓词留 D3 source/runtime 对应；字段语义本轮确定，
不以枚举覆盖 whole family 冒充证明。

## 3. SessionUpdate：两种绑定与实际状态版本

### A. AFTER_OPERATION：callback-free 元数据 primitive

- op 是普通非 terminator、无 callee/call/invoke/completions；behaviors 精确
  CONTROL/READ/WRITE，effects_complete=True。只有 R/B 和 L 的必要当前 state Uses。
- 按 LocationID，L 中每域恰一条 READ 或 READ_WRITE StateAccess；至少一个写域，
  `∅≠W⊆L`。WHOLE、reference=None、非 full_overwrite；结果只为写域实际 after。
  未写域只 READ 保留当前版本，D\L 在真实 CFG 保持 current，不凭空生成后态。
- post 的 support 为 L 的完整当前版本组合：写域取 access.after，READ 域取该
  access.before 对应版本。它们从 core 派生，不存成另一实际值表。
- 这个 primitive 不 decref、不 callback、不构造异常、不做 Python dispatch。
  源 native 若把这些混在一起，可选 B；不能把实际 callback 隐藏进“元数据”标签。

### B. NORMAL_COMPLETION：真实 helper 的正常后置

- op 必须为真实 INVOKE，R/B 是 invoke_arguments 的独立 owned Uses，保留
  NORMAL/RAISE 两个完成。首版 helper effects_complete=False，消费 D 每域当前态，
  两条 completion 都逐域产生真实后态，复用 CompletionResult→BlockArgument。
- post 仅绑定**该 helper 自己 NORMAL** 真实结果中的 L 版本组合；按 LocationID
  派生，不能用 dominating 旧 state，不能把普通 forwarded Reference 假作新结果。
- 这个闭合 helper 合同声明：**若实际 profile 条件适用且 helper 正常完成，其所有
  内部 callback 完成后，该 post 在最终 normal 后态成立**。它是有类型的条件声明，
  不是从 NORMAL 自动推断。D3 对 native 实现的适用另证；不执行字符串规则。
- 若 native 仅先写 post、随后 callback 可破坏它而没有再建立，则不得给整个 helper
  加此 NORMAL post。保留普通 INVOKE，或在真实展开中的先前元数据点使用 A。
- RAISE 返回真实 partial states：不保证 post 成立，也**不保证 post 没有发生**。
  source 失败后做清理和 cleanup helper 自己失败是两条不同真实边，不能相互替代。

**两路都保留，均无需重造 helper interpreter。**宽 helper 不必为了这个接口强拆；
但没有可保证的 post 时，完整 unknown boundary 不附加错误 post 即可。

## 4. post 的失效规则（精确到 operation 点）

由 metadata after / helper NORMAL 种下 `(R,B,post,support versions)` 的派生事实。

1. 普通 READ 不改变事实；canonical edge 的独立 state Use→formal 及 R/B 引用 copy
   按槽翻译，允许任意物理端口顺序。不得由同 type/Location/内容采样生成 copy。
2. 对 L 任一 support 域 WRITE/READ_WRITE 的新版本，默认杀死原 post；未知 callback
   helper、body compute、gate helper、FrameRelease 的新后态也杀死。不因为返回
   NORMAL 或 R 对象没换就继承。
3. 固定已知的 BodyOutcomeCommit/NoBodyFinish **只发布 body**，其合同不写 request
   phase、R/B association 或双方的 session/occupancy 字段；CreatedCloseTest 只读。
   在这些准确合同及原 R/B 路径关系下，可以把已有 post 支持重基到发布后的当前版本，
   不因 coarse world 被写就误杀。它不表示 world 内容相等、没有发生 body 写，亦不
   产生 selector/无alias证明。任何包含 session 写的 NoBodyFinish profile 都不能用此规则。
4. 失效后只有另一个 typed SessionUpdate 能按 A/B 重新建立 post；前项只是保持已知
   谓词，不从无谓词状态生成它。首版不增加任意 preserves_post 白名单/用户布尔位。
5. 合流逐实际 incoming 检查相同 post 和本路径 R/B 对照；每条边的 state/copy 关系
   必须成立。集合相同、某一 incoming 成立或一个 constructor 支配不够。
6. 这些是局部 predicate provenance，不修改对象状态、不生成可跨 host 保存的 token。
   query 可以返回 conditional declaration 及准确支持版本，不能升为 runtime verified。

## 5. TerminalFrameRelease：固定 scope 和 effect shape

固定解释为该真实操作处于**同一终态 native owner 的 frame 所持引用放弃/转移阶段**。
不是指定某个全部耗尽的 bundle，不是资源 free，也不要求调用前还有引用。
重复尝试可真实 idempotent；overlay 不判断任意 bundle 是否重复。

- op 是普通非 terminator、无 callee/call/invoke/completions；behaviors 精确
  READ/WRITE/MEMORY，effects_complete=False。Use 仅 owner 和 D 全部 current states。
- 每个 D 域恰一条 WHOLE READ_WRITE，reference=None、非 full_overwrite，结果仅为
  各真实 after。未知 finalizer、weakref、unraisablehook、重入/分配效果都在此保守边界。
- rules 完全复用已有 FrameRules：NO_FRAME_INTERPOSITION=UNKNOWN；若条件适用且
  完成则 PRESERVE_PENDING_IF_COMPLETED；UNRAISABLE、UNKNOWN effects、
  MAY_NOT_COMPLETE、NOT_GUARANTEED 均不可改。无 callback/无副作用不是前提。
- 保留 pending 是返回/异常控制及引用含义，不冻结可变输出/exception attrs。
  pending/context 不作为任意 opaque helper 的实参；需要过真正 INVOKE 时使用
  独立本地 forwarding Uses 与真实当前状态，保持 C1/C2B private escape 规则。
- 不复用同步 FrameModel 的 root/ENTER/单 world/邻接 EXIT validator；复用其窄
  FrameRules 与 state shape 原则即可。body DEL/rebind 仍在 Attached，终态 drop 在
  body Detach/terminal commit 后；traceback 后续 drop 保持其当时真实位置。

**宽 raising wrapper 的决定：**使用普通 INVOKE，不附本窄 tag；NORMAL/RAISE 保留
真实 partial effects，失败不 rollback 先前 commit/已掉引用。若展开其真实 helper
Region，只有准确的内层窄 reference-drop 点带 TerminalFrameRelease。若保持 opaque，
未知完整效果已经能表达它，不虚构一个额外 drop 或声称已验证内部释放阶段。
因此不需要第三类混合 rules，也不会把显式 close/lookup/adapter 错误吞成 unraisable。

## 6. unknown callback 后的 release 资格：不借历史锚猜 ownership

从现 BodyOutcomeCommit 的真实 Return/Raise 或 typed NoBodyFinish 成功边，派生
`HistoricalFinish(anchor, owner)`；Suspend、host exhaustion/request COMPLETE 都不种下。
多锚合流由 canonical CFG 按实际 incoming 的 owner Use→formal 关系派生；不存
source/completion tuple，不要求共享 release 只能关联一个 anchor。

D2 能力合同补足一个**固定适用条件**，不增加可写 proof 字段：

> DriverRule.PYTHON_RESUMPTION_V1 的本 D2 解释限于实际 direct native resumable
> owner，保持同一对象/生命周期；无外部 native reset/替换该 owner 的 continuation，
> 并满足 FrameRules.NO_FRAME_INTERPOSITION。它只规定同一 native activation 的真实
> terminal completion 不能由普通 Python callback 复活，不规定 mutable session 或
> request 关联不变。对应 callable/实现/对象条件由 interface.rule 的来源在 D3 验证。

旧 FrameRules 的“active frame”条件不能单独证明 custom wrapper 永不替换内部 body；
上面 direct-owner/no-reset 限制是 D2 固定能力合同的一部分，D1-only 解释不被改写。

在此**有条件模型**中，普通 unknown callback 后：

- 历史 Finish 仍发生；同 owner 续体不可复活的性质可依固定条件保持。必须保持
  owner 的准确路径 copy、当前全域 state 与已完成 body 的 Detach/context 接线。
- session/occupancy/current association post 按§4失效，不能从 Finish 重新补回。
- **完全不推出 frame still-held / 某 bundle尚未drop。**TerminalFrameRelease 只是
  真实阶段/尝试，NOT_GUARANTEED，故其合法性不依赖一个臆造的 ownership 余额。
- 若 source 含不满足 no-reset/direct-owner 条件的 C/native 行为，typed D2 对应不能
  授 runtime 适用；程序仍可完整表示为普通 effectful boundary。不是给它伪造一个
  Python RAISE，也不是说历史事件被撤销。D3必须报告条件不适用/未证。

当前声明验证只保证这些关系在声明的有条件协议下自洽，不替代 actual runtime guard。
不新增一次性许可、不把某个 unknown world version 当 frameownership 证明。

## 7. 机械验证、合法合流与验收反例

先 core/C1/C2B/D1 验证；在启用 D2 的 driver 内派生完成锚和 owner 的路径关系。
SessionUpdate 后置是独立版本谓词。既有核心 operation/current/edge 仍为唯一实际源。
多 incoming 必须逐路保留 anchor-owner 相关性，不能用 origin 集合相等代替当前 copy。
loop/reentry/new admission 重置当前 P/局部 visit，不自动抹掉同一 Reference incarnation
已发生的 terminal F 历史。定义点重新执行及真实 edge 的 simultaneous actual→formal
overwrite 时，忘记被覆盖 carrier 的旧对应、按本次实际来源重建；不能顺序改写 phi
而污染其他槽，也不清掉仍由别名 carrier 承载的同 owner 历史。**不增加 release consumed 位。**

| 必须接受 | 必须拒绝/不授结论 |
| --- | --- |
| A元数据→真实callback helper，post只在A after成立 | 回调新态仍继承A的COMPLETE。 |
| B helper在callback后实际重建post，NORMAL绑定最终版本 | 只先写post后被回调改掉，却标B正常后置。 |
| helper source RAISE触发清理，清理自身另有NORMAL/RAISE | RAISE后回旧world；断言RAISE意味着先前没写。 |
| AWAIT/HOLD，ASYNC_YIELD/COMPLETE且body仍Suspend | request COMPLETE/host StopAsyncIteration被当body Finish/drop锚。 |
| Return/Raise各commit后合流共享窄drop | Return/Suspend混合借Return锚授权全部路径；交换B1/B2 phi仅集合相同。 |
| 未知callback后准确同owner的条件性terminal历史仍可关联drop | 从这段历史推frame仍held/session仍active/native closedbit等于所有状态。 |
| 两个实际terminal-drop尝试均按当前state、合法idempotent | 仅因两个tag同owner/anchor判非法/冗余；或第二个用旧state。 |
| body DEL、不同bundle、traceback后来drop各在真实位置 | 将它们全当同一个终态bundle、后移body DEL或宣称对象free。 |
| 普通finalizer抛错走unraisable且外层pending保持 | 把显式close/adapter真raise吞掉，或把unraisable变宿主RAISE。 |
| 可能不完成的callback路径不造host结果 | 强迫所有release终止/产生假completion以便验收。 |

其中 source/native 实际保证属于 D3：structural tests 用有类型声明正反图核对字段/
连接，不能由 self-written IR “证明”真实 native 回调后重建了 post。

## 8. 迁移和查询的确定决策

- 增加显式每 driver D2 capability scope；本批新增表走下一 schema v12。v1–v11
  拒绝 D2 新表（包括空表）；无 D2 的旧图原 wire 保持，v11 D1 不被要求补 commit。
- D2 records 没有 scope 则拒绝，不能静默降级丢表；启用 scope 才运行这些义务。
  Scope/其余 commit/no-body表由根代理统一，不能由 SessionUpdate 字段冒充 scope。
- 查询只返回原 owned UseSite、derived current post support、derived finish alternatives
  及规则条件；不新增真实 producer，不将 FrameRules.UNKNOWN 改为 PROVEN。
- CLI 可以报告 declared lifecycle structure 已验，但 runtime/source/frame-stability/
  physical release/transform 仍 False。D3实际适用是后续证据门，不是本字段待定义项。

## 9. 证据与交付边界

不重复上一轮3组断言：`model_driver_lifecycle_design/review/session_release_probe.json`
SHA256 `23cf7fa00002d00eedff33234692e501ec58464ad1d0bee396c5ed00a419818f`。
已测普通helper的“先写后callback改写仍NORMAL”、“先写后RAISE保留写”、
“unraisable保留pending及真实写”；它们不是内置asend实现证明。
原8组终态/body DEL/traceback/Created-close证据同样保留原档不重跑。

本轮把字段、两种绑定、版本失效、drop固定scope、unknown callback后的条件性稳定、
合法合流/重复尝试和迁移作出确定建议。没有新增产品实现或声明D2.0已验收；根代理
可据此与其他审查合并冻结，而无需再引入任意native名字或通用历史权利系统。
