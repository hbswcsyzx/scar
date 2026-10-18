# 公共 resource_composition 通用集成测试

**Verified（有限 focused 范围）**。只新增 `tests/integration/test_execution_pipeline_composition.py`；没有产品改动、旧 fixture 改动或新的规范图/状态/producer。每项先 `require_valid(model, program, **catalogs)`，再构建 ExecutionIndex 调用公共 `resource_composition`。不存在 FakeContext 或绕过原模型校验。

## 实际命令与结果

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_pipeline_composition/focus.py pipeline_integration tests/integration/test_execution_pipeline_composition.py
```

首次且唯一 focused：**8 passed / 1.01s**；returncode 0；driver wall duration 1.6875487230718136s。原 command.json、Python 版本、stdout/stderr、junit、产品源前后指纹及退出结果在 `attempt001/`。没有本任务失败重试。driver 在 child 完成后仅删除 owned basetemp `/tmp/scar-v-focus-1xo929dj`。

本轮与其他 owner 并行实施，产品变化由 driver 的 source.before/after.json 记录；不是最终冻结组件验收。既有 focus driver 的源码清单只遍历 unit/fixtures 和 execution，未遍历 integration 文件；本报告另外保存实际执行后本 owned 文件的明确 SHA256，未伪造 driver 的运行前 integration 清单。

## 验收矩阵

1. `visibility_execution`：实际 Completed 左半与 pending Ordered 右半；known coverage INCOMPLETE，conditional coverage COVERED；actual/conditional、source OPEN 与权限 False 不混。
2. byte-prefix：原请求 8 bytes、实际 4 bytes；完成 outcome 不将 actual 扩成整个 request；没有 read 时不造 ContentRead。
3. host RAISE + work pending：删除 outcomes/quiescences，显式将 retention.release 置 Unresolved；原模型有效，保留真实 RAISE successor 与 fresh edge states，common AFTER 未知，工作/借用不被宿主异常伪终结。
4. WorkOutcome / WorkQuiescence / BorrowRelease / Handle.EndedAt / TargetLifetimeEvent.RETIRED 各为原独立记录；同 endpoint 时间不合并成 free/persist 证明。
5. 同一静态 callee 两个独立 activation；原调用端口回查；修改公开返回的 detached 原定义不污染 index 或原 program。
6. budget=1：原 ProgramGraph、ExecutionModel 及每张执行表精确计数完整保留；routes/read/source/work 的未检查游标/待处理分母不被预算删除。
7–8. scalar/reference 原输出根：显式 CompositionScope；保留原 Q requirements/roots/义务和准确 fd/handle 端口；没有新 Mat/denotation/read/work，保留协议未解释状态。

复杂 mixed read 组合使用显式总预算 16,384（包含 Q/P/V/routes/source/work 的组合派生，不改变产品默认 4,096）；其余使用默认或专门 budget=1。该测试不是性能基准，不报告加速。

## 范围与冻结

通用 canonical 声明图的 public 集成；没有新 native collector、LeWM/GPU 执行、自动完整 IO lowering、真实 source 配对恢复或 read/flush/persist 协议认证。本测试通过不关闭全部 R3.2/R3.3/M0–M2。等待 root 冻结后的组件与唯一全仓。

本 owned 测试文件已冻结，单一 LF EOF。其 SHA256 见同目录 `owned-source.sha256`（由实际文件计算）；后续不再修改产品/测试或追加可选测试。
