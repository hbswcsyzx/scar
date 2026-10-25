# 最小公共覆盖账本：完整 source/call 成员 producer

2026-10-25。**Implemented v2；主树 retained source/call membership 真实门已 exit0。**
完整枚举并索引 2217 个原 source 定义及 100438 次原调用，合计 102655 个成员。
这是原记录成员归属验收；依赖连接、内部展开、运行语义及其余六域仍 OPEN，第一阶段整体
保持 OPEN。本实现只新增四个模块，不修改 native producer、目标或既有 IR。
实际收据及成本见[本次结果](../artifacts/experiments/modeling_scope_retained_gate_20261025/RESULT.md)。
record/transport均为2，policy为SOURCE_CALL_MEMBERSHIP_V2。已保存的v1 prototype及recipe保留，
其ScopeRevision缺少输入/全部producer绑定是已知缺口；v2 reader明确拒绝旧prototype，不静默迁移。

| 新模块 | 责任与公共入口 |
| --- | --- |
| `scar/ir/modeling_scope.py` | Scope、原 artifact/record locator、八独立分母、Obligation/Member、四轴结果与精确缺口。`CoverageObligation` 保留 id/source/subject/required_relations/required_expansion/mandatory。 |
| `scar/ir/modeling_scope_codec.py` | `scar.modeling-scope-record`2，`to_dict/from_dict/dumps/loads`；固定类型/tag、严格字段与枚举，拒绝重复 key、bool 计数、错误 scope/端口结构与不支持的细化 subject。 |
| `scar/analysis/modeling_scope.py` | `InputArtifact/InputCatalog/InputBudgets/InputResolver/produce_scope_ledger`。固定 typed catalogs，无任意 callbacks 或 verified=True 授权。 |
| `scar/store/scope_partitions.py` | `publish_scope_ledger/ScopeBudgets/ScopePartitions`，`scar.partitioned-modeling-scope-ledger`2。有界 JSONL+gzip、双 SHA、derived lookup index、PUBLISHED 门及只读单 chunk 查询。 |

`InputCatalog` 绑定准确 source inventory manifest、source-invocations report、capture coordinates
和原合同的 physical SHA/大小/编码，可选既有 native bundle/OS fragment manifest。
它不会 import/compile/lower 目标、读取原 raw、重建全部图或新建 producer/use/state。

组合前提先于成员扫描：partitioned source只接受source-invocations2/3，`report.inventory`
必须是当前composition的准确 `{path,raw_sha256,raw_bytes,decoded_bytes}` receipt，分别等于所给
manifest的canonical原URI、physical SHA/大小及decoded大小。这个public合同的raw指physical
（gzip时也一样），本身没有decoded_sha256字段；后者由root读取及原InventoryPartitions的独立
双receipt核对。缺字段、未知receipt形状或不支持的旧profile明确拒绝，不猜迁移规则。
source-invocations2/3 的当前 public writer 五字段 descriptor 为
`path/rows/raw_sha256/raw_bytes/compressed_bytes`；正文打开前核 compressed_bytes 的 file stat 与
预算，完整遍历后核 decoded SHA/字节/行数。不支持的旧四字段 profile 明确拒绝。
同Run旧842报告与新843 manifest是输入组合矛盾，不能用语义轴OPEN掩盖。原compiler/static
code_source_origin是独立旧证据来源，不用于替代当前inventory匹配。

ScopeRevision绑定所有准确输入，而不只绑定Run/coordinate：对应Observability.sources保存
source inventory、source-invocations、可选native/OS的完整root与准确collection declaration。
这些只是typed来源锚，coverage仍UNKNOWN；没有把未审内容当成已证事实。故同Run、同command下
换新inventory及matched report，或只换report/native/OS输入，都会得到新的revision。
状态评估不参与ObligationID，原logical URI/namespace仍是成员身份的一部分。

新增显式policy_sources绑定四个必要producer源码artifact，不混入程序CODE_VERSIONS。
InputResolver在初始化冻结四者的初始URI/SHA/size；finish_publication与manifest receipt生成
都逐一终检，任一源码在运行中改变即拒绝。公开producer receipt只返回已冻结版本，不把中途
出现的新SHA伪装成当次已用版本。ScopeRevision包括这一组typed policy anchors。

