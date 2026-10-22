# 第一阶段建模：实际状态与下一项

日期：2026-10-20。**OPEN：完整 LeWM 自动建模未验收。**

### 2026-10-22恢复状态

注解/异常/断言也已接线并直接回查真实源码：19文件/24个原阻塞body，
4个局部成功、20个仍拒绝、0错误，60.15秒；下一缺口主要JoinedStr12、Dict6。
产品75fc24d，见[记录](../artifacts/experiments/first_stage_statement_blockers_20261022/README.md)。
与下面90-body诊断均为独立范围，未另报全量新覆盖率，未扩大测试。

随后的真实阻塞回查已完成：从上述环境inventory机械选出66个写入、15个BoolOp、
9个IfExp，31文件/90body中**37个成功局部展开、53个继续拒绝、0构造错误**。
新增receiver/key源接线和短路控制使用原canonical图，未扩测试；两分多钟完成。
这是独立cohort预算，**不能直接与全量54相加**。代码2b805c2及逐项图/下一断点见
[真实源码回查](../artifacts/experiments/first_stage_source_blockers_20261022/README.md)。
当前优先剩余解构、异常、声明、import及复杂目标表达式，运行state/resource闭包
仍未完成；下一动作继续第一阶段建模，不进入优化。

最新真实 environment inventory8 已生成（产品545fa4c）：同151文件/原raw/
256尝试/10000op预算，54个局部图、202个UNSUPPORTED、1961个NOT_ATTEMPTED；
core/source分组34/425。原45个环境拒绝只有3个最终成功，25个继续卡heap写，
其余展开到新的语言/slot阻塞；逐条记录及独立全量标准库比较已保存。
见[环境接线实际报告](../artifacts/experiments/first_stage_environment_inventory_20261022/README.md)。
本轮未另跑完整public重放或扩展测试；whole-program、runtime环境actual、细状态、
逻辑来源和资源闭包仍未通过。下一项按新66个首个写阻塞和15/9个BoolOp/IfExp
补真实来源与控制路径。以下是此前同日结果；不以它们覆盖最新数值。

临时开发目录已不存在，旧查询session和相关进程均不存在，未提交的10月20日
source-layer归档/日志不能作为当前可复核证据。Git提交保存了三图留存/复用及
expression→statement上下文代码（`ccf6cac`），已恢复到持久worktree
`~/AAA/scar-worktrees/structured-program-model`。不改LeWM或原SCAR checkout。
本次17项通用source-context/source-layer/CLI测试通过；全LeWM库存重建与独立
查询核验另见[本次报告](../artifacts/experiments/first_stage_source_context_20261022/README.md)。

现已实际完成原151文件三图恢复与全10,235调用查询，原snapshot/三摘要全部匹配。
9,116个调用有结构语句上下文，1,119个未连；原exact-CALL-ID匹配语句CFG为0。
独立标准库审核全量PASS，核63,541条operand、82,299条结果producer和78,691条
控制边；第一次审核的lambda phase误判及修正原样记录。这些只是源码结构关系，
不等于动态值、状态或资源因果闭包，缺口并未因新增边而自动消失。

公共`inventory-program --body-profile structured`已接原structured前端并输出显式
inventory7（默认及旧1–6不变）。66项相关新旧测试通过；同LeWM入口/raw calls/
source/预算的实际重建得到51个局部图、205个UNSUPPORTED、1,961个NOT_ATTEMPTED，
code/source分组接入33/425，仅比旧baseline增加1个body和1组。独立比较通过；
公开check-inventory完整raw/source重放也已REPLAYED（exit0，645.19s），并非
只读摘要或只验证声明。参见
[公共structured实际验收](../artifacts/experiments/first_stage_structured_inventory_20261022/README.md)。
接线提升很小：closure环境45、heap写41、expanded call15、BoolOp13、IfExp8等
仍造成整body回滚。不能把481条语言protocol或source图规模当完整模型完成率；
下一项按这些实际语言/接口断点排序，实际状态/来源/资源闭包仍未完成。

### 环境接线前的实施计划（已执行，保留历史）

优先**自动函数环境入口及cell/namespace依赖**，不预定下一项就是短路表达式。
这补全部函数的隐式输入断口，复用既有EnvironmentInterface、FunctionEntryLayout、
ReferenceOwner、CellContent/NamespaceKey和canonical Uses/state；不新增环境图。

