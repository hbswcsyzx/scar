# SCAR 建模集成设计：复用前端，连接程序与执行

日期：2026-10-16。状态：**设计与下一步验收合同；下列新 adapter 尚未实现。**
能力依据见 [工具调研](TOOLING_SURVEY.md)，基础实体与不变量见
[WHOLE_PROGRAM_MODEL.md](WHOLE_PROGRAM_MODEL.md)。本文补充事实从哪里来，
不另建一套可以独立修改的 def-use/state 图。

## 1. 建模不是要求一个工具捕获所有东西

```text
程序入口、依赖与版本
  ├─ Python ast/symtable/dis / 可选源分析前端
  │    -> 源定义、控制/作用域、调用与外部协议
  ├─ 已有 FX/Export/Dynamo graph / 受控捕获
  │    -> 带边界、阶段、约束的 Tensor 子区域
  └─ 一次真实执行
       -> sys.monitoring + ETO + profiler/Kineto
       -> 实际调用/算子/资源活动与测量

来源和适用范围校验
  -> 规范 ProgramModel + 不可变外部图/原始证据
  -> 明确的 definition/occurrence/realization 对应
  -> 观察根与依赖闭合查询
  -> 后续 OIR、具体修改指导与成本选择
```

source graph 保留未执行分支及 import/加载/预处理/环境/保存；Tensor 子图递归
嵌在对应 Region 内；EEG 保存真实发生的工作。OIR 引用已闭合的区域边界。
三者不强行拼成一种“节点相同就能替代”的平面图。

没有 Torch 图的 Python 部分仍须有输入、结果、状态、控制、异常和资源接口。
graph break 必须成为可定位的边界/续接，不得把周围已经恢复的结构丢掉。
来源缺口细到具体关系和域，不把整个节点笼统标 UNKNOWN 后结束分析。

## 2. 核心实体与图投影

| 实体 | 含义 | 现成工具如何补充 |
| --- | --- | --- |
| Operation | 定义中的操作，带输入 Uses、结果和控制/状态/资源接口。 | AST 的显式/隐式协议、FX/ATen 节点提供不同层级的定义。 |
| Value | 定义结果/region 参数，含数据、引用、绑定、状态和协议变体。 | FX args/kwargs、Export signature、源绑定提供规范化输入。 |
| StateLocation | 可能被改变的位置、owner、selector 与重叠关系。 | 编译作用域、op schema alias/write、mutation outputs 提供部分依据。 |
| Region | 可递归展开的有边界子程序/子图，支持多完成出口。 | Python body、捕获 Tensor 子图、显式 cond/loop 子 region；层级不可混为相同语义。 |
| Resource | 执行与承载身份/要求；实例及状态另记。 | runtime/device/stream、allocation、文件/编码器协议提供物理对应。 |

输入/输出是端口角色；VAL/REP/MEM/XFER/STATE/CTRL/ORDER/IO 是操作行为标签。
它们都不是再加一类互斥的基础节点。五类基础实体也不是“所有行为只有五种”。

用户需要的“节点是广义 function、边是数据、节点可展开”对应 **operation 投影**：
Operation 为展示节点，一个有序 Value use 是边；Region 可展开为内部 Operation。
存储层让 Value 成为一等记录，才能表达多 consumer、重复实参、alias、状态和版本。
控制、效果、资源与包含关系使用单独类型的边，显示时可折叠，分析时不能省略。

采用 MLIR 成熟的 Operation/Value/Block/Region 原则，不发明新的基本 SSA/Region
理论。当前不直接迁移到 MLIR/xDSL：它不会替代 Python completion、外部状态及
执行对应；迁移也需要先证明已有 wire、查询与依赖语义不丢失，而非用框架名验收。

### 2.1 粒度由问题决定

不将“比现有工具节点更细”作为目标。torchview 可以显示 Torch functions 和
中间 Tensor；TorchLens/ETO/FX 已提供不同形式的操作关系。SCAR 应导入其可用
结构，再补缺少的关系；在已有子图内部按需要展开，避免重复记录每个操作。

- 整个 pipeline：先连接加载、变换、调用、外部输出及必要状态，检查父级边界。
- function/module/loop region：分析输入可用位置、环境、状态、退出和生命周期，
  为后续 hoist/reuse 提供作用范围。
