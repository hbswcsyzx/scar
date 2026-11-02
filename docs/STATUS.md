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

## 本轮明确的问题、修复和下一步

当前不是缺另一套图格式，而是已有结构的关系/推理覆盖仍有缺口。按以下顺序继续：

1. **Observed / Implemented / Verified**：全范围 calls 曾被大主体派生索引反复淘汰阻断。
   缓存修复已生效于原大主体短核验；同一 corrected task 继续运行，尚未发布，详见下文。
2. **Implemented / Verified**：值分析已通过共同图消费原 BRANCH 的 CONTROL_CONDITION。
   完整固定点后才冻结无 unknown/MAY/外部 guard 的 builtin bool，并从原 seeds 重算；
   原边不删，schema2 新增 `branch_proofs`，保留选择及被排除路径的原证据。通用原 IR 中
   同一 callee 四个上下文分别得到 41、7、{41,7}、{41,7}，仅前两者产出证明；循环 widening、
   预算未闭合、外部 guard 和 INVOKE 均不冒充已选择分支。不是目标程序变换。
3. **Implemented / Verified**：共同图可导航既存 provider/native 原声明，含 native/core-only
   输入及所有正常/异常出口 Use、来源映射和逻辑端口 pair。使用 STRUCTURE、精确 locator
   和原 ID；默认遍历/cut 不把它们当值或实现传递，不制造多 Return 站点的笛卡尔积。
   current 的 class provider 样本内没有 ProviderEnvelope，不能拿它冒充此项真实 native
   验证；本项原声明导航用既有完整 IR 核验，真实材料验证如下。
4. **Implemented / Verified（实际安装材料）**：新增受限静态材料入口，复用已审计的
   torchgen FunctionSchema parser 与纯 Python SafeLoader，核对原 header/YAML、完整
   overload、版本、文件/字节/行和工具收据。`-I -S` 隔离、禁 torch/目标导入，默认值只
   保存原文；不运行生成器。6 个实际 overload 已构造现有 ProgramGraph/NativeBoundary，
   共 18 个操作，压缩图 15,734 bytes，抽取/构图/读回约 1.788 秒；这是静态分析器成本。
   机器材料、6 个独立接口分片及共同图查询存于
   `artifacts/current/queries/native-static-model/`，`summary.json` 明确它们尚未发布到
   current 整程序、Python binding 未建立、whole_program_complete=false。
5. **Observed / Proposed（下一步连接）**：安装包确有 `to`/`copy_` 的完整手工 Python
   binding 模板，可沿方法表→参数 parser/override→C++ wrapper→`_ops` 精确 overload
   建立有条件关系；`empty`/`expand` 的具体生成 Python binding 成品未提供，stub 与生成
   规则只能给候选。Python `to(other)` 先提取 device/dtype，可能调用 to.device 或直接
   返回 self，不能按同名或 stub 位置猜 ABI。下一步实现通用材料/转换连接，不按例名写规则。

上述新增语义合并短核验 **4 passed / 4.43 秒**，未重跑大源码 fixture。新 native 接口保留
opaque world 和可能正常/异常 completion，alias/write/dispatch 为声明，resource/实际
copy/allocation/kernel 与 effects closure 均未证明。第一阶段仍未完成，未进入化简。

后续进展：共同控制图已把原 CFG entry-edge dominance 必要选择扩到非循环 block，
与可能 postdom 影响分别保存；只保留最近必要选择，沿 controller 继续追踪，避免图中
物化全部祖先及逐 block 二次爬链。循环/未知 INVOKE 的终止性仍 open。原控制综合短验
**1 passed / 1.00 秒**。真实 `cem.py:276` 的原 TRUTH.NORMAL→BRANCH 必要关系已在
共同图读回：32 访问端点、64 CONTROL 边、1 条直接 exact 必要前提，冷查询 15.532 秒，
端点预算/效果/终止性前沿仍在；机器记录为 `artifacts/current/queries/lewm-control-necessity.json`。
TRUTH 以原 structured.protocols 合同定位，该操作的 source role 实为 EXPRESSION，不能
仅凭 role 标签判断行为。此为静态依赖核验，不是分支删除、完整闭包或目标加速比。

C++ 前端选型已做真实最小实验：SCAR 私有工具环境 19 MiB，未改 LeWM 环境。原 template
解析返回正常，但该版本 Point.row 属性遍历可 exit139；已隔离定位，未调整全局环境。
改用原字节偏移定位后，两次完整结果一致：7,955 CST 节点、83 个函数、6 个 ERROR、
0 missing，原文件和工具都有收据。证据保存在 `artifacts/current/queries/cpp-front-end-probe.json`。
这些是源码输入层验证，不是已接通 C++ 类型/ABI/重载/binary；完整方法表关系 reader 正在实现。

