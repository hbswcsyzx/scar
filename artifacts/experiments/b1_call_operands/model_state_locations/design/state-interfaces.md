# M1 状态 owner / selector：独立设计源审

状态：**Proposed，建议采用单规范状态域 + 原访问地址精化；本报告不关闭实现门。**
基线由 root 指定为 clean `78dbac3`；阅读时间 2026-10-18。只读下列源码/既有调研，未运行 Python、pytest、
full、目标程序、LeWM 或 GPU；未改产品、测试或 docs。反例均为源码推断/待实施验收，不冒称运行复现。

## 1. Observed：已有连接与真实缺口

| 原规范实体 | 实际持有的关系 | 不能据此推出 |
| --- | --- | --- |
| `StateLocation` (`model.py:138–150`) | id、显示 label、可选整数 extent、INTERNAL/EXTERNAL/UNKNOWN stability。 | 没有 owner、坐标单位、实例范围、父域或 alias/覆盖关系；label 不是地址解释器。 |
| `Footprint` (`model.py:107–128`) | WHOLE / 半开非负 INTERVAL / UNKNOWN。 | 没有 byte/element/key/field 单位；INTERVAL(0,4) 不能直接解释成4 bytes。 |
| `ReferenceValue` (`model.py:208–233`) | 可选字符串 referent_identity、可能 targets(LocationID tuple)、Footprint selector。 | 静态 ValueID、不同字符串或不同 targets 不自动是动态对象不相交证明。 |
| `StateAccess` (`model.py:370–400`) | 原 location、before Use、mode、after result、footprint、full_overwrite、可选 reference Use。 | reference 可以指本次 owner，但没有 key/index/slice 路径，也没有多域一致性机制。 |
| 环境 (`environments.py:39–55`) | 当前入口 reference 与必要 locations；captured cell 的本 body slot/position。 | cell_slot 不是 cell 动态身份；locations 不是完整 read/alias 集合。 |
| 资源 (`resources.py:152–179`) | 原 ResourceUse(requirement/definition/可选 handle Use)；ResourceLocation(location,definition)。 | definition 可有多实例；implicit resource 无须伪造 handle，静态 location 不等于该次实例。 |
| native (`native_validation.py:63–81`) | 原 entry/exit 分区及准确端口对应。 | raw role/signature/FactRef 不解释 lifted state 的 owner、元素地址或实际写回。 |
| execution (`effects.py:58–88,118–188`) | AccessRef→原 StateAccess + 本次 before/after/reference UseOccurrence；INVOKE→实际 completion/result/formal。 | INVOKE boundary 没有 mode/footprint，不能自造字节写或选 NORMAL。 |

`validation.py:425–437,454–495` 在每个 block 内以 `dict[LocationID,ValueID]` 检查 current，
每个 operation/Location 只准一个 access summary。READ 保持版本，WRITE/RW 产生同域后态。
`reference_binding:442–452` 检查已声明 targets/selector/identity 的相容性；`access:497–515`
核原 owned reference、target/footprint/complete alias。它们不会核字段名、key 的语义或跨 Location 的别名。
`stale_state` 拒同 Location 的旧值，不会自动连接另一个 Location 的新值。

`EnvironmentMember` 与 `FunctionEntryLayout` 已从原 call/invoke 实参派生，
`environment_validation.py:69–84` 校验入口引用与必要 state domains；不得再存另一份环境 actual。
普通 fast local 已有 LocalBinding SSA (`binding_validation.py:202–217` 等)，不应重新改成 namespace key state。
`structured_lowering.py:113–116,514–516` 现采用 coarse Python/external world 和保守 RW，未自动精化字段/元素。

execution 的 current/support (`execution/validation.py:161–205`) 已区分实际 activation/visit incarnation，
ContentDenotation (`content_validation.py:404–427`) 把 Reference 接 ObjectIdentity、Data 接 Version；
StorageContent 已用 scoped MatRef/RegionRef (`content.py:280–301`)。这些足以作为新地址的动态解析入口，
无需新增 object/producer/state 图。V 独立扫描每个原 WRITE/RW 与 opaque (`validity_stability.py:260–310`)，
新 selector 不得让删除可选 ContentRead/WriteAssociation 就删掉未知写威胁。

## 2. Inferred：必须先解决域一致性，而非只补 descriptor

