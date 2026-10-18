# R3.3 P0：同一跨函数流水线的构造与连接审查

**Proposed；未实现、未运行。** 基线为干净 HEAD `bccefcfb65dcdba71c050cbbecadd3b2f30f3fa2`。本轮只读产品/文档/既有 fixtures；没有运行 Python、pytest、OS witness、LeWM 或 GPU，没有改产品/测试/旧 fixture。本文是唯一新增文件，不将 R3.2 的 5,011 项全仓结果当成本门验收。

## 1. 构造决定：一张规范程序、一次关联执行

建立一个 `ProgramGraph(root=pipeline.main)`，含同一调用树中的五个 helper Regions：`load`、`prepare`、`run`、`save`、`close`。root 顺序调用前四者，最后在同 root 的 C1 cleanup 路径调用 close；各 Region 可在原图递归展开。各 helper 是广义函数接口声明，不冒充已恢复的 Python frontend 源图。

一个 `ExecutionModel`、一个 Run/Process/HostThread；root 与每次 helper 调用分别有独立 RegionActivation/BlockVisit/OperationOccurrence。**不能拼接多个独立 factory 的 ExecutionModel，也不能把别的 factory 的 actor/票据当成当前流水线。** 每个实际同步调用由原 caller occurrence → child activation → child InitialEntry visit → child 实际 RETURN/RAISE 的 `CallActivation` 关联。原 `call_arguments/invoke_arguments`、entry formals、RETURN/RAISE Uses、caller result/CompletionResult 是唯一端口/producer 来源。

root 的 control path 草图：

```text
entry → invoke load → invoke prepare → invoke run → invoke save
       正常/失败后携当前states与Pending(Return/Raise) → C1 cleanup
cleanup → invoke close → Resume旧pending 或 Replace为close新Raise
        → 原CleanupRoute → PendingDispatch → Return/Raise出口
```

load 失败且从未取得 output handle 的路径与已经取得 handle 的路径要有真实 CFG 区分；不能在 cleanup 无条件凭空 close。首版可把 output handle 由 root 入口给定为 external bound reference，保证 cleanup 适用；另以 create/open 部分失败反例验证所有权缺口，不能声称外部实例是本次 CreatedAt。若本门要求真实 open 成功后 close 的单路径，应把 root acquire op 的 NORMAL/RAISE 与 acquired flag/ref 作为原 ports 建图，不增加 lifecycle 影子状态机。

## 2. 原状态与资源：显式传递，不跨 activation 偷绑

选择有限、可解释的 Location 域，例如 input file entity/content、input OFD、CPU memory/pool、device memory/pool、queue/event、output entity/content、output OFD/buffer、coarse world（model/RNG/未知 hooks/environment）。允许 coarse 域包含多个未细分效果，但省略域不等于 NONE。资源仅复用 ResourceKind/Role：FILE_ENTITY、OPEN_FILE_DESCRIPTION、MEMORY_POOL、QUEUE、EXECUTOR 或有来源的 OPAQUE_RESOURCE；不新增“视频/goal/LeWM”业务类型。

- root/child 需要的共享域作为各自准确 entry StateVersionValue 和出口 state ports 传递；caller state 输出是其自己的 operation/landing producer，child state 输出仍由 child producer 定义。CallActivation 只给出路由，不重写成相同动态 ValueOccurrence。
- `StateAccess.before/reference/after/mode/footprint` 指原 Uses/结果。content READ 与状态排序、OFD position 变更、buffer 写、RNG 变更分别保留；full overwrite 不能删除先前观察/异常/cleanup。
- 每个 Region/Operation-owned ResourceRequirement 都用自己的动态 owner。child 的输入 file/queue requirement 可绑定到同一个 ResourceInstance target，但**不直接借用 root owner 的 RequirementBinding**。ResourceRealization 在准确 activation 注册；不同 scope 的 SAME_RESOURCE 不靠静态 relation 跨 owner 推导。
- Reference 输入在 child 有自己的 ValueOccurrence；ObjectHandle/NativeHandle/ImplicitBinding/Unresolved 保留实际可得关联。相同 file 路径、descriptor 数字、裸 ObjectID/AllocationID 均不能代替 handle lifetime/目标实例。

## 3. 每个 stage 的原连接

下表是一个同源 fixture 的规格，不是已执行观测。每个可能失败的 stage 优先用 INVOKE，把 partial states 放入真实 NORMAL/RAISE CompletionSignature 和独占 landing；**没有 common AFTER**。

