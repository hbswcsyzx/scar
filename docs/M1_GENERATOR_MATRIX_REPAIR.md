# P2 矩阵冻结回归失败与最小修复门

2026-10-18。原实现 `44d56af52d65cd3440f4600fa05ea34fd03ad7f1` 的一次
完整回归为 **5,672 通过 / 1 失败 / 0 error / 0 skip**，不是验收通过。
原始 `model_generator_matrix/full/`、preflight 拒绝记录和所有定向失败原样保留。
修复证据另存 `model_generator_matrix/repair/`，不覆盖第一次 full。

## 已观察到的原因

唯一失败是 Created-close 正例：原 Finish→host 路线存在，但默认 4,096
预算下没有完成当前 None 内容的证明。独立 fresh-process 调查在八个 seed 中
复现：seed 5 截断；充分预算下需 4,676 单位，另七个需 1,712–3,530 单位。
literal class/enum identity 均正常。旧测试污染不是复现的必要条件。

`ProtocolFlow._fresh_copies` 从 `frozenset(reached)` 初始化工作队列。hash
顺序改变迭代次数及公开预算消耗，同一声明模型因此有不同的完整/截断结果。
返回 None 本身保守；不稳定的查询成本是真实产品缺陷。不能调高默认预算、
降低原断言，或将截断解释为证明成功。

## 修复设计与不变条件

对原 CFG 按原 successor 次序做非递归 DFS，保存 entry-first 的 reverse
postorder。copy worklist 与 edge 初始化使用该有序 tuple；reachable set
只用于成员判断。它是查询调度索引，不是新图、许可或动态执行顺序。
保持原 meet、并行重命名、producer 每次重新求值时的 kill/reset、不动点、
预算计费与缺口分母。声明中的块/操作存储顺序不应改变有相同 CFG 的答案及
预算成本；原 successor 的顺序仍有含义，不承诺重排它后费用一致。

## 自主验收节点

| 节点 | 操作 | 通过条件 |
| --- | --- | --- |
| R0 | 冻结失败及定位 | 原 full FAIL 与八 seed fresh-process 证据保留；不借旧组件 PASS 宣称通过。 |
| R1 | 最小产品修复、定向回归、独立审查 | 原失败断言原样通过；八 seed 的答案、预算明细及截断一致；块/操作存储重排不改变费用；小预算仍截断；循环、旧值和错包反例仍拒绝。先运行新回归复现，再改产品。 |
| R2 | 完整本批 focused 与组件 | 在同一源码指纹下通过所有原 272 项及新增定向；保留原 36 标准并增加调度标准；所有旧 case/fixture identity 守恒。 |
| R3 | 新冻结完整回归一次 | R1/R2 通过后干净提交；采用原 SHA 的 full driver，在新的 repair/full 中完整运行一次。所有作者停写，无并行测试/工作负载。失败则保留并重新审计，不自动重试。 |
| R4 | 只读归档、版本管理 | 原 FAIL 与新结果各有明确 revision/指纹；manifest、旧 case/fixture 守恒、保护目录及 owned basetemp 清理核验。提交并 push。 |

此修复只稳定原声明图的有界查询。P3–P5、D3、完整 M0–M2、source 自动恢复、
native/runtime identity 及优化授权仍未关闭。没有新 detector/backend 或 LeWM
业务规则，也不产生新的 LeWM 加速比。

## R1 / R2 实际检查点

- 修复前新回归 **1 失败 / 2 通过**，原输出在 `repair/red/attempt001`。
- 最小产品修复后 **47 定向通过**；原八 seed、声明表重排、低预算、循环/
  旧值/错包/消费者定向均通过。独立源码审查没有发现本次调度修改的阻断，
  不授 whole-query 所有路径确定性的过宽结论。
- 同一注册源指纹下，`repair/final-focused/attempt001` **275 通过 /14.36s**；
  `repair/component/attempt001` **660 通过 /37 标准**，含原36标准全部保留。
- 源码 **647 文件**，指纹
  `7ead791af4340d886c51c0a37f9d32f16aa70ee63d4b5731ef294f8660a74815`。
  原646文件均仍在，原 full 的92个 fixture 内容未变。
- 下一步干净提交并启动 `repair/full` 的一次冻结完整回归。原 full FAIL 仍是
  先前实现的真实结果，最终 P2 验收尚未通过。
