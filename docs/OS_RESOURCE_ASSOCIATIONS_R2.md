# R2 最小资源限定关联：设计与静态实现

2026-10-23。R2.1类型、版本门控、validator和窄refinement adapter已实现，原35port与
少量executor已完成有限实档核验。原gate在全部检查后metrics footer报错exit1；独立
finalizer核已存收据后exit0，两者分别保留。collector和R1 OS producer未修改。
R1已发布的369749产物保持原样；完整模型仍OPEN。

## 1. 具体问题与最小边界

R1保留1,067,768个实际syscall WorkSubmission和35个新增FD producer ports。
现有`NativeHandle.value`要求ValueOccurrence；`ResourceAccessBinding.operation`及其
RequirementBinding要求canonical operation/activation，`WorkSubmission.executor`仅
接受该canonical ResourceAccessID或Unresolved。因此实际已知的FD target、thread
executor不能独立形成完整typed关联。

新增限定关联先表达外部证据，随后显式对应source。保留旧canonical record的原含义，
资源状态继续属于原StateLocation/StateVersion/Access体系；恢复算法内部的临时FD表
只是证据回放工作区，不是第二套可修改IR。

R2.1设计为**三个record（含一个明确的存储selector）、一个typed ID、一个关联表**，
不实现共享FD或完整VM解释器。selector不伪装普通JSON pointer，见2.3节。

## 2. 两个record

### 2.1 ProviderHandle：已观察到的句柄selector

加入既有`HandleEndpoint` union，保留ObjectHandle/NativeHandle/UnresolvedHandle：

```text
ProviderHandle
  namespace: HandleNamespace
  container: InstanceTarget | Unresolved
  selector: ProviderRecordSelector
  lifetime: NativeHandleLifetimeID
  source: FactSource
```

- selector复用R1 publicreader的实际chunk artifact、line、pointer_within_line及table/
  ordinal收据。例如line=N且pointer_within_line=`/record/created_handles/J/fd`。
  `#/lines/N/record/...`不是原gzip JSONL的普通JSON pointer，不能这样声明。
  同时保留原syscall receipt的source。
- container是一个既有ResourceInstance表示的HANDLE_TABLE incarnation。增加通用
  `ResourceRole.HANDLE_TABLE`（ResourceKind.OTHER），不以TID/ProcessID代替表身份。
- 已证明的exec/unshare/私有子进程区间可引入table resource；共享/继承表身份尚未
  恢复时只让container保持Unresolved。producer port已知的FD/target仍可typed保留，
  不因缺canonical ValueOccurrence而丢失。
- lifetime以实际producer/assignment receipt与原port限定。观察generation计数不是
  完整内核历史，更不是LogicalVersion；相同FD不能跨table/赋值代次合并。
- 复用原HandleBinding，把provider selector接到原ResourceTarget。不得制造DataValue、
  UseOccurrence或source operation。将来有真实源值路由时再添加限定对应。

### 2.2 ProviderResourceAccess：外部work到实际资源的一等关联

```text
ProviderResourceAccess
  id: ProviderResourceAccessID
  work: WorkTicketID
  purpose: EXECUTOR | INPUT_SELECTOR | OUTPUT_SELECTOR
  target: ResourceTarget
  handle: ExplicitHandle | ImplicitBinding | Unresolved
  point: EvidencePoint
  selector: ProviderRecordSelector
  source: FactSource
```

新增ExecutionModel表`provider_accesses`，并进入原TABLE_TYPES；没有新的图容器。
这个record是一条既有work/resource之间的限定关联，purpose是观察端口角色，不能
从INPUT_SELECTOR推出读取了完整内容、纯性或canonical StateAccess。

`WorkSubmission.executor`扩展为：

```text
ResourceAccessID | ProviderResourceAccessID | Unresolved
```

旧ResourceAccessID继续只表示canonical access。新ID分支必须指向同一ticket的
purpose=EXECUTOR关联，其target为已验证的ThreadTarget或其他真实EXECUTOR资源。
当前OS DirectExecution的已知native thread能直接提供这个关联；实际CPU core、
设备内部执行器和GPU ready没有因此被推断。

FD输入/输出通过同一`provider_accesses`表关联ticket、原HandleBinding及原target。
首次只对已证明的private interval或实际producer output建边，其他选择器保留前沿。
Queued、WorkRetention及content协议未在R2.1使用的新ID能力暂不扩展，避免未实现的
能力借新union进入旧协议。