| Stage / Region | 原输入与 reads | 原输出、写后态、资源与完成 | D/P/V/Q 接法 |
| --- | --- | --- | --- |
| `load` | 源handle/reference、请求范围/offset Data、input-content state、OFD state、CPU/world state | raw bytes/reference + 实际 bytecount Data + CPU/OFD当前states；read可改变OFD offset，input内容不因此变成新值；RAISE可已有部分 buffer/offset变化 | HostConsumer/原AccessRef描述源读取，CPU目标物化由实际输出/建立结果描述；endpoint read协议未知仍UNKNOWN，不借BytePrefixWrite假冒file-read语义 |
| `prepare` | raw ref/不可变data、当前CPU content、device/queue/world state | decode/normalize 新结果；CPU→device enqueue产生新Mat physicalcopy与work ticket，host正常返回可仍pending | representation/normalization用原operator新结果；WorkSubmission.effects/read/write/Mat集合指本stage原Access/Value；copy同version仅显式声明，不从`.to`源码推物理copy |
| `run` | device ref、model refs/currentstate、候选/控制Data、queue/event/world states | wait/compute/consume、结果ref/数据与currentstates；随机/隐藏state写保留；native outcome与host Return/Raise分开 | ResourceConsumer原Use/Access + WholeWorkRead/NativeWorkRead；samequeue FIFO或exact EventRecord/QueueWait到consumer Start；actual contribution+Completed/Ordered分别支持，不以CPU return当GPU完成 |
| `save` | result ref/data、当前结果content、outputhandle/OFD/buffer/world states | encode/serialize新bytes结果；host/native write实际n≤requested，更新真实buffer/file/OFD状态；失败可已有prefix | encoded CPU Mat可给已支持storage geometry；endpoint用EndpointContent/ProtocolSelector+原target/currentSupport保守表示；写入actual prefix、requested范围、后续覆盖不混 |
| `close`（从cleanup调用） | outputhandle、最新buffer/file/OFD/world states、旧pending/context由C1独立携带 | flush/close各自原op；flush可partial失败，close失败后的handle状態按实际协议保留；cleanup正常Resume或新Raise Replace | 原EndedAt只在有实际依据时给；BorrowRelease≠handle end≠retirement；flush≠fsync/persist，Q protocol不支持则保留UNSUPPORTED，不能因close成功关闭义务 |

save 的 serialize→write→flush 可在一个 helper 内保持多条原 Operation，不把它们合成一个写标签。close 的异常不回退 save 的已写状态；cleanup handler/context 与 pending 控制payload都独立于当前资源 states。

## 4. ValueGraph 与 provenance：一条血缘，多个物化，独立当前贡献

使用一份 scoped ValueGraph（或必要时通过原 SourceEndpointBridge 显式连接多份 exact artifact）：

```text
file-content-version → raw-read-result-version → decoded/normalized-version
                                         ├─ CPU Mat
                                         └─ device Mat（声明的copy）
                           → computed-result-version → serialized-bytes-version
                           → output-file-after-version（含旧file与实际prefix依赖）
```

- read 的内容/请求范围可能只取文件一部分；file source、raw result 不因同路径就同 LogicalVersion。normalize/cast如改变数值是新 logical result；单纯 view/layout 可同版本/同allocation不同Region，仍必须显式声明该关系。
- CPU/device 同一个逻辑版本不等于同物化、ready 或可互换 residency；view 不新造 allocation。alloc identity 包含 exact VG artifact/lifetime，不凭地址复用。
- 原 VG `ValueVersion.parent_versions/ProvenanceRecord.inputs` 是逻辑前提；`Materialization.producer/ProvenanceRecord.producer` 为原 EEG OperationInstanceID，不能填 core OperationOccurrenceID。通过原 correspondence/WorkEvidenceBinding/SourceEndpointBridge 接实际 source，不改其身份。
- Reference ValueDenotation 只能 ObjectIdentity；其当前内容由原 StateAccess/current support/ContentRead placement 连接。不可把 ref denotation 直接填 DataIdentity 来省略状态。
- 每个原 SourceEdgeRef/RawRecordRef stage、WriteAssociation、OutcomeProduction/EstablishedProduction 对应具体同stage原effect/actual selector/Mat。上游 raw/load/prepare 祖先不会自动加入 compute结果 Mat 的全体 current writers AND。
- source inventory 必须独立保留全部固定 raw/normalized components；删 write/work/produced 不缩候选universe。结果里的实际短写不能因删Outcome改成未来whole请求。Endpoint 无受解释 selector→Mat 对应时不能借相同FactRef/几何越过 V 的 placement_match=None。

## 5. Q：最终结果和端点是不同义务

一个 exact SemanticGraph Contract 至少声明 required output slot（计算结果或返回动作）与 required external/state/order facet；run/root activation的 CompositionScope 作为 query请求，不是自动适用性证明。

