# FD-table context：R2之后的只读审查

2026-10-23。本次只定位既有35个selector和小范围原证据，未修改生产代码、冻结R2文档、
R1/R2产物，未执行target、采集、全表扫描或新的模型变换。完整模型仍为OPEN。

## 1. 结论与实际边界

**Observed**：当前发布R2仍有35个`ProviderHandle.container=Unresolved`。分母为：

| actor | ports | 原行范围 | 本次证据 |
|---|---:|---|---|
| 369747 | 3 | 947；3309的两个pipe端口 | 378,274bytes、3,341行小原档完整双SHA核验 |
| 369749 | 31 | 4371..863713 | 既有35-selector证明；未重新扫描81,578,171bytes主原档 |
| 372874 | 1 | 4 | 16,696bytes、222行小原档完整双SHA核验；另点读其真实birth |

**Inferred，可机械闭合而尚未应用**：现有证据足够给上述第一、第三组共**4/35**端口绑定
各自的table context；不需要新IR record。其余**31/35**尚缺初始exec至最后选中端口的
table-context连续性证明。本次不能报告35个container已完成绑定。

本次小读产物位于：
`artifacts/experiments/first_stage_fd_table_context_review_20261023/evidence.json`。
它记录原manifest/coordinates/archive的SHA、35端口原ordinal、两个小raw完整回执，以及
唯一R1 birth chunk/row回执；没有重建另一张资源图。

## 2. 先分清三个概念

1. **HANDLE_TABLE资源身份**：描述任务所使用的descriptor namespace/context；不是
   FD整数，不是某一份table内容，也不是容量数组的地址或allocation。底层数组扩容不自动
   创建另一个此类资源。
2. **状态版本**：这个context中FD到OFD、CLOEXEC等映射的变化。`open/close/dup/pipe2`
   会改状态；`CLONE_FILES`共享者访问同一个context。它们不因每次访问创建table资源。
3. **观察区间/epoch**：目前证明到哪些原事件、哪些actor。缩短或重新开始观察区间不自动
   证明旧资源已销毁或新资源已分配。