正在修复值分析 normal/raise slot0 路由，并补原 TRUTH 合同推理。最小源码实验还发现
编译器常量折叠的 If 仍被前端 REQUIRED_EXPANSION 阻断；必须后续补静态展开，不能把
编译产物里没有对应指令误称为源码信息必须动态获得。producer/current 冻结期间不改 lowerer。

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
| 所有主体产物 / 无产物声明 | 8,819 / 27,345；产物含 326 unsupported 与 404 shape 拒绝 |
| 规范操作 | 1,262,346 |
| lowerer / shape 不支持 | 326 / 404 |
| 缺独立适配 / 新单位未派工入口 | 3,731 / 23,614 |
| 当前调用索引 / class 接线索引 | calls 未发布；class 已发布 1,065 bindings、400 parent shards、15 共享 provider |
| 压缩分片 | 14,927 个，2,409,074,599 bytes |

清单已去掉重复诊断数组：逐份核对 8,415 个带诊断的 body artifact 后，改为原分片内 count/pointer 引用。
当时 manifest 从 153,148,270 降到 35,455,247 bytes（减少 76.85%）；原图/源码分片字节与原 ID
未改，原声明指针和证明输入投影不变。处理 28.017 秒、8 个有界 worker；这只是分析器
存储整理，不是目标程序加速。旧 inline 格式仍可读回；未有可核对原分片的诊断不删除。随后新增 class 索引元数据，当前清单为 36,669,534 bytes。

新一轮沿原 import 关系，自动把 264 份外部 Python 源码、16 份 stub 送回原前端，共 280 个正常 units；新源层没有读取或构造失败。阶段记录的 analyzer_seconds 为 207.190 秒，8 个进程；该字段在随后材料刷新前记录，不能当全过程 wall-clock。原 source/canonical 分片没有重建或改写。

`--inventory-dependencies` 定点盘点材料，`--expand-dependencies` 将材料送回现有前端并更新全范围索引。原 import/material 证明输入内容寻址去重，作为当前图的必要依据保留，不保存旧 checkout 或旧 manifest。源码、stub、native 和 namespace 候选以及运行选择条件分别保留，不把找到文件算成已证明实际 import。

扩展后有 42,074 条 import 关系、9,843 个模块查询。本轮材料刷新只处理 4,096 个，5,747 个是明确预算未处理；不能当作不存在。当前仍有 725 份外部源码和 135 份 stub 候选待处理，依赖闭包未完成。材料盘点的 external_source_analyzed=false 描述盘点步骤本身；前端已分析的新增单位另见 dependency_expansion。

当前保留 37 条早期 BrokenProcessPool 的 unit/body-worker 记录；对应样本主体后来已有规范图。这是遗留问题记录，不是本轮 280 份源码新增失败。其终态归属仍需统一，不以 summary 的旧零计数掩盖。

## 新一轮实现：初始化状态与模块源码展开

- **Implemented / Verified（通用静态案例）**：v8 显式 import 初始化条件与精确 `{L,G}`
  owner 域，联合选择 writer/kill，并在原输入上 fresh replay。源码 G 写、L 写的双向覆盖、
  任意 exec 独立 owner、篡改拒绝和 v7 不获升级都已核查。真实小源码保存 A 函数后替换
  module 字段为 B 函数，共同图及同一值队列分别推导 11/22；其条件与其它未闭合项保留。
- **Implemented / Verified（原源码静态重建）**：修 compiler prelude 与首 import 共用 span
  导致的错误阻断，并补 module Global 的编译期零操作展开。`envs/utils.py` 从 0 条推进至
  7 条 import（164 ops），`callbacks/registry.py` 从 0 条推进至 5 条 import 和 Lock 调用
  （224 ops）；独立结构读回通过。剩余分别为第 11/9 行 AnnAssign，未隐藏或算作已展开。
  此为新鲜重建验证，尚未替换 current 的原主体，原 107/45 suffix 分母不改写。
- **Implemented / Verified（调用派工）**：没有 body artifact 的单位先核原 lexical receipt，
  保留原声明、范围、候选和按需 source context；无 MODULE canonical 时不提前解完整上下文。
  单条静态检查同时验证 census、后续按需定义/签名可用和目标未执行。新增 session cache
  hit/reread 字节统计；function-environment typed 输入在同一只读会话内有界共享，不缓存跨输入 PASS。
- **Observed（实际输入）**：当前 8,819 份主体产物、581 个有产物单位；另 264 个完整 source-only
  Python 单位与 17 个 stub。按新版 reader 的 stored+decoded 计费，单次冷 seed 下界
  **19,471,402,455 bytes**，尚不含按需材料及缓存重读。原默认 8 GB 必然不足，不能再把
  预算未处理写成源码未知；CLI 已提供 `--max-link-input-bytes/cache-bytes/seconds`。
- **Verified（相关合并检查）**：source-only seeding、初始化状态与 compiler/class 构造三项
  合并通过，16.03 秒。没有重跑原长 G 综合；只同步其 v8/旧 fixture 兼容约束。

第一次 v8 全范围任务 `5999061b31aa4e74b797e03ac6fadd15` 已由 Root **有原因地取消**，
终态 INTERRUPTED / exit130，3,319.5 秒，已进入 1,909/8,819 artifacts。不是观察超时：
原 65,027,047-byte body 超过写死的 64,000,000-byte 派生缓存，每次构造即淘汰；终止栈
确实落在 `_index` 重复 metadata decode/hash。取消前未发布，已验证 current SHA 不变；
未发布内存事实需要重算。此任务 PID 与监控均已退出，没有杀其它进程或改 LeWM。

