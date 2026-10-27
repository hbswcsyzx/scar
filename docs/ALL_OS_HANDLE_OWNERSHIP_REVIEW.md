# 全部既有OS handles：归属审查与最短后续

2026-10-23。仅只读审查；生产模块和所有原产物保持冻结，没有新gate、capture、compile、
target或million Work扫描。**优先恢复已经实际发生的FD来源，不先扩core未知节点类型。**
完整Run资源覆盖仍OPEN。

## 1. 实际全量小表分母

实验：`artifacts/experiments/first_stage_all_os_handle_review_20261023/`。
完整公共reader读取12684 handles、12683 resources及253 source artifacts，核所有相关
chunk SHA/ordinal并做显式source/process/target wire连接。两大表共95,750,749decoded
bytes。实际exit0，wall3.00s、RSS119,044KiB；不是全量public codec或ExecutionModel验收。

| 项目 | 实测 |
|---|---:|
| 已建OFD资源 | 12683，全部file / OPEN_FILE_DESCRIPTION |
| 已建handle bindings | 12684，来自8个native actors |
| 当前选中视图中已有typed container | 35 |
| 落在已有3context限定source区间、尚未连接 | 12110（仅候选） |
| 区间外 | 539 |
| 已观察handle end / 仍Unresolved | 573 / 12111 |
| process仍None的creator handles | 290 |

原R1端点全部是UnresolvedHandle；FD标量没有作为结构字段保存在handle表中。不能从
opaque HandleID解析FD、generation或TID。当下35个ProviderHandle来自明确的新选择视图。

12683个handle的source等于其target的导入source；另1个handle引用既有OFD。已从目录
机械选出的两个小raw代表核验：普通openat返回FD4；另一个实际为
`fcntl(3, F_DUPFD, 10) = 10`，是额外binding，不能创建另一个OFD。两个小档合计384671
decoded bytes，完整双SHA核验；没有读取main raw。

**Observed**：扣除已有35个provider端点，剩余**12649 handles恰好对应12649个唯一原source行**。
**Inferred from the frozen producer**：它们应为12648个成功open类输出及1个dup类输出，
不是本轮重新解析全部raw后测得的分类。pipe双端
的同source映射已经由原35个actual port selectors保留，不需要解析目标ID猜read/write端。

## 2. 8个actor及exec边界

下表中的阶段只是观察区间，**不是每阶段一个新table资源**。

| native actor | handles | 原source行范围 | own成功exec前后分布 | birth依据 |
|---|---:|---|---|---|
| 369747 | 290 | 12..3316 | 全部在line1 exec后 | creator无自身birth；不填TGID |
| 369749 | 12360 | 2..1030739 | exec7前1、后12359 | 已核vfork，独立复制表 |
| 369869 | 6 | 6..57 | exec17前1、17后4、49后1 | 原main6728，flags待自动恢复 |
| 370085 | 19 | 5..160 | exec62前1、后18 | 原main72256，flags待恢复 |
| 371397 | 1 | 1 | 无own exec | 原main232097，flags待恢复 |
| 372873 | 2 | 4..77 | exec69前1、后1 | 原main863700，flags待恢复 |
| 372874 | 5 | 4..121 | exec88前3、后2 | 已核非共享clone |
| 372877 | 1 | 923 | 无own exec | 原372874 line131，已核CLONE_FILES+CLONE_THREAD |

这些是本次固定Run的实际结果，不是通用规则的actor常量。未填flags不能从同process、
pthread等名字或CLONE_THREAD猜CLONE_FILES。8个actor中7个已有原coordinates process
归属；creator的290个point.process=None继续保留。它可作为ANCESTOR_CONTEXT存在，
数字TGID不影响RunRealm资源表达，不能把文件名当TGID。

## 3. 两个独立证明步骤

**container归属**只需真实actor、table context区间、copy/share/exec及身份连续性证据；
不需要捏造FD数值。**ProviderHandle**还必须有真实provider selector可读到其FD值。

当前UnresolvedHandle实际只有`value/gap`，没有container字段；不能偷偷给原record添
container。曾考虑optional字段或一个PartialHandle variant，但现在不建议先做它们：
本Run缺失的FD来源实际已在原raw/R1 observations中，先恢复它就可复用现有ProviderHandle，
container无法证明时继续Unresolved。无需为本步增加core类型、ID、表或mutable graph。

12110个“区间内”不能直接计为验证通过。逐条仍须核：

- exact source artifact/hash/line与原HandleBinding、目标OFD和Run保持一致；
- 同一实际native actor的source区间，以及其间无替换table的exec/unshare等事件；
- CLONE_FILES共享不创建另一个table，也不因共享者写FD映射而抹掉已知context身份；
- ImportedAt是导入观察锚点，不是kernel allocation；需合法的provider-local顺序/因果
  证明资源在该point可用，不能伪造canonical Operation或global timestamp顺序。

在已有限定区间内，source行不早于该context现有import anchor，证据最接近闭合；但本轮
只做catalog，未重新调用完整interval/availability validator或给它们写typed container。

## 4. 539区间外如何处理

- creator81个、main425个区间外handle包含现有观察anchor之前和选中区间之后的情况。
  原全scope无后续main exec/unshare/close_range能帮助延长后段；较早handle不能仅根据
  PID将资源“回填”。先明确ImportedAt是可延长的观察锚点还是available-from边界，原
  table ID保持稳定，不能每换最早selected handle就重算ID产生第二个table。
