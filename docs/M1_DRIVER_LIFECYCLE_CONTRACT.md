# D2.0：生命周期字段、来源与派生规则

2026-10-18；审查基线 `8ee8d02`。本文件收敛
[生命周期复审](M1_DRIVER_LIFECYCLE.md)的字段与算法；是声明层合同，不是产品验收。
产品按D2.1→D2.4实施；完整C2、D3、M0–M2及source/runtime对应仍独立验收。

## 1. 规范来源及适用范围

五类核心实体不变。下列records引用既有Operation/Use/Value/StateAccess/CFG；不
定义另一份actual、producer、before/after world、可传递许可或request历史状态。
driver全域D从entry状态参数派生，生命周期域L从DriverInterface取得，∅≠L⊆D。
规则及provider来源仅从该DriverInterface.rule取得，禁止函数名/业务名分派。

新增显式DriverLifecycle scope后，本声明合同的固定条件为：实际direct native
resumable owner、同一对象及生命周期、同一activation不可由普通callback复活，
不存在外部native reset/替换continuation，并满足FrameRules.NO_FRAME_INTERPOSITION。
该条件限制的是本合同的适用，不是任意程序的可建模性。custom wrapper/native reset
仍能用普通有effects的区域/边界表示，但不能借本合同获得terminal稳定性。

这些条件、callable/版本、真实字段与guard对应仍未证。声明校验通过不把UNKNOWN
改成PROVEN，不授权任何优化，也不修改旧D1-only图的解释。

## 2. 冻结的字段

```text
DriverLifecycle(region: RegionID)
DriveOutcomeRef(drive: OperationID, source: OperationID)
BodyOutcomeCommit(operation: OperationID,
                  outcome: DriveOutcomeRef, instance: UseID)

CreatedCloseTest(operation: OperationID, instance: UseID,
                 scheduler_request: UseID, effective_request: UseID,
                 session: UseID | None, result: ValueID)
NoBodyFinish(operation: OperationID,
             precondition: ControlEdgeReference, instance: UseID)

LifecyclePostBinding = AFTER_OPERATION | NORMAL_COMPLETION
SessionPost = HOLD | COMPLETE | ABANDON
SessionUpdate(operation: OperationID, request: UseID, body: UseID,
              binding: LifecyclePostBinding, post: SessionPost)
TerminalFrameRelease(operation: OperationID, owner: UseID,
                     rules: FrameRules = FrameRules())
```

records为frozen/slots、exact IDs/enums/tuple，递归重验嵌套记录；无verified/consumed/
drop_once/phase字符串。ControlEdgeReference复用现structured接口，不造同形第二类。
没有SessionUpdate.source或TerminalFrameRelease.completions可写清单。

DriverLifecycle必须定位已有DriverInterface；其scope内每条有限BodyDrive source
恰有首commit；新metadata必须在启用scope内。同一operation不可承担相冲突角色。
原v11无scope图继续按D1合法，不能静默升级生命周期范围。

## 3. body publication及状态覆盖

BodyOutcomeCommit.outcome引用本driver中真实BodyDrive的实际source successor，
commit是其私有landing首操作。种类从真实source派生：Suspend仅发布暂停；
Return/Raise发布该continuation结束。空frontier不造commit或虚假完成。

instance是本操作独立REFERENCE Use，等于Drive.instance的原Value，或来自该
source边独立forward Use→formal的精确copy。不能把BodyDriveResult同类型payload
认成owner，也不由Create集合或同Location猜身份。

commit是无callback、无retain/drop/lookup的ordinary intrinsic：无call、terminator、
completion；行为为CONTROL/READ/WRITE，effects_complete=True。其Uses仅instance与
各实际StateAccess.before；结果恰是实际写的after。所有访问为L内WHOLE READ或
READ_WRITE、非full_overwrite；非空写集W⊆L。不强制W=L，不给未写域捏造after。
state-selector可保持coarse；精确reference若存在仍须通过原core别名检查。

publication明确不修改request phase、R/B association或任一方session occupancy。
它不完成session、不放弃引用；有新StateVersion不证明真实body字段更新。实际字段/
owner-selector与native操作对应留后续来源门。D\L及未写域沿原CFG保留current。

## 4. no-body：真实bool分支，不制造异常

CreatedCloseTest是ordinary无callback只读intrinsic，读取L每域当前状态，结果恰为
自己的一个builtins.bool DataValue；行为CONTROL/READ、effects_complete=True。
Uses恰为独立角色Uses与READ before，结果/访问均在原core定义。
它紧邻同block末尾BRANCH，其bool结果直接成为condition。

**统一核心BRANCH的既有约定：successors[0]为true，successors[1]为false。**
两个已有source lowerer一直按(yes,no)生成边；在核心文档明确此含义，不改变wire。
不在D2加true_successor_index让overlay重新解释同一条core分支。

NoBodyFinish.precondition只能指上述BRANCH的edge0，私有landing首操作即mark。
owner可直接用仍dominating的原instance Value，或沿独立edge Use→formal精确转发。
其shape/非空W⊆L/body-only语义与§3一致；没有body Return、Attach/Detach或假异常。
test→branch→mark之间无其他操作/写入/callback；false沿实际替代路径继续。

角色不混用：

- BODY：instance是interface.receiver的must-copy，S是interface.scheduler的must-copy，
  effective_request是S的独立Use，session=None。
- ASYNC_REQUEST：session是interface.receiver的must-copy，S仍是固定scheduler，
  instance和effective_request均须有真实Reference/RAW来源。predicate的true合同
  包含当前R/B/latent关联及当前step适用性检查；可复用实际AssociationRead端口，
  不强迫必须有独立read站点，不从同类型/同名补造值。R/S/B/E各角色Use独立。

