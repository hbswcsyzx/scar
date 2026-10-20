# 独立对象身份与准确 marker 参数对应

日期：2026-10-20。实现提交：`448b912`。
**本组件验收通过；完整程序建模第一阶段仍 OPEN。**

## 解决的实际缺口

旧 ValueGraph 只能通过 ObjectBinding 登记对象，强迫元数据观察附带内容版本。
现在 ObjectInstance 独立拥有 Python 对象身份，旧 binding 保持内容关联。没有
添加优化规则、detector、backend 或替代程序图。详见
[原生模型文档](../../../docs/NATIVE_OBSERVATION_MODEL.md)。

本次只读取已归档真实 CPU 实验
[`first_stage_marker_probe_20261020`](../first_stage_marker_probe_20261020/)，
没有重跑 LeWM、forward 或 GPU。原实验执行了 view、重复参数、原地写入和有
梯度的运算；本次验证的是引用桥重建，不能由此声称生产 trace 已自动采到该桥。

## Observed / Implemented / Verified

| 项目 | 实际结果 |
| --- | --- |
| marker / Python Tensor 对象 | 10 / 6 |
| 新的逐槽对象—provider 引用对应 | 12，保留双侧原始 locator |
| 重复实参槽 | 2，未去重合并 |
| 发明的 logical version / allocation | 0 / 0 |
| 原生 provider input/output 引用边 | 43 / 17，仍不是内容 producer |
| 图版本 | Values2 / evidence6；旧能力仍输出旧版本 |
| 直接 Python→ATen / state effect / ready | 均未证明 |
| 对应的证据状态 | Inferred，受 supplied research capture 合同约束 |
| GPU/transfer/timing | 未提供 Kineto，明确 ETO-only gap，不能推出零活动 |

`replay.py` 用产品 adapter 重建；`audit.py` 仅用标准库，从 raw 文件逐槽核对
全部12条边、对象 owner、重复参数及无虚构内容；`roundtrip.py` 用公共 codec
读回实际产物。canonical bundle SHA256：
`3ab343cd0aa34dff30dd15321ce13f8a5733bd3a8f730b67eab98d0df9c06d0c`。

adapter 加序列化内部 wall 0.040742秒；完整离线 Python replay 0.24秒、
peak RSS 25,480 KiB；独立审计0.05秒、17,964 KiB，均 exit0。
这是小型 CPU 元数据处理成本，**不是 LeWM 性能或加速比**。

## 测试与失败保留

| 记录 | 结果与范围 |
| --- | --- |
| tests-core | 165 passed / 3.24s：对象目录、旧 IR/codec 和 native |
| tests-bridge | 119 passed / 150.70s：既有 content/source/resource/identity；随后补的 locator/缺槽边界在下一批验证 |
| tests-owners-initial | collection error：测试从错误模块导入 EvidenceKind，已修正；生产代码不受影响 |
| tests-owners | 62 passed、1 failed / 12.31s：测试预期遗漏 `resource_` 诊断前缀，实际正确拒绝未知对象 |
| tests-owner-fix | 该失败案例修正预期后1 passed / 1.03s；没有放宽生产校验 |
| tests-cli-final | 最终 CLI/profile/缺少必要 sidecar 拒绝案例1 passed / 1.52s |

各批有重复，不相加为总数。错误和失败日志保留。正例覆盖无版本的对象 owner、
引用桥、JSONL 原物理行号及 CLI；反例覆盖 schema 降级、重复/缺失 marker、
缺槽/坏 descriptor、不同进程、snapshot、重复 path、缺 phase、伪 direct
context、预算和 snapshot 变更。未知对象仍失败；引用不授权内容推导或优化。

## 复现与下一项

在开发工作树 `conda activate lewm`，设置 PYTHONPATH 为工作树根目录，运行
replay/audit/roundtrip。replay 排他创建输出，不能覆盖当前归档；再次实验应
使用新目录，并保持同一 source capture。公共 CLI 参数见模型文档。

Proposed（仍属于第一阶段）：研究 collector 改有界公共引用/context接口，
补 session/thread、预算/丢失、异常收尾，再验证 mode/subclass/线程边界；保存
现有 source semantics/CFG 并接有序 use/当前状态；闭合 OS/CUDA 资源寿命、
物化/就绪及输出依赖。源码旧分母和缺口不变，不用本组件 PASS 替代全程序验收。
