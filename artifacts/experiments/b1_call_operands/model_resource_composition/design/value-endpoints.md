# R3 值、来源与 Q 端点：独立设计审查

状态：**Proposed / 只读审查**。基线 `348d18277b963bc183fb420bf173f05594d667d8`。
本轮没有改产品/测试、执行 pytest/新见证、采集目标或初始化 GPU；不对已验收 V 重做验收。
649-component/4826-full 是既有 V 归档结果，不是本报告新运行的证据。

## 1. 建议根决定

1. **组合表达不需要先新增一套通用 Endpoint 类型/表。** 现 ResourceTarget、EndpointContent、ProtocolSelector、Q requirement/root 已能保守保存所需身份、当前状态及未知协议。read/flush/persist 未解释不是再加 enum 就能解决的问题。
2. **优先实现一份公开的、从完整 Q/来源分母出发的组合视图和真实 canonical 组合夹具**，复用 D/P/V、原 Uses/StateAccess 和 per-query snapshots；不复制 producer、state、pytree、geometry 或 writer 清单。Endpoint 未解释、cross-call 未配对不得伪装成已完成路径。
3. **当前不能无条件称“跨调用全过程已接通”。** dynamic caller occurrence→callee activation 没有 typed 关联（§4.1）。单 activation pipeline 可先作为限定结构组合正例；若 R3 关闭标准包括多次函数调用/跨 Region 递归端口回查，则先冻结这条最小对应，不能用同名 Region、时间或 provider parent 猜它。
4. **不要为了让 EndpointDomain 从 MISSING 变 MATCHED 就硬造 native parser。** 若本门明确要求一个端点协议的正向机械解释，必须先选有实际源记录的窄协议，列出原资源、selector/返回值、后态、observer 及失败规则；只是增加 FactRef/COMPLETE 不能闭合。通用接口可保留，具体协议适用仍单验。

## 2. 已有规范引用路径（Observed：代码，不是物理事实）

| 关系 | 可实际回查的原路径 | 不能推出的结论 |
| --- | --- | --- |
| core 端口与内容 | `ContentRead.consumer.subject=UseRef/AccessRef → UseOccurrence → ValueOccurrence → 原 ValueID/producer`；`ContentRead.effect/anchor/support → 原 StateAccess/current StateVersion`；`content.py:309`，`query.py:164/188/222`。 | Reference/ObjectIdentity 不是永久内容版本；传递引用不等于读其内容。 |
| 逻辑值/物化 | `placement.materialization=(ProviderArtifact,MaterializationID) → VG.Materialization.value_version → ValueVersion.provenance_id/parent_versions`；`values.py:61/82/150`。 | 同 value version 不等于同 allocation/domain，两个物化不能自由替换。 |
| 物理位置 | StorageContent → 原 mat.region → StorageRegion.allocation/offset/shape/strides/dtype；EndpointContent → region=None Mat + ResourceTarget + 原 selector；`content.py:280/291`，`content_validation.py:312`。 | region=None 不是文件/NVMe；endpoint selector/Footprint 不能直接当 byte region。 |
| 实际生产 | `WriteAssociation.stage → RawRecordRef(line,SHA) 或 SourceEdgeRef → inventory/resolved bundle`；`writer → ticket/host/external`；`production → 原 value/effect`；actual → OutcomeProduction 或 EstablishedProduction；`production.py:233/263`。 | PRODUCES 是 observed result，可能是 view/no-op，不当然是物理写。COMPLETED 不等于 whole。 |
| 来源 scope | inventory manifest/index → strict replay IRBundle → 固定 VG/EEG/SG component artifact；`source_validation.py:17/106`；跨图用 SourceEndpointBridge。 | 相同裸 MatID/ValueVersionID、路径、shape、采样值或字符串 locator 不能跨 artifact 合并身份。多对多缺 pair 不是排斥。 |
| Q 观察 | `ObservationRequirement.contract=(SG artifact,ContractID) → RequiredOutput(slot)/RequiredEndpoint(requirement,facet)`；`ObservationRoot.requirement → actual OutputValue/BoundEndpoint/ExternalEndpoint + interval/anchor/support`；`observations.py:24/50/97`。 | EXTERNAL facet 不等于 file durable；root 存在不等于 Q 已满足。 |
| ready/有效性 | 每个 ContentRead → P 的完整 source candidates → exact write/actual/version/placement_match → V 分段 labels AND/替代项 OR；`validity_query.py:157`。 | 输入血缘祖先不变成本次物化的 AND writers；一条队列边不能证明文件 flush/persist。 |

