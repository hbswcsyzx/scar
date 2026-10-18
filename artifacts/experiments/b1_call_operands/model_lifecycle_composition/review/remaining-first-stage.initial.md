# D2.4 之后的 M0–M2 有限缺口

## 范围与依据

本审计把“D2.4 之后”当作下一停止点：当前 `FIRST_STAGE_COMPLETION_MATRIX.md:26` 仍把 D2.4 组合/公开范围复核列为未完成，因此下列项目不是 D2.4 的验收替代品，也不表示整个 C2 已关闭。审计截至 worktree HEAD `fdf9d0d37ab043db297f095bfafa685b32b0b058`；没有运行测试、目标程序、GPU 或全仓任务。`git status --short` 当时有 root/其他工作正在写 lifecycle、codec、tests 与 D2.3 文件；代码指纹表示本次读取的工作树内容，不应冒充该 HEAD 的提交内容。

读取基准 SHA256：

| 文件 | SHA256 |
| --- | --- |
| `docs/FIRST_STAGE_COMPLETION_MATRIX.md` | `1b4df5432a8844cbd3a47a3117301cae74e4901bd2a3d60a0d2637cb437d2382` |
| `docs/WHOLE_PROGRAM_MODEL_PLAN.md` | `20a94ad28016e02efa1997b0c6c2b082d6e14f13bb0505dcabdd071f526497ff` |
| `docs/MODELING_INTEGRATION.md` | `71fc1827428195be702bb9b953a5d93d52612f210a8d8c01a8807645f0dbf6fb` |
| `docs/WHOLE_PROGRAM_MODEL.md` | `ea4bb6cd1d4976ad7e6d1b7ccd214c5cdeafa0f657623e2363fd110bada9e509` |
| `scar/ir/program/resources.py` | `167f0b2e1267278362341e6622e5cb164292e93484da94c8403b382e1e6e434f` |
| `scar/ir/program/resource_validation.py` | `f2709a6d9e9898bc5ecb87ae2396510750550fde1bb071f8ab9808569f352c39` |
| `scar/ir/program/model.py` | `3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1` |
| `scar/ir/program/resumption.py` | `ef9d208d57ff6d3cd834529df7b68f377d1ac210f3f262b421c15aeadf5109ac` |
| `scar/ir/program/drivers.py` | `d1a4844d3b00fefed05e2fb743daaf32c9082ae8f0fec3a9db6bce255561aabd` |
| `scar/ir/program/native.py` | `17543d01b8351d74eefc665d48c74383bca27d820507fff98646dc3cef2a22b0` |
| `docs/model/PYTHON_DATA_DEFINITION_PROTOCOLS.md` | `1a5f87dce26236a97e41ad24e0085ec2d73a634b9ce0bd709ce9fc693100fb4a` |
| `docs/model/PYTHON_CONTROL_PROTOCOLS.md` | `db0269f2fd50e9da3fde14986d4f1e69d19c0751f63f24661b53a1ed62c7707d` |
| `docs/model/RESOURCE_PROTOCOLS.md` | `5033fd3221d112dcebcbf087788440d7545effc88330dff589ed3ed4cdd482e4` |

## 已有机器接口与有限结论