1. 以symtable分类，复用已有准确compiler/source见证取得co_freevars/co_cellvars及
   顺序；不能按变量名或自行排序猜closure tuple。隐式编译器依赖也需保留。
2. 在原入口ReferenceValue/StateVersion参数中声明五个固定环境role及captured
   cells；被调用body的free-variable slot与外层formal slot独立，实际alias允许。
3. freevar读连cell引用owner和CellContent，global/builtin读连准确namespace；
   每条正常/异常路径携自己的后态。不能删除freevar guard后退回普通global读。
4. 新source profile复用既有入口完整分区检查，替换固定formals+world和index+1
   actual假设；旧SourceProgram3/inventory7按V1固定重放，不静默重释旧产物。
5. 单独采集当前callable及环境actual身份。现monitoring CALL可拿到callable，
   旧calls-only及f_locals只给code/内容，不能补造函数对象或cell身份。静态参数化
   依赖通过与动态actual闭合通过分别报告；不以静态入口存在称动态已连接。

验收先用普通Python testcase自动恢复：同code的两个closure、多个函数共享cell、
cell被改写/删除、global/builtin重绑、代码版本/环境不符及错误cell顺序。测试不手
补IR；同时检查真实LeWM每个旧环境阻塞body的环境连接与下一终止点。**45个首个
环境拒绝不代表下一轮必新增45个成功图。** 随后同范围、同预算重建并记录结果。

再按证据补owner明确的attribute/subscript写、失败后态/释放与source slot对应，
destructuring另验。之后补BoolOp/IfExp的取值/条件上下文及expanded calls，禁止
多执行truth或预执行未选分支。实际Uses/逻辑来源、OS/CUDA资源和ready/输出闭包
继续使用原S3/S4合同，不因完成某语言子集而进入化简。

旧说明中CALL的同ID直连语句CFG建议已撤回：同ID类型不等于同粒度，parent_id也
不是AST父节点。新查询按源码指纹、完整AST字段路径和scope关联原语句，保留
短路、默认值、延迟body等边界，不宣称表达式必执行。S3/S4仍OPEN；原50个局部
typed body、206个UNSUPPORTED、1,961个NOT_ATTEMPTED未因该连接而增加。

设计仍按[合同实体表](FIRST_STAGE_MODEL_CONTRACT.md)：代码来源；Operation/Value/
StateLocation/Region/Resource规范结构；运行occurrence与对象/环境；逻辑内容版本/
来源；allocation/view/materialization；work/completion及证据。类型、角色和动作
标签不混在一层。下一步补实际源码→core恢复、Uses/状态与资源生命周期闭包；
不进入detector/backend/化简或性能A/B。以下保留10月20日已入库记录的原范围。

最新增量：独立 ObjectInstance 目录及准确 marker 参数引用桥已落地（`448b912`）。
重放真实 CPU 原档，得到6个对象、12条逐槽对应、保留2个重复参数槽；独立 raw
审计通过，没有制造 LogicalVersion/allocation。此为有条件的研究 profile，不是
生产 Python→ATen 对应，也没有改善原源码覆盖分母。实际报告见
[对象引用验收](../artifacts/experiments/first_stage_object_reference_20261020/README.md)。
下一项仍是生产采集/来源状态连接和资源闭包，不能开始化简或性能 A/B。

范围及验收由 [第一阶段合同](FIRST_STAGE_MODEL_CONTRACT.md)接管。旧协议组件
报告保留原有限结论，不再作为下一项任务的自动选择器。F20 未开始实施。

## 本轮已确认

- 开发分支 `codex/structured-program-model`，起点 `221819f`，使用隔离 worktree。
- LeWM 原仓库 clean，未修改目标、conda 或 CUDA；本轮暂未执行新的 LeWM/GPU run。
- 现有五类规范结构有基础，但完整身份清单还包括代码、运行 occurrence、对象、
  内容版本、分配/表示和证据；只有分类表不能验收自动建模。
- `inventory-program` 默认 BOUND_FRAME_V1；函数体检查对 for/import/try/with 等
  尚拒绝；structured profile 可单独处理部分循环，但没有接入公共 inventory。
- 历史真实 inventory 的 151 文件/2,217 定义只有 50 个带缺口的局部 body，
  206 UNSUPPORTED、1,961 NOT_ATTEMPTED；这些是旧产物，不是本轮重建结果。
- 现有资源 sampler 采 CPU/GPU 抽样，不等于文件/mmap/queue/allocation 等自动资源模型。