- operator 子图：按需使用已有 FX/Export 或动态 provider 的有序输入关系。
- kernel/copy/wait：用实际 profiler 活动回答物理成本与顺序，不从高层调用猜测。

同一内容可以同时有这几个层级；它们通过展开/实现关系连接，不能合并成一个
通用 ID。细化终止于当前问题所需精度或预算；未展开部分仍有完整的边界接口。

## 3. 每份外部图都必须携带的适配合同

以下是完整集成所需的设计字段。[P0 来源声明](M1_PROVIDER_INTERFACES.md)已把
envelope、表示归属和有序端点接入原 core，组件 225 项通过；它不包含 adapter、
artifact 重放或完整边界对应。下列全量合同不能据此算作全部已发布：

```text
ProviderEnvelope
  provider + provider_version/source_revision + schema_version
  immutable_artifact_reference + digest
  capture_mode + transform_pipeline
  program/source/code identities + entry/region boundary
  input/output tree spec + ordered ports
  specialization/shape constraints/guards + compilation/mode assumptions
  execution scope (run, process, thread/window where applicable)
  coverage/unsupported/dropped/conflicting facts
  capture/replay side effects and instrumentation cost observations

Correspondence
  source identity -> canonical definition / imported provider node
  definition -> dynamic occurrence (many-to-many when justified)
  host occurrence -> runtime activity -> resource work
  evidence + rule + scope + unresolved obligation for each relation
```

不能以节点显示名、相同行号、相同 Tensor 地址或接近的时间戳当跨图主键。
源 span 必须带源码/编译版本；provider node ID 带 artifact namespace。
同一函数多次调用有一个定义和多个 occurrence；一次融合 kernel 可实现多个 op，
一个 op 也可发射多个 kernel。匹配数不要求 1:1。

导入后 producer/ordered use/state 只在 canonical core 有一个规范来源；外部图
作为不可变证据保存。别的工具给出更具体的事实时，记录精化或冲突，不能覆盖
原始证据，不能在两张可修改图各维护一套不一致的 canonical inputs。

这里的 canonical 指**各个表示内部**的事实唯一，不是把变换表示与原 Region
混为一个定义。原 source Region、raw export 与 functionalized graph 属于不同
表示/版本，使用不同 Value/Operation 身份；在同一 core 命名空间登记其归属，
不能为原 ValueID 直接替换 producer。它们间的 relation 必须声明原边界、变换
pipeline、假设和逐域结论：数值/梯度、写回、alias/identity、RNG/modes、异常/
控制、外部历史。未证明的域保留未闭合边界。只有 schema/def-use 导入成功时，
只能解释 provider 自身的计算；不得称原 Region 已等价展开、无效果或可替代。

### 3.1 字段归属及导入时必须保留的区别

这是下一阶段 provider 接口的字段映射规格，**不是已实现 adapter 清单**。

| 原始事实来源 | 规范落点 | 必须保留或检查 | 不授予的结论 |
| --- | --- | --- | --- |
| AST/symtable/dis 或成熟源前端 | SourceReference、定义 Region、环境/控制接口的来源。 | source digest、编译阶段/选项、作用域与准确 span；源码构造与运行操作不要求一对一。 | 每个 AST 节点都执行过；无绑定歧义；完整 CFG/dataflow。 |
| FX `Node.op/target/args/kwargs` | 所属表示内的 Operation、结果 Value、有序 Use 与容器/slot 路线。 | 同一 Value 的重复实参分别记 Use；字面量、get_attr、不同结果投影分别处理。 | users 集合包含全部输入槽位；get_attr 是不变常量。 |
| Export signature/call spec | 子区域输入/输出角色、实际环境/状态接口、pytree 端口。 | 区分原始与 decomposed 阶段；参数/buffer/常量/用户输入/写回逐个映射。 | lifted Tensor 永久不变；图外没有 Python 效果。 |
| Export constraints / Dynamo guards | 带范围的模型适用条件及 graph-break 续接边界。 | 来源版本、环境、模式、shape/value 特化及不满足时的 provider 行为。 | 逻辑数据相等；同一分支对所有输入成立。 |
| ETO node / inputs / outputs | 动态 OperationOccurrence、局部 Tensor/存储观察、有序实参观测。 | artifact/run/process 命名空间、真实字段类型与 shape/stride/offset；缺失槽位明确保留。 | 记录 ID 是静态 ValueID 或逻辑内容版本。 |
| ETO `rf_id` 与 Kineto record ID | 同采集窗口内的 CPU occurrence 对应。 | 排除非正 ID；校验唯一性、名称和窗口；冲突不可强配。 | CPU 返回等于 GPU ready；任意窗口均一对一。 |
| Profiler event tree / memory DataFlowGraph | 版本限定的物理身份/分配观察、schema-derived may-write 与候选版本依据。 | 记录采集 flags、字段缺失、private API 版本；TensorKey 聚合关系不当有序 Use。 | allocation ID 是逻辑值；无写边证明外部写不存在。 |
| Profiler runtime/correlation/kernel/memcpy | 物理 Activity、ResourceWork、Measurement 与有依据的实现关系。 | 原始时钟/进程/device/context/stream 域；无关联时保留 gap。 | 按时间邻近补数据依赖；`.to()` 必定发生传输。 |
| TorchLens 等动态依赖 provider | 动态子图及其来源/捕获条件，按 `parent_arg_positions` 的具体路径导入已提供的关系。 | 上游版本、重复 use、嵌套位置、未跟踪来源、重跑与状态影响；折叠的 ParentEdge 不能替代逐槽映射。 | 折叠展示边保持所有实参；捕获路径等于完整程序。 |