成功exec保证调用者不再共享先前共享的FD表；若原本已私有，不能据此断言物理分配了新表。
因此可用现有`ResourceInstance(role=HANDLE_TABLE, origin=ImportedAt(point))`表示首次观察到
的context，保留前史。没有新建/终止证明时不发`CreatedAt`或资源retirement。Linux契约见
[execve(2)](https://man7.org/linux/man-pages/man2/execve.2.html)。

`CLONE_FILES`表示同context；未设置该flag的成功birth给子任务一个独立context，其初始FD
指向相同OFD。不能复制父任务最终table状态。见
[clone(2)](https://man7.org/linux/man-pages/man2/clone.2.html)。
成功`unshare(CLONE_FILES)`或`close_range(..., CLOSE_RANGE_UNSHARE)`需要分别处理；
不能将失败调用当作切换。见[unshare(2)](https://man7.org/linux/man-pages/man2/unshare.2.html)、
[close_range(2)](https://man7.org/linux/man-pages/man2/close_range.2.html)。

## 3. 为什么现有4个端口足够

**369747的3个端口**：小原档line1为成功exec；全档唯一另一个相关事件是line3310的
`vfork() = 369749`。三个端口在line947和3309。没有中间exec/unshare/close-range切换；
vfork子任务并不因共享VM而共享FD表。因此这三个端口可指向一个在line947首次观察到的
HANDLE_TABLE；不宣称它创建于exec，也不声称继承FD已恢复。
[vfork(2)](https://man7.org/linux/man-pages/man2/vfork.2.html)给出其clone等价flags。

**372874的1个端口**：coordinates将其birth精确指向main原line863883。本次公共
`OSResourceBase.resolve`实际核验：

- 原observations ordinal867219；chunk85、JSONL行7386；真实source为artifact1/line863883。
- `clone`成功返回372874，完整flags为
  `CLONE_CHILD_CLEARTID|CLONE_CHILD_SETTID|SIGCHLD`；无`CLONE_FILES`/`CLONE_THREAD`。
- 该chunk的stored/decoded SHA、line与ordinal全部核验；chunk decoded15,999,783bytes。
- 子原档line4创建epoll；其第一个CLONE_FILES birth在line8，成功exec在line88。

因此line4属于该子任务独立context；它不同于birth时父context。可在line4 `ImportedAt`
锚定。**line88的exec不能反向给line4填身份**。其后来共享线程不会把已知container抹掉，
但这里不推导line8之后FD内容或其与exec后context的同异。

parent clone普通返回的receipt不是child的出生后最早时刻：child可能在parent返回之前
已执行。所有`-ttt`值继续仅为provider printleader时间，不构造跨线程时间全序。

## 4. 其余31个端口的最小补证方案

既有全scope R1/audit的分母是execve32、execveat0、unshare0、close_range0。这些是既有
已发布完整读取结果，本次未重新解释百万条record。main的初始exec由coords原line7锚定，
但目前小读没有证明其后不存在另一次成功exec，所以31个端口暂保OPEN。

**Proposed，尚未执行**：一次有界扫描其余252个OS原档，共9,264,445decoded bytes，
按原receipt核hash、精确文件名和行，保留exec/birth/表切换投影。完整非main exec数量与
既有全scope32作差；只有得到main恰好一次exec，并核线程组exec/actor延续边界，才能
给31个端口证明同一初始context。保存全252档的读取分母，不把未命中误称不存在。

预算建议：12MB decoded、200,000行、16KB单行；预算或渲染不完整即保OPEN。archive未
声明每档行数，因此200,000是预算而不是已观测行分母；不为预算不足隐去原事件。内存
只保相关receipt，不保所有raw或
table状态。如总量/格式不符，报告后再考虑一次81.6MB主档流式事件投影，不读取10.8GB
接口表、不反复为每个端口扫描同一档。本次没有执行此方案。

`CLONE_FILES`本身只增加使用同context的actor，不应使container变UNKNOWN；它使映射
状态的写入顺序与读依赖需要额外证明。只闭合container不等于FD binding、OFD offset、
retention、effects、quiescence或GPU ready闭合。

## 5. 唯一ancestor/context缺口

coords.seed.target_birth与369747原line3310精确同源，line1又保留了实际外层启动exec。
原采集命令明确`strace -ff`并保留启动命令；这足够定义一个与target有真实出生因果的
**ANCESTOR_CONTEXT actor**，不依赖SCAR/LeWM/可执行名规则。

当前坐标只做target向下闭包，故未将这个已验证actor加入membership；这不是raw缺失。
扩充时保持原Run/target/descendant IDs不变，新增context角色和其receipt。数字TID不
自动等于TGID：无独立父birth/数字TGID证明时，可先用`ProcessInstance.pid=None`和
有明确provider-native TID的`HostThreadInstance`；不能因为文件名369747填pid369747。
child的非CLONE_THREAD birth可单独证明child线程组，不能反推父TGID。

容器4端口的闭合不必等待这个数字TGID：现有`RunRealm`足够容纳已知context资源，
EvidencePoint.process可继续None。不能顺手改写R1 Work的process、executor和其他字段。

另需显式消费原archive retention映射：R1原Resource/Handle source保留`.gz`实际输入URI，
coordinates保留collector逻辑无`.gz` URI。连接必须核同archive SHA中的**精确logical/local
路径对+rawSHA+bytes+schema**，不按basename、PID或hash独立合并，更不改写原两套receipt。

## 6. 最小实施与下个验收点

**Proposed**，本次未实施：

- 核心IR继续使用R2已有`ResourceInstance`、`ImportedAt`、`InstanceTarget`和
  `ProviderHandle.container`；本轮无需新record/ID/codec版本。
- 在窄OS adapter中加入有界table-context证明器；proof输入明确为原R1和R2 manifest SHA，
  对旧选择视图核精确preimage，仅精化既有handle的container，增加实际需要的table资源。
  不能把同一ID的base/refinement同时当两个权威record，也不扩成通用patch引擎。
- context membership是单独的capture profile增强；当前冻结coordinates不动。没有必要为
  本地4端口container精化先补一整套祖先算法。
- 未来FD映射内容/offset/flags必须接既有StateLocation/StateVersion/StateAccess与资源
  realization；当前缺canonical state port及并发因果时继续OPEN，不新建可写FD状态图。

先验收4端口/2个观察context：所有原selector/preimage、OFD/lifetime/rights/起止/Work
字段不变，container FK有效，pipe两端仍不同OFD但同table；无创建/释放或ready声明。
通过有界补证后，再将35端口统一检查为最多三个**本次观测范围**的context，不把这等同
整个程序所有FD表已完整恢复。共享alias只沿实际flags+限定区间；先验证边界再决定是否
允许跨区间共用同一ResourceInstance。完整ExecutionModel仍需真实ProgramSnapshot，
不得为局部验收伪造。
