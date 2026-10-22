# 真实源码回查：格式字符串

2026-10-22，产品7bcece2。第一阶段OPEN，不是全量inventory。

自动从原inventory8和前两份阻塞诊断摘要选择JoinedStr首断点，无函数名单、
不执行目标。19文件/22body，单body10000op预算，不能与原全量54相加。
命令及逐项结果见run.time.txt、run.stdout.jsonl和result/。

Observed：16 LOWERED_WITH_GAPS、6 UNSUPPORTED、0 ERROR，exit0；
wall55.59s，peak523652KiB。没有扩大测试或做新的全量source replay。

将格式字符串递归分为值求值、!s/!r/!a转换、spec求值、format和拼接，保留world、
异常与引用释放；显式区分无spec与空spec。超过CPython直接BUILD_STRING阈值的
形式继续拒绝，未将潜在用户format调用当作纯计算。

六个剩余首断点：缺旧overlay的target-child Call、DictComp、expanded Call、
解构/其它写各1，With2。原canonical/source/profile验证在恢复过程中执行。
运行环境、跨调用数据、资源和来源闭包仍未验收；没有优化或性能结论。
