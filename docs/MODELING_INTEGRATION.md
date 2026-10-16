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

## 3. 每份外部图都必须携带的适配合同

以下是必须满足的设计字段，不是新 Python dataclass 已发布：

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
