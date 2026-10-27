# 条件值来源消费者：实际进展

2026-10-20，基线 `fff1895fd3abc312409b9b95d40affa9b2c06f86`。
[冻结计划](M1_VALUE_SOURCE_CONSUMERS_PLAN.md)；归档位于
`artifacts/experiments/b1_call_operands/model_value_source_consumers/`。

## G0 — Observed

原913源文件指纹 `51ff19e5d0619404596f8ab96267b3eb7d9b83f8bd376ea188db31e9704adb7e`。
先复验上门不可变checkpoint，再对相同实际load比对：公开stored来源True，原
ordinary pair为None，原copy表不变，当时还没有value_source_pair入口。所有源码
前后相同，完整原库存保存在baseline.json。

第一次baseline脚本在已经完成上述断言后，仅因ExecutionIssue gap不是JSON
可序列化对象而失败。保原脚本和traceback，不称模型/目标运行失败。修归档脚本
的dataclass gap序列化后成功；基线报告保fixed script SHA。没有产品源码变动。

## G1 — Implemented，静态审查

新增独立query-local多边来源图和准确own-read投影，不改普通copy表/roots。
读取缓存有ACTIVE generation与深度32界，fresh context/shared query隔离。
原stored地址与body普通None后的独立条件分支接入该关系。

独立审查发现support路径先扫描后收费，root改为每边先计费再收集。root另发现
cache命中context已冲突、多个原Read共用同landing两处接缝，A在首次运行前修复；
准确incoming/edge/slot逐候选选择，未借兄弟。产品接线与helper再次静态审查无
未决阻塞；此处不代表执行测试或native对应已经通过。

## 执行与最终限定验收

全体源码作者FROZEN后，首轮 `first-composition`：917/ff0e8f…指纹稳定，
46节点中45 PASS/1 FAIL，pytest 2.88秒、wrapper 3.652743171900511秒。
失败仅新shared-landing fixture在query前被原completion_private_target拒绝：
INVOKE的own N/R落点必须独立，不能由两个producer直接共用。保该失败与原源码；
B仅修两NEW文件为private完成落点→普通forward→共同consumer join，不放宽原
验证、不改旧fixture/test、不缩减21个新case。原“多Read共own landing”只是
实现前的防御性考虑，不能称当前合法IR已经覆盖的有效程序组合。

第二轮 `corrected-private-landings`：917/31936a…稳定，仍45 PASS/1 FAIL，
pytest 2.75秒、wrapper 3.4966253312304616秒。仍仅新fixture：两arm未带完整
state参数、call读entry旧版本；查询未开始。B只补原WORLD/CONTEXT块参数、
choose两边独立STATE_CONTENT Uses及每call的本arm当前state。

第三轮 `corrected-arm-states`仅回归该失败节点：1 PASS，pytest0.98秒、wrapper
1.7373763239011168秒，917/51da77…稳定。21新caseID、旧tests/fixtures和产品
逻辑均未因上述两次fixture修复改变；不放宽验证或降低原分母。

默认depth探针在第二轮及最终源码各执行一次：length40/default32/shared2M，
均689计费后深度截断，公开detached结果为None且保cursor、40Read/40Write，
没有RecursionError。最终快照51da77…，0.3683352330699563秒；这不是性能收益。

每次保source-before/after、差异源码、命令、JUnit和stdout/stderr。最终数字及结论另见
[限定验收](M1_VALUE_SOURCE_CONSUMERS_ACCEPTANCE.md)。不预先填写通过数或加速比。

## G3 — Verified，有限范围

最终 `verified-current` 一次26模块：292 PASS，21新增、271既有；pytest318.32
秒、wrapper319.10433820448816秒，917/51da77…前后稳定。全部首败及21新身份
保留，旧test/fixture与Program27/Execution8无改变。C对最终七文件只读复审
无未决阻塞，明确body只覆盖薄分支，公开F19整链仍未证。到此停止扩大可选测试，
只作账本、旧文件守恒、普通commit/push及远端SHA/clean核验。