首个 producer 完整遍历原 source shards 的全部 DefinitionInventory；有无 canonical body、是否
UNSUPPORTED/NOT_ATTEMPTED 都不影响入账。它随后流式遍历同 Run 的全部 published invocation
rows，核原完整 decoded SHA/字节/行数、唯一 InvocationKey、已知 Run/process 及原 anchor。
无 source/body 的调用仍有可定位的 obligation。

subject 是原 JSON/JSONL 的准确 artifact/record pointer/实际行 SHA，加稳定 ScopeID。
本版本显式不支持重解释裸 ID 或其它 qualified-entity 细化 variant。ObligationID 使用原 logical
URI/namespace、schema、decoded SHA及准确 pointer/line；同字节、同scope但原URI不同不能合并。
初版 InputArtifact 的原URI就是固定输入路径，没有物理retention迁移映射，不能据新路径/相同
SHA猜测仍是同一原artifact，也不承诺搬家后自动保持身份。需要迁移时必须另有显式原logical
URI→物理retention路径的证据接口；原IR/provider身份不因本账本改变。

SOURCE_DEFINITIONS 与 OBSERVED_PYTHON_CALLS 在完整遍历及 receipt 核对后可标 ENUMERATED。
其它六域各有 mandatory 集合义务、准确原集合引用、declared count（若来源确实提供）、
未访 cursor 或缺 provider debt。dispatch attempts 从原 coordinates 的 collector declaration
取值；不知道数量的域保持 null，不当作 0。native/OS manifest 仅读其描述，不展开大 archive。
现有已建 OS/physical 表不是现实资源的全集，observation completeness 保持 UNKNOWN。

Scope 保留原 argv/cwd/code-env/config/input/run/process/window/provider 层级的全部十一类字段义务。
初版不从分析机填缺失的历史值。这些 scope-field 缺口可以与已实核的原成员归属同时存在。

四轴分别查询。初版只把实际固定 owned scan 确认的 ORIGINAL_RECORD_MEMBERSHIP 记为满足；
依赖、内部展开、运行语义的原 requirement keys 全部保具体 OPEN。它没有 accepted semantic scope
adapter，显式拒绝语义 SATISFIED/NOT_APPLICABLE 输入，不因原报告的 PASS/validated 字段升级。
因此本 policy 的聚合始终 OPEN；不能通过改分母、missing count、mandatory 或元数据获得全程序通过。
后续如增加原 accepted-scope 复用，须显式 policy/capability 及准确 receipt 适用范围，不能静默扩权。

新 native-capture-batch 留有 typed 输入位置，但在实际公共 schema 发布、固定 adapter 接入前
明确拒绝非空输入，不猜其字段，也不要求修改旧 dispatch bridge。完整39796 dispatch主线产物
可以在发布后直接对接；本版本没有反复16-prefix或 scalar小门。

每个 data/index chunk 同时限制 decoded/stored 8,000,000 bytes、1000行；单记录有独立上限。
publisher 只接受 InputResolver 的逐行 owned handoff，漏行、改 mandatory、提前结束或全文 SHA
不符均拒绝。发布前失败/预算/中断保留 BUILDING、已闭合 chunks 和 FAILED 收据，不发布 manifest；
原子commit完成后的中断不撤销已完成root，若写失败收据则准确标为PUBLISHED。
index 只存 obligation ID→chunk/line，是可重建定位记录，不是新的程序事实权威。

`ScopePartitions(manifest, expected_sha256=..., budgets=...).query(id,scope_revision=...)`
核准确根 receipt 和 scope，读一个 index chunk、一个 data chunk；不读原 source/raw 或要求 live
会话。`last_query` 报告复用 retained byte/membership 来源、此次 raw 未重放，语义仍 UNREVIEWED。
查询不依靠全量 source/call 复扫来维护可信性；根及 chunk 的不可变 receipt 是原发布资格的边界。