`source_validation.resolve_endpoint` 只在同一严格 bundle 中派生 facets；跨 artifact bridge 保留 runtime-unverified。
Object 多版本绑定不选“最新”；`source_validation.py:129` 明确保留当前版本缺口。
`ProvenanceRecord.producer` 与 `Materialization.producer` 是 **v2 OperationInstanceID**，不是 core OperationID/OperationOccurrenceID；必须经 exact scoped occurrence/work binding 回查，不能改前缀当同一个 producer。

## 3. 一条全过程应怎样组合（Proposed，不捏造语义）

1. **open/read**：path 是普通数据；namespace/file content/OFD offset/wrapper 状态是原 StateLocations；ResourceInstance(FILE_ENTITY/OFD) 与带代次 handle 独立。Read 的有序 Uses 读当前内容/offset，readinto 另写 destination；真实 NORMAL/RAISE 结果及部分后态保留。
2. **原始值**：文件当前内容 snapshot 可有 endpoint Mat；read 返回 CPU bytes/tensor 有自己的 Mat 与 allocation。只有明确的、带范围和版本的 exact-copy 依据才可共享 logical version；子范围、decode/normalize/cast 默认明确记录 VIEW/TRANSFORM 等来源，不凭 bytes 一样就等同整个 file version。
3. **CPU→GPU**：exact materialization 可让同一 Version 对应不同 CPU/GPU Mat/alloc；真实复制由原 work/effect/source 与 actual 连接，不能从 `.to()` 名称推 DMA。转换精度/表示含义变化时保留新 Version/provenance。mode/RNG/autograd 等仍是原 StateVersion/effect 依赖，不塞进 ValueVersionID 伪造值父节点。
4. **compute**：consumer 使用 exact original input port/current state + actual ticket/input correspondence；结果新 Version 的 provenance inputs 解释血缘。对其结果 Mat 的 V 只判断该 Mat 的准确实际贡献，前面 file/read/normalize 是逻辑前提/上游 read 义务，不能全列为结果 Mat writers。
5. **encode/write**：序列化/编码有状态时保留其 StateAccess；产生 encoded version/物化。写出同时是输入 Mat 的 consumer 与 endpoint 状态的 writer；两面都引用原操作的不同端口/效果，不能合并成一个“save”纯节点。无 work 的 host write 用 EstablishedProduction，不造 ticket。
6. **flush/close/观察**：各动作保留原状态及真实返回/异常；ObservationRoot 指明确 observer、resource target、selector、interval/Q requirement。最后一条 close 不是观察根自动选择规则。读取、缓冲排出、持久化的合同分别保留。

同一个 object 被 readinto 或 NumPy alias 原地覆盖时，ObjectID/storage 可保持而 StateVersion/内容版本必须改变或保持 unresolved；deepcopy 新对象/alloc 的关系通过原 provenance/copy 依据，不以指针 `_version` 或采样证明。
旧 `scar.ir.provenance` registry 的 `ExactContract/mark_ready/ReadyState` 属旧声明接口（`provenance.py:417/600`），新组合查询不能借它们绕过 V 的 occurrence/domain/source 义务。

## 4. 真缺口：什么是不能靠“公开面”补出来的

### 4.1 动态 call/activation 对应

`coordinates.py:114` 的 RegionActivation 只有 region/process/entry EvidencePoint；InitialEntry 只有 source，ResumeIngress 只接 suspension successor。
`model.py:62` 的全部表没有普通 CALL/INVOKE occurrence→child activation 的 typed 关系。
`query.formal_route`（172）只沿实际 ControlTransfer 定位 successor formal；`program.queries.environment_call`（885）提供原静态 call_arguments/invoke_arguments→callee entry 的映射，不能选择这次运行的 child activation。