已修复：派生缓存服从显式 session/record 预算，复用 loader 的已校验 typed metadata/module；
单体超过缓存预算会在构造前显式拒绝，不再构造后立即丢弃而反复重算。相关 public reader
使用其会话预算，默认独立 reader 上限 256 MB。原输入和 namespace/source 检查保留。
同一原 DINOv3.forward 主体新冷读/校验 29.079 秒，连续索引查询 0.047 秒，属性收集
0.129 秒，1 次 build / 732 次 hit / 1 次 metadata reuse，83 个读接口。机器证据保存为
`artifacts/current/queries/module-index-regression.json`。这不是完整上下文工作队列或目标加速比。
相关初始化/派工/小 IR 合并 3 项通过，8.34 秒。修复已提交/推送 `38b06e42`。
修复后的整范围任务已实际启动：task `22e44842ba63409b97867674ac6da292`，PID 51564、
start_ticks 2075508、Root handle 52351；身份已核对 RUNNING。保持 862 units / 8,819
artifacts 分母和 128 GiB input、8 GiB cache、7,200 秒预算；producer/current 重新冻结。
旧任务不是因观察超时重启，新任务尚未发布，不能宣布整范围调用或第一阶段完成。

同一 corrected task 在 1,857.3 秒已推进至 **1,958/8,819 artifacts、unit210**
`methods/maskfeat.py`，确认越过旧 unit204/body18 的具体阻塞点。此为实际全范围运行中的
进展证据；仍 RUNNING，不能把越过单个热点当作整批发布成功，也不以不同运行计算加速比。


共同查询会话新增按 namespace 的 shard 元数据邻接索引，不再每端点扫描/解码所有 header。
class 短检查通过（9.53 秒）；同一 current LeWM 三层查询的新旧规范化节点、边、条件、
证据与前沿逐字段相等，本次查询 5.561 秒。先前 9.065 秒与本次系统状态不同，只是成本
样本，不据此计算 LeWM 或分析器加速比。索引为会话内派生结构，不是第二份程序图。

共同值分析新增独立 immutable_tuple 字段（report schema 2），支持原 tuple 构造、跨层
参数/返回和 int/bool/负索引；保持 literal 位模式，不保存 Tensor 数值。原静态源码已推导
`(4,(8,16))`、嵌套索引 16、bool 索引 3；未知/覆盖/mutable/越界反例仍保留前沿。
READ_CODE_CONSTANT 复用原静态编译证据并保持 active-code 条件；编译缓存限 4 units，
按源码与 CodeType/co_consts 闭包计量上限 16 MiB，不是分析进程 RSS 限制。扩展原集成
2 项通过（47.61 秒），最终小 IR 类型边界与 MAY/N/A 未知路径检查通过（0.95 秒）。

声明导航补齐 EnvironmentInterface 成员/状态域与 ControlPort 的原 block/具名 exit；
原精确 locator 与上下文保留，不造 scope/exit ID，不把声明/结构边当身份或实际 transfer。
区域、v8 初始化和小 IR 值分析合并 3 项通过（9.65 秒）；native/provider 其它关系欠账仍保留。

长计算热点的进一步诊断仅作用于分析器：原记录约 65 MB（metadata 约 37 MB），
15 秒限时 core decoder 探针显示递归 record_errors 有明显成本；另一采样分离出 core约11.6秒、
metadata约4.5秒、index再校验约6.8秒。它们不能解释二十多分钟反复重建；精确 cache-thrash
控制流和取消时调用栈才定位了本次根因。外部调试附加不可用，未修改系统权限。

## 已有统一图的核验

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
   预检和重复解码成本已修，corrected task 持续运行；不放宽 schema/receipt/语义校验。
2. 补有限值推理残留的生产者契约、binding/容器读取和 module 初始化 L/G；不能删掉未知路径
   来伪造确定性，也不能把已有完备接口重复当作未知生产者。
3. 将调用、alias、逐地址 reaching writes、effects、常量/类型/Tensor 属性接入共同固定点，
   补齐各区域正常/异常/cleanup、逃逸及可观察效果边界。
4. 补主体结构：107 项模块后缀、8 项 deferred-child、45 项 class suite 后缀、其余规则缺口；
   23,614 个新依赖入口尚未派工。统一查询层不等于这些结构已完成。
5. 完成按需依赖闭包、库/native 契约及 CPU/GPU/DRAM/HBM/storage/stream 等资源关系。
   已有实际 native 材料/接口验证，尚缺 Python callable/参数转换到 native 实现的通用连接。
   有 Resource 类型不代表已填实；此前抽查四份原图资源表仍为空。
6. 核对完整范围构建、保存、读回与跨层推理；未支持、预算和未定字段继续按实际范围报告。
   完成条件不缩小为小型检查通过或目录建完。

完整实施顺序见 [唯一计划](STATIC_ANALYSIS_PLAN.md)。第一阶段结束前不进入化简或优化。
