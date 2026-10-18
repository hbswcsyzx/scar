# R3.2：单次证据快照、全过程义务与生命周期组合设计审查

## 结论与范围

基线为 root 提供的 clean HEAD `f0dbbd478095b07a684fe4d35ba3b53be20ed17c`；
R3.1 已推送及 4951 full PASS 为 root 的历史结果，本报告没有重新运行。
本轮只读源码、写此新 ignored 报告；**未运行 Python、pytest、full、LeWM、GPU、
capture、安装或 git**，未改产品/tests/docs/旧证据。以下均为 Proposed，待 root 冻结实施。

建议：一次 composition 调用准备一个新的、内容寻址的外部快照视图和完整校验上下文；
在该上下文上调用 P/V 的非 detach 内核，所有需求共享**一个总预算**，最后只 detach
整个公开结果一次。不建新的 producer/state/materialization/lifecycle 图，不把新表或
完整 native/endpoint parser 当作组合前提。

必须修的连接风险不是单纯少一个批量 wrapper：当前 `_content_context` 只刷新
source inventory/Q/D/P/V，清空 gaps 后未重新校验 resource/work/order/evidence bindings，
这些阶段会访问外部 VG/EEG。全过程若直接沿用它，就可能保留旧 external 派生、漏掉
catalog 改变和旧资源缺口。应抽取 `_analyze` 的统一后半 orchestration 复用，而非另抄
一份易分歧的 validator 顺序。root 已确认此实施方向。

## 1. Observed：当前入口实际做了什么

- `query.py:50–79` 每个公开 content 查询新建 ExternalSnapshots，依次重跑 inventory、
  Q、D、source bridges、write/produced、validity；它浅复制原 ctx 并清空 issues/gaps。
  `content_read/production/validity/write/outcome_production/observation_root` 各自再调用
  此准备函数。循环调用公开 API 会逐 read 反复 replay、校验和复制。
- `production_query.py:412–453` 每次构造新 `_Budget`，从独立 inventory 枚举候选后才接
  optional writes/produced，最后 deepcopy。公开 production wrapper 又 deepcopy 一次。
- `validity_query.py:160–169` 每次构造 ValidityBudget；调用 P 时仅把本次 remaining 整数
  传入，再记总消耗。单 read 已有共享预算，但多 read 调用各有一份4096，不能称总预算。
  V 最后另 deepcopy 整体结果（`:276–295`）。
- `snapshot.py:51–58,134–166` 仅在一个 resolver 中按 exact family/SHA/schema/size 缓存
  detached 图；URI 不打开，缺工件是 None/gap，已供坏 bytes/schema/family 必须拒绝。
  `include` 对 source bundle 的派生组件仍会核已供 caller catalog，不可借派生图遮坏图。
- `source_validation.py:17–48` 单次 pass 内已按 manifest/index 身份去重 replay，并在该
  resolver 内 include VG/EEG/SemanticGraph。因此无需另造跨查询“可信 source cache”。
- `validation.py:389–432` 的完整顺序包含 canonical flow/call，以及 inventory、resource、
  work、order、evidence bindings、Q、D、bridges、P、V；当前公开 content refresh 不是它的
  完整外部依赖投影。

这里的 single snapshot 指**一次查询内，对每个准确 artifact 的同一已核 bytes 视图**，
不是所有 mutable caller catalog 的原子时刻快照，更不是一次物理 runtime snapshot。
跨 artifact 的时间/物理对应仍未证，不能由缓存这个实现选择推出。

## 2. Proposed：最小准备与内核分层

1. 先严格核 query-only scope、RunID FK 和正整数总 budget；bool/string/零/负值先拒绝，
   不在错误请求上 replay 工件。scope 使用现 exact `ContractRef + RunID + FactSource`，
   与 reuse 的 Q 设计一致，不新建 wire 表，也不接可任意删小的 read/contribution 列表。
2. 从 index 复制轻量 query ctx；复用 immutable canonical registries、已核实际 flow/SSA、
   call 端口派生，保留该层原 gaps。分配一个全新的 ExternalSnapshots；所有与 external
   graph 相关的 resolved dict/list 必须本次重建，不能 shallow-copy 后修改旧共享对象。