反例：同一父函数连续两次调用同静态子 Region，第二次参数/环境/state 已变化，或递归调用。两个 child activations 都指同 Region；绑定各自的 entry 数据/退出到 caller completion 不能由裸 RegionID/provider parent/时间推出。
**若 R3 要覆盖此类组合，最少需要显式对应来源与双端发生身份**：实际 caller occurrence、实际 child activation、实际 child normal/raise exit（存在时）到 caller result/completion 的准确对应；actuals、formal order、环境/state 分区仍由现 canonical callee/ports 派生，不存第二 actual tuple。未见 child entry/exit 要有精确 gap，RAISE 不回滚部分 state。此处是需 root 冻结的关系，不预设表名/wire 或本轮已实现。

### 4.2 Endpoint 的表达与解释是两个问题

表达能力已有；解释能力缺：`ProtocolSelector` 只有 FactReference，无已解释的范围/单位；BytePrefixWrite 是 Storage uint8 前缀 profile，不能把它用于任意 file/codec endpoint。
`production_ranges.py:47–84` 对 Endpoint/不可映射实际范围保留 placement_match=None；`validity_query` 不把 None 计为实际覆盖。
`validity_validation.py:569–579` 明确 EndpointDomain 恒 unsupported，协议/Q FactRef 相等也不成功。这是准确当前边界，不能在 R3 报告中删掉。

若要正向解释 endpoint，所缺不是另一套 FileValue/ReadyState，而是固定 native/source schema 回到：准确 handle/resource incarnation、原请求 selector/current state、实际返回与 partial footprint、建立 observer domain 的动作和生效/失效区间，以及 protocol/error obligations。
现 SourceEndpointBridge 目标限 Value/Mat/Object/Region/Allocation（`production.py:158`），不是 provider ResourceID→ResourceInstance 的通用 identity 证明；native file handle 对应仍不能靠裸 fd/路径填充。
没有上述实际数据时，组合查询显示端口链、所需义务和 UNSUPPORTED 即可，不伪造 parser。

### 4.3 Q 内容映射不能由 facet 猜出

`observation_validation.py:94–113` 能核 required slot/facet 存在；137–154 仍明确 output-correspondence-unverified；BoundEndpoint 校验 exact requirement binding，但不解释 protocol。
ContentRead 把 Q root 与具体 version/placement 关联，仍须报告原 basis/slot/selector 的对应状态。一个合法 ContentRead 的局部 MATCHED 不等于契约全部输出或所有 endpoint obligations 已满足。
`required_outputs`/facet 并不按读取关系自动分配观察区间；没有 root 的 requirement 不能从结果分母消失。

### 4.4 whole-work 边界

`WorkEvidenceBinding` 只有 ticket/artifact/instance（`content.py:192`），没有 instance 是整 work 的 start/end 还是内部 stage 的角色。
`validity_order.py:127–130` 正确拒把内部 EEG HB 升为 WorkEnd→WorkStart。R3 优先复用现 queue FIFO/event/wait 做正例；若要用 native HB 闭合跨层边界，须有准确 whole-ticket extent/profile 来源，不能新增 START/END 枚举自证。

## 5. read / flush / persist 的合同分离及 overwrite

| 请求 | 必须准确引用 | 不能作为充分依据 |
| --- | --- | --- |
| 读取某版本/范围 | 实际 consumer/root、读取区间、所读 Mat/endpoint selector、当前内容、visibility/alias/lifetime 条件。 | 相同文件路径、同内容采样、一次返回相同、只有 handle live。 |
| 排出 wrapper buffer | 该 wrapper 待输出内容及版本、目的 endpoint、具体 flush 动作的实际 completion/post-state/可能部分写、错误传播。 | producer WorkEnd、buffered write 成功返回、另一个 wrapper 的 flush。 |
| 系统/存储持久化要求 | 精确所需 file/content/metadata/namespace 范围、sync 协议及原成功/失败、需同步的层级和版本边界。 | flush/close/host ack、reader 能读回、最后 bytes 一样、同一个 protocol FactRef。 |

