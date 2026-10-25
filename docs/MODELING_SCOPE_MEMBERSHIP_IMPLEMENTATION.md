# 最小公共覆盖账本：完整 source/call 成员 producer

2026-10-25。**Implemented，小必要 API/拒绝检查通过；真实现档门尚未运行。**
第一阶段整体保持 OPEN。本实现只新增四个模块，不修改 native producer、目标或既有 IR。

| 新模块 | 责任与公共入口 |
| --- | --- |
| `scar/ir/modeling_scope.py` | Scope、原 artifact/record locator、八独立分母、Obligation/Member、四轴结果与精确缺口。`CoverageObligation` 保留 id/source/subject/required_relations/required_expansion/mandatory。 |
| `scar/ir/modeling_scope_codec.py` | `scar.modeling-scope-record`1，`to_dict/from_dict/dumps/loads`；固定类型/tag、严格字段与枚举，拒绝重复 key、bool 计数、错误 scope/端口结构与不支持的细化 subject。 |
| `scar/analysis/modeling_scope.py` | `InputArtifact/InputCatalog/InputBudgets/InputResolver/produce_scope_ledger`。固定 typed catalogs，无任意 callbacks 或 verified=True 授权。 |
| `scar/store/scope_partitions.py` | `publish_scope_ledger/ScopeBudgets/ScopePartitions`，`scar.partitioned-modeling-scope-ledger`1。有界 JSONL+gzip、双 SHA、derived lookup index、PUBLISHED 门及只读单 chunk 查询。 |

`InputCatalog` 绑定准确 source inventory manifest、source-invocations report、capture coordinates
和原合同的 physical SHA/大小/编码，可选既有 native bundle/OS fragment manifest。
它不会 import/compile/lower 目标、读取原 raw、重建全部图或新建 producer/use/state。

组合前提先于成员扫描：partitioned source只接受source-invocations2/3，`report.inventory`
必须是当前composition的准确 `{path,raw_sha256,raw_bytes,decoded_bytes}` receipt，分别等于所给
manifest的canonical原URI、physical SHA/大小及decoded大小。这个public合同的raw指physical
（gzip时也一样），本身没有decoded_sha256字段；后者由root读取及原InventoryPartitions的独立
双receipt核对。缺字段、未知receipt形状或不支持的旧profile明确拒绝，不猜迁移规则。
同Run旧842报告与新843 manifest是输入组合矛盾，不能用语义轴OPEN掩盖。原compiler/static
code_source_origin是独立旧证据来源，不用于替代当前inventory匹配。

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
实际100k吞吐或内存；真实门应分别保GNU进程树peak及runner SELF，并报告其范围。
这些都不是程序建模完成证据。

真实 runner 默认 `PREPARED_NOT_RUN`，不打开输入。待主联合 gate终态、root 确认准确 catalog后，
才允许 `--read-inputs`。拟定预算：200000 members、1000 source files、root/shard各32MB、calls
compressed128MB/decoded1GB、输入 stored+decoded计费2GB、输出 decoded8GB/stored1GB、wall1800s。
这些为独立上限；压缩产物大小和耗时须实际报告，不能用合成数据比例宣称已完成或预先保证。