- 规范 `ProgramGraph` 已有 Operation/ordered Use、Data/Reference/State/LocalBinding/Protocol 值、Block/Region/CFG、StateAccess、typed completion、cleanup、resume、driver、provider/native 端口；这些表复用同一 producer/use/state 图。见 `scar/ir/program/model.py:66-95,107-163,191-263,370-401,423-510`。`Terminator.BRANCH` 的 edge 0/1 已固定表示 true/false，见 `model.py:487-493`。
- 静态资源子项确已接入原图：`ResourceDefinition`, `ResourceRequirement`, `ResourceUse`, `ResourceLocation` 在 `scar/ir/program/resources.py:40-186`；`resource_validation.py:10-117` 校验 owner、引用 Use、静态 kind/role 与关系闭包。有限组件已验收，但不是实例/完成证明，见 `docs/M1_RESOURCE_INTERFACES.md:7-18,79-84`。
- Resumption 与 driver 类型确实不是空壳：`ResumableBody`, `SuspendTerminator`, `SavedSlot`, `ResumeSlot`, `ResumeSuccessor` 位于 `resumption.py:32-60,63-70,109-230`；`ResumableCreate`, `AsyncRequestCreate`, `RequestAssociationRead`, `DriverInterface`, `BodyStart/Resume/Drive` 位于 `drivers.py:42-44,66-93,95-193,195-300`。它们明确区分创建、请求与 body drive，也保留当前 state 与私有 saved frame。
- Provider P0 与 native P1 的声明表、严格端点分区和查询已有机器实现。其含义仍是“记录了可检查的来源/边界义务”，不是实际 artifact replay、tree flatten/unflatten 或等价性。`providers.py` 的 envelope/region/binding；`native.py:1-8,49-145,157-220`；`queries.py:705-789`；`docs/M1_PROVIDER_INTERFACES.md:13-25,64-87` 与 `docs/M1_NATIVE_INTERFACES.md:64-84,98-110`。
- M2 已有 Python 3.14 字段级数据/定义、控制、资源分册及本机小语言见证；catalog 当前分母为 113 AST 构造/196 字段。规格明确说 AST 字段次序不是执行次序，未知协议要保留输入、状态和异常边界，见 `PYTHON_DATA_DEFINITION_PROTOCOLS.md:12-41,454-473`。这属于**仅规格/见证**，不代表当前 lowerer 覆盖。

## D2.4 后仍需完成的有限清单