某个字段若已有规范 producer/use/state 来源，adapter 只能引用或精化，不能
重复造另一套可修改关系。对精化不一致的情况记录 conflict 及各自依据。
provider 不提供的内容精确定位到对应 slot、状态域或完成边界，不填为 NONE。

### 3.2 未展开部分如何建模

完整类型模型不要求 SCAR 自己编译每个 Python/native 内部。每个未展开 Region
仍要说明实际已知的输入/输出、环境、可能访问的状态域、normal/raise 完成、
挂起/恢复、资源/ready 与 retention/escape 接口，并给出未解析部分的保守范围。
语言完成、挂起协议、host 返回和资源完成是不同通道；可能不返回也须保留。
接口中未知关系可以阻止某种化简，不能让周围已恢复的结构全部消失。
边界还须声明覆盖范围、可能 alias/escape 和未知效果的保守后态：不能以
`effects_complete=False` 为由，让未列 StateAccess 的可能受影响域被当作不变。
同样不能给未知输出增加 identity/alias 精度，或把未知 ready 写成 host-return ready。
失败出口也携带可能已经发生的写入和外部历史，不能把部分失败当作无效果。

源码归属、内部展开、依赖精度和执行证据分别报告，不能把一个 opaque 外壳
算作“已完全理解”。模型支持表示一个库边界，也不要求在第一阶段实现该库的
完整解释器；额外源码 lowering 属于后续自动建图阶段。C1 等控制接口的用途是
把现成前端和运行证据接到共同边界，不能扩大为自写通用 Python 编译器的项目。

## 4. Tensor 子区域的导入规则

1. **先识别 graph 的种类与阶段。** FX symbolic trace、Dynamo segment、原始
   ExportedProgram、functional/decomposed graph 的边界不同。记录版本与 pipeline，
   不把 `run_decompositions` 产生的纯值形式冒充原始执行的 storage 行为。
2. 对 placeholders 使用 Export graph signature / call spec（如有）区分 user
   input、parameter、buffer、constant、token 等；pytree leaf 和有序 slot 保留。
   同一个输入传两次仍有两个 use；get_attr/parameter 不自动等于不可变常量。
   每个 lifted slot 的连接还必须带具体 module/function environment 实例、实际
   原引用/selector、该次调用入口的规范 StateVersion Use 和对应依据。`target='b'`
   只是此 capture 内的属性路线；同名属性、shape 或相同代码不能证明父级是同一
   location/版本。未解析实例、alias、mode 或入口版本时保留具体 slot boundary，
   不从 capture snapshot 伪造当前 parent state。
3. 结果使用 output signature 定位 user output 与 state/input mutation；未规范化
   图还需检查 mutating op/interface。本机原始 export 中 USER_OUTPUT 唯一并不证明
   无写。op schema 的 alias/write 是库合同的一部分，不覆盖自定义/native 任意效果。
4. 将导出状态写连接到父 Region 的规范 state 接口；若规范化引入额外结果或 copy，
   保留 adaptation rule 与 alias/identity 限制。graph signature 不单独证明旧 Python
   region 没有 hooks、列表写、RNG 或外部交互。
