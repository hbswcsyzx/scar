# 原209入口门：保留失败与已返回产物

Root session48283 actual **exit1**，2768.343111s。原terminal/ledger/freeze/runner与
各worker输出均保留，不重写为通过。209入口的准确终态是：

| 状态 | 数量 |
|---|---:|
| SUCCEEDED | 63 |
| UNSUPPORTED | 49 |
| FAILED | 17 |
| PENDING_NOT_STARTED | 80 |

17个FAILED的原detail完全相同：普通source owner复核时，原main绝对URI
`first_stage_dependency_continuation_20261023/result/continuation.json`不存在。
这不是17个Python语义反例，也不是资源预算不足。Root归档时的Git操作触发主树
稀疏检出，移除了427个已恢复但未被cone保留的原证据文件；driver在第6批处理后退出。

本门实际累计输入8,430,477,302B，pending reservation0、budget refusal0；原16GB
input/2GB output/8GiB/14400s上限不变。未把原运行延长或在原目录重启。63项成功
是原worker保存并正常读回的结果；不据此宣称整门通过、这些body已publication，
或已绑定当前LeWM运行。source858/6882正式指针保持。

## 已执行恢复及下一独立范围

Root已将主树改为精确保留所需路径的non-cone sparse pattern。526个main必需
input/graph路径全在，原1865个已物化tracked文件均未丢失。446个原input逐size/SHA
复核一致，读取19,838,310B；99个graph路径存在，恢复阶段未解图或重授图资格。
所有原逻辑URI/namespace未改，恢复使用Git内原件，不覆盖任何已存在的不同内容。
恢复明细在main的 `artifacts/experiments/source209_workspace_recovery_20261026`。

新目录 `source209_resume01_20261026` 只选择17个环境失败与80个未启动，共97项。
原63成功、49不支持和更早33终态仅保留历史，不重算；新物理stat必须进入新freeze。
它是独立后继，不升级本门状态。新图的正常准入、跨函数接线、state/content/ready
以及完整第一阶段仍OPEN。没有执行LeWM、增加detector/backend或进行优化。