### 2.3 ProviderRecordSelector：真实JSONL记录定位

此窄record只描述已经发布的表记录，不包含动态import或可执行查询：

```text
ProviderRecordSelector
  chunk: ProviderFactReference
  table: str
  ordinal: int
  line: int
  pointer_within_line: str
```

chunk引用的是**原manifest中真实存在**的JSON pointer，例如
`#/tables/observations/chunks/K`，其artifact为原manifest的logical URI、stored SHA、
bytes、storage schema。该manifest成员声明实际chunk URI与stored/decoded receipts。
line是一基JSONL物理行，ordinal是原table ordinal；pointer_within_line只对该行
独立JSON envelope解释，例如`/record/created_handles/0/fd`。

OS侧提供窄公共resolver，接收显式原`OSInterfacePartitions`与selector：核manifest
receipt、真实chunk描述、table/ordinal/line对应，整chunk hash后解析选中行，再应用
行内pointer。返回值和原reader locator必须一致。不从selector URI任意开文件，不
把定位成功写成资源身份/效果证明。IR构造器只校类型/范围，不引入trace依赖或读盘。
resolver按chunk分组或有限缓存，不能为每个port反复扫描整个1.7GB observation表。

ProviderRecordSelector是当前manifest+JSONL协议的**证据定位**，不是资源的规范身份，
也不是所有provider的通用地址。CUDA或其它provider的复合token不能被core当作POSIX FD
验证；core只核限定namespace/container/lifetime/端点及selector关联，FD非负整数域由
OS adapter核。其它格式需要显式locator variant、capability与其公共resolver，不能
伪装JSONL行或把其token等同ResourceInstanceID。

core规范Resource/Work/Object身份仍引用原ID，不由selector文件名、table ordinal或
chunk行号生成/替代。当前adapter为新增的证据关联生成base限定局部ID，不能将这种
receipt-local关联ID误当物理资源身份；原ResourceTarget与WorkTicket始终保原ID。
rechunk/搬迁改变证据定位时需要新的显式receipt映射，不能据此重命名或合并资源。

## 3. 类型、codec与validator修改清单

| 文件 | 最小改动 |
| --- | --- |
| `execution/ids.py` | 新ProviderResourceAccessID，独立于canonical ResourceAccessID |
| `program/resources.py` | 通用HANDLE_TABLE role及其kind约束 |
| `program/codec.py` | ProgramGraph v28 capability；旧1..27显式拒绝新role |
| `execution/resources.py` | ProviderRecordSelector、ProviderHandle、ProviderResourceAccess与purpose enum；只扩HandleEndpoint |
| `execution/work.py` | 仅executor union增加新ID |
| `execution/model.py` | provider_accesses tuple与TABLE_TYPES注册 |
| `execution/codec.py` | 新capability version9；旧1..8继续支持并拒绝新variant |
| `execution/validation.py` | 新表索引、ID唯一性及原artifact/point引用扫描 |
| `execution/resource_validation.py` | 新handle的namespace/container/selector/lifetime及原target FK |
| `execution/work_validation.py` | executor按canonical/provider ID分派；核ticket/purpose/target/Run/process |
| `trace/os_resource_refinement.py` | 显式新adapter/片段schema，保留R1 producer/artifact不覆盖 |

公共selector resolver已放在新adapter，复用原OS reader的manifest与wholechunk verifier，
无需修改R1 reader/producer，也不构建通用查询/重写引擎。

公共`record_codec`由显式类型递归解码，无须增加运行时registry或动态import，也不
计划改其通用实现。带版本的`execution.codec`必须严格处理：

- 新表在version<9的record schema中排除；旧wire不增加空字段。
- HandleBinding.handle与WorkSubmission.executor在version<9仍使用旧union，防止
  新tag通过旧版本的reachable vocabulary泄漏。
- HANDLE_TABLE enum成员也需显式capability gate；仅把SCHEMA_VERSION改为9不够。
- 新记录只做constructor/引用/合同一致性验证，不能顺带授权身份、可见性或释放。