5. 导入形状范围、编译模式、training/grad/autocast、捕获环境依赖与被特化的 scalar。
   专门化图是条件模型；guard 不满足说明该 specialization 不适用。Dynamo 的
   重编译/回退与 standalone ExportedProgram 的 guard 拒绝须按 provider 区分；
   不由此推断原程序成功/失败，也不能把一次分支删成普遍常量。
6. `node.meta` 的 stack/module/shape 等仅按实际存在和版本解释；有 metadata 不等于
   精确 source 身份，缺失时明确边界，不按名字补猜。cond/loop 子图递归导入并连 carried
   values/state；普通动态 Python if 留在父级控制模型。

自动发现与调用额外 forward 是两件事。已有 compiler graph 可直接收集；没有图时，
先复用真实执行的 ETO/profiler 和源码结构。FX/Export 捕获可能运行 Python、修改
状态或消耗 RNG，不能在 live 程序中偷偷再调用一次然后称其无影响。额外捕获放
受控 replay 的独立进程/状态中，记录输入与外部效果边界；不能安全重放时保留
已知结构及具体缺口。不得给 LeWM 或某类 module 写人工 pure/constant 特例。

## 5. 执行证据的接通与观测成本

优先在同一次采集中启用 ETO + Profiler，保留两者原始 ID 和 window；复用
现有 Python monitoring、module span 和 Kineto importer。

另将 [TorchLens](TOOLING_SURVEY.md) 作为已有细粒度动态依赖 provider 进行后续
隔离评估，与 ETO/现有 wrappers 比较来源完整性、metadata/payload 成本、mode/
状态影响及能力范围。未通过前不接入 live 程序；重跑恢复、force-eager、结构
hypothesis 等必须进入 provider envelope，不能当原物理执行或纯性证明。

| 对应层 | 可使用的关系 | 必须拒绝的捷径 |
| --- | --- | --- |
| Python source ↔ code | source snapshot、compile context、code/position witness。 | 只按文件名/行号/qualname。 |
| Python call ↔ Torch occurrence | 实际调用/嵌套上下文、准确 runtime ID、可验证 wrapper/span。 | 同名 module 即同一次调用；默认 Python CALL 含完整 actuals。 |
| ETO ↔ profiler CPU | 同 run/process/对齐 window 的非零 rf_id / Record function id，验证唯一性和记录一致性。 | rf_id=0、跨运行裸 ID、重复冲突强行匹配。 |
| CPU op ↔ GPU activity | 实际 external/correlation/runtime IDs 与已验证版本规则。 | 用 CPU 同步返回或时间邻近证明 GPU 完成。 |
| Tensor ↔ object/storage | provider 局部 ID + shape/stride/offset/type/device + 生命周期证据。 | 裸地址长期唯一；StorageID 是内容版本；同设备 to 是 PCIe copy。 |

当前 ETO CPU 关联已实测，GPU 链路仍未验收。ETO tuple 的存储标识还需生命周期
代次和 selector；同 tuple 的原位写产生新内容版本，不能复用旧 LogicalVersion。
NumPy/native 外部写不一定经过 Torch dispatcher；来源协议与外部状态边仍由 SCAR
连接，不逐迭代复制 Tensor 来掩盖缺失的写依赖。

新增的 profiler event tree / memory dataflow 来源已做单次 CPU 能力探针，详见
[调研 3.5](TOOLING_SURVEY.md)。先评估本来已采集的字段；不能为了读取 metadata
就无条件打开 with_stack 或再启动一个 profiler。rich memory profile 的额外
选项、private/deprecated 状态和来源语义需要单独记录，未接入当前 SCAR。

默认先收集 IDs/shape/stride/dtype/device、op schema 与必要控制事件；按预算选取
关注区域。少量值样本只作排除/预筛，不证明相等；不保存完整参数/activation。
ETO 额外内容采集配置必须显式记录，不能仅依赖 `extra_resources=False`。
避免同时常开 profiler、全指令、所有 hooks、TorchDispatch 和全 Tensor observer；
比较 ETO 能替代哪些重复记录后再选采集组合。instrumented 时间不当 clean 性能数据。

## 6. 跨层的“同一个东西”仍由规范关系回答