1. OutputValue 指 root 原 result ValueOccurrence；通过 caller result→child return→原Uses回查完整调用链。root结果和child结果各自producer不合并。
2. 输出 endpoint 用 root自有 RequirementBinding（与save/close各自binding显式同target声明）、ProtocolInterval、anchor/support；不能用最后close的存在取代整份required contract。
3. 有实际内容读取义务才加原 ContentRead(ObservationConsumer(root),placement,effect/current state)，scalar/ref原输出不造read/Mat/ticket。
4. required facets 没有端点目标/基数，保持 FACET_TARGETS_UNINTERPRETED；输出slot仍SLOT_UNVERIFIED；Endpoint read/flush/persist协议可表达但当前未解析必须明确标UNSUPPORTED。缺根/缺read/缺支持不被success路径删掉。

## 6. 实质缺口与最小可实施修正：跨 activation 的 host 控制顺序

现 `_Context.point_precedes`（validation.py:212起）只在同一 activation 沿实际 CFG 比较；不同 activation 直接 None。CallActivation 输入/输出路由已存在，但尚未进入该顺序关系。单独展示调用树不足以让整个流水线的跨函数 wait/read/write/lifetime检查获得host控制前后关系。

root 提出的最小修正可复用原记录，**不新增表/producer/state**：

- `caller BEFORE → callee exact InitialEntry block首个规范Operation的实际occurrence BEFORE`。entry或该首个op缺捕获则gap；不选后来的某个已捕获op假装完整入口。
- `callee actual RETURN/RAISE AFTER → caller AFTER`（普通同步CALL仅NORMAL），或 `→ caller exact taken EDGE`（INVOKE的实际NORMAL/RAISE、CompletionResult与landing）。缺completion/transfer/对应则不补返程边，不默认NORMAL。
- 用原同activation CFG关系加这些边做联合、受预算的host因果查询/防环；避免递归调用point_precedes又重复重建同一图或无限展开递归静态callee。
- 保留准确activation/occurrence并通过原CallActivation确定端点。entry/currentstates不需要等同caller states才能确定控制端点；原states只负责各自当前版本，跨调用路由不证明内容相同。
- 只对已声明准确同步关联派生条件性host控制顺序；线程/owner/terminal冲突由既有callvalidator拒绝。两个结构相同的child互换仍可能无法判真，source/runtime identity保持False。
- **不产生** GPU WorkEnd、CPUCompleted、queue wait完成、错误传播、flush或persistence；host return且work仍pending完全合法。跨host/device因果仍经原 Work/Event/Queue/OrderAssociation，各协议条件保留。

这是真实连接缺口；其余stage可用现接口保守表达，无需为“load/save/flush”新增业务节点、native解释器或新wire。若欲把声明endpoint selector升级成物理文件内容/持久化证明，则需要具体源协议adapter与实际partial结果映射，目前不由上述HB修复完成。

## 7. 可复用构造与验收，不复制独立程序

优先复用 `execution_call_graphs._model/_activation`：它已经可为同一ProgramGraph的多个Region创建同run/process/thread、独立entry/formals/results/actual paths；复用其坐标构造代码，不反复修改program.root。`declared_path` 目前只单root，可用其生成规则但不能拿多个独立root模型直接拼接。

新增一个小 fixture builder集中构造六个Region的原values/Uses/Blocks/StateAccess/signatures，再一次 `snapshot_for(program)`；动态 helper只产生坐标/CallActivation，不自己决定期望校验结果。queue/resource/work/source/Q overlay都引用这个唯一program/model坐标。既有 work/visibility/produced factory仅可参考字段构造方法，不能把其ResourceInstance/WorkTicket/Rawstage直接移植后声称是一条流水线。

最小公共检查复用：`resource_composition`（全分母/原routes/reads/PV/lifecycle）、`call_entries/call_activation`、`definition_for_use/formal_route/state_at`、`canonical_effect/work/order_path/validity`、`write/outcome_production/observation_root`。所有查询继续原身份+条件+gap；不新增pipeline shadowgraph。

