# FD-context continuity前提审查

2026-10-23。**只读审计；未改生产、原terminal artifact或staging list，未导入CPU R1，
未运行target、未扫描日志。** 输入仅当前源码与已成功CPU门的少量metadata，准确SHA见
`first_stage_fd_continuity_premises_review_20261023/inputs.json`。

结论：**当前OSFDTableContexts仍存在不健全的条件路径**。selection-qualified coverage2
可以进入_prepare，但没有独立的相关控制流完整性/资源同一性证明；满足其它旧形状守卫
的输入仍可能因保留行0计数而得到同一InstanceTarget。当前新CPU门未生成context
artifact，这不是一次已观测到的错误绑定；旧context v1依然拒绝，FD_VALUES_ONLY_R2
依然保持所有container Unresolved。新owned-launch有限资格验收仍正确。

## 1. 三件不同的事

| 层次 | 能表达/证明的事 | 不能偷换成的事 |
|---|---|---|
| O：observed-context | 同Run、actor/artifact与一段已保留行的证据分组 | 实际资源跨两点同一 |
| N：实际descriptor namespace | Linux任务使用的FD命名空间及其共享/分离/生命周期 | 底层数组/内核allocation地址 |
| P：physical implementation | files_struct/fdtable/FD-array等物理对象及allocation epoch | 仅source line或namespace label |

ResourceRole.HANDLE_TABLE当前用于N层命名空间资源，ResourceInstance不要求地址；但是
多个ProviderHandle指向同一InstanceTarget仍是**真实资源coidentity断言**，不能只凭O
层分组成立。ImportedAt仅表示首次导入观察，不证明之后同一，也不证明创建/销毁。
将名称写成observed-context不撤销该typed关联。

