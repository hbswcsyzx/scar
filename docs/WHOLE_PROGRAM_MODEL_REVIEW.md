# 完整模型规格审查与验收边界

日期：2026-10-16。当前判定：**控制/身份/资源接口规格完成本轮一致性修订；
整个模型的代码实现、逐构造规则及自动全程序图仍未完成。**

## 1. 本轮修订的实质问题

| 原缺陷 | 现在的规范接口 |
| --- | --- |
| 四类 ProgramGraph 被误认为完整模型 | Resource 在完整模型独立；旧图只是控制/数据投影。 |
| Suspend 混成函数完成 | LanguageOutcome 分 Complete 与 Suspend；恢复有实例/代次。 |
| 静态控制目标混为动态 activation | Program typed target 与 Execution occurrence binding 分开。 |
| completion overlay 另存 post-state | 后态只经 canonical StateVersion/边参数传递。 |
| Requirement/Definition/Instance/handle 混合 | requirement 是约束，handle 经关系连接资源；实例有生命周期。 |
| 两套 value 身份未接通 | ValueID → occurrence → denotation，引用内容由当前 StateRead 确定。 |
| provenance 混合值和 copy 关系 | ValueDerivation / RealizationDerivation 分开，避免自环；lineage 允许分叉。 |
| environment/ready 缺接口 | 显式隐式环境、ControlPort、WorkTicket、消费可见范围与 generation。 |

正式规格：[WHOLE_PROGRAM_MODEL.md](WHOLE_PROGRAM_MODEL.md)。独立审查保留原
问题及修订复审，不用最终 PASS 覆盖原始缺陷：

- [控制模型审查](../artifacts/experiments/b1_call_operands/model_connection_audit/whole_program_control_model.md)
- [规格一致性复审](../artifacts/experiments/b1_call_operands/model_design/WHOLE_PROGRAM_MODEL.review.md)
- [值/资源审查](../artifacts/experiments/b1_call_operands/model_design/VALUE_RESOURCE.review.md)

## 2. 自动检查的准确范围

[检查脚本](../artifacts/experiments/b1_call_operands/model_spec_check/check.py)在实际
conda lewm/CPython 3.14.7 运行，结果保存在
[report.json](../artifacts/experiments/b1_call_operands/model_spec_check/report.json)。

它执行两类检查：

1. 从本机 AST 反射具体构造及 fields，核对协议清单没有遗漏、重复或多余项；
   记录版本、构造清单和文档 hash。这是**清单守恒**，不是逐字段求值规则验证。
2. 独立执行普通 Python 反例：finally 改写完成、return 引用后态、with 抑制、
   generator 创建/恢复/返回、共享 cell、不可达赋值的 scope、WAR、copy dispatch、
   view 内容更新、文件/dup offset、常量 import 初始化。它们约束规格，**没有
   调用 SCAR lowerer 或解释其图**，不冒充图实现验收。

本机首次检查：**113 个 canonical 构造、19 个协议族，无遗漏/重复/多余；
11 个独立 Python 案例通过。** `finally` 改写 return 的刻意反例在本版本产生
预期 SyntaxWarning，原 stderr 保留；这不是产品测试失败。

所有检查都不授予 transformation authority，也不验证 GPU readiness。局部
Markdown 文件链接一并核对，以便报告可审查；这不代替模型验收。

## 3. 没有通过的门

本轮规格一致性审查不能关闭下列工作：

- M1：新类型、ports、规范表和组合 validator 接入现 core。
- M2：每种构造的逐字段 phase/求值顺序/隐式调用/完成规则及独立验证。
- M3—M5：完整自动建图、运行对应和从输出观察根回溯全过程依赖。
- M6：具体化简指导、正确性及成本验证。

已有有限同步实现的 2,657 项测试和固定候选压力另见
[N2_STRUCTURED_BODY_ACCEPTANCE.md](N2_STRUCTURED_BODY_ACCEPTANCE.md)。这次文档
修订没有重跑 GPU workload、增加 detector/backend 或修改 LeWM。

**整体模型仍未完成。** 下一步先落实 M1/M2，而不是沿用旧模型继续增加候选。