必要小检查与准备的 runner 在
`artifacts/experiments/modeling_scope_membership_20261025`。三组 unittest 覆盖 codec 往返与关键
错误输入、成员分母守恒/明确 debt、错 Run/重复调用、篡改 chunk、错 query scope、改 mandatory、
未发布 batch 拒绝，以及预算中断不发布；同scope同bytes但不同原URI必须得到不同义务身份。
64个合成调用+5个定义的两次小成本记录分别约0.49/0.54s、SELF peak39816/1073056KiB；
后者保存当时producer SHA（在原URI修正前），不与当前代码混为同一测量。不能用小测保证
实际100k吞吐或内存；真实门分别保GNU-time worker command的maximum RSS及runner SELF，并报告其范围。
这些都不是程序建模完成证据。

主树真实门由 root 审核准确 catalog/freeze 后在 conda lewm 中持有会话执行，session11385
实际 exit0。runner 默认仍为 `PREPARED_NOT_RUN`；本次使用 `run_gate.py --execute --freeze-sha256`
的显式入口，固定输出 `modeling_scope_retained_gate_20261025/attempt01/ledger`，未自动重试。
输入为保留的 source inventory shards 与完整 source-invocations archive；没有新 LeWM episode、
目标执行或 raw capture replay，也未展开 native/OS chunks。既有 source_revision_current 报告只作
准确输入，不把其独立复核尚未完成的结论记为本门成果。

本次记录 102655 个 DenominatorMember、102661 条 mandatory obligation（含六域集合义务）。
八域均保原集合定位与独立分母；SOURCE_DEFINITIONS 为 2217/2217、OBSERVED_PYTHON_CALLS
为 100438/100438 ENUMERATED，二者的 observation_coverage 仍为 UNKNOWN。其余六域为
DECLARED、enumerated_count=0，保原 declared_count、DOMAIN_UNENUMERATED 和 cursor；
native 的 CATALOG_RUN_BINDING_UNREVIEWED 仍保留。依赖轴未满足 requirement 数 1629202，
内部展开与运行证据轴各 102661，结构轴为六个未枚举集合义务；这些是 requirement 计数，
不是去重的缺失程序边或已完成语义事实数。

| 实测项目 | 本次记录 |
| --- | --- |
| chunks（data+index） | 637 |
| stored / decoded bytes | 126695719 / 4268542417 |
| 输入 stored+decoded 计费 bytes | 710234125 |
| worker wall / launcher wall seconds | 694.3875720299839 / 694.529312846018 |
| GNU-time elapsed / user / system seconds | 11:34.51 / 688.87 / 0.71 |
| SELF / GNU-time maximum RSS KiB | 114576 / 114576 |
| 只读查询样本 | 10；各读 1 个 index chunk 和 1 个 data chunk，raw_replayed=false |

完整 locator、规则/证据引用和四轴要求在逐义务编码中重复，decoded 产物超过 4.2GB。
这次实测证明有界发布与成员定位可运行，不能称为高效编码，也不测得逐查询延迟或推广到其它
工作负载。查询复用的是准确冻结版本的字节/成员资格；语义证据仍为 UNREVIEWED。原生产图
仍是事实权威；PUBLISHED_MEMBERSHIP_ONLY 与 aggregate OPEN 不等于全程序建模 PASS。

本次独立预算为200000 members、1000 source files、root/shard各32MB、calls compressed128MB/
decoded1GB、输入 stored+decoded计费2GB、输出 decoded8GB/stored1GB、producer wall1800s；
外层2100s、20s heartbeat。实测没有越界，但不以这一次成本预先保证后续全域 producer 成本。

v2增量必要检查另见`check_scope_revision.py`及`scope-v2-checks-01.json`：matched新inventory/report、
仅report或可选native/OS根改变会改变revision；任一四源码初始版本改变会改变revision、中途改变
拒绝发布；仅assessment改变不改ObligationID。constructor/codec重新核revision等于全部typed
scope字段（除revision自身）的规范hash。旧prototype1 record/transport明确unsupported。
全部11组小检查通过；另有 descriptor header/stat 小检查增量。真实 source/call 门已在主树
完成，未在隔离树重开；原 receipt、旧小产物、recipe 及本次冻结文件全部保留。
