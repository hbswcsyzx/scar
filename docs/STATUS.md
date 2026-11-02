# 当前状态

当前唯一任务：整程序纯静态建模与建图。第一阶段未完成；目标程序未执行，LeWM 未修改。唯一 checkout 为 `~/AAA/scar`，分支 `main`。

## 当前首要问题与本轮修复

原来的瓶颈是：局部 CFG/SSA/状态图存在，但跨主体关系靠多个专项 reader/solver 解释，
通用分析没有统一依赖导航。本轮已实现 `ProgramDependencyGraph` 和共享只读 session，
使用原 namespace/typed ID/context，投影局部、call/env/G、class provider、状态和控制依赖。
不复制 callee，不把包含/顺序当控制依赖，不将一般依赖当内容或对象身份。

值分析与区域边界查询已经实际消费该共同接口，并接入公开 CLI。有限 scalar/type/来源
工作队列能跨两层参数/返回与绑定传播；覆盖赋值不借用旧值，循环/预算保留已知字段。
这不代表完整 alias/effects/逐地址状态或 Tensor 属性推理已经完成。

当前优先完成真实全范围接线，再补共同推理缺口与主体覆盖。不会继续增加 detector/backend。
主图设计和关系边界见 [程序分解 §3.4](PROGRAM_DECOMPOSITION.md#34-主图决策与当前结构性缺口)。

## 当前已发布产物

`artifacts/current/static/manifest.json` SHA-256：
`d2945ccf6d5847e8cbe2bf3d3a9156e2f8d55a61784480611ffb0d9f84bddc2b`。

| 项目 | 当前结果 |
|---|---:|
| 源码单位 / 实际文件 | 862 / 862 |
| 原始源码 | 12,447,536 bytes |
| AST occurrence / 词法入口及上下文 | 1,493,620 / 36,164 |
| 源码操作 / 关系 | 835,725 / 3,738,042 |
| CFG 节点 / 边 | 478,899 / 569,425 |
| 有限常量事实 | 124,535 |
| 有规范图的入口 | 8,089，原有主体未因材料扩展重建 |
| 规范操作 | 1,262,346 |
| lowerer / shape 不支持 | 326 / 404 |
| 缺独立适配 / 新单位未派工入口 | 3,731 / 23,614 |
| 当前调用索引 / class 接线索引 | calls 未发布；class 已发布 1,065 bindings、400 parent shards、15 共享 provider |
| 压缩分片 | 14,927 个，2,409,074,599 bytes |

清单已去掉重复诊断数组：逐份核对 8,415 个 body artifact 后，改为原分片内 count/pointer 引用。
当时 manifest 从 153,148,270 降到 35,455,247 bytes（减少 76.85%）；原图/源码分片字节与原 ID
未改，原声明指针和证明输入投影不变。处理 28.017 秒、8 个有界 worker；这只是分析器
存储整理，不是目标程序加速。旧 inline 格式仍可读回；未有可核对原分片的诊断不删除。随后新增 class 索引元数据，当前清单为 36,669,534 bytes。

新一轮沿原 import 关系，自动把 264 份外部 Python 源码、16 份 stub 送回原前端，共 280 个正常 units；新源层没有读取或构造失败。阶段记录的 analyzer_seconds 为 207.190 秒，8 个进程；该字段在随后材料刷新前记录，不能当全过程 wall-clock。原 source/canonical 分片没有重建或改写。

`--inventory-dependencies` 定点盘点材料，`--expand-dependencies` 将材料送回现有前端并更新全范围索引。原 import/material 证明输入内容寻址去重，作为当前图的必要依据保留，不保存旧 checkout 或旧 manifest。源码、stub、native 和 namespace 候选以及运行选择条件分别保留，不把找到文件算成已证明实际 import。

扩展后有 42,074 条 import 关系、9,843 个模块查询。本轮材料刷新只处理 4,096 个，5,747 个是明确预算未处理；不能当作不存在。当前仍有 725 份外部源码和 135 份 stub 候选待处理，依赖闭包未完成。材料盘点的 external_source_analyzed=false 描述盘点步骤本身；前端已分析的新增单位另见 dependency_expansion。

当前保留 37 条早期 BrokenProcessPool 的 unit/body-worker 记录；对应样本主体后来已有规范图。这是遗留问题记录，不是本轮 280 份源码新增失败。其终态归属仍需统一，不以 summary 的旧零计数掩盖。

## 本轮代码和实际核验

- **共同图/调用**：原 actual/formal、normal/raise、world、环境和 G/state 进入同一接口；
  匹配静态接口栈进出，不回退到不同调用并集。唯一跨模块综合检查通过，222.42 秒；独立
  公开读回通过。异步/生成器创建不冒充同步 body 返回，模块初始化 L/G 仍有明确前沿。
- **共同值分析**：原源码综合和新增最小原 IR 检查均通过，合计 14.22 秒。`relay(4)`、`relay(9)`、先覆盖为 7 再加 1
  分别传播到 5、10、8；opaque 覆盖不借用旧值。循环使用有限候选与 widening。
  原 literal 可 EXACT，call 结果目前仍有条件及 `PRODUCER_VALUE_CONTRACT_OPEN` 等前沿；
  不是已经证明可常量替换。完整声明的本地同步 region 结果可得到精确常量 7；
  已知候选不返回不再抹掉未知 dispatch 的正常路径。`未知 int ∪ 7` 保留未知分支，
  UNKNOWN 在同一工作队列传播，已知 int 类型仍单独保持精确。
- **class/control/区域边界**：共享 provider、两类上下文隔离、normal/raise 状态、CFG 控制依赖、
  区域输入/消费者/原状态地址及资源/顺序接口接入。未知 alias、allocation/free、RNG、外部
  和 observer 效果不冒充 NONE。短检查已通过；另修复只读 INVOKE 状态直通、binding 数据边和未枚举边界误报。
  独立创建的 ResourceDefinition 现在沿原 creator 操作接通；外部资源入口及 requirement
  约束保留依赖，不据此宣称实际分配、共享或物理搬运。
- **公开入口**：`static-query --program-graph` 的 walk、`--infer-values`、
  `--boundary-operation` 已在保存的通用小模型读回，均保留条件/前沿且不授予变换权限。
  本次同进程边界 6.543 秒、值查询 0.154 秒、遍历 0.082 秒；缓存、模型和查询不同，
  不能据此计算相互加速比或 LeWM 性能。
- **真实 LeWM 查询**：保存的 `solver/cem.py::solve` return Value，公开共同图有界遍历
  到 96 个端点、142 条边，含数据、状态、控制与 block 参数。达到端点预算；调用关系
  尚未发布，相关前沿明确保留。这是实际静态图查询，不是完整跨层闭包或目标执行。
- **真实 LeWM class 跨图查询**：发布后使用公开 CLI，从 `solver/cem.py` 原 module 的
  builder 输入 Use 到共享 provider formal，5.017 秒，2 个访问端点、1 条跨 namespace
  ARGUMENT 边、1 层静态上下文和 4 项原条件。原接线记录为
  `indexes/classes/bindings/000345.json.gz#/bindings/0`；没有用类名选择分析规则。
  calls 未发布、关系 scope 和 alias 未闭合前沿仍保留；关系过滤后的查询不能冒充依赖闭包。
  机器记录为 `artifacts/current/queries/lewm-class-interface.json`，含当前 manifest receipt。
- **真实 LeWM 三层依赖路径**：进一步从同一原 module 输入，经 provider 内原操作，到
  suite globals formal，使用同一 GraphView 到达两层上下文端点。9.065 秒，访问 58 个端点、
  保留 160 条边、涉及 3 个 namespace；边预算触顶，仍未闭合。可核对的连续依赖路径及
  原条件保存在 `artifacts/current/queries/lewm-class-chain.json`。这不是值相同或可优化证明。
- **全范围 class 发布完成**：任务 `10f2bbe7f469444f9652e8b6cfc07484` 以 exit 0 / PUBLISHED
  结束，耗时约 51.23 分钟。862/862 units、2,306/2,306 类声明完成枚举，发布 1,065 bindings、
  400 parent shards 和 15 份共享 provider，class 索引压缩 9,542,932 bytes，不复制 suite。其余类声明是 285 个 stub-only、956 个父构造未展开；
  两者与 1,065 之和为 2,306。另 165 条父图不可用是父级缺口，不能再加进类分母。
  37 个已连接 suite 仍有残片；whole_program/effects_closed 继续为 false。
  `body_records_read=1659` 实际统计条目检查，包含没有 artifact 的条目，不是磁盘读取次数。

长任务未因观察超时重启；发布前 producer/current 冻结，终态确认后解除。部分 class 索引
缺失的原接口映射保留 CLASS_RELATION_INTERFACE_OPEN，不把空结果当枚举完整；已连接的
其它 parent 和普通 literal 不受无关缺口影响。相关 6 项检查最终通过；class 单项采用当前
publication 声明重新核对，9.49 秒，仍拒绝未注册旧 basis，没有降低输入校验。

上述时间均为分析器或验证时间，不是 LeWM 性能/加速比。目标未运行、未改动，未做
trace/profiling/benchmark、detector、planner 或 backend 工作。

## 尚需完成

1. 发布新版调用关系。已发布 class 的真实公开跨图查询已通过；先处理已定位的无 artifact
   预检和重复解码成本，避免直接重跑耗时整树；不放宽 schema/receipt/语义校验。
2. 补有限值推理残留的生产者契约、binding/容器读取和 module 初始化 L/G；不能删掉未知路径
   来伪造确定性，也不能把已有完备接口重复当作未知生产者。
3. 将调用、alias、逐地址 reaching writes、effects、常量/类型/Tensor 属性接入共同固定点，
   补齐各区域正常/异常/cleanup、逃逸及可观察效果边界。
4. 补主体结构：107 项模块后缀、8 项 deferred-child、45 项 class suite 后缀、其余规则缺口；
   23,614 个新依赖入口尚未派工。统一查询层不等于这些结构已完成。
5. 完成按需依赖闭包、库/native 契约及 CPU/GPU/DRAM/HBM/storage/stream 等资源关系。
   有 Resource 类型不代表已填实；此前抽查四份原图资源表仍为空。
6. 核对完整范围构建、保存、读回与跨层推理；未支持、预算和未定字段继续按实际范围报告。
   完成条件不缩小为小型检查通过或目录建完。

完整实施顺序见 [唯一计划](STATIC_ANALYSIS_PLAN.md)。第一阶段结束前不进入化简或优化。