建议 **方案①**：Location 是规范 SSA 同步域，owner+selector 是该域内一次原访问的地址精化。
相互可能 alias 的 field/cell/element/storage/world 访问共用一个 carrier LocationID；细地址不另生成状态链。

两向最小反例（未执行）：

1. `field.read(S_field0)`；`opaque/world.write(S_world0)->S_world1`；再读 field。
   若 field/world 各独立链，S_field0 仍通过“当前”检查，却没有依赖可能改了 field 的写。
2. `field.write(S_field0)->S_field1`；`world.read(S_world0)`。
   coarse 读取没有经过细写，可能看到被模型错误保留的旧 namespace/对象状态。

采用①后，两次读写均消费同一 carrier 的 current Use，写产生 S1；下一访问只能读 S1。
`fine` 是地址路径，不是第二个 StateVersion。按 selector 证明某次写不影响某次读，只能是以后独立的
有条件分析/重写合同；本门不切断已有 SSA 依赖，不给该证明默认权限。

方案②（重叠多个 Location 同时 SSA）需要：每个写同步更新所有可能覆盖域，所有 CALL/INVOKE 完成、
branch/loop phi、resumption current ingress 都保持同步；未知 alias/外部写还须使所有可能细域失效。
仅存 covers/overlaps 边而不更新版本不够。加入 coarse epoch 再校验细缓存也实质回到共享 carrier，
另有缓存有效性协议。此阶段不推荐这套复杂机制。

**新能力的不变量：** 引入 owner/selector 时，不据描述再拆 Location；同一 may-alias universe 仅一个
规范 carrier。多 carrier 只用于已有、明确隔离的状态域；不同 LocationID/Region/resource definition
本身不证明隔离。无法说明隔离时使用共同 coarse carrier。若以后声明“coarse 覆盖 fine”且两者同时
是独立 state ports，严格新 profile 应拒绝这种未同步形状，不能把关系记录本身视为同步。
旧多域图继续表达旧声明，读取时不自动获得新 partition/alias 证明；不能通过新 wire 默认值提升其精度。

## 3. Proposed：收敛后的推荐 record shape（待 root 冻结实施合同）

只新增附着原 access / invoke state operand 的只读精化。原 aggregate StateAccess 及 state SSA 不变；
不复制 location、before、after。一个 atomic op 可在同一域内读多个 owner/selector 再写 out，必须可直接表达。

```text
StateAddressRefinement(site: StateEffectSite, effects: nonempty tuple[AddressEffect], coverage)
StateEffectSite = ExistingAccess(operation: OperationID, index: int)
                | InvokeStateOperand(operation: OperationID, state_use: UseID)
AddressEffect(owner: AddressOwner, selector: typed path, mode: AccessMode, stage: int | None)
AddressOwner = ReferenceOwner(use: UseID) | ResourceOwner(requirement: ResourceRequirementID) | DomainOwner
coverage = PARTIAL | DECLARED_COMPLETE
ResourceOwner := 同 op 原 ResourceUse(requirement)，handle/definition 从原记录派生
path = nonempty typed tuple[SelectionStep]；whole owner 用 WholeOwner
SelectionStep = NamespaceKey(operand) | ObjectField(name)
              | CellContent | Element(index_operand) | Slice(start,stop,step)
              | StorageRange(unit, start_operand, count_operand) | UnknownSelection(reason, operands)
operand = StaticName(exact str) | StaticIndex(exact int, 非bool) | ExistingUse(UseID)
slice bound = OmittedBound | operand       # 不把“省略”与实际 None Use 混合
unit = ELEMENT | BYTE | ABSTRACT          # 只说明坐标，不宣称已有 dtype/byte映射
```

- ExistingAccess 必须选择真实原 summary；同一 `(op, derived LocationID)` 仅一份精化。
  aggregate READ 只容 READ 项，WRITE 只容 WRITE 项，RW 可含 READ/WRITE/RW。DECLARED_COMPLETE 时
  项的 mode 并集须等 aggregate mode；PARTIAL 则保留其未描述 residual，不把未列地址当 NONE。
  完整性是声明闭包，不自动授原 operation.effects_complete 或源码完整性；metadata 无法自证真实效果集合。
- stage 为非负 exact int（非bool）或 None。较小数仅声明该 op 内较早效果阶段，同号不添加顺序；
  None 保留未描述阶段。复用 MLIR 式效果阶段概念，不造新 op、时间或第二层 producer/CFG。
  stage 不证明 native 步骤/原子性，不能把 wrapper 异常改成某阶段没执行。