## 执行顺序

1. 只读审计程序模型、自动前端和资源对应，冻结清楚的 S1 设计。
2. 原 LeWM 入口自动生成 S2 当前覆盖清单，对照旧归档确定真实阻塞。
3. 优先接通已有结构和 provider；每项修改必须改善真实端到端必需覆盖。
4. S3/S4 未完成时不添加 detector/backend，不宣称第一阶段完成或报告新加速比。

本文件后续追加命令、结果与失败，不用单元测试数换算程序完成率。

## 只读审计结论

见 [自动化审计](FIRST_STAGE_AUTOMATION_AUDIT.md)。两个独立审查确认：主要缺口
是自动 source lowering、同次证据到规范模型的适配、资源/输出因果闭包。
source atom 归属已经保留，不能称整个源码结构完全没有；typed body 遇单个
unsupported 会整体回滚，才是待修的具体损失。calls recorder 仍持有 profile
hook，不能与 inject 整体简单叠装；ETO 的执行表示也不能当作原静态定义。

第一阶段合同已补先固定 mandatory/required_expansion 的要求：完整原生接口
不等于 native 内部已展开；实际涉及的资源不能通过缩 scope 从分母消失。

## 当前版本真实自动重建（Observed）

起点产品代码 `221819f`，conda `lewm` / Python 3.14.7，使用旧真实成功运行的
原始 calls trace，**只重新分析，不执行目标**。运行脚本和全部产物位于
[`first_stage_model_20261020`](../artifacts/experiments/first_stage_model_20261020/)。

| 项目 | 当前重建结果 |
| --- | --- |
| 自动 source 文件/定义/源码调用 | 151 / 2,217 / 10,235 |
| body | 50 LOWERED_WITH_GAPS / 206 UNSUPPORTED / 1,961 NOT_ATTEMPTED |
| 全 source atom 分母 | 122,323；682 CONNECTED / 107,351 INVENTORY_ONLY / 14,290 UNSUPPORTED |
| 可用运行 code/source 分组接入 | 32 CORE_LINKED / 393 INDEXED_WITHOUT_BODY，共 425 |
| 已索引 scope 类型 | 1,636 FUNCTION / 301 CLASS / 253 COMPREHENSION / 27 LAMBDA |
| 未尝试原因 | 1,380 受构图预算限制；581 需要 class/lambda/comprehension 接口 |
| discovery 缺口 | 1,083 |
| 分析成本（不是 workload 性能） | 636.94 秒 wall；358,460 KiB peak RSS；exit 0 |
| 完整程序/细状态模型 | 仍为 false；没有完整资源模型产物 |

现有库存生成与独立记录重计数均成功，历史与当前结果的主要覆盖计数完全相同。
这不是完整模型验收 PASS：CONNECTED 只表示 source link，不表示完整依赖；当前
预算保留了所有未尝试项，没有把 256 次尝试当成全部 2,217 个定义。

**下一实施项：** 固定这份真实分母；统一 Python call/operand 与原生 ETO/Kineto
采集的生命周期及准确来源，再接规范端口/资源。同时按真实阻塞补 typed source
恢复，避免整 body 回滚。不先做 F20，不新增 detector/backend；S3/S4 仍 OPEN。

## 同次采集的有限实现（Implemented / Verified）

`trace --call-operands --execution-evidence` 现可保持原 Python hook，同时延迟
启动原生 ETO/Kineto，不重跑目标、不采 Tensor 数值。5 个真实新 CPU 集成测试和
33 个旧 CLI 回归通过，共 38；具体范围见
[采集说明与验收](FIRST_STAGE_NATIVE_EVIDENCE.md)。这只解决采集共存，尚未做
完整规范图导入，S3/S4 仍 OPEN。下一项是原 LeWM 同配置真实采集及 OS 资源对照。

## LeWM 同次真实采集（Observed / Verified，非整模型通过）

产品 `1650431` 使用原 pusht checkpoint、单 episode、budget/goal offset 25 命令，
conda lewm / Torch 2.13.0+cu132 / CUDA build 13.2 / RTX 4090。
**exit 0，success_rate=100.0**；302.0469 秒为 instrumented wall，不是 clean 性能。