- main有1个pre-exec handle；成功exec不能一般地证明前后物理table相同或不同。应保留
  coidentity前沿，不能“每exec一新资源”，也不能无证合并。
- 369869/370085/372873的出生和多次exec涉及不同区间。恢复3个真实birth flags后可证明
  初始copy/share关系；跨exec身份仍要独立处理，不复制parent最终FD表。
- 371397的1个handle需要真实main232097 flags。若CLONE_FILES成立，连接父已有context；
  若未成立，则是复制后的独立context。两者都不能由相同process推断。
- 372874的pre-exec另外2个handle可考虑延长已知private-birth区间；post-exec2个及其
  共享者372877的1个handle需要post-exec身份说明。line8曾创建共享线程不意味着line88
  一定新分配物理表：exec会终止其它线程，内核实现可能复用已private结构。保持未知
  coidentity，不制造多个必然不同resource IDs。

以上讨论只涉及container。FD内容、CLOEXEC、OFD offset、close是否最终释放、共享写入
的因果与retention仍是不同证明。现有12111个unresolved ends不能因container已知消除。

## 5. 两条真实FD恢复路线及成本

**建议先选A：一次顺序raw选择性投影。** 需要的8个原档合计
**82,093,008decoded / 8,624,059stored bytes**；可以一次双SHA扫描，只解析12649个
尚无provider selector的准确source行，并顺带解析4个缺失birth flags行。其余原行仅
计数/哈希，不构造Action/Work、不重新导入。当前没有授权执行，此数是原archive计量。

它确实要顺序读main文件以核全raw SHA，不能说“只读12649行”；但这与扫描/重建百万
Work不同。必须分别报告读取行数、实际解析行数和生成端口数，不混淆成本。

**B：批量读原R1 observations选中chunks。** 原表共106chunks、1,691,630,083decoded /
82,609,083stored bytes。若source→ordinal足够稀疏且chunk重复少，可一次验证chunk后
提取全部需要行，保留原fd/new_fd/created_handles及binding/target。不能对12649行逐个
重新decompress或从头readline。现有getter适合少量查询；需要additive bounded batch API
或一次可重建provider source索引，而非另一个可修改IR。先按声明chunk总量预算，若接近
全表则改用A，不隐含重扫百万Work。

A的信任义务更显式：新投影只能声称“原raw回执中的真实FD值”，不能冒充旧R1 row。
每行保原SourceFact、Run、exact retained mapping、原HandleBinding/target引用与其限定
preimage，提取值必须来自受支持syscall的真实return/output argument。
open类核return FD；dup/F_DUPFD类核输出与原binding/既有target，不当新OFD。35个已验证
pipe/eventfd/epoll端口继续用原provider selectors，不重新猜配pipe双端。

## 6. 最短下一接口与存储

建议仅新`scar/trace/os_fd_source_projection.py`，内部公共流程：

```text
原R1 handles/resources + 当前selected view
 → 自动生成未解析source requests（不接收人工TID/ordinal）
 → 8档一次全SHA、选中行解析、frontiers
 → fresh bounded provider evidence projection
```

复用既有bounded chunk writer/encoder。新manifest明确schema/version、原Run/R1/archive
receipts、requested/projected/frontier分母。JSONL每条是新provider的真实record，保留
original SourceFact/HandleRef和actual fd；ProviderRecordSelector指向**新manifest真实
tables/fd_ports/chunks与真实line/ordinal/record.fd**，不假装原R1 JSON位置。

薄的组合resolver按显式原base/new projection的**完整artifact receipt**分派到各自公共
reader，不按URI任意开文件，也不只按hash判身份。HandleNamespace仍表示原native FD
协议和其table context；projection的存储schema不是新的FD namespace。

原R1 preimage可用公共小表reader的真实chunk+line及**decoded canonical record SHA**限定；
如果需要原raw-envelope row SHA，可最小additive暴露reader当前已读的raw行SHA，不能把
重编码SHA伪称原行SHA。无需在本阶段做通用图patch框架。

随后一个窄只读association adapter可将12649个endpoint精化为ProviderHandle，沿原
HandleBinding ID/target/end/rights/ownership不变；35既有端点不改。container再由独立
context证明决定，未闭合的保持Unresolved。先完成真实FD来源，再选择是否需要其它
core表达增强。输入/所有字段/新provider reader验证范围必须明示，不能借发布状态授
来源、alias、纯性或ready。

此步可先只精化HandleBinding，原Work/access不变。后续若增加Work→resource边，必须
另有原WorkTicket/endpoint的限定存在证明；不能凭opaque ID字符串格式构造一个节点。

## 7. 本Run“所有实际资源”仍缺哪些

现12684只是R1已经建立的bindings，不是所有发生过FD引用的全集。初始stdin/out/err、
出生复制、成功exec保留/CLOEXEC和source未知的dup/IO没有因一次使用就被R1建成OFD；
继承处不能用parent最终snapshot补造。应先完整列出已观测输入FD与缺失producer范围，
再决定未知OFD target关系的最小表达，不能为了填Target构造一个假OFD实体。

普通文件与device open都先是OFD；路径不等于文件实体、更不证明GPU设备/HBM、DMA或
PCIe。R1目前没有FILE_ENTITY与driver/native物理设备的first-class对应。pipe共同producer
已保留，底层pipe buffer生命周期也不等于两个OFD的生命周期。Poll/metadata/mmap等其它
资源关系仍需各自协议；本审查没有把它们隐藏成“资源完整”。