3. 抽出并复用 `_analyze` 后半的 external-stage orchestration：inventory → resource →
   work → order → evidence-binding FK → Q/D → source bridges → P → V。同次准备只执行一次，
   使用同 resolver；有 issue 按现入口明确拒绝，不把已供坏图改成 UNKNOWN。缺证据仍 gap。
   如使用完整 `_analyze` 一次也正确，只须诚实把重做 canonical/FK 成本列入 preparation。
4. 公开 P/V 保留原签名、默认4096、状态/diagnostics 及 detached 约定；抽出内部 prepared
   core 接同一个预算对象、返回尚未 detach 的 view。公开单 read wrapper 自行分配一次
   预算/准备/复制；composition 调用 core，**不能**回调公开 `.validity()` 逐 read 准备。
5. 同 Run 的 source replay、规范原行/edge 清单可以只准备一次。可 memo 完全相同的
   source endpoint/write 索引；实际建立索引、扫描和连接的派生工作记账一次。每个 read
   的 lineage、准确版本/selector relevance、consumer domain/interval/威胁检查仍独立；
   不能按同 Mat/对象/host op 复用另一 consumer 的结论。缓存只活在本次查询，不跨调用。
6. 最后顶层 deepcopy 一次并丢弃 prepared ctx；返回只含原记录/typed refs、派生 routes、
   ledger、conditions/gaps/costs，不把 ctx/resolver 可变对象交给调用者。

无需复制原 StateAccess、CompletionResult 或 ValueOccurrence。新内核名称及具体字典键
由 root 冻结，本报告不把建议命名当已发布 API。

## 3. 义务分母、scope 与缺失 ledger

**先建义务目录，后看哪些 join 存在。** 从 scope 指定原 SemanticGraph/ContractID 的
完整 required_outputs，以及 required=True facets，接显式 ObservationRequirement。
不扫描 caller 提供的全部 SemanticGraph catalog，把无关合同加入当前需求；也不只从
现 roots/reads 倒推分母。每个 selected scope 都返回其原合同、Run、来源及适用条件。

- RequiredOutput 按原 ValueSlotID 逐项列出；删 requirement/root/read 后，该 slot 仍在。
  该 slot 没有显式对应是 gap，不造一个输出 ValueOccurrence。
- facet 只有 facet+required，**没有 endpoint 或 cardinality**。缺独立 typed
  RequiredEndpoint/协议映射时，只能保留 facet-level 未解释义务；不能因 EXTERNAL、
  STATE、RNG、EXCEPTION 等名称就补一个 endpoint、一个 root 或“没有额外要求”。
- 每个显式 requirement 下保留所有原 roots，每个 root 下保留所有 ObservationConsumer
  reads 和缺项。无 root、无 read、缺 source/write/result/support 分别有 ledger 项；
  不能仅列已成功 reads。非 Q 的实际 Host/Resource reads 也须有独立账目或明确未遍历
  边界，不能在汇总时静默当作不存在。
- 不把其它 run 的 root/read 当当前 run 支持。原 model 的所有 inventories 仍在目录中，
  按准确 run 分 scope；已知其它 run 的观测不充当前贡献，未知 scope 保留 gap。
- Run 对每调用合同可能不够：同 run 多 activation/多个 roots 没有由现 ContractDefinition
  定义的适用次数或 root-level AND/OR。保留所有原 root/read，显式列 scope/cardinality
  条件；不把 static call 数当合同实例数、不任取一个 MATCHED root 宣称 fulfilled。
  P/V 内已明确的“必要 selector 部分 AND / 该部分替代支持 OR”继续复用，不能拿它自动
  定义 Q 根的数量语义。后续确需更精确 scope 应先冻结关系，不增加通用 Q 语言。
- scope 元数据完全缺失/合同图未供时，返回明确 scope/contract unresolved；不是空 AND
  成功。FactSource 只是来源，不是已解析 scope applicability 证明。

独立源 universe 保留 P 的 source-first 次序。删 contribution、OutcomeProduction、
write 或 ticket join 不能删原 raw/EEG 候选；已观察 native result 未连接时，继续禁止
请求 whole 的 pending fallback。删完所有 optional joins 也只能留下未接义务。

## 4. 一个默认总预算与可审查截断

