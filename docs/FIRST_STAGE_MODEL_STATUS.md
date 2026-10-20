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
