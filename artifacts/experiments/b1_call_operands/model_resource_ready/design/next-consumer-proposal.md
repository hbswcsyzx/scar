# 下一步 R2.3-D：exact consumer、原 native port 与真正 Q root

**Proposed，未冻结 API/records；不计当前 G 验收。** 本轮仅只读源码及合同并写本 ignored Markdown。root 冻结 full 运行期间未编辑产品/tests/docs，未运行 Python、脚本、pytest、GPU、LeWM 或其他测试。以下名字是字段草案，不是已有产品接口。

## 1. 已有事实与必须保留的边界

P1 `NativeBoundary` 已以有序 native inputs/outputs 指向原 `EntryPortRef`/`ExitPortRef`，native 与 core-only 分区严格覆盖原区域入口/逻辑出口。native position 不等于 core 参数物理序号；raw role 和 TreeSpec 不被核心解释。
`ProgramIndex.native_input_values/native_output_uses` 从原图解析，没有另一份 signature/actual/producer。输出查询保留所有真实 Return/Raise UseSite；cleanup 发散时允许准确空结果，不制造输出 producer。

P1 只覆盖**区域 flat 边界**。它不保证 wrapper 内每个 kernel 的所有输入都是这些入口，也不把 native mutation output 解释为 StateVersion。`BoundaryRelation` 是部分/多对多声明，八域义务没有自动 discharge。
R1 的 RegionActivation 没有自动证明“这个 caller occurrence 调用了这个 body activation”；同 Region、静态 callee、名字或 host operation 相等均不足以完成动态 pairing。

因此 D 应复用 P1 的原槽引用，明确动态 instantiation 和输入对应；不能为了某个内部 kernel 再造 NativeBoundary、入口 formal、输出值或 signature。

## 2. 最小 consumer 分支与字段草案

所有 subject 都是准确原 `UseRef | AccessRef`，或真正 Q root 的 typed ID。读取 Reference 可能只是传递 wrapper，必须另有 read/denotation basis；不是遇到 Reference Use 就默认读内容。

| Proposed 关系 | 必要字段/信息 | 派生与限制 |
| --- | --- | --- |
| **HostRead** | 原 subject；原 read effect 或明确未知；准确 `HostReadPoint/Interval`；current support 的原 OccurrencePoint anchor；denotation 引用；source | 同一原操作的 BEFORE..AFTER 只能在该封闭读取规则成立时界定区间；跨点读取保留准确端点/协议依据。没有 work 时不 mint ticket。 |
| **ResourceRead** | 原 subject；exact WorkTicketID；本 ticket 原 read effect 引用；native input binding；`WorkReadInterval`；denotation 引用；source | work 存在才使用。read effect 回查原 WorkSubmission.effects，不重复 mode/location/footprint；未知 INVOKE boundary 不冒称 READ 或 byte footprint。 |
| **EndpointObservation** | exact Q requirement 引用；准确 ResourceTarget；content/selector binding；真实观察 point/interval；current selection/state anchor 或明确未对应；source | 不伪造 core op 或 work。Q 需求与本次动态观察分开，见 §4。 |
| **ContentDenotation** | 原 subject/实际 ValueOccurrence；scoped MaterializationRef；原 selector/EndpointPlacement；current support/basis/source | version、region/allocation 从原 ValueGraph 派生。D 只校验对应的准确声明，不能凭这一行宣布内容/runtime 已证明。 |

`HostReadPoint/Interval` 使用原 OccurrencePoint，或有准确 EvidencePoint scope 的协议区间；EvidencePoint 没有 core current-state 时必须保留锚点对应缺口，不能写入一份新 state。
`WorkReadInterval` 默认保守 `WorkStart(ticket)..WorkEnd(ticket)`；如有更精确 last-read，用原 native/provider access 事实及其与本 ticket 的对应收窄。start/end 属同一次工作，不能借另 ticket 或旧代发生。
`EndpointObservationInterval` 使用真实 endpoint/观察协议点，不强制不实际存在的 WorkStart。三种分支共享内容绑定，不强行共用一种时间坐标。

## 3. native 输入/输出只引用原槽，动态 actual 沿原图取

### 3.1 原 P1 槽

最小引用为 `NativeInputRef(boundary: NativeBoundaryID, position: exact int)` 与 `NativeOutputRef(boundary, position)`；本 ProgramSnapshot 已提供原 graph 身份，不再复制原 port、raw role、类型或 signature。
从 `boundary.inputs[position].port` 派生原 EntryPortRef；输出同理。位置越界、方向错误、引用 core-only 端口为 native 槽是结构 issue；raw role 字符串不提供读写语义。

