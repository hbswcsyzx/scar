# D2.3 session/release 与 E/F/P 声明派生验收

状态：**PASS，仅声明合同内的结构和派生**。
实现提交：`f67037d632b093e68f26eb0c2fab34767878651c`。
[计划](../../../../docs/M1_SESSION_RELEASE_PLAN.md)；
[验收](../../../../docs/M1_SESSION_RELEASE_ACCEPTANCE.md)。

## 真实验收结果

| 证据 | 结果 | 范围 |
| --- | --- | --- |
| records | 初次10P/17F；修正测试隔离后27P | 原始污染共享default失败保留，不冒充产品拒绝 |
| codec | 首次40P / 1.89s | v14、独立历史wire、原factory字节相等 |
| flow | 8P、14P、4 selected P三批 | 重叠集合；最终terminal文件18项，不算26独立项 |
| session | 初次5P/1F；修正fixture参数假设后6P | AFTER/NORMAL、RAISE、current支持、失效与alias |
| fixtures smoke | 四个基础图通过；Suspend release被准确拒绝 | 仅IR，非真实native实现 |
| graph | 首次18P / 0.69s；precision selected2P / 0.39s | F前提、真实partial states、完整D、core alias约束 |
| queries | 首次13P / 0.82s | 原Use/state/source、条件事实及CLI权限边界 |
| composition | 首次14P / 0.58s | 多来源must join、loop、错owner、body-only rebase、L内外写 |
| component/final | 974P / 27标准 / 15.967s | 全443源hash不变，包含先前836项 |
| review | 两份独立交叉有界源码复审及最终receipt PASS | 无额外独立测试或native证明 |
| full/report | 4,009P / 0F / 0E / 0S / 468.490s | 唯一冻结全仓，三条警告，RSS 1,030,312KiB |

集合重叠不能累加。组件在dirty `817cc0b`采集，全部逐文件hash等于后来clean
实现，不伪报为同一HEAD。全仓期间未改源码/文档或启动其他SCAR测试；443源、
38fixture、HEAD前后一致。原35fixture逐字节未改，原3,871测试身份保留，新增138。
子进程结束后只删除本次独占basetemp。原LeWM和主SCAR checkout均未修改。

v13 golden由不可变`817cc0b`的独立git archive生成（89,825 bytes；SHA
`b833f028476a379e4c178fcfc7ad33d5dfebf2f7423df51593c871589139e6b6`）。
当前原factory也与该payload字节完全一致，不用新codec生成旧期望。

## 失败、审查及修正归属

记录测试最初用object.__setattr__破坏共享默认FrameRules，后续17项受污染；
修正为独占测试实例后27项通过，产品没有为规避测试放宽规则。
P测试最初把strict_subset误读为L⊊D，改成正确extra_domain参数后6项通过。
源审发现额外coarse-only reference限制和CompletionSuccessor注解错配，已修正并
定向验证；没有伪造修改前的失败运行。root提出的跨region literal假设被既有
cross_region_use规则反证，已撤回，未作为产品漏洞修改或重复实验。

终态模块由一名代理实现、另一名独立审查；root的P/shape/analysis/query由前者
交叉审查。最终receipt绑定443源指纹
`23e4c97fc75b7ea889c964fb77a5eada6b617ab94e9a3b308d617f16af340596`。
复审未冒充又一次测试，也未把self-written IR当成native实现证明。

## 只读核对

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_session_release/check_evidence.py
```

校验器只读核对manifest、源、测试身份、历史fixture和保护仓库，不重跑测试或
workload。总manifest包含内部full manifest，只排除总manifest自身。

E/F/P有条件派生不证明真实guard/纯性、owner generation、native/no-reset适用、
source/runtime对应或资源free/ready。D2.4/D3、完整C2及第一阶段M0–M2仍开放。
没有新detector/backend/source lowerer、LeWM profiling、变换或clean A/B加速比。
下一门按完成矩阵检查C1/context组合与公开事实的条件范围，然后补后续模型缺口。
