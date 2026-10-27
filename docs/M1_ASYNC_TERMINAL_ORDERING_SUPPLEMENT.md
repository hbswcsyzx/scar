# 原 F18：canonical choices 不表示发生顺序

2026-10-20。原计划和 residual 补充不改，生产文件仍四份、无新类型/旧测试改写。
有限43项通过后，独立审查发现 root 把排序后的 choices 当作时间序列。

原两 helper 正反已实测：`canonical-choices-counterexample` 的2项均失败。
899 文件稳定，指纹 `1e1360b32da29340581eb1f2530037c91251040bce9797c6d6bac75f6de4fc9e`。
早 helper 的 ID 为 async.session.helper，晚 helper 为 a.later.helper；两者实际
先后 RAISE。修前错误拒绝晚 helper 新包，却接受仍可用但不属于当前失败的旧包。
这不是 merely gap，而是真实不健全性；保存旧源码、命令、JUnit 和前后指纹。

修订只沿原 source.successor.block 出发，用原 chosen edge map 重放同一有限
CFG 路线，顺序来自原控制边和 block 内位置。预算按原 block/edge/完成全槽
收费；循环、缺选择或耗尽保持未证，不把规范 ID 排序当时钟。不另建控制图，
不枚举新路径，不放宽 packet 身份或 adapter 的普通路线义务。

验收保两项当前/旧包正反、原43项全部节点和旧2058精确身份。同源最终affected
通过及独立复审后才允许原 F18 条件性结构验收；其余七族及整体阶段仍开放。