- ReferenceOwner 直接引用本 op 原 owned REFERENCE Use，不另放 ValueID。原 access.reference=None
  时可有多个原 Reference Uses：例如 srcA READ、srcB READ、out WRITE 共用唯一 aggregate before/after。
  原 access.reference 非None时，refinement 不能越该引用/selection：初版至少要求 owner 实际为同一
  canonical ReferenceValue（允许不同 owned UseID）且 selector 可被原 selector/envelope覆盖；已知矛盾拒绝。
  不能仅凭不同引用的同 referent_identity 字符串放宽此守卫。未知包含关系不能宣称精确/完整覆盖。
  DomainOwner/implicit resource 不强塞 Reference Use。资源 requirement 必须为本 op 已有 ResourceUse，
  owner scope/known definition/resource-location 矛盾须拒绝；实例仍由 execution RequirementBinding 解析。
- InvokeStateOperand 是必需 site，不是普通 StateAccess 的替身。state_use 必须为本 INVOKE 原
  invoke_arguments 中的 StateVersion Use，carrier Location/current 与既有 STATE_CONTENT/STATE_ORDER
  角色由原端口派生；精化不改变角色，也不凭地址声明把 CONTENT 降为 ORDER。
  地址项是该输入域的潜在保守读写精化；没有普通 access 的 mode/footprint可借，不从新增记录推纯性。
  NORMAL/RAISE 各自后态严格沿原 CompletionSuccessor 的 CompletionResult 或 forward Use 派生，
  不能在 row 复制 after、默选 NORMAL、把 fresh completion state等同实际写，或把部分写RAISE回退输入态。
  PARTIAL 保留未知 residual；DECLARED_COMPLETE 是明确潜在效果集合声明，仍不证明native/source适用。
- `ObjectField("x")` 是声明地址，不是“obj.x 已证明直接无回调读槽”。原属性/item/hash/descriptor/resize/
  index conversion 的真实计算和读写必须仍是普通 op/INVOKE、原 Uses、NORMAL/RAISE 和各自后态。
  未解析协议保留 Unknown/DomainWide 地址，不凭 field/key 文本标 effects_complete 或纯性。
- 动态 operand 只能指同原 op owned Use，沿原类型/availability/current-state 校验；不重新求 key/step，
  不另列 input values。Python Reference index/key 不自动等于 unboxed Data(int)；转换须原端口/协议。
- paths 仅表达真实地址路径。`obj.attr` 读出新 owner 后再 `[i]`，若实际有 lookup/callback，必须经该 lookup
  的原结果和下一 op Use；不能用一条路径跳过必要数据/state/异常依赖。
- 旧 Footprint 保持 carrier-relative 保守 envelope。world 的字段访问可继续 WHOLE/UNKNOWN；
  新 selector 不能把旧无单位 INTERVAL 直接当 byte/element。只有相同已声明 coordinate system 才核数值包含。
  **部分 owner/field/element 写不得设置 full_overwrite coarse world**；STATE_ORDER 仅在整个 carrier
  被真实完整覆盖的旧条件下适用，不能以覆盖一个 selector 的局部写绕开旧 STATE_CONTENT。
- storage 静态路径只指原引用/坐标。实际 offset/shape/stride/dtype/allocation/Mat 复用 v2 StorageRegion，
  经原 AccessRef/ContentPlacement 精确关联；不向 program 塞裸 StorageRegionID，不复制几何算法。
  v2 region offset/stride 是 dtype elements (`v2/values.py:120–130`)，byte关系需 dtype/layout 的有界解释。
- `protocol?` 如需只是 scoped ProviderFactReference 来源，不设 validated/proven 位；缺适用解释仍保守。
  没有地址描述保持原粗摘要，不表示没有访问；删除描述不能减少旧 carrier/opaque 义务。

## 4. Proposed：验证与派生查询

1. 构造：exact frozen/slots 嵌套 variant、非空并集、精确ID namespace、bool/int区分、下标/坐标有界语法。
2. graph：唯一原 site/derived域，选择真实原 access 或准确 invoke state operand；原 current/结果/位置/behaviors 不变。
   每个 ExistingUse 属该 op，owner 必须原 reference；资源路径解析原 ResourceUse；跨 Region 只经原调用端口。