新provider access validator必须检查：同一WorkTicket、原Run；已知process/thread
一致；selector来源为显式receipt，handle target与access target相同；container存在
且属于对应namespace/table incarnation；旧canonical use/requirement验证保持原路径。
过程/表身份未闭合应给具体关系前沿，不能抹掉已经核实的selector和target。

## 4. 首个真实闭环验收点

使用已发布R1产物离线产生不可变关联delta，不重跑22分钟CLI、不执行目标：

```text
原13 pipe2 / 5 eventfd2 / 4 epoll_create1 receipts
  → 35个原有序producer port
  → ProviderHandle + 原HandleBinding
  → ProviderResourceAccess(OUTPUT_SELECTOR)
  → 原WorkTicket / ResourceTarget
```

pipe两端必须仍是不同target/lifetime。能证明private FD选择的read/dup/close才继续
接输入关联，不跨共享表猜绑定。已知native-thread的work可用EXECUTOR关联接
ThreadTarget，当前未归属actor的3340个观察仍保持原None，直到独立context补全。

验收分开核完整delta分母/端点/原locator、全部wire关系与实际结构分支codec，
不再次逐百万调用未改codec。不得宣称canonical effects、内容版本、GPU completion或
全ExecutionModel语义已闭合。资源state与source对应仍是后续明示工作。

## 5. 另一最小补全：祖先/context actor

本capture的唯一未接target ancestry actor是369747。原raw第一行是完整外层collector
exec；coords.seed.target_birth引用同raw的3310行。archive精确URI/decoded SHA/bytes已
核；这说明raw存在。当前只从target向下展开clone闭包，所以创建者context未进入
process/thread membership，不应当作缺失raw或用PID大小推断归属。

可独立实现通用的**双向出生因果+启动声明**闭包，角色明确区分TARGET、
TARGET_DESCENDANT与ANCESTOR_CONTEXT：

1. 从已核target exec/birth出发，birth原receipt提供创建者actor与子TID。
2. 在同一原per-actor trace内找被完整保留的context exec/启动声明；用原行序与生命周期
   前沿限定，不按不同文件timestamp排序，不根据scar/LeWM/可执行名匹配归属。
3. ancestor身份以Run+原exec/birth evidence限定，增加context membership；已有Run、
   target/descendant身份不因扩充context而重新编号。
4. ProcessInstance、HostThreadInstance和数字TGID分别证明：原provider TID不是TGID。
   无CLONE_THREAD的已核birth可证明子进程线程组；父TGID必须有launch/内核/状态receipt。
   若只有实际context actor/process存在而没有数字TGID证据，ProcessInstance.pid可为None，
   继续保留真实thread selector，不编造TID==TGID。
5. 原profile只把pid_for_tid成员写membership。新profile应显式列全部已验证OS artifacts
   与各自actor role、process-bound/unbound及证明收据，避免消费者将缺membership等同缺档。

这是坐标建模的独立证明增强，不能把parent整个trace的最终FD状态复制给child。
FD-table snapshot只能取实际出生点的已证明状态；并发共享/未捕获actor、VM映射和
完整线程生命周期继续单独处理。当前冻结capture_coordinates模块未修改。

## 6. 仍推迟的内核状态解释

共享FD表、copy-on-fork、CLOEXEC/F_SETFD与OFD offset分离、partial munmap/mremap、
VM backing/extent、epoll interest state、driver内部协议属于R2.2及以后。它们应连接
本节新增的typed端点，状态使用既有state体系，不能把“可表达”写成“已证明”。

## 7. R1 base与不可变refinement片段

R1是原资源/work片段，**不是完整ExecutionModel**。R2不创建fake ProgramSnapshot，
不将片段to_dict冒充完整model，也不把同一ID的原/精化record都放入同一权威表。

使用一个窄OS association refinement artifact，显式绑定原R1 base manifest的
logical URI、stored SHA/bytes（当前SHA `cbc6dcfd…aec14`）与fragment/profile版本。
每个所引用的HandleBinding/WorkTicket均由原table/ordinal/真实chunk+line定位，
核原typed ID，并绑定原行preimage收据：base manifest SHA、该chunk两层SHA/bytes、
原line/ordinal、原整行SHA。原行SHA直接取已验证的JSONL bytes，不重新编码10GB数据。

片段只允许三种明示内容，采用固定字段的专用adapter：

