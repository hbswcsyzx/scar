# 第一阶段建模：实际状态与下一项

日期：2026-10-20。**OPEN：完整 LeWM 自动建模未验收。**

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