3. 环境：入口 member.reference/locations 只是角色/必要域；本次 owner 来自 lookup op 的原 Use。
   captured cell 保留 cell identity 引用，读内容消费 current carrier；cell_slot 不当动态 owner。
4. CFG：只用 canonical actual→formal（含 SavedInput resolver）保持 owner/key 与 current carrier 同时转发。
   INVOKE 不允许新增伪 StateAccess，使用 InvokeStateOperand 及原实际 completion boundary；
   child 内另有 access 时仍引用该原 access，不能在 caller 再造同一个 producer。未声明范围继续 Unknown。
5. 查询 `state_address(site)` 返回原 access/invoke operand、各 owner/selector Uses，不制造 Use；
   `execution_address(AccessRef | InvokeBoundaryStateEffect)` 从现 resolve_canonical_effect 取原
   UseOccurrences/current state/activation/准确实际后态，再逐原项解析。
   `address_relation(a,b,budget)` 返回 SAME / DISJOINT / MAY_OVERLAP +原依据/未证条件；未知或截断不为 DISJOINT。
   同一点相同 Reference Value 可为相同 carrier；跨 loop visit/activation 的同静态 ValueID不能当运行实例相同。
   不同 references/Referent字符串/namespace标签默认 MAY_OVERLAP；路径合流不能将 owner集合与selector集合交叉配对。
6. 初版只机械核同地址与矛盾；精确 disjoint 需要已解析同 owner/同坐标与受支持的选择语义。
   字符串不同只有在准确 builtin-entry 坐标/profile 下才是不同 entry；`1/True` 不按literal tag强说不同key。
   不实现通用 Python alias/points-to 分析，不解释任意 FactRef；此范围可表达保守关系并保持组合正确。
7. execution/P/V 继续以原 effect+scoped Mat/actual production做几何和全区间威胁。新描述不能替代 actual
   allocation generation、外部 alias/source invalidators、target lifetime 或 native whole-read interval。
   缺 denotation/selector解释保留具体 gap；来源解析、快照额外成本与共享派生budget分别列账。

## 5. 有限验收分母（Proposed，尚未实现或执行）

| 必须组合的正例 | 必须拒绝或保留的反例 |
| --- | --- |
| world carrier 的 namespace key→field→cell→元素读写，全沿原current版本 | 上述粗写→细旧读、细写→粗旧读；两条独立链宣称覆盖却无同步 |
| 原 env entry/两个调用共享 cell、alias actual、原 Use 位置不去重 | 仅同cell_slot/名称推同identity；不同ref/Region推disjoint；错entry owner |
| atomic op对srcA/srcB READ、out WRITE+stage，共用原单aggregate；rootreference=None合法 | 越界access index、额外/外部Use、错role；有rootreference却越owner/selection；mode越aggregate；把PARTIAL当完整 |
| INVOKE原state operand，NORMAL/RAISE不同端口顺序/actual completion后态 | 漏全部无StateAccess的invoke；错state Use/location；NORMAL结果作RAISEpost；partialfailure回退输入；freshpost冒实际写 |
| dynamic key/index/slice的Use与求值副作用、NORMAL/RAISE currentpost | helper/custom lookup写后RAISE被伪装成无效应fieldread；局部写full_overwrite world |
| branch owner/key同时实际→formal，loop/ref重新定义和saved恢复 | 合流反选交叉owner/key；上次visit同静态Value冒当前instance；旧saved sharedstate |
| v2 uint8 bytes及非uint8/strided元素坐标，准确Mat/原effect | INTERVAL无单位当bytes；错误artifact/Mat/allocation代次；unknown layout当disjoint |
| ResourceLocation + 原 ResourceUse；implicit owner无fake handle | 静态definition当唯一instance；重复open/dup handle/OFD/文件路径关系混为一种身份 |
| coarse opaque和外部来源保留，selector删除不缩独立威胁集合 | 省略地址/对应即宣称NONE；内部stability字段抹去外部别名写 |

再加严格 records/wire/公开query/旧能力自动schema保持，以及一次最终冻结组件/full的既有门流程。
测试通过数只衡量此声明接口的正反组合，不等于source自动恢复或M0–M2建模覆盖率。
本门不应同时要求完整literal、完整Python前端或native parser；但不能省掉共享carrier一致性后宣称owner/selector完成。

## 6. 成熟接口核对与复用边界