动态 instantiation 至少连接：该 boundary 的准确 RegionActivation/entry visit，以及实际 caller occurrence 或带原因的未对应。若原 CALL/INVOKE callee 已知，callee Region 必须匹配 boundary.region；actual→formal **从原 call_arguments/invoke_arguments 及 entry 参数派生**，不新增 actuals tuple。
实际入口 ValueOccurrence 必须属于该 activation 的真实 entry visit。caller→activation 来源未闭合时保留 pairing gap，不能靠同 run、最近 activation 或 provider owner 猜选。

将某输入槽接到 ResourceRead 时，保留 source native operator/input 槽与 exact ticket 的对应依据。直接原端口复制规则可沿本次真实 CFG 的 Use→formal route 检查；有 transform/alias 的关系必须显式保留其源依据和待证内容，不偷作直接 copy。
`f(x,x)` 的两个 native position、原 UseID 和实际输入槽保持独立，即使 ValueOccurrence 相同也不合并。

输出引用解析为该 activation 的实际 Return/Raise UseOccurrence，且符合原 logical ExitPort 槽和真实 completion。没有实际站点或 transfer 就没有具体输出发生；只保留 source/output-unobserved gap，不选一个静态 producer。
INVOKE 的上层状态/返回仍沿实际 successor/CompletionResult→formal，不能把 callee 原输出记录额外注入 caller SSA。

### 3.2 wrapper 内部 native 输入不在 P1 flat boundary 时

保留 **原 provider operand reference**：精确 provider/EEG artifact、原 native operation occurrence/fact、INPUT/OUTPUT 方向、原槽序号及依据；它是外部 FK，不是新 native signature/producer 图。
适配器须回查原 artifact 的该 operand 与本 ticket 的实际 submission/native-op 对应；如目前只拿到 FactReference locator 而未能核对原操作/槽，表示为有范围和原事实的 unresolved binding。不得伪造 P1 placeholder 或将 boundary position 0 当所有内部 kernel 的 input 0。
这条分支使接口可保守表达现有 opaque 边界；完成其真实解析与对应仍是 D/adapter 后续验收，不授 `PROVEN`。

## 4. Q：旧 ContractDefinition 不能自动提供 endpoint root

旧 SemanticGraph 的 `contracts[ContractID]` 只含 required_outputs、facets、assumptions、evidence，无法机械确认“必须观察这个文件的这些字节且持久化”。应分开一个**显式 Q 要求定义**和一次**动态观察**：

1. **ContractRef**：准确 SemanticGraph artifact（hash/schema/size）＋现存 ContractID。
2. **Output requirement**：引用原 ValueSlotID，必须在该 ContractDefinition.required_outputs 中，且 slot 在同一 SemanticGraph 中。不能由 name/direction 字符串猜 slot。
3. **Endpoint requirement**：新增明确的、版本化 Q 扩展要求行，引用 ContractRef 和 typed requirement ID，保存原 Q endpoint/selector 要求及精确观察协议条件；必须是 contract 的显式扩展声明，不能由 EXTERNAL facet 或任意 assumptions 字符串推导。
4. **ObservationRoot**：引用该准确 output/endpoint requirement，另绑定本次 ResourceTarget、content/selector、point/interval、current support 和 source。不在根中重新自由填写一份不同的合同条件。

最小 Q 扩展可是一份受版本控制的 typed requirement 表/工件，不需要新数据流图。该工件登记精确 ContractRef 和 requirement 行；endpoint subject/selector/protocol 指其原 typed 定义或明确原事实引用。
验证需解析/核对工件中的准确行及其与旧 ContractRef 的关联；裸 `ProviderFactReference` 的存在不自动证明它声明了这个 endpoint requirement。工件尚未提供或 Q admissibility 未核对时保留具体 gap，不将旧合同偷偷解释成更强合同。
静态要求描述 endpoint 的选择/协议，动态 Root 才接本次 R1 ResourceTarget；避免静态 Q 工件引用 execution bundle 再被 execution 反向引用形成 hash 循环。

若 Q 的完整观察要求 inventory 还未闭合，删除一行 endpoint requirement 不能被当作“所有观察要求已满足”；原 required_outputs 必须逐项保留，扩展要求与其原工件 manifest 对账。COMPLETE 标签不能替代该来源。
路径/文件名可作 selector 数据，资源身份仍经当前 pathname/endpoint selection 状态与 R1 target 对应；同字符串不推出同 file entity/内容。

## 5. 有限机械验证规则

