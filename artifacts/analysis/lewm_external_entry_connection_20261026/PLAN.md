# LeWM external entries：旧continuation → 静态body → 当前Run接线

**只读设计；858 session11969仍RUNNING，未赋终态。** 不修改冻结consumer，不重lower其15图、不读raw/大source graph、不compile/执行目标。本次仅读API、小docs、原continuation元数据2,026,468B及两个archive manifests（42,283B/9,689B）；未再次读817 grouped bindings。

## 现成可复用的链与准确scope

原 `first_stage_dependency_continuation_20261023/result/continuation.json`（SHAc9ff2f87a0e90ee42297501d256d9d24aeeab60273c6172fe692c0323207173e）保817 groups/100438 calls：SOURCE_VERIFIED243/86702、PROGRAM_SCOPE_RETAINED553/12933、UNRESOLVED21/803；106 snapshots/三图，current guards105/106，drift14与非文件来源803保留。243不是已证明有普通definition/CodeType/可lower的数量；候选细分仍待正常metadata catalog。

**这份continuation的trace是272038；当前physical runtime是369749。** 两者相同code/count不代表同Run。旧SOURCE_VERIFIED是原compiler/source证明，既不能把PID改成369749，也不授当前函数对象、globals、state或effects。完整CapturedCode、SourceSnapshot、flags/optimize、compiler/build完全匹配的静态代码可复用；当前369749动态入口仍须独立scan与genuine coordinates/静态来源证明。

现有 `SourceEntryCatalog(archives=...,admissions=(SourceAttachments(...continuation...),),projects=())` 已合法接受原continuation。`catalog.metadata()`保全817/100438，候选按真实原call-weight排序；PROGRAM_SCOPE_RETAINED不产生外部candidate，因此不重15个project图。`resolve → prepare → SourceCodeEvidence.from_entry → plan_source_entries/run_source_entries` 使用原qualified definition/context与普通sealed lower；没有新AST特性需求。candidate key来自完整source/descriptor/locator，不能按包/函数名挑选。正式publication阶段加入原plain858 project view；静态compiler origin与导航origin仍分列。

## 三个实际断口与最小改口

| 断口 | 当前准确限制 | 最小切面（不在本轮实现） |
|---|---|---|
| 可用CodeType archive | 20-key store的20个sources全部在原LeWM project内，**没有external filename key**。`CompilerWitnessArchives.metadata_variants`因此不能让这243 external组直接dispatch。CPU4-key archive含Torch/stdlib，可显式加入并逐compile-key试匹配，不能直接迁移CPU SP5的origin。 | 先metadata全量枚举，缺key保CODE_WITNESS_UNAVAILABLE；已有key后仍必须readonly resolve完整nested descriptor。缺项在新独立archive从原归档source按准确flags/recorded optimize静态compile，不exec目标，旧20-key只读。 |
| 原归档source的compiler接点 | `CodeWitnessStore.text`写者缺source时只读live path（L188–203）；`acquire_observed_witnesses/_requests`只从project `call_sources.code_links`取VERIFIED（L158–235），不会取continuation的新增link。 | `source_attachments.py`暴露有界原snapshot文本+准确locator；`code_witness.py`新增显式原归档source入口（核snapshot/fingerprint/encoding/raw与normalized hash），默认live行为不改；`compiler_witness_archives.py`增加明确continuation owner分支，核owner原report/parent/descriptor/link/definition后复用原writer+readonly重读。不能把metadata key存在当CodeType证明。 |
| continuation publication/factory | `source_program_publication._entry_parent2` L531仅direct-admissions；`CompositionIndex.from_source_entry_publication` L814–825也仅`from_admissions`，旧continuation不能冒该schema。 | 两源新增显式continuation publication能力/版本（建议schema3）；保存完整report+parent locator，普通SourceAttachments continuation构造验证，未知/半locator拒绝。schema1/2 direct合同保持。原SP5、AST/CodeWitness/CP2 UNKNOWN及ADD/REVISE CAS均复用，不造fi/bi、CP1或第二图。 |

当前CLI `source_entry_run._terminal/_execute` 只接受自己dependency-stage immutable terminal及direct-admissions产品。不能伪造一个G1 terminal包住旧LeWM archive。首门可用公开catalog/worker/publisher API；通用CLI随后增加明确“existing continuation + project composition + explicit archives + original capture/profile”输入路径，固定原roots，而非import实验run.py或绕过旧terminal guards。

## 当前369749资格与旧SBA的桥

**新静态body出版可先独立完成，不能因此声称86702或其它权重已BODY_LINKED。** 原272038 descriptor/源码证明可产生合法SP5；当前369749在独立fresh raw里验证完整CodeID/descriptor与原静态来源，readonly archive重验后，才能把真实InvocationKey关联同一个qualified body。复用当前 `SameRunSourceProof` 的“精确静态membership + 当前独立owned scan”原则与原attachment full witness，保两capture证据域；不恢复report里的live owner。

这里还有一个真实API guard：`source_invocations._bind_source_invocations` L863当前v4/v5只准`same_capture`，而LeWM当前链用`reused_code`；`qualified_body_admission(process_id,code)`又只含原publication的272038 origins。需要**显式新qualified-static-reuse能力/报告版本**，在当前owned scan完整验证后，为当前369749 origin正常derive admission，再连原qualified ref；不能直接查不到就改PID或复用旧admission。descriptor/来源矛盾必须hard reject，缺archive/环境分别保frontier。旧v1–3、v4/v5默认guard不放松。

旧SBA不只缺一个schema号：`SourceBodyAccess.__init__`只收source report2/3（L116），`bundle`按project fi/bi选body/signature（L466–523），external没有该槽位。需要明确cap下的qualified body accessor：从普通 `CompositionIndex.typed_qualified_body(QualifiedSourceBodyReference)`取得原graph/interface/signature/language/code证据，再给现SBA/operand/environment相同端口/Use检查；namespace始终完整qualified。connector也须显式选新cap，不把v4报告伪装旧3。source/body关联层可先实测通过；actual-formal/env/defaults/return/state/effects/ready仍各自OPEN，SBA桥未验就保“不支持该qualified body路径”，不把所有calls概括reject。

## 下一门：先可核的静态范围，不再CPU探针

G0只做同一LeWM原scope的catalog/archive metadata清点：全817/100438与243 external原组守恒，机械列definition缺口、resumable、已有/缺失compile-key及unique source文件/声明decoded字节；metadata预算显式≥8MB（旧CPU2MB单report不足），graph decode/raw/compile/lower/target=0。可先不打开858大index，仅continuation metadata；publication时正常读plain858一次。

依据G0实际unique-file工作集再申请一次有界批次：新archive缺key静态compile→readonly完整match→普通worker按权重与文件预算自动调度→保存全部terminal/未试→独立普通publication/qualified query。项目15图不加入window，所有候选/原分母不丢，预算不足保未试；不运行每函数100k门。该批通过后，另经Root批准一次当前369749 genuine scan做新qualified-static-reuse body关联，最后才接SBA qualified accessor，不能用static weights填动态计数。确切compiler/lower/graph预算待G0声明工作集，未授权现在执行。