1. **新增关联**：新ProviderResourceAccess、必要的HANDLE_TABLE ResourceInstance。
   ID与base既有表无冲突，端点引用原精确ID/selector；不修改base。
2. **HandleBinding精化**：绑定其原preimage，仅允许原UnresolvedHandle端点换成已证
   ProviderHandle；id、target、start/end、rights/ownership、source均保持原值。不能
   顺带延长生存期、改变target或宣称权利。
3. **work executor精化**：绑定原WorkSubmission preimage，仅允许原Unresolved
   executor换成同ticket的已证ProviderResourceAccessID。其他字段必须逐项保持。
   不复制其余完整record到delta，不改effects/dependencies/retention/quiescence。

最终组装使用只读、有条件的选择视图：给定base+指定refinement，原record先核
preimage；有且仅有一条满足合同的精化时，流式产生一份替换后的record，否则使用
原record。preimage漂移或多条冲突精化必须拒绝/报冲突，不能按最后写入覆盖；最终
每表每ID仅一份record。原base保留但不同时作为第二份权威record进入组合模型。

这个选择视图不是已构成的ExecutionModel，不运行一般patch指令或任意字段改写。
以后只有真实ProgramSnapshot/source拼接与正式validator可用时才组装完整model。
没有source snapshot时继续输出限定片段/已核引用与具体前沿。

首次35port闭环只读取必要R1表/selected chunks，使用已有WorkTicket身份与准确
原record定位；新增delta和选择收据即可，不重导22分钟CLI，不重新输出整个10GB
规范表。大范围executor关联可流读必要的原work表一次核preimage，仍不复制base。
原R1 frozen artifact与producer均未修改。R2.1静态实现范围见第8节；共享FD/VM和
ancestor/context算法尚未实现。

## 8. 本轮静态实现与待授权gate

### 8.1 共享Enum的双层capability门控

ResourceRole定义在program层，generic record codec会解码其所有成员；只改execution
版本不足。当前实现采用显式ProgramGraph v28：仅实际resources/requirements出现
HANDLE_TABLE时选择28；旧1..27在返回graph前拒绝该typed role，普通字面量字符串不受
影响。无新role的图仍选择原capability版本/字段。program validator本身不带wire
version，继续检查真实resource origin/owner/FK/kind-role，HANDLE_TABLE必须OTHER。

execution v9只在新provider access/handle/executor或新role出现时自动选择；显式旧
version拒绝新capability。旧schema的HandleBinding/WorkSubmission字段仍使用旧union，
新table和新tag不可通过旧reachable vocabulary进入。resource role在execution编码/
解码也有单独版本门控。公共record_codec本轮未改。

### 8.2 实际API

```python
from scar.trace.os_resource_refinement import (
    OSResourceBase, OSResourceRefinement, build_os_resource_refinement,
)

base = OSResourceBase(original_r1_manifest)
selector = base.selector("observations", original_ordinal,
                         "/record/created_handles/0/fd")
selected = base.resolve(selector)
receipt = build_os_resource_refinement(base, fresh_output,
    executor_observation_ordinals=explicit_few_ordinals, progress=callback)
view = OSResourceRefinement.read(base, fresh_output / "manifest.json")
one_record = view.record("handles", original_handle_ordinal)
```

原observations只流读一次保created port与真实envelope ordinal；handles/resources
各查一次原小表。原work按manifest ordinal/chunk有界point read并核实际ID/entry/Run/
process，不按邻近记录猜。两端口同一work复用已核收据。chunk cache默认2、最多8，
每个chunk原独立reader budgets不变；没有新gzip/JSON encoder框架。

本轮只绑定原manifest发布路径；不提供“同hash就换logical URI”的override。已发布
refinement在迁移后需另外提供可核的retention映射适配，当前不静默变更其namespace。

当前默认预算是2M observations、128个declared created_handles ports、8个显式executor
选择、4MB refinement document；超限拒绝，不发布假完整结果。scope只覆盖R1的
created_handles声明和所选executor，不声称恢复所有open/openat或输入依赖。

所有base Work/Resource/Thread引用都带原selector+行SHA+typed ID，不在delta复制
另一份权威base表。两种固定精化保持原ID及其他字段；view只返回一份原/精化record。
新增provider access有独立ID，回指准确原work及target，型别/前像/端口全在原base下核。

### 8.3 精确保留的缺口