可用同一 ContractID 的多个 ObservationRequirements 分别指准确 protocol facts；每条有独立 ID/root/read/selector，不加线性 READY 等级。协议未解释时仍分开列原事实，不把人类描述字符串当解释器。
partial n 仅建立实际部分；FAILED/CANCELLED/RAISE 不删除此前前缀或 offset/buffer 状态；未知 footprint 保留 gap。
后来 overwrite 可能损害某 reader 的版本/区间，但不能擦去已经发生的外部输出历史/早先 Q 观察；“最后文件内容等同”也不满足要求中间日志输出或错误行为不变的 Q。
flush/sync 只可能建立其实际捕获版本/前缀的协议后置条件；后写不是自动包含在先前 flush/sync 中。新版本需重新核对，alias/mmap/图外写入未闭合不能声明 coherence。
这些是原合同所需关系，不是本轮运行了 persistence 协议或断电实验。

## 6. 最小实现/公开面建议（不预设新 wire）

- 新建**派生组合 query**，建议 `ExecutionIndex.resource_composition(budget=...)`；输入是已有 model 全体或一个明确 scope，**不接受 caller 自选 roots/contributions 来定义完整性**。所有 ObservationRequirements、无 root 的 requirement、多 root/多 ContentRead、未配对 source/canonical/resource/returned/raised obligations 均留在 ledger。若按 run 过滤，无法归属该 run 的要求/源保持 unresolved，不筛掉。
- 单次 `_content_context()`/ExternalSnapshots 解析；在一个共享预算内调用原 P/V/几何/order 内核。不要逐节点调用 public API 反复 replay/hash 或为每 read 重置预算；重放/校验/copy 成本另列。
- 返回原 references/原事实和**有类型的派生关系用途**：canonical value-route、logical-parent/provenance、physical materialization、writer association/actual、resource/handle/current-state、Q observation。logical-parent 边不能被当 current contribution 边。
- 最少返回 `requirements/roots/reads` ledger、`source_inventory/candidate_ids/pending_sources`、每 read 原 P/V结果、原 ports/state/effects/materializations、未配对 call/端点协议和 typed gaps、预算/截断、source/native/runtime/transform 独立状态。组合状态按已知矛盾/缺失/unsupported/截断分别报告；不能只有总 False。
- 对有原 Data/Reference/State 关系的端口机械回查；Reference 本身不能当内容，必须沿已声明 ContentRead/current state。未知副作用/外部观察即使无数据流 consumer 也保留。
- **本门先不改 schema**；仅当冻结验收要求确需 §4.1 的跨 Region 发生连接，或真实 endpoint schema 提供了现 FactRef 无法机器校验的结构，才讨论最小关系扩展并独立版本化。不要先造 endpoint 类大全、另一个 provenance registry、或把 load/save 方法名当规则。

## 7. 必需验收与真实微见证建议（全部 Proposed）

1. canonical 单 activation `read → decode/transform → CPU/GPU声明Mat → compute → encode → host write → flush/close → Q roots`，各 stage 都有原 Uses/StateAccess/实际出口；无伪 ticket。显式同时包含 normal 与部分 RAISE 声明路径。
2. 同逻辑 Version 的 CPU/GPU 两 Mat、两 allocation，copy/source/ready 条件分开；cast/normalize 新 Version 有 lineage，但这些祖先不变成最后 Mat 的 AND writers。相同裸 ID 跨 artifact 反例须 gap/issue，不合并。
3. required read/flush/persist 三要求仅供两 roots：第三要求仍在缺失分母；相同 EXTERNAL facet、相同 FactRef 或同 endpoint 不让它成功。最后 close 无 Q root 不能填补。
4. short write n<N + later overwrite + flush 失败/部分 state：保持 actual前缀、失败后态、既有外部输出历史和特定Q区间；删 work/write/actual 仍保留原 source candidates。
5. 两个调用同子 Region 的多 activation：若本门不增对应，准确报告 call-activation gap；若增对应，正例逐 actual/formal/normal/raise 端口吻合，交换 child activations/旧state/错误exit拒绝。不能仅用单 Region 正例宣布跨调用已通过。
6. 多 source/native stages 的 HB，只绑定内部 instance 不授 whole WorkEnd/Start；错误 event generation/consumer domain、allocation退休、handle复用和未知 alias 保留已有负例/条件。
7. 真实 stdlib CPU 微见证可复用现 R0 的 dup/open/replace、buffer→flush→fsync 及 V 的 short pipe write；若新增，独占临时文件，记录精确输入/实际 n/实际后态和异常。可小文件读→CPU变换→写→flush→os.fsync→readback，脚本断言与模型fixture映射分开归档。**readback/返回不能证明 power-loss durability**。
8. 可选真实 CPU tensor transform/clone 见证只证明所测API；GPU部分若没有实际 CUDA命令就标声明fixture，不能用CPU witness称已测H2D/跨stream coherence。无需安装工具/采集完整程序来验结构组合。