```text
source result ValueID
  -> ValueOccurrence(run, activation/resume, visit)
  -> Denotation: Reference(ObjectID) / Data(ValueVersionID) / ...
  -> StateRead(current location/version) where contents are required
  -> ValueDerivation or RealizationDerivation
  -> Materialization(allocation generation, region, representation, ready)
```

FX 值名表示定义关系，ETO Tensor/storage ID 表示局部执行身份，Profiler 表示
活动，三者都不能直接作为 LogicalValueID。deepcopy 也不能靠相同来源无条件合并；
先连接通用 copy 协议的实际 inputs/state/outcome，再在确切 domain 上证明值关系。

例如从文件经 parse→normalize→GPU materialize→encode→后续计算，程序图保留
全部 producer/state/control/effect 边；EEG 提供实际调用和物理成本。只有这些
接口接通后才能沿父级 Region 查找最早可用且合法的位置，判断可否 hoist/reuse。
这一步不需要重新实现 normalize 内部所有 ATen 算子的 tracer。

反向依赖闭合从返回、必要状态、外部输出及完成行为出发。视频和 Tensor 文件保存
均落在变换、protocol state、write/flush/close；不同数据载荷不另造业务节点类型。
import 最终只消费常量时仍须审查初始化/注册/hook/异常等观察依赖，工具画出的
常量叶节点本身不授权删除 import。

## 7. 后续顺序与自主验收

M0—M6 主阶段保留；本次复用审查作为 M0/M1 的输入，**先于继续扩大自建 lowerer**。
以下是阶段内顺序，不要求用户逐项批准：

| 顺序 | 交付 | 自主验收与失败条件 |
| --- | --- | --- |
| T0 工具能力审查（本轮） | 调研、版本化小实验、当前 collector 盘点、复用决定。 | 官方/原源码支持；实测/推断/拟接入分开；不报 GPU/LeWM 未测结果。 |
| T1 完成模型适配合同（第一阶段内） | provider envelope、规范接口/来源归属、source/FX/Export/ETO 字段映射、边界与错接规则。 | 同步/异常/恢复、state/alias、资源完成不混；已有工具可给的事实明确归属；独立审查。仍须完成 M1/M2 全分母。 |
| T2 最小公开导入闭环（建图阶段） | ETO+Profiler 同运行导入，FX/Export 规范化子图；未捕获 Python 外壳保留。 | 微型通用 pipeline 实际读→变换→计算→写的有序连接；原位/NumPy写、view、RNG、graph break、部分失败等反例不获假证明。 |
| T3 全程序连接与源前端对照 | 自动选取入口/依赖/子区域，比较 stdlib 与 LibCST/CodeQL 的收益及成本。 | 不要求手工 module/function 名单；源码归属与语义展开分开报；预算/未展开分母公开；不以 opaque 计理解完成。 |
| T4 外部 testcase 压力 | 同一路径验证未修改 LeWM 的加载→执行→保存，复用已有原始证据。 | 来源/状态/控制/物理对应可查询；实际 consumer/异常/escape 缺口逐项定位，无特殊业务规则。 |

T2—T4 属于后续建图/精化，不在用户要求的第一阶段停止点之前偷跑。
第一阶段完成时先停下来讲解模型、证据、未可证明范围；不开始化简或新增 backend。
T0 完成也不意味着 M1/M2 或完整程序模型完成。

在 T1 内先确定源前端的替代字段与语义缺口，再决定是否增加自建 control
lowering。CodeQL 已有 Python CFG/basic-block/dataflow；包括 finally 的多种
控制路径，不能只因它用于安全分析就认定要重写。其版本支持、提取成本与
SCAR 所需状态/完成接口须做有界对照；当前没有本机 CodeQL 运行验收。
T3 负责集成后的全程序结果，不作为“到了后期再考虑复用”的理由。

### 7.1 替换现有 observer / lowerer 的准入条件

1. 列出逐字段覆盖：哪些现有事实由 provider 取代，哪些仍需原 observer，哪些
   两者都不知道。保留原始来源、缺失/截断和不同层级的语义，不按节点总数验收。
2. 用相同通用反例检查有序重复实参、原位/外部写、view、状态、随机性、异常、
   graph break 和生命周期。若 ID 相同被误判为内容相同，立即判该映射不合格。
