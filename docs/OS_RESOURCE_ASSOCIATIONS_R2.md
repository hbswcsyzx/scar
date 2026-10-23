# R2 最小资源限定关联设计（未实现）

2026-10-23。本文件是设计审查输入，未修改IR、codec、collector或OS producer。
R1已发布的369749产物保持原样，实际audit状态另见该实验报告；完整模型仍OPEN。

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

## 3. 类型、codec与validator修改清单

| 文件 | 最小改动 |
| --- | --- |
| `execution/ids.py` | 新ProviderResourceAccessID，独立于canonical ResourceAccessID |
| `program/resources.py` | 通用HANDLE_TABLE role及其kind约束 |
| `execution/resources.py` | ProviderRecordSelector、ProviderHandle、ProviderResourceAccess与purpose enum；只扩HandleEndpoint |
| `execution/work.py` | 仅executor union增加新ID |
| `execution/model.py` | provider_accesses tuple与TABLE_TYPES注册 |
| `execution/codec.py` | 新capability version9；旧1..8继续支持并拒绝新variant |
| `execution/validation.py` | 新表索引、ID唯一性及原artifact/point引用扫描 |
| `execution/resource_validation.py` | 新handle的namespace/container/selector/lifetime及原target FK |
| `execution/work_validation.py` | executor按canonical/provider ID分派；核ticket/purpose/target/Run/process |
| OS导入/分表schema | 显式R2模式或新fragment version，保留R1 artifact不覆盖 |

另需在原OS publicreader补窄selector resolver；不构建通用查询/重写引擎。

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
本设计未实现，原R1 frozen artifact、producer与IR均未修改。