建议第一实现保持 **4096 为整次查询派生总额**，不乘 read 数、不为每 read 重置。
共享 ValidityBudget 或兼容 adapter 贯穿 obligation/source/lineage/join/geometry/order/
威胁/组合公式扫描；P 的 `.take` 与 V 的 `.spend` 可适配同一对象。局部 view 可以列
消耗 delta，顶层给真实总额，不能把同一消耗加两次或把局部复制当免费新预算。

最小调度用稳定的合同 slot/typed requirement/root/read 顺序，按实际消耗把余额传给
下一个需求；无必要先造可恢复的 round-robin 查询机。第一项较大可能先耗尽总额，
须诚实显示后项未访问。默认值不保证任意 N 个 read 都完成；增大预算是显式请求，
不是悄悄随输入规模提升默认限制。未来公平分配可以优化，不能改变当前账目含义。

截断必须保留：已核 prefix、已知冲突、当前未完成项、原 scope/contract 容器和剩余
义务 typed IDs 或稳定 cursor/count。准备阶段可一次索引原声明的义务目录并单列其
成本；预算内逐项解释，未解释尾部不当作空。若连目录遍历都在派生预算内截断，则
至少保留准确原 container/ref、next position、总数或尚未知总数的边界，不能声称全集。
失去遍历资格的后项均 TRUNCATED/未检查；顶层不得 MATCHED。

特别 guard：剩余为0时不要调用旧 `production(...budget=0)`，它正确拒绝非法预算；
返回截断 stub/cursor，而不是给下一 read 新建4096或人为补1。已发现 unsafe conflict
可以保留在 ledger，但总遍历截断时不得声称已完整识别所有冲突/缺项。

**成本分账**：

| 类别 | 需要报告的实际范围 | 是否由4096派生预算覆盖 |
| --- | --- | --- |
| preparation | record/FK、canonical flow 若重跑、resource/work/order/Q/D/P/V声明校验及原表索引 | 单列，不冒称有该CPU上界 |
| artifact/replay | hash/schema/family/bytes、manifest/index、原 raw bytes/lines、fixed normalizer replay；准确重复项只处理一次 | 沿原解析器独立限制并单列 |
| derivation | 本次义务/source/lineage/关联、几何、order、invalidator/lifetime、AND/OR | 共享总预算、分kind成本、截断ledger |
| detachment/output | 最顶层一次 deepcopy；若计时/大小，则按实际测量列，不再序列化只为虚构便宜计数 | 单列，输出规模不是常数 |

不能把所有全图扫描和索引都挪到“免费 preparation”再宣称整个查询 O(4096)。prepared
artifact/FK/copy 的实际工作要在公开 scope 说明；本报告没有运行或捏造成本测量。

## 5. 生命周期账目与不得提升的关系

一次 receipt 分别列原 host actual completion、work terminal observations、quiescences、
retentions/borrow releases、handle end、target lifetime events，以及 endpoint/Q 协议。
无 Outcome 表示**未观察/未连接 terminal**，不自动证明还在运行、FAILED、CANCELLED 或
尚可请求 whole。work/资源全集从原 scope 记录和独立 source 取得，不仅列被 Q/read 接上的行。

- host RAISE：`WithinOperation` 仍可在 wrapper 内提交 work；保留实际 RAISE 的
  InvokeBoundaryStateEffect→原 CompletionResult/formal，以及已知部分 produced 和
  outstanding retention。不存在通用 INVOKE AFTER，也不把 wrapper 的异常换成 ticket 终结。
- ResourceOutcome.COMPLETED 可能 short write；FAILED/CANCELLED 保留 actual 部分。
  terminal 不自动 quiet；quiet 不自动结束所有借用；BorrowRelease 不 retire target。
- 结束一个 HandleBinding 不结束另一个 dup，也不证明 OFD/file entity/allocation free。
  fd/address/path 数值复用要用新 lifetime/target。TargetLifetimeEvent 才指准确目标代次；
  其 native 适用仍是条件，不能凭 RETIRED enum 证明真实 free。
- C1 Resume/Replace 只管理原 pending/context 与当前后态；cleanup 可能回调、写、发起
  新 work、RAISE 或不完成。TerminalFrameRelease 的 NOT_GUARANTEED 不退化成文件 close。
  body Return、session COMPLETE/ABANDON、frame 引用放弃均不证明 native work quiet。