R1没有输出FD-table incarnation原receipt，单个table_status或TID不能补成table身份。
因此本轮真实port的ProviderHandle.container仍明确Unresolved，同时selector、原OFD
target和handle lifetime能合法成为typed关联；没有因为缺canonical ValueOccurrence
丢失这些已知事实。HANDLE_TABLE类型门控已实现，但不凭旗标制造实际table实例。

当前adapter只建立OUTPUT_SELECTOR和所选EXECUTOR；INPUT_SELECTOR类型可表达，依赖
恢复仍拒绝。源state/effect、共享FD/VM、ancestor补全、ProgramSnapshot和完整模型均未
因此建立。完整ExecutionModel validator可显式传只读provider_selector_resolver；未
提供时保selector bytes前沿，不用缺省成功掩盖证据。窄fragment gate不创建假snapshot。

初次冻结只完成11个代码文件AST检查与源码审查；随后按授权执行一次原35port差量/
少量已知executor实档gate，实际范围及运行缺陷见第9节。没有重跑22分钟CLI/目标或全suite。

## 9. R2.1 实档核验与报告冻结

实验：`artifacts/experiments/first_stage_os_resource_refinement_20261023/gate-attempt01/`。
输入是原R1 `cbc6dcfd…aec14` manifest，代码为6e6b67b+revised-freeze补丁，11个模块
逐字节核对后才import。第一次static-freeze与FD核心修正后的revised-freeze均保留。

### Implemented

3records/独立ID/新关联表、ProgramGraph28与Execution9双门控、只读selector resolver、
两种固定preimage精化。core不限定FD token域；OS adapter验证实际FD非负整数。没有
新增optimization/backend、target执行、共享FD/VM/ancestor算法或假ProgramSnapshot。

### Verified（有限范围）

- 原35个created ports全部接原HandleBinding、OFD target与新provider handle/access；
  22个原producer work，13组pipe双端target/FD/lifetime均不同。
- 从原已发布audit实际locator选3个known process/native thread观察，建立3个executor
  关联，只精化executor字段；其他Work字段及UNKNOWN coverage保持。
- 35个handle精化只改变endpoint；原ID、target、start/end、rights/ownership/source
  逐项保持。未精化record仍返回原BASE，单表/ID没有两份权威record。
- 所有实际selector及原preimage经public resolver核原manifest、整chunk两层SHA、
  line/ordinal、行SHA和行内pointer；35port不是从原raw OS再导入。
- 新record公共codec roundtrip：35个ProviderHandle、73个ProviderRecordSelector、
  38个ProviderResourceAccess。actual HandleBinding经execution record codec v9往返。
- 6个旧版本负例明确拒绝：execution8的新handle encode/decode及新role encode/decode，
  ProgramGraph4/27的新role负wire。负wire不是被接受的程序图或snapshot。

产物是**443,446bytes**的窄refinement，SHA256
`6b5e1ae12e2c05364c76364cf1b1cf7859d2f6ddb09380c8940a3980381bde5c`。
扫描R1 observations一次1,067,768records，再按chunk point-read原work/preimages，
没有重导22分钟CLI或重写10GB规范表。

### Observed：原gate footer缺陷

原进程wall **55.03秒**、peakRSS **592,948KiB**，实际exit **1**。它已写BUILT、
ENDPOINTS_PASS、35条selector-proofs和6条codec-boundaries，之后汇总metrics时局部
`resource`字典覆盖stdlib resource模块，导致AttributeError。原脚本、producer、
traceback、time与日志完整保留，生产adapter未因此修改，也没有重跑gate。

独立`finalize_report.py`只核已发布delta/proofs/time，实际exit **0**，wall0.05秒、
peakRSS18,484KiB。`finalized-summary.json`和completion receipt分别记录gate1/
finalizer0，状态为VERIFIED_SCOPE_WITH_ORIGINAL_GATE_REPORTING_FAILURE，不把原进程
改写成PASS/exit0。源码依然保持revised-freeze。

### OPEN

35个table container仍Unresolved：R1没有精确table epoch receipt。没有恢复INPUT
dependencies、共享FD/VM或ancestor，也未验证完整ExecutionModel语义；ProgramGraph28
正向完整图组装未在此gate执行。Resource/Work/State原义保持，完整模型和优化授权均OPEN。