旧R0见证 `model_resource_execution_design/witnesses/run.log` 有六组PASS；其中buffered-write返回3、flush前底层0bytes、flush后3bytes、fsync返回，但显式 `power_loss_durability_tested=false`。V归档的真实pipe 131072请求/65536实际已被独立端口夹具接入，但原报告明确不是自动恢复。本轮仅阅读这些既有证据，不声称重跑。

## 8. 完整分母与完成声明

R3组合结构、端点协议解释、cross-call/native source matching、runtime capture/closure、自动全程序恢复、化简/速度是不同分母。
要求报告至少全体 Q requirements/roots、ContentReads、observed canonical operations/actual completions、资源/handle访问、work/outcomes、bound manifests/raw rows/source candidates，以及未归属/截断项；未知不是零。
本轮可交“限定组合表达/公开面”，不能据此关闭 typed selector/literal、完整 logical provenance、剩余家族/M2构造守恒，或宣称自动LeWM建图/优化与加速。

## 9. 阅读环境与指纹

未发现本 worktree 或 `/tmp`、`/` 的 AGENTS.md。未导入Torch，未执行新程序实验。
`v2/provenance.py` 不存在；实际读取 `scar/ir/v2/values.py` 和 `scar/ir/provenance.py`，没有假定两个实现同一套 authority。
Python：3.14.7 | packaged by conda-forge | (main, Sep  2 2026, 21:08:32) [GCC 15.3.0]