P层更严格：Linux文档说明files_struct指向fdtable，扩容会分配新的fdtable并更新该
指针。因此即使N层保持同一，物理fdtable/数组也可能因增长而替换；零unshare不能证明
物理allocation同一。[Linux内核文件管理文档](https://docs.kernel.org/filesystems/files.html)

## 2. 逐项源码条件

本节行号绑定本次源码SHA，不用状态标签替代实际条件。

| 位置 | 实际检查 | 已证明边界/尚缺前提 |
|---|---|---|
| coverage.py:105–106 | v2要求observation_completeness为UNKNOWN | 明确没有event-complete资格 |
| coverage.py:128–161 | exact Run/archive/launch/nonce、实际selection、owned native与镜像 | selection/发生过采集，不是相关事件无遗漏 |
| coverage.py:169–182 | require_fd_continuity只重读同一对象/receipts | 没有额外continuity predicate；方法名不能当证明 |
| contexts.py:115–116 | 先调用上述coverage guard | 允许合法UNKNOWN profile2进入后续 |
| :125–149 | base/R2/summary/audit/接口count收据一致 | 原表与已有输出守恒，不证明输出包含所有真实接口 |
| :150–154 | 全部**保留行**分类仅COMPLETED/SIGNAL，行数与coords相等 | 排除已见格式/未完成前沿；对根本未写出的事件没有分母 |
| :155–166 | Run及所有proof输入精确bytes/SHA绑定 | provenance，不能把保留内容升级为完整事件流 |
| :167–195 | archive/R1原档集合、实际文件集合与byte身份一致 | 没丢归档中的成员，不证明原producer没有漏actor/事件 |
| :201–223 | 现有thread/process/member端点一致；唯一creator None例外 | 没证明完整actor/sharer cohort、所有incarnation区间；None不等TGID |
| :224–274 | 非main原档双SHA、逐行重读；拒exit/migration/unfinished/resumed，flags完整 | 仅非main已保留行；不检查未出现的drop/detach/actor |
| :275–280 | 与旧投影内容/counts一致，counts为full子集 | 同源计数相减，不能独立发现共同遗漏 |
| :281–286 | main补集exec唯一；execveat/unshare/close_range全scope计数0 | **从观察到0推无实际transition的关键跳跃** |
| :287–309 | target私有birth与一个preexec child的原source/flags | 这些正向birth事实可靠，但不能闭合其后所有相关转移 |
| :310–335 | exact selected FD source/actor；按URI分组；first..last内无成功switch | “没看到switch”仍依赖尚缺的相关控制scope完整性 |
| :336–347 | target sole-exec、非main前一个exec或限定private child birth | 是观察anchor，不是跨所有selected points的持续同一证明 |
| :348–367 | 按首观察hash建ResourceInstance；全部端口变为同一InstanceTarget | **把O层证据分组提升成N层coidentity的写入点** |
| :368–388 | ID collision、metadata稳定、counts | 正确的存储/引用检查，不补事件完整性 |
| :391–402 | _expected写FK/codec验证、full-model OPEN | OPEN标记不撤销已经写出的typed coidentity |
| :411–431 | _qualified重算相等，检查role/realm/ImportedAt/原preimage | 若重算前提不足，确定重算仍会重现同一不足 |
| :435–440 / :470–484 | public read/build都调用_prepare | 同一缺口会同时出现在两条公共路径，非只writer问题 |

contexts.py是`scar/trace/os_fd_table_contexts.py`，coverage.py是
`scar/trace/os_capture_coverage.py`。本轮只发现路径，没有执行它或构造一个假输入。

## 3. 其它loss/control/membership守卫为何还不够

这些守卫应该保留，不能因发现缺口就删掉。它们能拒绝**已被保留并识别**的控制前沿，
但没有消费独立完整性资格，也没有检查coordinate.open全部相关code或按本claim的
actor/interval做前沿排除。summary/audit/同raw投影共享同一来源，三次相等不增加遗漏
事件的独立观察能力。archive roundtrip只说明producer输出未在保留过程中损坏。

没有普通syscall return、正常exec/exit、空stderr或正常tracer退出能单独代替这个前提。
同样，global observation UNKNOWN不逻辑蕴含“所有局部事实都不能证明”：若将来有
独立的**有限相关控制域**或每个选定边界的正向identity证明，可以在其它事件仍UNKNOWN
时闭合相应资源关系。当前没有这种独立证明，不应要求全世界纯性，也不能假定它存在。

共享还需明确scope：CLONE_FILES的意义是共享descriptor table，copy与共享不能只用
TID归组；exec可能解除共享，close_range的UNSHARE标志也有独立作用。调用方table的
身份、别的sharer对内容的修改、kernel数组增长，是不同义务。不要把FD内容/OFDoffset
是否变化误当namespace identity。[clone](https://man7.org/linux/man-pages/man2/clone.2.html)、
[execve](https://man7.org/linux/man-pages/man2/execve.2.html)、
[close_range](https://man7.org/linux/man-pages/man2/close_range.2.html)

_RELEVANT目前还不是完整kernel-control模型：只包括exec/clone/fork/vfork/unshare/
close_range，exit、actor lifetime、兼容personality/detach等主要依赖外围行分类与既有
membership。不能因为一个name不在_RELEVANT就把其资源影响解释为NONE。具体哪些
控制可以保持table identity，必须由限定版本的Linux/provider合同判定。

## 4. availability不由codec/FK自动补齐

`resource_validation.py:326–340`对ProviderHandle.container检查HANDLE_TABLE role与
realm/FK，仍给provider_handle_effect_alignment gap；`:422–423`对ImportedAt只核
realm。它没有证明该实例跨选定source points同一或available。

`validation.py:209–219`与`host_order.py:24–36`的canonical host order只对已知
OccurrencePoint建立本地顺序，不能把两个EvidencePoint文件行直接排序。因而“首行
ImportedAt→后面行号更大”没有自动成为core availability/ordering证明。即使provider
合同能证明某些单TID receipt顺序，也必须通过限定对应关系表达，不能拿wallclock或
entry+duration补成实际return。当前adapter仅codec/FK局部检查，没有完整ExecutionModel。

## 5. 已有CPU metadata的实际含义

成功门profile SHA603ecfab…adfea明确保留`observation_completeness=UNKNOWN`与
`os_event_loss_not_established`。launch event_loss/effect_completeness均UNKNOWN；
coords含`process_thread_observation_intervals_incomplete`及一个具体
`os_process_witness_frontier`，native all_paths/all_processes/all_threads等均False。
这些metadata没有被contexts._prepare当成独立连续性前提消费。

CPU门自身还真实调用unshare/close_range各1次，因此不能把它宣传成“满足_prepare所有
零计数条件并误绑”的实证。它也没有构建CPU R1或context delta。新owned direct-target
capture的target_birth可按现profilefallback到exec；旧context算法还要求补集中一个
private clone birth等特定形状，本轮也未证明适用。这里是**静态不健全路径审查**，不是
一次已运行的反例实验；有限launch资格保持有效。

新launcher没有旧-qq抑制选项，现有_prepare对PROCESS_EXIT等分类的旧限制也可能先
拒绝自然的新capture。此类额外拒绝不是缺失前提的替代品：本审计没有证明一个真实
新样本已走通全部旧shape守卫。后继资格化若要支持这些输入，应正向处理匹配的exit/
生命周期事件，而不是为获得通过删掉barrier或恢复旧“不见即无”的逻辑。

## 6. 最窄安全门设计

**下一步建议（本轮未实施）**：将selection资格与identity-continuity资格作为两个独立
前提。在_prepare现coverage检查之后、任何raw重读/新增ResourceInstance之前，若没有
独立可验证的本claim continuity证据，明确拒绝coalescing container。当前所有现有
receipts只够selection，因此不得产生新InstanceTarget；FD_VALUES_ONLY_R2继续正常。
不把metadata中UNKNOWN手改COMPLETE，不加调用者trust bool，不伪造空图/快照，不通过
把实体重命名为observed-context来保留同一关联。

未来允许两类有限证明，均须绑定完整Run/selected handles/preimages/source selectors：

1. **相关控制区间证明**：对实际selected points、对应task incarnation与必要sharer/
   exec迁移scope，独立核可用的provider收集/丢失/attach/follow/lifetime合同；闭合相关
   control events和flags，明确gap frontier与边界，机械证明区间内namespace未换。
   不是只加一个status字段或重复一次同raw计数。此合同可有明确假设，但不能从正常
   exit/roundtrip推导；无需同时证明无关tensor effect、所有IO数据或全局purity。
2. **正向边界身份**：每个所选边界有真正受验证的provider identity/incarnation receipt，
   精确证明namespace同一；地址或数值相等不足，必须排除allocator/pointer复用。
   该路径不依赖“中间没看到变化”，但本次strace格式没有该数据。内核指针若无epoch
   不能充当方案。物理fdtable allocation还需单独生命周期证据，不能混用N层ID。

无任一证明时，可保留观测分组/候选证据，不把它写成规范真实container关联。获得N层
资格后，ImportedAt/availability、原Work/access/state、共享关系及非container字段守恒
仍各自验；不会因一个局部证明宣布全resource model完整。

下一门应只验证新的拒绝边界与既有FD-values正常路由，禁止新episode或百万重导；
有独立正向证明producer之后再设计相应真实最小门，不能预先自授能力。完整模型OPEN。

## 7. 可实现的有限控制闭包路线，而非永久占位拒绝

临时quarantine只是先阻止不健全关联，不是本阶段最终完成。后继应实现一个有明确
provider合同的有限证明器，优先复用当前strace的同步ptrace机制，而不是另写profiler。

### 7.1 已核primary source与尚待完成的合同

官方strace v6.8的`src/strace.c`完整SHA
`21fe0b653612b9354ff783a9ca1643d39682d85fd38bf32a14b09cdea41febd1`：
`:2986–2988`的followfork配置启用TRACECLONE/TRACEFORK/TRACEVFORK，`:3666`与`:3848`
使用wait4(__WALL)收取停止，`:3868–3900`启动tcb/分派entry-exit decode，`:4237`
执行next_event→dispatch循环。[provider主循环源码](https://raw.githubusercontent.com/strace/strace/v6.8/src/strace.c)

这给出可核的同步机制：对真正被跟踪的task，syscall-stop会受tracer控制，并不是
自行滚动后可静默溢出的异步事件ring。不过必须分别审其startup/restart/ignored-stop/
detach/error分支；不能只由“使用了ptrace”得出完备。内核API对entry/exit停止与fork
自动跟踪有明确条件，seccomp、exec去线程化等也会改变停止序列。
[ptrace API](https://man7.org/linux/man-pages/man2/ptrace.2.html)

**退出码不足有源码证据**：strace.c:800–813在line_ended时flush；`:721–732`的
outf_perror只报告输出错误，没有强制fatal；`:1142`及`:4191–4193`还存在未逐一升级
返回值为fatal的关闭/flush路径。因此不能把return0等价成输出无失败。
`src/syscall.c` SHA `0d8c5449b011a8cd16f0b5d0864f57fa633867876682270fee294390bb0e62b1`
`:584–620`还有decode返回0的忽略路径，`:649–652`有显式隐藏/过滤分支，`:1290–1316`
描述ptrace状态/错误。须证明各跳过分支在本合同下只涉及非相关停止或产生可拒前沿；
不能把缺失行当成功。[syscall处理源码](https://raw.githubusercontent.com/strace/strace/v6.8/src/syscall.c)

本次仅核这些相关源码段，不声称完成了provider全路径形式验证。精确下载SHA、行号与
有限excerpts保存在新审查artifact；一次尝试的output.c不存在(404)也保留，不当成功来源。

### 7.2 合同必须限制并实际验证的范围

| 义务 | 可实现的检查/证据 | 缺失时 |
|---|---|---|
| provider身份 | 现有运行镜像SHA + package/source-patch/build选项与已审合同映射；必要kernel/API/ABI范围 | 不承认未知binary只是版本字符串相同 |
| 启动/覆盖 | owned spawn而非晚attach；准确target exec是区间起点；原argv trace=all/-ff，无status/path/fd过滤/inject/limit/detach参数 | 保selection或startup frontier |
| 同步事件路径 | pin PTRACE_SYSCALL wait/restart/child-option继承合同，限定是否seccomp优化；逐相关分支建立可拒诊断/行形约束 | 不能仅由无错误文本授完整性 |
| actor闭包 | 每个task incarnation由实际exec/birth/exit锚定；clone结果与child存在对应；所有实际sharer/exec去线程化相关cohort收束 | 不按PID/TID数值补成员，不拷最终parent表 |
| escape/ABI | CLONE_UNTRACED、detach、未知personality/兼容ABI切换、未知控制syscall、ptrace读取错误均拒绝相交scope | 不把未见child解释为没有child |
| 输出通道 | 核line flush/错误报告路径，独立收集provider诊断及byte/write-failure信号；保整个相关日志生命周期 | 当前mixed tracer/target stderr不足以直接认定独立channel |
| 区间关闭 | 观察到所需起点至所选最后边界以后的可信close-through；相关退出/取消/exec迁移有receipt，未发生预算强停/脱离 | 任意EOF或main exit0不等于所有cohort已闭合 |
| 解析/控制 | 完整entry-return/flags或协议定义的no-return，合法signal/restart对应；所有可能影响namespace的未知项为barrier | 不靠COMPLETED名字或int return抹平unknown |

CLONE_UNTRACED会影响tracer强制子进程跟踪，必须看实际flags；不能把-ff当无条件
actor闭包。[clone条件](https://man7.org/linux/man-pages/man2/clone.2.html)

需要provider运行/诊断字段不在旧capture中时就不能补造。对当前owned profile2，可以
保留已证明selection并追加**新的派生qualified-control证据**，但只有能从原真实回执
独立满足上述限定合同的scope才可资格化；不能直接改原profile UNKNOWN。若新增实际
collector字段不可由既有metadata恢复，下一joint capture才生成，原Run维持未证。

独立provider stderr可用一个通用exec边界redirect把target诊断移至另一受收据约束的
通道；若采用wrapper，必须真实建模wrapper argv与后续准确target exec，版本化新
launch协议，不能继续假称Popen argv后缀就是原target。也可以审查现provider已有
可核telemetry，但不要把mixed stderr/空stderr当缺省完整性。这是后继设计，不改本轮
已冻结的launch2。该问题是具体可实施收集边界，非要求无条件全世界完备。

### 7.3 最短实施与自主验收节点

1. **立即安全门**：仅contexts._prepare，在创建资源前拒绝当前没有独立continuity
   proof的路径；public read同门。明确unsupported qualification，不新增一个永远为真
   或永远为假的伪proof状态类型。原FD-values/R2继续可用。这只完成隔离，不完成闭包。
2. **版本限定provider合同**：完成上述有限源码分支审查与实际binary映射；输出明确
   可接受条件/不可接受分支，不声称仅review几段源码已证明。当前新owned路径没有
   seccomp优化，可先缩小到native ABI、无逃逸的同步ptrace合同，不强求一次支持所有模式。
3. **有界control projection/qualifier**：同原archive/coords/launch binding，单次流式
   投影相关exec/birth/exit/control、sharer cohort及所有barrier，保真实SourceFact。
   每个资格绑定所选SourceFacts/handle preimages、actor incarnation、起止边界、合同
   revision与原收据。复用既有parser/存储/selector，不重放百万Work或造另一资源图。
4. **真实局部门**：优先复用已存小CPU capture，只评估实际能闭合的scope、明确拒绝
   本样本具体process-witness前沿所影响区间。相交barrier不能隐藏；不相交也要有起止
   和actor依赖证明才可排除。证明器应正确区分unshare(0)/无UNSHARE close_range等
   已知无namespace切换接口，而非永远要求这两个name计数为0。原样本不足的字段不能
   凭空补齐；需要新producer时再按单个明确joint门收集，禁止当前偷偷重跑episode。
5. **container消费**：只有public qualifier重新机械核实全部claim证据后，builder才
   替换相应container；其它仍Unresolved。先自动从实际selected endpoints生成需求，
   不要求手填actor/行号，不按LeWM函数名做规则。N层同一与P层allocation另分合同；
   core availability/source对应仍按实际证明状态处理，不能由FK PASS替代。

该路线允许以有限且可验证的provider合同逐段闭合真实资源关系；不会把当前不健全
路径留下，也不会把临时全拒误报最终建模完成。本轮到只读审查/设计为止。