已读本机既有 TOOLING_SURVEY §6、MODELING_REUSE_DECISION；本轮对 lewm site-packages 的有界文件检索
未发现 xDSL Python源码安装，不能据此声称所有环境均不可用，也未运行迁移/性能试验。
必要的主源核对（2026-10-18）：[MLIR effects](https://mlir.llvm.org/docs/Rationale/SideEffectsAndSpeculation/)
现明确 resource 层级/粗粒度效果与精细地址/offset alias 分析的边界；
[xDSL traits.py](https://github.com/xdslproject/xdsl/blob/main/xdsl/traits.py) 有 EffectInstance(kind,value,resource)
与 None=未知效果。可复用这种“效果引用现SSA值+资源、未知不等于空”的结构原则。
两者不是已替本项目实现 owner/current state/partial completion/source correspondence；
也不能因为框架不恢复Python就拒绝借用其成熟SSA/验证接口。现阶段不迁移wire，不再造通用CFG/alias求解器。

## 7. 阅读范围与 SHA256

下列是实际选读文件（段落范围在上文），非宣称每行审计；没有运行测试或创建探针。

```text
3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1 program/model.py
04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264 program/validation.py
14e9c16d89db388793236a3636adaac0557c410a5c633c65f7558d413db029f8 program/environments.py
edfefa6a74b80fbbe425de3dce2a0d4750ab971c42f372072f7252c6d19da834 program/environment_validation.py
167f0b2e1267278362341e6622e5cb164292e93484da94c8403b382e1e6e434f program/resources.py
17543d01b8351d74eefc665d48c74383bca27d820507fff98646dc3cef2a22b0 program/native.py
7fb36d01c70dc36889cf6dea65aa23763c0dd5139afc1bccdee65324e5e2743b program/native_validation.py
498e7515e4951013822befc419c85b842159be70c1ced08e5cd6ab74d8cd99cd program/binding_validation.py
584fc4b40c83d3618b42f84c71c06d750e264465195f62676bc542e29f0d3ad1 program/queries.py
fd3d756ea382af33916ae6076b17e71a7bc3bc59a45db30c2b7974b573534e6d execution/effects.py
4b828b9a95b5d46b82c5fb3045d514b277dd586bfa3747376807e64f2a624896 execution/validation.py
2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501 execution/flow.py
1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e execution/content.py
e54ec95c69d80b5e00d4b59e4f98aca1bf3c9a9029bde28f0b7bae0f9043071f execution/content_validation.py
ef78805eba6be300dcc222836b8920910720b811ce19c15f1f327ac2000adea6 execution/validity_stability.py
2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259 v2/values.py
2e15e5c3586523507d164152f367e39ae6db9436c312273f3943bc1438688969 scar/analysis/structured_lowering.py
5ab3f166d4f949fe3efa0905dfacc39657562cf3dc0bc96bb1193c1a94b75068 scar/analysis/program_lowering.py
ea4bb6cd1d4976ad7e6d1b7ccd214c5cdeafa0f657623e2363fd110bada9e509 docs/WHOLE_PROGRAM_MODEL.md
2067ce9b9c475b3f98e02fc8151d92f0606778d47279f69f0e082d75eb14a7d8 docs/FIRST_STAGE_COMPLETION_MATRIX.md
028b99cc8e41c65c32a38f96586b90ef6b620ce4d98115607014c629b80fe094 docs/M1_ENVIRONMENT_INTERFACES.md
2e90ce87f80f024916f9a5ab67cbae5aee8bde5fcb7eb39fef501b6b293892a2 docs/M1_NATIVE_INTERFACES.md
fdb61e304d61ba73c937c4cf6aace62713bb9fc3f7527273263a3024595ca3b5 docs/TOOLING_SURVEY.md
39520e50f5440bf9a420a4eceddfd23d17377b58efa422ddf351cc6756bf22f1 docs/MODELING_REUSE_DECISION.md
b8b5b122377a4634d41a357be20da5ea14b7a4c695d56c33f7a2cf198801a95b artifacts/experiments/b1_call_operands/model_native_interfaces/review/next-state-boundary.md
```

短路径 program/execution/v2 均相对 `scar/ir/`。结论不授 runtime/source authority、重排/reuse/transform，
不把本门描述完成等同完整第一阶段；第一阶段完整通过后仍应先停止并向用户说明。