| 优先级 / 状态 | 具体缺口与落点 | 可执行的验收证据 |
| --- | --- | --- |
| **M1 — 未实现：资源 instance / generation / realization** | 当前 core 只记录静态 definition 与 requirement。`ResourceUse.definition` 可以为空；代码没有 `ResourceInstance`, generation 或 realization 类型，见 `resources.py:123-179`。设计分册已明确外部实例、多次执行生成不同实例、handle lifetime，但不是现表，见 `RESOURCE_PROTOCOLS.md:59-103`。 | 在原 `ProgramGraph` 增 typed `ResourceInstance` 与带 scope/evidence 的 definition/requirement→instance、handle→instance 关系。图级正反例：一个静态 Create 两次 activation 对应不同 generation；同一 handle 在关闭后不可继续绑定；外部实例无源内 Create；两个静态 ID 不自动推出实例不同/相同。通过 strict codec/query 与 `require_valid`，查询仍标声明/observed 不同。此门只验类型和组合，不要求 source/runtime 自动匹配。 |
| **M1 — 未实现：WorkTicket / outcome / Ready** | `scar/ir/program` 没有 WorkTicket/Ready 类型。v2 `Materialization.ready_event` 仍是可选字符串 (`scar/ir/v2/values.py:150-175`)，whole-model 明确指出 host return、device completion、consumer visibility、flush/close/persistence 不是同一事件 (`WHOLE_PROGRAM_MODEL.md:305-320`)。 | 新类型必须接既有 Operation Uses、StateAccess、normal/raise completion 和 ResourceInstance generation：提交结果只产生 Ticket；wait/完成状态产生 typed outcome；Ready 同时绑定 work generation、materialization/content version、allocation generation 与 consumer visibility domain。验收：host enqueue 返回后仍不可读；完成了旧 generation 不满足新工作；cancel/partial failure 保留已经写入的后态；文件 write 与 flush/close 分开。不要用时间戳先后或 event 名字符串替代 readiness。 |
| **M1 — 部分实现：location owner / selector / alias 失效** | `Footprint` 只有 `WHOLE/INTERVAL/UNKNOWN` 数值区间，`ReferenceValue.targets` 只是 `LocationID` tuple，见 `model.py:107-128,208-233`。这足以保守写粗粒度 world，不编码 namespace key、object attribute、container index/slice、closure cell 或资源 handle owner 的精确选择。矩阵将此列为粗粒度可表达、精化接口未齐 (`FIRST_STAGE_COMPLETION_MATRIX.md:27`)。 | 加版本化 typed selector/owner 关系，规定未知选择怎样保守覆盖已知选择，并与现 StateLocation/StateAccess/SSA 合流，而不为 fast-local 造全局 world。验收两个引用 alias 到同容器，分别写不同键与同键；首个写必须失效对应读版本，UNKNOWN selector 与任意具体 selector 冲突而不能静默 disjoint；closure cell 与普通 local 不得混为同一 binding。 |
| **M1 — 未实现：literal 的完整表示** | `LiteralOrigin` 只收 `None/bool/int/有限float/str` (`model.py:154-163,299-310`)；`DataValue` 校验 builtin 标量类型 (`model.py:191-205`)，literal `ReferenceValue` 不给 identity/targets/selector (`model.py:208-233`)。M2 catalog 同时列 `complex`, `bytes`, `Ellipsis` 并指出 spelling/value 不证明 object identity (`PYTHON_DATA_DEFINITION_PROTOCOLS.md:407-430`)。 | 定义 exact tagged union/编码，让 `b"x"`, `1+2j`, `...` 可无损 round-trip；区分 scalar literal 与容器构造、常量折叠和 runtime object identity。正反例包含相同 spelling 的两次构造不可因字面相等合并 identity；dict/list/set 的 hash/equality/部分失败保留调用与状态。f-string conversion 与 t-string interpolation 采用各自求值协议，不把二者降为 constant。 |
| **M1 — 仅有基础 records：ValueOccurrence→Denotation / Provenance bridge** | v2 已有 LogicalValue/Version、Provenance、Allocation/StorageRegion/Materialization/ObjectBinding (`scar/ir/v2/ids.py:65-93`, `scar/ir/v2/values.py:150-185`)；core `ValueID` 是静态图值，尚没有从一次 activation/visit 上的 ValueID occurrence 到 Data/Reference/ObjectID/Binding/State/Protocol/Unresolved denotation 的强类型桥。定义与要求不是实例，静态 `ValueID` 也不能充当 v2 `ValueVersionID`。见 `WHOLE_PROGRAM_MODEL.md:88-120,126-130` 和矩阵 `FIRST_STAGE_COMPLETION_MATRIX.md:29`。 | 为 occurrence、denotation、value derivation、materialization derivation 和有效范围建立 typed link，producer/Use/state 仍只以 core 为规范来源。验收同一 static ValueID 在两次循环 visit 指向不同版本；两个 Use 同一个对象但读不同 state version；copy 新建 materialization 而非逻辑 lineage 自环；证据缺失返回具体 unresolved reason。**只验接口可组合**；真实采集是否对应该 occurrence 留 M4。 |
| **M1/T1 — 部分实现：native/provider 边界的 state/resource 端口关系** | P0/P1 现有 envelope、ProviderBinding、NativeBoundary、BoundaryRelation 已有类型，但 native role/tree 不解释、不读取 artifact，也不证明条件；`native.py:1-8,120-145`。已有八域义务不等于实际 tree-to-slot、lifted state、写回或 artifact provenance 已验，见 `M1_NATIVE_INTERFACES.md:64-84,98-110`。 | 补齐**通用接口合同**：每个外部边界 slot 如何引用现有 entry/exit、Use、StateAccess、ResourceRequirement/Ready，并逐域表达 condition/coverage/unresolved obligation。验收 native/core 端口错接、缺写回域、部分输出和异常后态的 fixture。无需重建 native 内部 ATen/Export 子图；不允许把 `OPAQUE` 或 boundary completeness 声明成内部已理解。真实 artifact digest/replay、跨表示动态匹配属后续适配与 M4。 |
| **M2 — 仅有规格：协议 catalog 到规范类型的守恒矩阵** | 113 AST 构造/196 字段已有分册，但 `WHOLE_PROGRAM_MODEL.md:508-516` 明确 structured source lowering 只覆盖有限表达式/同步控制，whole-body unsupported 仍存在；`PYTHON_DATA_DEFINITION_PROTOCOLS.md:456-473` 也把自动覆盖与 M3/M4 分开。M2 不是再做一遍 Python compiler。 | 对 catalog 每个构造/field 增一行机器可审矩阵：phase、求值顺序、有序 Uses、定义/绑定、state owner/selector、normal/raise/cleanup/resume、资源/生命周期端口，或者引用一个明确的 bounded protocol boundary。行要连接到现有 canonical records 和独立正反图/小语言见证；没有记录的字段单列 gap。对未知 descriptor/call/native 内部保留真实调用边界，不默认纯或无写。测量条件是 catalog 守恒和接口结构正确，不要求每个 AST 实例自动lower。 |