- retention 不能证明内容稳定；继续覆盖 producer extent 到实际 read end，扫描独立
  writer/alias、原 WRITE/RW/未知 INVOKE 和准确 handle/target end；write→restore 的两个
  端点相同不能抹掉中间写。不能 blanket 排除同 owner/ticket 的其它 stage。
- 当前解释的队列有序消费仍需原 FIFO/event generation/wait，到**该 consumer Start**。
  它不授 Host read、buffer flush、文件/目录 persistence。EndpointDomain 当前
  `resolve_support` 明确不 MATCHED（`:569–579`）；composition 必须保留 UNSUPPORTED，
  不能用相同 Q protocol FactRef 或 close NORMAL 自证。
- R3.1 CallActivation 只连接同步调用的准确 ports。当前 `validity_order._canonical`
  仍只用 `ctx.point_precedes`，没有由 CallActivation 自动派生跨 activation causal
  path。全过程可展示原 call route；若要将它用于 order，需单独实现并审查窄的同步
  host-edge解释；不能偷偷把 call completion 升为 WorkEnd 或把内部 span 当 whole work。

## 6. 有限但真实的组合验收建议（待冻结，未运行）

| 场景 | 尽量复用的原 fixture | 必须保留的正/负结果 |
| --- | --- | --- |
| Q output+endpoint→load/compute/consume/save | observation_execution + host_lifetime_execution / visibility_execution 的真实端口 | required slot/facet先在分母；无work Host初始化/观察不造ticket；端点协议unsupported仍可建模 |
| 单snapshot完整refresh | 任一原资源/work图，index建好后改变调用者 VG/EEG/catalog | 本次resource/retention/order及D/P/V都核新供图；已供坏hash/FK issue，缺图gap；下一query重查，不借上次cache |
| 两个read共享解析和总预算 | visibility_execution 中两个准确consumer/read，保持各自Use/interval | 一次replay/一次顶层detach；4096不变8192；低预算后项仍在ledger，截断不全成功 |
| root/read/join删除 | 原Q图逐删root、read、support、Produced、write/work join | 原slot/facet和source候选仍在；known source result不能变futurewhole；跨run根不借 |
| submit后host RAISE仍pending | invoke_work_execution 的真实RAISE槽；**另造无Outcome变体** | 原fixture raised默认FAILED，不能冒称已覆盖pending；保留ticket/effects/retention/实际部分后态，不补NORMAL |
| host RAISE但部分native产出 | invoke/produced图接精确原result和actualselector | wrapperRAISE与native终结独立；FAILED/CANCELLED部分仍保留；COMPLETED4/8不充whole8 |
| cancel请求/timeout、terminal但无quiet | work图+真实普通/INVOKE helper | cancel请求不当Outcome；无quiet/borrow-release继续缺口，错ticket或早release拒绝 |
| cleanup返回/raising close | driver_cleanup_release_program(helper=False/True)，保留body C1 | 在同一图接资源work/retention；Resume后仍可有outstanding work；helperRAISE真实freshpack/Replace，不将private token传opaque |
| quiet→borrow release→close→retire | work/resource/lifetime图准确scope和point | 分项账目可回查；一个动作不自动产生另一个；重复frame release不授free，dup close-one不retire共用target |
| overwrite/restore、allocation/fd reuse | intervening_host_execution / resource_execution_program | 原interval内写不漏；new lifetime不能借old支持；unknownalias/phase继续gap |
| 同/跨queue与event重录 | event_order_execution / visibility_execution | r1不覆盖p2/r2；仅End→C.End不授C.Start；无FIFO/错误generation保留缺口/错误，不推Host同步 |
| flush/close/persist及partialcapture | Q endpoint + 原普通/INVOKE file helper | 无nativeparser不伪MATCHED；flush/close RAISE保留actualstate；没有实际后续站点不补terminal/quiet/持久化 |

这些应是新组合中的准确连接断言，不是重复跑旧独立case后加一个“pipeline通过”标签。
首实现可用少数完整小图共享构造，避免每个矩阵行重建全图或引入native捕获后端。
source/runtime/visibility/identity/transform 的原 false flags继续保留；本门不产生
LeWM加速比、不关闭R3后续全部native协议或完整M0–M2。

## 7. 阅读与实际源SHA

