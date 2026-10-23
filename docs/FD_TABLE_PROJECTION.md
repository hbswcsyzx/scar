# FD-table context：一次有界补证结果

2026-10-23。承接`FD_TABLE_CONTEXT_REVIEW.md`，仅执行已授权的既有raw离线投影。
生产IR、adapter、coordinates和原R1/R2产物未修改。**现在35/35个既有端口具备在原
capture契约下绑定container的证据条件；实际绑定尚未实施，原R2仍有35个Unresolved。**

## 实际范围与结果

实验：`artifacts/experiments/first_stage_fd_table_projection_20261023/`。
单次`run.sh`实际exit0，wall **0.99s**，RSS **43,076KiB**。

| 项目 | 实际分母 |
|---|---:|
| 原archive中的OS档 | 253 |
| 本次精确排除的target原档 | 1，81,578,171decoded bytes |
| 本次完整双SHA核验的其余原档 | 252，9,264,445decoded bytes |
| 本次原行 | 36,665 |
| 完整call rendering / signal | 36,664 / 1 |
| 保留的context事件 | 78 |
| execve / clone / clone3 / vfork | 31 / 45 / 1 / 1 |
| 成功birth，其中CLONE_FILES / CLONE_THREAD | 47，其中46 / 46 |
| unfinished/resumed、迁移marker、必须字段缺口 | 0 / 0 / 0 |
| 不完整相关argument rendering | 0 |

预算为12,000,000decoded bytes、200,000行、16,384bytes单行，均未触达。不读取主原档、
10.8GB接口record表或任何Tensor值；只额外核验R1已有253条artifact公共chunk。

## 为什么这次允许计数作差

不是从“没有搜到”直接推导不存在。脚本先实际核以下限定条件，再作差：

1. 原archive SHA同时等于coordinates seed/retention和原audit03 producer声明。
2. 原R1 manifest SHA精确等于已完成全11表审计的audit03 receipt；summary、manifest内
   summary和audit03的完整interface_counts三者一致，54类总数等于全部observations。
3. archive的253个logical/local路径均唯一，当前OS目录精确等于该原档集合；R1 artifact
   公共reader对253条核整chunk双SHA/ordinal，再与每个**精确URI+rawSHA+bytes+schema**匹配。
4. 排除项精确来自coordinates.seed.target_exec的原artifact receipt；不是根据PID大小、
   basename、程序名字或hash独立挑选。补集252档全部核stored/raw SHA及完整行。
5. 每行使用冻结R1 parser的时间前缀、call/unfinished/resumed grammar和参数/flags拆分；
   未解析、相关必须字段不全、迁移marker均会保留为阻断frontier。本次实际没有这些前沿。
6. 相关成功exec逐条核其既有coordinates出生/线程组归属。除已核ancestor上下文外，成功
   exec均属于已证明的其它process group，未出现target-group exec或非leader exec。
   数字TID相等本身不是归属证据；此处复用原已核birth profile与精确source receipts。

原完整R1：execve32 = 成功7 + 失败25。
本次完整非target补集：execve31 = 成功6 + 失败25。
故target原档中execve恰好1次成功、0次失败，正是既有coordinates原line7锚点。
全scope `execveat/unshare/close_range`计数均为0。原完整R1行分类也与本次完全一致：
本次36,664 COMPLETED+1 SIGNAL，target补集结果为1,031,104 COMPLETED+4 SIGNAL。

因此不需要重新扫描百万行主原档来证明31个target端口之间没有表切换调用。这个结论
限定于**原已保留capture及其声明契约**，不升级为全路径/全进程完整性，也不消除原
process/thread生命周期、外部效果或源码对应前沿。

## 35个端口怎样连接

使用现有R2类型，新增三个本次观察到的HANDLE_TABLE context资源即可表达选中范围：

- ancestor的3个端口：同一个在原line947首次观察到的context；不宣称由line1 exec新分配。
- target的31个端口：同一个在原line4371首次观察到的context；上述完整补集证明它们之间
  没有exec/unshare/close-range切换。其共享线程引用同context，不按线程创建另一个表。
- 子372874的1个端口：在其line4首次观察到的独立context。原main line863883的完整
  birth flags没有CLONE_FILES；它的line8共享出生和line88 exec均不能反向替代line4身份。

这不是三个物理allocation声明。`ResourceInstance(role=HANDLE_TABLE,
origin=ImportedAt(point))`表示观察到的descriptor context；**表身份、映射StateVersion、
观察epoch分别保留**。不推断exec前后同/不同physical files_struct，不将容量数组扩容
视为新context，也不发布资源创建/销毁或GPU ready。

下一实施仍须根审查后进行：绑定精确原R1/R2 manifest及preimage，只精化这35个
`ProviderHandle.container`，沿既有`InstanceTarget`/`ResourceInstance`连接；原OFD、
NativeHandleLifetime、rights、起止、source、Work和pipe两端不同OFD等字段均不改变。
无新IR类型、无通用patch引擎、无另一个可写资源图。

## 保留的缺口

- ancestor actor的上下文角色可由既有exec+target birth因果表示，但其数字TGID不能从
  文件名补出。当前坐标不改；container资源可先在RunRealm表达，EvidencePoint.process保None。
- CLONE_FILES已经提供同container身份；它没有提供并发FD表写入的唯一全序。
- FD内容/继承状态、CLOEXEC、OFD offset、escapes、retention、完整effects、quiescence与
  source/native的canonical对应均未在本次证明；不将UNKNOWN改NONE。
- 完整ExecutionModel语义仍OPEN；没有构造ProgramSnapshot，也没有应用任何优化。

脚本SHA为`96b38e540a50fa6ae8ba3a319a0ef6f8e14eaff29dd2bf37b026c0be1a00f44a`，
冻结R1 parser SHA为`c52f45a62693e3e78875b3a23b7c56e0a4cdb48862436981f8d98941a4900c1b`。
原始producer、完整252档receipts、78条context事件、summary、time/progress均独立保存。