3. 在受控窗口量采集开销、文件体积、峰值内存、引用/状态影响；按字段选择最小
   采集组合。没有这些数据时不能宣称“更高效”或默认叠加全部 hooks。
4. 原 observer 的删除只在被替代字段及兼容读者通过后执行。失败保留证据，
   回退既有来源并报告缺口；不把 provider 不兼容变成整个程序不可表示。

本阶段先交付字段合同、组合校验及构造规则；最小运行导入与上述成本比较在
第一阶段汇报后的 T2 执行。不会因为又发现一个工具就再建一套独立图模型。

### 7.2 收缩 native 接口：保留原生合同，不复制工具内部模型

2026-10-16 对 P1 草案的复审发现，若把通用 TreeSpec、全部 native 角色、所有
completion 投影、写回及跨表示证明捆成第一次导入的前置，仍会重复实现现成工具。
因此作以下设计修正；这是 **Proposed 的实施约束，不是新 adapter 已完成**：

1. **原生事实留在原生 artifact。** FX 的 `args/kwargs`，Export 的
   `graph_signature.input_specs/output_specs` 与 `call_spec.in_spec/out_spec`，
   由固定版本 adapter 读取，保留原始顺序、重复位置与路径。优先复用
   `torch.utils._pytree` 的原生规则，不先写一套 flatten/unflatten 解释器，也不
   克隆所有 Export 枚举。自定义 pytree 的反序列化不能隐式执行任意代码。
2. **SCAR 只补必须跨边界查询的引用。** native 槽映射到已有 entry/exit；
   同一 Value 的两个使用位置保持独立。entry 指实际区域参数，exit 指逻辑
   ExitPort，查询保留其所有 Return/Raise 站点。映射不再复制 producer、类型、
   call actual 或前后状态；原始事实和可重算索引不能成为两份可修改的真相。
3. **先明确导入对象的范围。** 导入一个 provider 自己的 GraphModule，仅说明
   该表示内的 def-use；不要求先伪造它与原 Python 调用的连接，也不宣称它是原
   Region 的等价展开。后者仍须具体实例、当前状态、mutation 写回、alias/梯度、
   RNG、异常、外部历史及资源完成合同。缺项定位到关系，不以全局 UNKNOWN 代替。
4. **按真实 slice 增补接口。** native 输出是 Tensor payload 时不能改型为
   StateVersion；opaque tuple 不凭 TreeSpec 自动拆成多个值。可能抛异常的 lookup/
   写回不能强塞入当前禁止普通 StateAccess 的 INVOKE。若某个边界确实需要这些
   关系，列出最小反例再扩展规范接口；不能给每个 provider 预造全部语言协议。
5. **执行图沿用执行图。** ETO 的有序观测及 profiler 的现成 activity/correlation
   不先强制变成静态 SSA，再据此反推未执行路径。它们进入已有 occurrence/evidence
   层，与定义图通过有范围的对应关系连接；未连接不影响保存已知的原始事实。

验收顺序：固定一份原生 artifact 和端口分母 → 薄引用映射与错接反例 → 明确
未证的跨表示域 → 第一阶段完整模型汇报 → T2 的公开导入与采集成本对照。
第一阶段无需实现所有第三方内部类型；也不能仅保存 artifact 路径就宣布其依赖
已经进入规范模型。复审记录见
[reuse boundary review](../artifacts/experiments/tooling_survey/reuse_boundary_review.md)，
独立的[字段归属检查单](../artifacts/experiments/tooling_survey/value_provider_review.md)
补充了最小采集组合与不能合并的身份。

## 8. 调整现有投入

- 保留现有 parser、trace/profiler、source identity、严格 wire reader 与已验证有限
  core；不因新方案删掉历史证据和测试。
- 在新的 Tensor 图适配器落实前，不再扩写与 FX/Export/ETO 重复的通用 Tensor
  tracing/metadata 机制。新增内容必须说明现成接口为何不足。
  已有 TorchLens 的细粒度动态结构同样纳入复用范围，不因最初清单遗漏而继续自建。
- Python 协议规格继续约束模型，但不把“列全语言构造”变成从零写完整编译器的
  必经路线。优先导入成熟前端的结构，再补 SCAR 需要而前端未表达的依赖关系。
- 保留一套 canonical core 与 scoped correspondences；适配器不直接造 candidate，
  planner 不把 provider 成功当 legality。化简与修改指导仍在建模/建图之后。
