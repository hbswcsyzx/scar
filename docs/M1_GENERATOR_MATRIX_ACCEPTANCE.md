# P2 同步 generator 声明矩阵验收

2026-10-18。结论：**PASS_WITH_SCOPE_P2_DECLARED_MATRIX**。
关闭[父计划](M1_PROTOCOL_FAMILY_PLAN.md)的 P2 同步 generator 声明模型门；
P3–P5、D3、完整 M0–M2 及自动全程序建图仍未完成。

## 1. 本门实际接通了什么

核心仍为 Operation、Value、StateLocation、Region、Resource，不增加第二套
producer/Use、状态链或执行图。原图的连接现在能表达并核对：

```text
caller 实际 raw pack / 原 operand / literal 附件
  → 每个原 CALL/INVOKE 的 ordered actual/formal recipe
  → driver 当前输入、实际状态读取 / arg-is-None
  → 本次 bool → 原 BRANCH → gate 输入状态
  → Start / Resume / 无用户入口路线
  → 本次 body 首出口或 helper 的实际 NORMAL/RAISE
  → 当前 payload / packet → host 消费者、状态和终结记录
```

Created/Running/Suspended/Closed × NEXT/SEND/THROW/CLOSE 的16格均有原图
正例及错误来源、旧状态或错误消费者反例。补充包括 close 的 Return(value)、
GeneratorExit 消解、其他异常传播、非法 YIELD 后重试；内部/外来/启动前
StopIteration 的分别适配；真实静态 body callback 重入后继续 YIELD。
Raw 处理或同类型 packet 的存在，不能代替本次来源与消费者之间的连接。

静态输入来源保留不同 caller 的各自完整 recipe，并联合 raw、原 operand 与
独立 predicate input 的同一 caller context。prepared indexes、flow 与预算
共享；已有 recipe 不会把 PARTIAL/TRUNCATED 洗成完整。它不推动态对象相同。

Program18 只在只读 AdmissionPredicate 或准确单 completion INVOKE 能力
出现时选择。一般 INVOKE 支持非空且准确的 NORMAL/RAISE 子集；特殊 final
gate 仍需双边。原 v1–v17 family/bytes 保留，独立 v17 golden 有冻结来源。
Execution schema 仍为7，本门没有实现 P3 的动态关联表。

## 2. 失败、修复与范围

| 状态 | 事实 |
| --- | --- |
| Observed | 原冻结 `44d56af` 完整回归5,672通过/1失败；Created-close 当前 None 证明在默认4,096预算下截断。原 full、preflight拒绝和所有定向失败原样保留。 |
| Verified | 八 fresh hash 进程独立复现预算差异；seed5需4,676，而其他seed需1,712–3,530。literal class/enum identity正常，旧测试污染不是必要条件。 |
| Implemented | 只将 copy worklist 改为原CFG successor决定的非递归 reverse postorder；不改meet、kill/reset、并行重命名、不动点或公开预算。 |
| Verified | 新测试先1失败/2通过，再通过八seed答案/预算一致、声明表重排和小预算截断；独立源码复审未发现本次调度修改的阻断。循环、旧值及错包反例仍拒绝。 |
| Rejected | 提高默认预算或降低原None断言来掩盖不稳定成本；把原failed full改成PASS；把声明连接当作native/runtime或变换证明。 |
| Proposed | P3按已冻结合同接多次Drive与同一持续body的实际activation、segment、instance和首出口，并接有条件host顺序。尚未实现。 |

原失败调查位于 `full-failure-investigation/identity-order/`，修复计划见
[修复门](M1_GENERATOR_MATRIX_REPAIR.md)，设计及源码复审在
`repair/design-review.md`。原 `full/` 和修复后的 `repair/full/` 具有各自 revision、
源码指纹、命令、日志、cases、JUnit、时间/RSS与manifest，不互相覆盖。

## 3. 实际验收证据

证据根目录：`artifacts/experiments/b1_call_operands/model_generator_matrix/`。
这些检查有重叠，不累加为模型覆盖率。

| 检查 | 实际结果 | 绑定范围 |
| --- | --- | --- |
| 原 native observer | 本机 CPython3.14.7 的40组合及6补充观察 | 本机语言行为；不是自动 source 恢复。 |
| 修复前新回归 | 1失败/2通过 | `repair/red/attempt001`，故障可复现。 |
| 修复定向 | 47通过/7.36s | `repair/focused/attempt001`，原失败及受影响反例。 |
| 最终本批定向 | 275通过/14.36s | `repair/final-focused/attempt001`。 |
| 组件 | 660通过/37标准/25.220s | `repair/component/attempt001`；原36标准全部保留。 |
| 冻结完整回归 | **5,676通过/0失败/0error/0skip，5 warnings** | `repair/full`，pytest546.47s；外部548.571s，峰值1,028,776 KiB。 |

冻结完整回归实现提交：
`bd673cd81938d7b8af2692645685123e85cc6965`。
注册源 **647文件**，前后指纹一致：
`7ead791af4340d886c51c0a37f9d32f16aa70ee63d4b5731ef294f8660a74815`。
原基础门5,401 case与原失败full的5,673 case身份均保留；之前82个及当前92个
fixture内容守恒。全仓期间所有作者停写，没有并行SCAR测试/工作负载；driver
只清理自己创建且子进程已结束的basetemp。测试耗时不是工作负载性能数据。

保护目录 `/home/zyf/AAA/le-wm`、`/home/zyf/AAA/scar` 保持原HEAD且clean。
可用 `python artifacts/experiments/b1_call_operands/model_generator_matrix/check_archive.py`
只读核对manifest、两次full、指纹、守恒和保护目录；它启动零测试/工作负载。

## 4. 仍未完成与下一步

1. **P3发生关联：** 原Drive→同持续activation→准确entry/segment/首outcome；
   Create NORMAL handle、captures、saved/current输入逐binding核对；错实例/
   线程/代次/来源拒绝，缺采保gap。复用原执行坐标和已有同步call resolver原则。
2. **P3因果连接：** 分别核entry与completion的conditional host桥，并与原CALL/
   CFG联合查occurrence cycle；不把部分采集当完整路径，不授GPU ready。
3. **P4/P5：** 其他body family、delegation/await/cancel与完整28组ledger及公共面。
4. **M2与总验收：** 回到原113构造/196字段清单，逐项核phase、依赖、效果和
   normal/raise/cleanup/resume规则；完整M0–M2完成后先向用户讲解，再推进自动建图。

每个有产品改动的门自行执行定向→组件→干净提交→一次冻结全仓→只读归档→
commit/push。不得把native类别、holder coherence、runtime/value identity和source
inventory等未证事项写成已完成；声明矩阵通过不授权reuse/hoist/delete。
本批没有新增detector/backend、LeWM业务规则或重型profiling；**没有新的LeWM
自动变换或可信clean A/B加速比**。
