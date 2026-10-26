# C02 12,541 个 native/source 缺项

完整声明审计已收齐 **24,082/24,082 work、115/115 chunks**。12,541 个缺项都有原 provider host：其 ETO host 与 canonical native INVOKE 不是同一 instance，但全部沿保留索引的 `nodes.parent` 命中 canonical native 祖先。数据支持缺少“内部 ETO host → 外层 canonical occurrence”包含连接的诊断；尚未核原 per-node `ctrl_deps/parent_basis`，不授调用、source invocation 或数据／状态边。

| Observed 完整分布 | 数量 |
|---|---:|
| 有 native/source context/static code-source binding | 11,541 |
| 三者均未接；原因均为 ETO scope 不在 canonical native exact-ID 集合 | 12,541 |
| 每 work host 关系数 / distinct host 数 | 3 / 2 |
| PROVIDER_SCOPE_CONTEXT / SUBMITTED_BY_RUNTIME 关系 | 48,164 / 24,082 |

三条关系是同一 ETO CPU scope 的两条准确路径（scope直达；scope→runtime→work），以及 runtime→work。缺项的25,082条 scope路径均为 ETO cpu_op，另12,541条为 Kineto cuda_runtime；完整 host ID 的 native join 均为0。相关37,623条路径 pid/tid/external id均为整数、raw locator均存在，不是空host或丢定位；ETO logical tid不能当OS TID。全部gaps与原report一致：native/source各12,541、STATE_CONTENT_READY_UNPROVED=24,082、STATIC_BODY_MEMBER_UNREVIEWED=2,391。完整分布见RESUME.json。

独立精确SQL的物理GPU分母为kernel22,457、memcpy543、memset1,082，合计24,082；每target有唯一direct provider scope。缺项对应10,823个distinct ETO host。首次canonical祖先的work加权深度：

| 深度 | work |
|---|---:|
| 1 | 10,047 |
| 2 | 2,208 |
| 3 | 256 |
| 5 | 30 |
| 断链／无parent／环／未命中 | 0 |

典型例按统计类别中最小原ID机械取：GPU …:kineto:385137，ETO host …:eto:20837 → canonical candidate …:eto:20833，深度1；原nodes ordinal17303/17304、同pid369749/logical tid1，candidate对应一条native记录。完整qualified路径/原raw引用在RESUME.json。没有按函数名、裸correlation或最近时间选例／补连。

**源码解释（Inferred）。** analysis/fragment_relations.py:311–327只索引canonical entry INVOKE，:470按host完整instance等值连接；:417–418在native缺失时跳过source查询。因此source缺口是这条连接链的下游断口，不等于source inventory缺失。ir/execution/fragment_relations.py:192要求native binding与host为同一原instance；此guard正确，祖先不可偷填此字段。需要单独有证据的内部host→parent路径→外层qualified occurrence关系，再引用外层retained source context；不能造内部CallActivation/Tensor/state边。现WorkRelations的source-context membership也只承认host.native，因此须明确typed接点，不能仅在query中替换身份。

**证据限制。** nodes.parent由analysis/fragment_relations.py:246复制OperationInstance.parent；当前trace/native_import.py:210–262从ETO ctrl_deps生成，标collector-stack containment。SQL未保留per-node parent_basis/ctrl_deps，本轮未重放原EEG；下一小门需定点核原字段及provider合同，不能将索引候选倒授原始证明。原C02 scope是source858/current-runtime858，旧843导航不替换；全程序state/content/ready仍OPEN。

**窗口／原失败。** 首轮exit1/180.003484s原样保留AUDIT.json、ACTUAL_TERMINAL.json和INITIAL_PARTIAL_REPORT.md。prefix最后完整归类ordinal16086；第16087条中断后的部分计数按实际贡献先撤销，再在续审完整计一次。经root授权resume实际exit0/93.520744s，suffix16087–24082共7996条，无ordinal重叠遗漏。只解suffix chunks75–114；partial gzip必须重复解178行前缀但不再归类。全115chunks stored SHA/decoded SHA/bytes/rows已跨窗口EOF核对；全局ID唯一性未再跨窗口重放，不扩授该项。

Manifest SHA98faaa2fe721ccd1377dcfdea0ed28278f4577f4a244099d23fe077ec9df91d7对原receipt核。四源SHA同旧C02，直接strict codec解声明；新版helper的旧producer guard未调用／放宽，C02旧整门exit1不改。

SQLite旧receipt为NOT_REMEASURED；本次新测并续审重核SHA9d2ab538685645abc61ab2805adc6677ced91f377bfe7c88fd640889171fc421、697,589,760B，末stat不变，仅同bytes只读内存SQL。nodes461,242/selected edges78,171/native39,796/source79,592。新测量不补旧历史SHA、不替代原EEG重放。

首轮计费输入1,334,213,422B（另81,017B四源和1,455B旧receipt）；续审1,026,588,983B/RSS1,401,192KiB，在新1.5GB/180s内。两窗口计费合计2,360,802,405B，含两次DB及gzip前缀重复读取，不称总计小于原2GB；小定向源码／报告读另列。没有EO/raw、大native/static graph、目标执行、模型重产、main/五源/原index修改或Git操作。收据见RESUME_ACTUAL_TERMINAL.json、两份read-plan及RETENTION.json。


后继独立parent抽查实际exit0/1.071011s：现有BundlePartitions.selected_records普通选读同chunk的17303/17304两原EEG行，并用原OperationInstance strict codec解码，确认host eto:20837.parent=eto:20833、ctrl_deps=20833与parent_basis完全匹配。固定provider源cf30153… SHA c6ec2dac4140b28eea17c8c6054d42e084ab6014fa8f47e72282e7c4caba46db，observer读取当前线程operator stack并原样写ctrl_deps，非时间推断。该样本只授两原记录资格，不覆盖完整12541候选。前两次小harness错误（receipt字段名、tuple返回形状）独立保留FAILED01/02；首个未读chunk，第二个已核同chunk后在typed adapter前失败。三次共原输入34,107,845B，另固定provider源33,269B；不是一次17MB的总成本。原全量审计资格不受这两个harness失败改写。下一typed关系设计见ENCLOSING_NATIVE_PLAN.md（未编码）。