1. 重用原 ProgramSnapshot，校验准确 execution occurrence/Use/Access/Value FK；原 native/semantic/value/EEG artifact 分别校验 schema/hash/size 和 typed FK，不读 URI，不按裸 ID 拼接。
2. Host subject 的 Use 属该 occurrence 原 operation；AccessRef 索引原 access。已知 WRITE-only access 不能冒充 read；coarse/INVOKE 读范围未知保留条件，不补 byte footprint。Reference Use 到 access 的 relation 未建立时不能宣称实际消费内容。
3. ResourceRead.ticket 存在，effect 是它的原关联；native slot 源及动态 boundary activation/call 归属一致。两个 work 同 WithinOperation 不证明同一个 consumer；同 host occurrence 的原输入也不证明所有 work 都读取它。
4. 每个 core support 引原 StateVersion 的准确 ValueOccurrence，在其**声明的 core anchor** 检查本次 current location/version/activation；不能把 host anchor 偷当 device WorkStart 的 current state。
5. 读取/观察 point 与目标资源已知 realm/run/process 相符；跨 activation/native point 的相对顺序、call pairing 或共享资源桥缺失时给精确 gap。logical 内容可有多个实现，物理 allocation/endpoint 的同一性另验。
6. Storage selector 使用原 scoped RegionRef，Footprint 单位需准确映射；endpoint selector/placement 必须明确。缺 region/selector 不默认 whole、不造 allocation。
7. Q requirement/Root 类型、旧 ContractRef、原 required slot/扩展行、实际 endpoint 角色/selector/protocol 条件必须一致。Host/Endpoint 无 work 正例不触发缺 ticket 错误。
8. D 不把 source presence 或字段一致性升级为完整 denotation。稳定读取、alias invalidators、实际 produced universe、AND/OR 和 visibility 由 P/V 接本关系继续核验；retention 不保证内容未变。

## 6. 必须准备的正反例（设计，未执行）

| 合法声明路径 | 错误/未闭合对应 |
| --- | --- |
| 原 Host READ AccessRef＋本次 current state＋准确操作/协议区间，无 ticket | 为它伪造 work，或把传递 Reference 的 Use 默认当内容读取；读取方式不明应 gap |
| Direct/queued 资源 consumer 对应某 exact native input，原 P1 position 可与 core index 不同 | native position 按 core index 猜、把 output/core-only port 当 native input、直接 copy 规则接错入口 route |
| 两个 work 由同一个 opaque host op 提交，分别引用其实际原 native operand | 仅 operation 相等就把 work A 的读取端口归给 B；证据未区分应 unresolved |
| 同一个输入值出现两次，两个原槽/Use 独立保留 | 因同 ValueOccurrence 合并输入槽或把两次消费改成一次 |
| 真正 EndpointObservation 引准确 typed Q 扩展要求与本次 endpoint，无 work/core op | 只有 EXTERNAL facet、路径字符串、最后一条 close 就创建 persistence root，或伪造 Return/WorkStart |
| 原 native output 在本 activation 的实际 NORMAL/RAISE Use 上解析 | 从另 activation/未走分支/cleanup 发散的逻辑出口造输出；原 index 相同不能借旧发生 |
| current support 对应 enqueue core 点，另有实际资源读取区间 | 仅 enqueue 当时状态正确就声称读至结束都稳定；retention 存在不能补并发覆写缺口 |

## 7. 实际读取的源码 SHA256

这里只读相关文件/章节，不计为测试或完整产品复审。

| 文件 | SHA256 |
| --- | --- |
| `docs/M1_NATIVE_INTERFACES.md` | `2e90ce87f80f024916f9a5ab67cbae5aee8bde5fcb7eb39fef501b6b293892a2` |
| `docs/M1_RESOURCE_READY_CONTRACT.md` | `b222e95fc46773f2b681fc2f44f8f9461fdaa094b567b1401635c79046a6866f` |
| `scar/ir/program/native.py` | `17543d01b8351d74eefc665d48c74383bca27d820507fff98646dc3cef2a22b0` |
| `scar/ir/program/native_validation.py` | `7fb36d01c70dc36889cf6dea65aa23763c0dd5139afc1bccdee65324e5e2743b` |
| `scar/ir/program/queries.py` | `584fc4b40c83d3618b42f84c71c06d750e264465195f62676bc542e29f0d3ad1` |
| `scar/ir/execution/query.py` | `1dd206368dba9a2ef9d3e3ed5bc15fce266ef3dd139d58874ab681c69dae892d` |
| `scar/ir/execution/validation.py` | `6c167f7a3594bcc2e6c8872520e1b14f7c453d7f3439026028a36343e6b48f2d` |
| `scar/ir/v2/contracts.py` | `c7aaae3ea0e292e425cfbe820d4508363b9e26e0c94427cefc5a4bb0ae6e15b1` |
| `scar/ir/v2/semantic.py` | `9d0af8a2b4a868df00388ccb910cdabdc93066aad7ff0e593d1c8d0e969885ab` |

下一步只应收敛 D exact records/来源职责及上述有界反例；本报告不增加实现、不授 native/runtime/ready 权限、不关闭 P/V/R3 或第一阶段，也不改变用户“第一阶段完成先停下来说明模型”的要求。