选择性阅读：当前query准备/公开入口、完整预算类、P/V core及ledger、snapshots、
统一validation顺序、inventory重放、Q FK/scope、work/outcome/retention、order和V
invalidator/endpoint规则；fixture名称/结构与前轮已读同hash源码核对。未将自写V文件
当独立产品验收，也没有运行fixture或测试。SHA以只读`sha256sum`取得。

| 文件 | SHA256 |
| --- | --- |
| scar/ir/execution/query.py | 94b098d75a0568cf48240ff7078f8d4a99b9353c5abd73ccbef804c28803400a |
| scar/ir/execution/validation.py | e3a440dc32c4aacba3b4a53b536d11341c0892a4bb5dda08007448bc5dba395d |
| scar/ir/execution/snapshot.py | 7757c299a965e37f5e73eeaa1f4ed304da6b7bfb970cded5d274fdc4e8483107 |
| scar/ir/execution/source_validation.py | 34f1f929dec9f55ae74913ff19ec23820e262433ed59340bf5b70c79fd91b1e2 |
| scar/ir/execution/production_query.py | 3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab |
| scar/ir/execution/validity_query.py | de6313dc979859a7c92d79a67e36b49c6f29d6bb0ce4bc34a1bbfef52d6113b9 |
| scar/ir/execution/validity_budget.py | e1b297345fc1a63716da5d8d7f2434b4999e3200ad3b6ee4f3823c5d99244b10 |
| scar/ir/execution/validity_order.py | 8e0c0afcf8ada6cfddbc217c6de733868406921ed85f709f7979f70951b55ad4 |
| scar/ir/execution/validity_stability.py | c394f306fe4ff318ee80badf112881f5c2b8c310b881b74253eeca66afe9aadd |
| scar/ir/execution/validity_validation.py | b347ece5df59c8a6aeeb0e7421a533f1decb1c21eacd6cbaf755c3254c6a161e |
| scar/ir/execution/resource_validation.py | 3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08 |
| scar/ir/execution/work_validation.py | 1cccc760cb93268f4e282417e1d5fe8f1034870c474866237246ea7bae9e6984 |
| scar/ir/execution/order_validation.py | cbea6d0b1072c0cf7a3579e07a13a3a9bad808b807c779e66ac76acf43f6ea09 |
| scar/ir/execution/observations.py | 8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882 |
| scar/ir/execution/observation_validation.py | eaae52e54664107ac7baa7aa5707fbf2a19be6e9b59346f0ce37040f563ff983 |
| scar/ir/execution/content_validation.py | 92afdb38caf716c4187c4a2a9173207c8dc2cc6110a3fd3d83f22852b67ed49a |
| scar/ir/execution/production_validation.py | 6eda717b717581c91b9301fcb6995e199ae98fb2f618066f79dfe509819da256 |
| docs/M1_VALIDITY_API.md | 26e6812924b8ef2628a0a0642d8af1d01ccf264aeaf5b03b866d813db909e445 |
| docs/M1_RESOURCE_READY_CONTRACT.md | b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f |
| tests/fixtures/execution_work_graphs.py | 7428d0bd7a1597232d49587d5378cce3b4fae077a306d51d474e8d46e6aec60f |
| tests/fixtures/execution_visibility_graphs.py | 478eb976dc8aef267bce1d5fbd50beacb6cdeef6797d7c6c417c0cc21895a5fe |
| tests/fixtures/execution_lifetime_graphs.py | 1d0323fb080758156ee10f4f675bdab5acb990fe60bcd6963498b7577c9d7c3e |
| tests/fixtures/execution_observation_graphs.py | fef4e061a5af321f1173b34366df908495ed2505345994f19169e9baeaa419d9 |
| tests/fixtures/program_lifecycle_cleanup_graphs.py | 2c50833ec7571796d9c500e7a43a8daf46ada860676f4bf6203e3662cc841238 |
| tests/fixtures/execution_call_graphs.py | 6fa0d2eca706edc3a371d4d8d8581973b7e28b94ce5623e89048789e3fc8c90b |

结论：R3.2需要一次完整准备、共享派生内核、显式Q/Run义务ledger和生命周期分账；
这些是已有接口的组合/查询修正。真实跨call order解释或更精确合同实例次数若需支持，
应单独冻结窄关系；当前不能用parser缺失或任意FactRef去伪造完成，也不必新增完整前端。
