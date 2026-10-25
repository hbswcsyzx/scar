# 有限FD namespace控制闭包producer设计

2026-10-23。**Proposed，尚未实现此资格producer。** 当前已实施的临时隔离见
[FD_NAMESPACE_QUARANTINE.md](FD_NAMESPACE_QUARANTINE.md)。该隔离防止无证coidentity，
不代表本设计或第一阶段完成。8个owned-launch模块与已保存CPU门保持冻结。

目标是从真实provider合同与有限运行证据机械推出一组selected source boundaries属于
同一真实FD namespace。不是把global observation UNKNOWN改COMPLETE，也不是要求
全程序纯性/所有IO内容都已理解；所有未闭合scope保留Unresolved。

## 1. 输入、产物、身份与职责

后继接口示意（**当前不可调用**）：

```python
projection = project_fd_controls(capture, selected_fd_view, provider_contract, budgets)
qualified = FDNamespaceScopeQualification.read(projection_manifest, exact_inputs)
build_os_fd_table_contexts(..., namespace_qualification=qualified)
```

需求由public FD-values/R2选择视图与其原manifest/preimages自动生成，不接手填TID、
ordinal或业务函数名单。对每个HandleBinding.source，通过原archive logical/local映射、
已有coord/birth/exec事实找provider task incarnation；不解析opaque IDs，不把TID当TGID。
默认分析已有handle范围，未建stdio/继承/network等仍列原分母，不称FD全集。

projection是固定provider事实与证明的有界sidecar，不是第二张可改资源图：

- `demands`：原选择manifest、同ID/canonical preimage、FD selector、相关source边界；
- `control_events`：真正观察的exec/clone/exit/namespace操作及原SourceFact、真实参数/
  return/no-return形态、task关联、精确locator；不造OperationOccurrence或Tensor数据；
- `barriers`：未知name/ABI/flags、ptrace/output/attach/detach/预算/格式/缺成员等前沿；
- `scopes`：特定task/cohort、起止边界、selected demands及所需事件集合；
- `qualifications`：逐claim的证据引用、contract revision、假设、已核guards与前沿。

遵守既有bounded encoder/chunks/public resolver和双SHA/line/ordinal；不能把JSONL
pointer伪装普通数组，不复制整个R1百万Work或把summary布尔当authority。public reader
重验每条claim绑定的完整input namespace/bytes/端点，而非只读PASS字段。资格对象不能
通过普通构造/trust bool创建。所有原IDs、Work/access/state/targets保持原图权威。

## 2. provider合同：证据与假设分开