### 需要归类到后续阶段，而不是用来拖延 M0–M2

- **D3 接口义务（M1/M2）**：生成器/协程/异步生成器 create、request、resume、throw/close/cancel、delegate/await、body yield/return/raise 的 typed 参数、状态、出口和合法组合；控制/资源/cleanup 的相邻组合。`drivers.py` 与 `resumption.py` 已给静态骨架，但 `M1_DRIVER_LIFECYCLE_CONTRACT.md:163-172` 仍把全 family/source-runtime 对应分开。接口可通过手工 generic IR + 语言例子验收，不需要收集目标运行来声明字段语义。
- **M3**：自动把 source definitions/imports/calls/field operations 映射到上述接口；保留未支持子树的周围结构、预算与来源。不能因手工 fixture 通过而宣称 automatic lowering。
- **M4**：运行时 `ObjectID`、activation/resume visit、ResourceInstance generation、实际 request/dispatch、FX/Export/ETO/Profiler/native artifact 之间的 scope/evidence/many-to-many 对应；缺失、冲突和截断要有记录。Provider scope 不是 occurrence match (`queries.py:710-728`)。
- **M5**：从必要输出、返回、异常、文件/视频/日志和资源完成根做依赖闭合与未知边界定位。它消费已连的 source/core/occurrence/work/ready，不应混进每个 M2 构造协议测试。

这也限定 native 范围：M0–M2 要有完整、保守且可验证的跨界接口；不要求把第三方 native 内部重新实现为 Python 语义。边界声明可表示“未知”，但未知内部不计为已理解，也不授化简权限。`WHOLE_PROGRAM_MODEL_PLAN.md:30-32,48-56` 已明确这一点。

## 建议的下一批顺序与停止条件

1. 先独立关闭 D2.4 组合/公开查询范围，再把其结果固定为 D2 baseline；不要在本清单把它与 resource 接口糅合。
2. 补 **resource instance → work → outcome → ready/visibility** 的静态规范 records 与 validator，复用现有 StateLocation/StateAccess、ResourceUse、Materialization/Allocation，而不维护第二份 state 或 producer。用“checkpoint load→decode/materialize→推理 work→wait/consumer→encode/write→flush/close”同一通用 fixture 做端到端组合；checkpoint 路径不造业务专用节点。
3. 补 **typed owner/selector + literal tagged union**，并给 Name/Attribute/Subscript、容器、格式字符串各一组有序访问、别名写和异常反例。精确目标未知时保留 UNKNOWN 与保守 state frontier。
4. 补 **occurrence/denotation/provenance 接口**，将 core static definition 与 v2 logical/materialized identities 按 scope/evidence 连接；用循环、重复调用、alias/copy 三组反例证明静态 ID 不被当动态 ID。runtime trace/native adapter 只提供后续 M4 evidence。
5. 将 Python 3.14 catalog 的 113/196 分母映射到这些既有/新增类型或有界边界，合并 data/control/resource 分册，补通用 typed graph 正反例；随后由 M0 独立审查核对身份、端口和规范事实是否矛盾。M2 完成只表示所有构造都“有规则或明确边界”，不表示所有构造已自动恢复。

到此停在第一阶段：类型、组合、构造规则与工具映射合同完整且可校验。Source lowering、artifact replay、runtime realization、whole-program consumer closure 继续各按 M3/M4/M5 验收；既不要求先写完整 Python compiler，也不把 typed conservative boundary 说成其内部依赖已理解。