错association、非CLOSE、非CREATED通常使这个检查false，而不是图类型错误；
不能为它们制造RAISE。E与S同Value也不天然非法。predicate的实际实现/纯性须
独立证实；typed true声明不是运行时guard已执行。外部instance、多Create均保留。

## 5. session后置与窄引用放弃

HOLD表示R对B的活动session仍可按协议继续；COMPLETE表示该R协议终结且不再持有
该活动占用，但仍可强引用B；ABANDON仅撤回该活动占用，不保证R终结/可复用。
它们不代替完整family状态表，不推出body终结或资源ready。

AFTER_OPERATION：普通无callback CONTROL/READ/WRITE、complete；仅R/B与L状态Uses。
L每域一条WHOLE READ或READ_WRITE、W非空、结果仅after。后置支持版本为L的完整
当前组合，写域取after，READ域取before。NORMAL_COMPLETION：真实unknown INVOKE，
R/B在invoke_arguments；消费D全域，NORMAL/RAISE均产生D后态。后置只绑定最终
NORMAL的L状态formals；其合同要求所有内部callback之后确实重建/保持该后置。
RAISE保留部分写，不承诺post成立，也不承诺没有发生。无此保证时保留普通INVOKE。

TerminalFrameRelease固定为真实终态owner-frame引用放弃/转移阶段/尝试，普通非call/
nonterm、READ/WRITE/MEMORY、effects_complete=False；仅owner与D每域current Uses，
每域WHOLE READ_WRITE、非overwrite、结果仅真实after。FrameRules固定不变：条件
未证、若条件适用且完成则保留pending、unraisable、unknown effects、可能不完成、释放无保证。
它不证明仍held、耗尽/free或ready；同owner两个tag不自动非法或冗余，没有consumed位。
宽raising wrapper保留普通INVOKE，不冒用本窄规则吞异常。

物理组合操作可以经既有provider关系对应同一次执行的区域分解；不是再执行两次。
不为了凑字段把同一个core操作同时赋予相冲突的body-only与session更新合同。
body DEL、frame终态清理、traceback后来drop仍在各自真实位置，不套同一bundle证明。

## 6. 高效派生：先沿边改名，再合流

### 6.1 历史terminal性质F

使用有限must分析，不枚举所有执行路径或配置。每个可达程序点有当前Reference的
must-equality关系E，以及每个carrier的must-finished性质F。F成立才附带可能来源集合
用于解释；来源集合不是独立owner集合或许可。未证相等不表示不相等。

1. 真entry种子只有引用自反关系，无F；不可达bottom与“可达但无F”不同。
2. 定义结果/重绑entry formal时先forget旧静态ID所代表的incarnation。沿每条真实edge
   snapshot旧E/F，**同时**赋值actual→formal，并在该边恢复已证alias闭包。
3. 对reachable incoming重命名后的E取交；F仅在所有incoming同一carrier均成立时
   保留，再union其可能来源用于解释。不能先分别unionowner/origin再配对。
4. Return/Raise commit与真实NoBodyFinish种下owner等价类的F；Suspend不种F。
   后续准确alias可承载先前F；重定义一个ID不抹除其他仍存alias的性质。
5. 本固定no-reset条件下，普通unknown callback、新gate不会撤销已发生的terminal
   历史；它们不从F得到当前occupancy/ownership。newgate不凭空种F。
6. 窄release只要求其当前owner有F及原core current-state正确，不消费F，不要求唯一锚。

这支持“不同完成来源→对应owner phi→共用release”，而交换未finished owner的
edge actual会在改名后丢F。无种子loop不会造F，静态ID循环复用不会继承旧incarnation。
实现分两阶段：先固定E与F的布尔must解，再在这个固定解上求解释来源T的有限union
最小不动点。T只通过常量源、copy/同时改名、forget清空与union传播，不参与F真值或
release资格。不能把terminal重置来源与E/F联合解释成同一个简单单调格。有限关系/
性质工作队列收敛；不推一般bool路径可满足性，精度不足不授优化权限。

### 6.2 当前session性质P

P按本路径R/B、post及当前L支持版本派生，同样先edge同时改名后逐incoming取must。
普通READ保持；触及支持域的未知写、callback/helper、body计算的新状态默认失效。
SessionUpdate按§5建立准确after/NORMAL性质。固定body-only publication/NoBodyFinish
不改request phase、关联及occupancy，可把**已有**P支持重基至新版本，不生成新P，
也不声称world内容相等；CreatedCloseTest只读保持。无用户可写preserves_post标志。
历史F与当前P独立，F不会补回已失效P。所有结果均派生，不写回ProgramGraph。

## 7. 实施、wire及验收界限

按原D2.1–D2.4门实施每条实际连接、正反图、query、codec和CLI。D2.1先交付
DriverLifecycle与BodyOutcomeCommit及原Use/state/source查询，不加未接线的其他表。
该能力使用schema v12；后续新增能力再显式版本化，不借旧版偷带新字段。
无新能力的v1–v11保持原字节。查询/CLI区分body publication声明、完整D2声明、
实际source/runtime/稳定性与transform；前者通过不使后者为真。

验收覆盖原D1路径、Return/Raise/Suspend、L≠D、W⊊L、coarse alias、空/发散frontier、
多Create/外部instance、错source/owner/state、错误分支成功边、共享合流与错接、
循环重定义、unknown写后P失效/F保留、两种session绑定与partial RAISE、窄/宽drop。
source/native真实条件与完整family协议属于D3，不用自写IR证明实际native正确。