| 必需路径/反例 | 原模型/查询应证明或保留的结果 |
| --- | --- |
| NORMAL full声明路径 | root→各helper的动态calls、每层stateentry/return/callerresult逐port回查；原Q/资源/Mat/source完整清单，host跨call顺序可查询，不授native/transform |
| RAISE：load或run失败 | 准确child RAISE+caller实际RAISE edge/current partial states；不补NORMAL结果，不丢已经提交的work或已得资源 |
| PARTIAL：save actual4/request8，随后flush/close | original prefix只能覆盖[0,4)，tail义务未满足；COMPLETED/close不扩actual；fileendpoint协议未解释与storage prefix解析分开 |
| PENDING：host submit/RETURN或RAISE，设备无terminal | outcome/quiescence可缺，borrow release Unresolved；consumer Ordered支持须精确到consumer Start，hostHB不能代替device依赖 |
| CLEANUP normal/新raise | 原Pending Return/Raise跨lateststates进入C1；close正常Resume，close抛错Replace；不可恢复旧world或绕过cleanup，borrow/handle/retirement独立 |
| 错call/旧state/错误Mat scope | owner/process/thread、实际exit、当前state、exactartifact/allocation/Mat membership矛盾应Issue；仅缺join保留gap，不借同名/同值串线 |
| 删除req/root/read/source桥/write/work | 合同/原source分母和未绑定操作effects保留；不以候选变少得到空AND成功 |
| budget与未采集 | 截断完整inventory+pending/cursor；静态未走分支不当observed，缺entry/completion不当pending的已证状态 |

小OS见证可独立用临时文件/pipe验证实际read/write部分结果、buffer flush/close和异常部分状态；只封存明确字节范围/原返回值，不冒充IR/runtime自动配对或GPU见证。具体脚本与语言/OS事实由该见证门核实，本文未执行。声明的GPU stage也不等于已真实NVIDIA执行；需要真实GPU证据另列Observed，不能报模型测试的加速。

## 8. 关闭范围与读取源指纹

本报告完成P0构造/连接提案；等待root冻结具体实施分工。没有宣布完整静态Python源码覆盖、所有执行路径已观察、Endpoint协议闭合或M0–M2完成。

以下路径 execution/program/v2 相对 `scar/ir/`；全部SHA256为本次实际读源版本：

```text
3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1 program/model.py
167f0b2e1267278362341e6622e5cb164292e93484da94c8403b382e1e6e434f program/resources.py
88d2640c7cb23c454f95888ced4130784fd829e8d1d60292a17000278fbe4ef2 program/control.py
79b5888885bf8c4ad50df77e8f6dc7ffff4e5aa8956aca9010a98a055cbd372c program/cleanup.py
a287446babd077c072f51182d12ecc5e670bd2e1700b6396e914e134d95a183f execution/calls.py
79febd82eea06447ad045e8302a62a17164bb04771c9a2ef852b28640a127f4b execution/call_validation.py
1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e execution/content.py
cd829f5c62533f5ab38c2d8b44b9c1b251358b526c41061d83fb6a135c5fa098 execution/production.py
8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882 execution/observations.py
ed631511a56893d419edf76c8ddbf15862761c7e851227db772348471587aa6c execution/composition_query.py
4218b52b7f2d7f9b775011127dbca54015303ae17d062d465cc687f93a36e7ca execution/composition_routes.py
7f3c536a36ddcc905a0200c440c2e2d62660aba49fd1be3104bd9de7893da601 execution/composition_requirements.py
c092b7b39691fce22d8cc00d8922cce5df4800c6ece615d28492edbd3fc6bd70 execution/work.py
e4ce65c33bb8169e643eb5bebd8bf5f3620d8d2cc5c8d333b62b52e2e4aea43a execution/order.py
8e0c0afcf8ada6cfddbc217c6de733868406921ed85f709f7979f70951b55ad4 execution/validity_order.py
94dbd22027c328fa2a33b678f5a555f16c176f61c0d1f18bab80776a7260c930 execution/validation.py
2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259 v2/values.py
c7aaae3ea0e292e425cfbe820d4508363b9e26e0c94427cefc5a4bb0ae6e15b1 v2/contracts.py
6fa0d2eca706edc3a371d4d8d8581973b7e28b94ce5623e89048789e3fc8c90b tests/fixtures/execution_call_graphs.py
f9f0023e212adfb251b5f8e33fc79c868f3aac45d076df79b58eb5d51f3f832b tests/fixtures/execution_paths.py
478eb976dc8aef267bce1d5fbd50beacb6cdeef6797d7c6c417c0cc21895a5fe tests/fixtures/execution_visibility_graphs.py
751b40a5c3e5190c5bf08341dc7c68c4fafe76aed3cdae7fb50fba9546c79aa6 tests/fixtures/execution_produced_graphs.py
fef4e061a5af321f1173b34366df908495ed2505345994f19169e9baeaa419d9 tests/fixtures/execution_observation_graphs.py
1348d91478261f99dd350fdb05c163ac2e6dd900fb522be60b2cc1b1fef34c4f tests/fixtures/program_cleanup_graphs.py
07bf3e5ef2d2442e2e93ecfb30ba81c826027c03b1c9c5a8256abcb62f997ebe docs/M1_RESOURCE_COMPOSITION_PLAN.md
```