| 自动取得的证据 | 实际结果 |
| --- | --- |
| Python entries / records / code descriptors | 84,315 / 168,630 / 851 |
| ETO 节点 | 151,228 |
| ETO→Kineto 正 RF ID/名称唯一匹配 | 151,226，重复正 ID 为 0 |
| GPU kernel / 物理 memcpy / memset | 22,457 / 543 / 1,082 |
| GPU activity→runtime correlation | 上述活动在本 capture 均有唯一匹配 |
| OS 记录 | 253 个逐 TID 文件，705,569 行；含启动器/采集器及后代 |
| 外部输出 | 实际生成本地 mp4 和结果文件；OS 中见 ffmpeg/libx264 与文件写/关闭 |
| 正常采集收尾 | provider CLOSED、failures=[]；call/operand dropped=0 |
| 如实保留的缺口 | 945 operand gaps、65 unknown exits；没有把零丢失称为精确建模 |

第一次无 seccomp-BPF 的 strace 开销过高，停止监督器后未正常收尾，判 FAILED。
完整失败记录保留，未当作 LeWM defect。验证轻过滤后完成第二次采集，目标源码、
数据和环境未修改。详见 [实际结果与原始证据](../artifacts/experiments/first_stage_lewm_capture_20261020_bpf/README.md)。
约 610.6 MB 生成元数据经逐文件字节哈希验证后无损归档为约 41.1 MB；未存 Tensor
逐轮数值、未清共享缓存，未删除用户数据。

**第一阶段仍 OPEN：** 原 source inventory 的 50 个局部图没有因此变成全程序图。
尚缺 source 内部自动恢复、准确 Python→Torch 有序端口/当前状态/逻辑版本，以及
OS/CUDA 资源身份、生命周期和输出因果闭包的规范连接。下一项只落实这些自动
建模适配与源码结构复用，不开展图化简、candidate 或 backend。

## 原生观察的自动建图（Implemented / Verified；全阶段 OPEN）

`fdae346` 的通用 `import-native` 已离线处理上述真实 LeWM ETO/Kineto，输出
205,424动态记录、429,336条边；357,090有序引用槽、151,226 RF对应和24,082
runtime→GPU关联经独立标准库脚本对原始字节重放通过。保留5,593个provider引用
编号，**没有据此生成内容版本**。3个设备/流选择器也没有被当成已知生命周期。

入口、实体边界见 [原生观察模型](NATIVE_OBSERVATION_MODEL.md)，实际命令、测试、
首次CPU输入失败和修正、分析成本见
[实验报告](../artifacts/experiments/first_stage_native_import_20261020/README.md)。
本次只使用已有捕获，不重跑 GPU，不改变源 inventory 的分母。

**当前具体断点：** 30,007条runtime的External id尚未建立经来源核验的CPU对应；
Python occurrence/源码CFG、非Tensor完整端口、当前状态/逻辑版本与OS资源闭包
仍未连接。下一项核验provider关联合同并接已有调用来源证据，不扩detector/backend。
完整程序建模仍未验收，不能把本次原生观察图当作最小依赖程序或报告新加速比。

## CPU→原生 scope 对应已接通（Verified；不代表源码或数据身份已接通）

随后核验固定Torch/Kineto官方源码，并机械导入54,089条provider scope关联：
30,007条runtime/driver、24,082条GPU活动。真实图现在205,424动态记录、483,425边。
独立差分审核核对全部新增关联及原有图不变；7条未报告scope的runtime仍不补猜。
见 [原始源码、命令与验收](../artifacts/experiments/first_stage_native_scope_20261020/README.md)。

这解除上一段的External id合同缺口，**没有解除Python occurrence、logical/state、
source内部恢复和OS资源生命周期缺口**。下一桥先做准确带实参marker的CPU实验，
不按_cdata/shape/名称猜对应，不用测试数或图规模宣布全阶段完成。

## Python Tensor对象桥原理实验（Verified；生产桥尚未实施）

同一provider带Tensor实参marker已在独立CPU testcase中验证：5次dispatch、
10个marker、6个weak token，可按nonce和有序槽机械连接到ETO编号；重复实参、
view、原地写与梯度均检查通过。真实marker直接parent是PythonDispatchMode包装
scope，未按opname猜原ATen；Python上下文也保留包装调用链，未强并InvocationID。

详见 [实验、首次审核失败和后续门槛](../artifacts/experiments/first_stage_marker_probe_20261020/README.md)。
这仅验证准确连接原理。下一实施项是有界生产桥、所有权/异常/foreign mode验收；
之后才重新采LeWM。source内部/状态/资源闭包依然OPEN，继续第一阶段。
