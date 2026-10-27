# 真实源码回查：dictionary与heap receiver表达式

2026-10-22；第一阶段OPEN。原inventory8与前序三个cohort自动选出20文件24body；
19个Dict、3个缺overlay的Call、2个Attribute，含同body新首断点，未按函数名分支。

Observed：8 LOWERED_WITH_GAPS、16 UNSUPPORTED、0 ERROR，96.72秒，
peak598956KiB。run.time.txt保留完整命令，result/保留逐项完整graph及下一断点。
单body10000op诊断预算，不与原54相加。没有扩大测试、不执行目标。

Dict采用BUILD_MAP/MAP_ADD/DICT_UPDATE，保留CPython3.14批次/插入/覆盖顺序，
普通key/value与**mapping的异常、world及temporary ownership；hash/equality/
user mapping/effect继续未知。缺旧computational overlay的heap receiver只基于
准确SG/source恢复Name/常量/attribute/index/fixed Call，不伪造StaticValue。

真实入口main已得到局部图；get_action推进到ListComp，CEM.solve推进到解构。
这些名称仅用于本外部测试的定位，不出现在通用建模规则中。剩余首断点：其它写4、
expanded Call4、Subscript2、With2、Delete/ListComp/Slice/DictComp各1。
整个程序、真实跨层来源及资源闭包仍未验收，不产生优化/性能结论。
