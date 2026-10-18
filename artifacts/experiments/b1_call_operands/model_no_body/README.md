# D2.2 no-body 声明组件验收归档

状态：**PASS，范围仅限声明的 predicate/branch/mark 结构**。
实现提交：`006a0e06a1f5739cec4948c690a382fc191f1af8`。
验收文档：[M1_NO_BODY_ACCEPTANCE.md](../../../../docs/M1_NO_BODY_ACCEPTANCE.md)。

## 实测与审查

| 证据 | 实际结果 | 范围 |
| --- | --- | --- |
| records | 初次 6P/1F，修正断言后 7P | exact/nested/冲突；原失败保留 |
| fixture 首烟 | 缺 bool 定义，未到其他两图 | 原命令、原失败及完整源码快照保留；不是 detector 拒绝 |
| root 三图首烟 | BODY、ASYNC、实际 AssociationRead 均无 issues | typed graph，不是 native runtime |
| graph/attempt-001 | 43P / 0.82s | 正反连接、current-state、角色、真/假边及多 Create |
| codec_queries/initial | 45P / 1.71s | strict v13、旧 wire、原 UseSite/结果、CLI 权限边界 |
| component/final | 836P / 21 标准 / 12.709s | 430源 hash 不变；包括先前741项 |
| review/final.md | 有界源码复审 PASS | 同源指纹，无另一次独立测试或 native 证明 |
| full/report.json | 3,871P / 0F / 0E / 0S / 463.982s | 唯一冻结全仓；三条警告；峰值 RSS 1,028,088KiB |

这些测试集合重叠，不能累加。组件在 dirty `e86563a` 基线上采集，完整逐文件 hash
等于随后 clean 实现提交。冻结运行期间没有修改源码/文档或启动其他 SCAR 测试。
HEAD、430源和35fixture前后一致。原3,776个测试身份全部保留，新增95个。
原32份fixture仅明确授权的 publication helper 抽取发生变化，旧JSON wire保持原字节。
当前原factory也与独立v12样本字节相等。独占basetemp在子进程终止后已删除。

v12 golden 由 `historical/generate.py` 从不可变 `e86563a` 的独立 git archive
生成（69,273 bytes；SHA `76f594871b1f80e8fb62039bff15f3ee5efd4d2a274f12f28ca4a1ad53e36b2f`）。
禁止用当前 v13 codec 生成历史期望。

## 失败与修正的归属

`records/` 保留断言正则不匹配的失败与修正后记录。
`fixtures/attempt001` 保留 fixture 缺少 bool 定义的失败，
`fixtures/fixture.before-root.txt` 与当次源码 SHA 一致。root 删除覆盖同名函数的
未完成草稿，补真实 association、规范值/操作表和状态转发；`root-smoke-002.json`
保留三个修正后结果。源码审查发现的普通 UseID 子类兼容与 branch unknown-effects
约束已修复，再经定向/组件/冻结全仓验证；没有冒称修改前运行了复现器。
编辑/报告命令未激活 conda 的 shell 失败单独保存，不冒充产品测试失败。

## 证据复核

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_no_body/check_evidence.py
```

校验器只核对归档，不重跑测试/工作负载。总 manifest 包含内部 full manifest；
只排除总 manifest 自身。独立全仓命令、环境、JUnit、结果和源快照均位于 `full/`。
保护仓库检查见 `protected-checkouts.json`：原 LeWM 与主 SCAR checkout 未修改。

没有新的 source lowerer、runtime adapter、detector/backend、LeWM profiling、
变换或 clean A/B 加速比。实际 guard/纯性、关联、native/no-reset 条件、完整D2/C2、
D3与第一阶段M0–M2仍未完成。下一门是冻结合同内的session后态、失效、终态owner/
release和派生E/F/P连接，不绕过前置建模去增加优化规则。