- `docs/M1_RESOURCE_EXECUTION_PLAN.md` SHA256 `5708b647e226335f02a6ac53b236063ae4b1dd9769e0d285a6e6730da40576a7`
- `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` SHA256 `74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729`
- `docs/M1_RESOURCE_READY_CONTRACT.md` SHA256 `b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f`
- `docs/M1_VALIDITY_API.md` SHA256 `26e6812924b8ef2628a0a0642d8af1d01ccf264aeaf5b03b866d813db909e445`
- `docs/M1_VALIDITY_ACCEPTANCE.md` SHA256 `f76512c9611f8e6561fb15e68a616ac8b54c18fb4320b86115bcfb0fc849a15d`
- `docs/model/RESOURCE_PROTOCOLS.md` SHA256 `5033fd3221d112dcebcbf087788440d7545effc88330dff589ed3ed4cdd482e4`
- `scar/ir/execution/model.py` SHA256 `5b7bcefb18bfaaf4b8548f2ebdd4c8346046913dcb5adac528929f85306d5a6d`
- `scar/ir/execution/coordinates.py` SHA256 `b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09`
- `scar/ir/execution/content.py` SHA256 `1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e`
- `scar/ir/execution/observations.py` SHA256 `8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882`
- `scar/ir/execution/production.py` SHA256 `cd829f5c62533f5ab38c2d8b44b9c1b251358b526c41061d83fb6a135c5fa098`
- `scar/ir/execution/source_validation.py` SHA256 `34f1f929dec9f55ae74913ff19ec23820e262433ed59340bf5b70c79fd91b1e2`
- `scar/ir/execution/production_query.py` SHA256 `3d3d2ab7798edbf9b284552587dc7b154fd676e8df39645a913d1c6864256eab`
- `scar/ir/execution/validity_query.py` SHA256 `de6313dc979859a7c92d79a67e36b49c6f29d6bb0ce4bc34a1bbfef52d6113b9`
- `scar/ir/execution/query.py` SHA256 `b2bb3bfd92f2dd1ee6d71cc9a8b0bdebad519cfa43065244b1d2e1621739deec`
- `scar/ir/execution/observation_validation.py` SHA256 `eaae52e54664107ac7baa7aa5707fbf2a19be6e9b59346f0ce37040f563ff983`
- `scar/ir/execution/content_validation.py` SHA256 `1f308c4e27ff02f751d1129eaeacfda23e0716974d248ab7934546da5e19a1ba`
- `scar/ir/execution/validity_validation.py` SHA256 `b347ece5df59c8a6aeeb0e7421a533f1decb1c21eacd6cbaf755c3254c6a161e`
- `scar/ir/execution/validity_order.py` SHA256 `8e0c0afcf8ada6cfddbc217c6de733868406921ed85f709f7979f70951b55ad4`
- `scar/ir/execution/production_ranges.py` SHA256 `b271aec4114679468269101f870f208fd933d06dc103eeed98b03b5ec0bbaabf`
- `scar/ir/execution/flow.py` SHA256 `2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501`
- `scar/ir/v2/values.py` SHA256 `2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259`
- `scar/ir/provenance.py` SHA256 `f8f11d353a05c9b2ec893ae5ab3da7be747b4a2ea3b28a21eb1f7891237523c1`
- `scar/ir/v2/contracts.py` SHA256 `c7aaae3ea0e292e425cfbe820d4508363b9e26e0c94427cefc5a4bb0ae6e15b1`
- `scar/ir/program/queries.py` SHA256 `584fc4b40c83d3618b42f84c71c06d750e264465195f62676bc542e29f0d3ad1`
- `artifacts/experiments/b1_call_operands/model_resource_execution_design/witnesses/run.log` SHA256 `6e5c17cd4080fbb58180f0c13936d36cee89a87122d9f4118f7c3252881c405f`
- `artifacts/experiments/b1_call_operands/model_resource_execution_design/research/sources.json` SHA256 `05ec52b26f9b8ee727e072e1c33ee5309e71c28b38f1c90153ceb1130dbf6c4e`


## 10. 应 root 要求补足：最小显式调用对应（实施前 Proposed）

现 core 已经约束以下形状（不是本报告新加规则）：

- 普通 direct CALL 是非terminator、有静态callee、无自带access；callee恰有一个NORMAL exit；call_arguments覆盖原所有Uses，顺序与callee entry formals吻合，results与唯一exit.types按位置匹配。`program/validation.py:576–622`。RAISE不属于这类CALL的出口，要表达抛出需INVOKE，不能把RAISE completion塞入普通CALL或默认为正常。
- INVOKE有独立NORMAL/RAISE signature和私有successors，invoke_arguments与callee.entry逐槽相配、callee.exit kinds/types与completions相配（同文件517–557）；结果不在operation.results，而沿实际ControlTransfer所选edge的CompletionResult.index流向landing formal。flow.py:210禁止common AFTER。
- EnvironmentCall只从上述canonical actual tuple派生env/cell/explicit Python parameter/state端口；不能把state参数当Python形参，也不能凭tuple前N假定物理entry布局（program/queries.py:885–916）。
- execution UseOccurrence不能直接引用别的activation的ValueOccurrence（execution/validation.py:331–341）；普通/恢复ControlTransfer也不能跨activation（flow.py:15–46）。因此不能把call-entry/return伪造成CFG transfer绕过原身份规则。

最小关联建议（root此后已选入R3.1计划，仍未当产品）：`CallActivation(id, caller:OperationOccurrenceID, activation:RegionActivationID, entry:BlockVisitID|Unresolved, completion:OperationOccurrenceID|Unresolved, source)`。entry显式选择准确初入visit，避免多个partial entry取首；completion只选准确child Return/Raise，不新增结果/参数/后态副本。

机械校验/派生顺序：