初期仅支持已审查、精确binary映射的strace native-ABI同步ptrace模式，优先复用工具，
不重写trace loop。合同是版本限定的可执行规则集，来源包括官方源码/实际package
patch/build与内核API；任意相同版本字符串不足。当前已读来源与SHA/行号见
[前提审查](FD_CONTINUITY_PREMISES_REVIEW.md#71-已核primary-source与尚待完成的合同)。

| 类型 | 例子 | 如何使用 |
|---|---|---|
| 已有真实事实 | owned Popen argv、运行镜像SHA、native intent、原exec、archive字节 | exactreceipt引用，不补造旧Run |
| provider合同 | 在限定startup/restart路径中，已跟踪task的相关syscall stop同步被处理/输出；错误如何显现 | 必须完成版本化源路径审核与实际模式限定 |
| 明示信任假设 | 固定producer/受信内核按合同运行；观察artifact未被应用/外部篡改 | 单列，不能伪装Observed字段 |
| 未证事项 | 当前global event_loss UNKNOWN、mixed诊断归属、未知ABI或skip分支 | 阻止相关claim，不能以空文本填NONE |

已有primary source说明ptrace有同步entry/exit stop及条件化child-follow机制；它不等于
无条件完备。strace6.8的line_ended会flush，但outf_perror只报告、部分关闭返回未fatal，
decode/hidden/filtered分支也须逐项审。正常exit、空stderr、roundtrip都只是一组证据中
的局部条件，不能独立授权完整性。
[ptrace](https://man7.org/linux/man-pages/man2/ptrace.2.html)、
[strace主循环](https://raw.githubusercontent.com/strace/strace/v6.8/src/strace.c)、
[syscall处理](https://raw.githubusercontent.com/strace/strace/v6.8/src/syscall.c)

合同审核的具体交付必须覆盖：initial tracee在目标exec前已受控、ptrace option安装/
继承、wait/dispatch/restart、ignored/decode-failure、exec去线程化/消失task、输出所有
相关控制记录的flush/error路径。没有被审清楚的分支，给scope barrier；不把“已浏览
几个函数”命名成一个普遍COMPLETE合同。record runtime kernel/API/personality范围，
而非只存host machine字符串就假设所有ABI相同。

若stock provider的既有transcript/诊断在该合同下足够，可离线消费；若证据不够，需
实际producer新字段。不能在旧profile旁手写一个complete=True。优先利用已有可核
provider diagnostics；确实不足时可设计隔离的已审strace观测补丁/sidecar，记录实际
option/follow/stop/decode/output-error与关闭计数/序列，仍复用其ptrace实现，不新写
完整profiler。该选择须先完成源审查再定，当前没有构建/安装新的strace。

## 3. 输出/错误通道是独立证据

现owned launch2的stderr是tracer/target混合，且未记录所有provider内部stop/write
确认；不能直接以该文件空/非空决定完整性。后继可使用通用exec边界redirect区分target
diagnostic与tracer diagnostic，或受验证的provider telemetry通道。若采用wrapper，
真实Popen argv、wrapper与后续准确target exec必须分别记录，版本化新launch协议；
不能继续假称实际argv后缀就是原target，不能变更已发布launch2解释。

每个相关输出通道需保存实际打开/独占归属、写失败/中断/flush/关闭状态和完整byte
receipts；scope内若没有独立错误完备合同则仍OPEN。只在所有已关闭payload核对之后
发布qualified sidecar；缺少最后关闭回执/预算终止/截断不发资格。丢失事件计数若未知
就未知，不能让第二个独立计数器自身掉数却声称0drop。

## 4. task/cohort有限闭包算法

1. 从真实需求反推最早必要anchor，通常是已证成功target exec或已证private child
   birth；不用命令名称。每个task incarnation用真实birth/exec/lifetime锚点，不以PID
   数值或时间邻近合并。无锚点的creator/外部actor可保原process=None并列frontier，
   不能伪造ProcessInstance；将来有provider-incarnation证据再闭合相应域。
2. 正向解析clone/clone3/fork/vfork flags/result与实际child日志/启动/退出。CLONE_THREAD
   影响process归属，CLONE_FILES影响namespace共享，是两种关系；未看到child不等于
   没有child。UNTRACED、detach、未知personality、ptrace错误或无法解释exec migration
   令受影响cohort区间不合格，不用最终parent表补child初值。
3. 单task以provider合同支持的真实顺序处理entry/return/exec/exit，跨task只用clone/
   exec等已证因果；不做全局wallclock强排。signal/restart/unfinished/resumed必须真实
   配对且保调用entry state；不能因文本拼接成功就保证控制状态正确。
4. 扩张到影响所选namespace身份的必要sharers/group-exec cohort，直到每个潜在影响
   有已证边界或明确barrier。开始锚点之前/最后边界之后不必声称全局完整，但必须证明
   边界之外的事件不会倒灌claim；EOF、main退出或正常tracer return不单独代替close-through。
5. 按控制语义切分有限证明区间。barrier只阻断依赖它的claim，不能无依据越过；同样
   不能为获得部分PASS机械丢掉关联actor。每个拒绝保存所缺具体证据，不只UNKNOWN标签。

namespace控制合同需逐API/flags/result证明，至少区分：

- preserve-current-namespace；
- create-child-shared / create-child-independent；
- possible/current namespace replacement；
- actor/group exec/exit/lifetime transition；
- unknown effect on namespace identity。

open/socket/dup可能写FD entries并扩展物理数组，却不因此等于换逻辑namespace；反之
unshare(CLONE_FILES)、带UNSHARE的close_range等有不同意义。unshare(0)或无UNSHARE
close_range不能永远当identity切换；也不能普遍由return=-1推出所有相关状态未变，
该断言需相应Linux API/实现合同。成功exec解除共享，但已private实现可能复用，不能
每exec宣布新physical resource。相同/不同/未知分别证明，不把区间切分自身当资源
distinctness。跨区间未证部分继续Unresolved，不造每actor/exec的新allocation ID。

## 5. namespace、physical allocation与availability分别消费

资格首先证明N层descriptor namespace coidentity。P层files_struct/fdtable/FD-array
allocation仍需直接物理incarnation/lifetime证据；fdtable扩容可更换数组，所以N层同一
不等于P层allocation同一。kernel pointer没有epoch也不能解决地址复用。
[内核fdtable管理](https://docs.kernel.org/filesystems/files.html)

只有public qualifier通过的selected cluster才可写入既有ResourceInstance及同ID
HandleBinding.container；其余保持Unresolved。ImportedAt是首观察，不是分配或销毁。
固定refinement publication必须携带资格artifact/每条claim支持，reader每次重核原
preimage/selector/qualification；不能单独导出一个失去证据依赖的已知container当新权威。
如组装器尚不能保留此支持关系，暂不推广该关联，报告最小接线缺口，不发假完整图。

provider-local证据顺序与canonical OccurrencePoint的order/availability对应仍是独立
义务，当前core codec/FK不会自动证明它。资格不能顺带改变OFD target、handle end/
lifetime/rights、Work/access/state或授GPU ready；原边界与unknown效果一律保留。

## 6. 后续自主gate与当前边界

当前唯一已完成新门：已保存CPU coverage2真实回读合格，调用同公共continuity helper
明确拒绝；0raw/target/R1、无资源创建。这只完成quarantine，不完成闭包producer。

下一阶段按序推进：

1. 固定并审核一条具体strace/ABI同步合同，列每条假设/源路径与可验证runtime字段。
2. 对当前小CPU metadata与真实原控制记录作有界可行性审计：哪些所需字段已有、哪些
   需要新producer，不重读GB旧Run或导入百万Work。
3. 实现自动demand→有限control projection→public qualifier；对真实可闭合区间与
   实际barrier分别报告。若既有capture缺必要字段，不给旧Run补造它。
4. 必要新joint capture仅在所需字段/入口就绪后跑一个明确门；使用既有strace实现，
   独立限预算。只有实际正向qualifier通过后，才接container refinement与逐原字段验收。

具体门由root继续自主审查，不需要用户逐门批准。全部阶段都报告真实退出/成本/证据与
假设/未证分母。完整资源问题与第一阶段目前仍 **OPEN**。