1. 查caller原Operation有显式callee，child.activation.region恰等于该callee；核caller与child的run/process，entry必须属于该activation的原callee.entry且是InitialEntry，无CFG前驱，不用loop/resume visit冒初入。同一个callee静态Region可以重复/递归，但一个具体child activation的调用父端不能被两个不相干caller抢占；同一ordinary caller occurrence不是无限多个“这次callee”。图外/native多次回调是别的原动作/协议，不借此关系复制一次call。
2. input只按原call_arguments或invoke_arguments逐槽找owned UseOccurrence；child input只按准确entry visit+formal ValueID找ValueOccurrence。Data/Reference/State/Binding/Protocol类型、env与formal分类仍用原core；新关联表示路由而非内容相等/同对象/alias/native真实性。缺actual/formal occurrence给准确gap，不接别次调用的同静态ValueID。
3. completion存在时必须属于同child activation，原term是RETURN或RAISE，term.exit准确选callee出口，原term.values按出口顺序回查child ownedUse/动态value。不能因找到任意后来的Return或“最后一条op”就补completion。
4. 普通CALL只接受child RETURN/NORMAL；第i个child exit Use路由到caller的第i个原OperationResult occurrence（未捕获则gap），包括state results，不能把child value直接冒充caller producer。
5. INVOKE按child exit.kind选caller completion signature，并核本次actual ControlTransfer的successor.kind一致。对该真实edge第j个landing formal：只有argument=CompletionResult(i)才由child exit第i个Use路由；argument=UseID的是原caller自身转发，不得错接child返回。索引允许同一CompletionResult被多个合规端口消费；按位置保留各端口，不用UseID去重吞槽。state在NORMAL/RAISE各自沿原结果走，不能选BEFORE/common AFTER或用正常后态替代失败partial。
6. completion=Unresolved表示完成来源未捕获/未确定，不等于“没有返回”“正在running”“已Failed”。entry未捕获与childcompletion未捕获分开显示；childcompletion存在但caller实际transfer未见，同样保留return/raise-to-caller缺口，不能制造successor。
7. 递归链以caller/activation/entry/exit发生ID区分；亲子关联不能成有限身份环，不能用source parent或静态callee的自递归造同一个activation自指。不得增加新的时间排序/native适用证明。

公开查询最小路线：单条关联返回原record/caller/childactivation/entry/completion、逐槽input routes、ordinary results或INVOKE实际completion routes、原state与缺口；按caller查关联列表，**不按source名字/内容denotation自动配对**。完整分母还要列有静态callee但无关联的caller及声明但缺entry/exit的关联。可在接口层detached返回；不把派生路由写入Graph/codec。

补读指纹：
- `scar/ir/program/validation.py` SHA256 `04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264`
- `scar/ir/program/model.py` SHA256 `3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1`
- `docs/M1_RESOURCE_COMPOSITION_PLAN.md` SHA256 `eb5d7761bacc9140e8c171adb82914574886e9006a4345f6db25fe59bb902093`


## 11. 调用声明与真实绑定的判定边界修正

依root独立复审收窄§7.5“交换child activations拒绝”的适用范围：只有交换造成**可机械判断的**不同静态callee、known run/process/thread、entry owner、actual completion kind/port或canonical定义冲突时才可拒。两个child若静态callee/scope/type均相同且没有native身份依据，恶意交换声明pair本身可能结构完全合法；不能把这种情况说成typed validator已能识别。query忠实显示声明pair所导出的路由，source_runtime_verified/runtime_identity_verified/value_identity_verified/transformation_authorized仍False；原ValueOccurrence/StateVersion和port路由不构成真实对象/内容或真实caller绑定证明。当前query测试不要求无依据的交换必拒。此为Proposal边界澄清，非新执行结果。


## 12. core CompletionResult 唯一性核对

补读 `program/validation.py:316–320` 后纠正§10第5点关于“同一CompletionResult多个合规端口”的提案：当前core明确要求各completion索引恰好一次，并且索引全集等于signature槽全集，因此重复索引不属于当前合法模型。R3.1应沿这个现合同逐真实位置映射，不增加重复索引能力。f(x,x)的独立**输入Use端口**仍合法，两个Use可以读相同actual Value；这与同一CompletionResult重复路由是两件事。该核对是静态读源码，未运行探针。
