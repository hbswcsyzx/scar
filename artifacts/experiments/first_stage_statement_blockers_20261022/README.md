# 真实源码阻塞回查：注解、断言、异常

2026-10-22，产品75fc24d。第一阶段OPEN；不是新全量inventory。

由原环境inventory8的首个缺口自动选择8个AnnAssign、11个Raise、5个Assert，
无函数名单、无手工IR、不执行目标。使用前一份recover.py通用入口，新增
`--terminal-family`三个精确原因参数，完整命令保留在run.time.txt。
19文件/24body，单body10000op诊断上限；不得与原全量54个直接相加。

**Observed：4 LOWERED_WITH_GAPS、20 UNSUPPORTED、0 ERROR，exit0；
wall60.15s，peak529592KiB。**

实现函数内annotation的求值边界、Assert正常/失败路径及仅失败时的message，
以及exception→cause→归一化→RAISE；构造/归一化失败均携各自world后态。
协议不会假定输入就是BaseException，RERAISE保留thread exception context合同；
Assert只声明optimize=0源码语义，不认证live optimized code。复杂无值annotation
按CPython3.14逐项求值/丢弃，annotation本身不执行。

下一首个阻塞：JoinedStr12、Dict6、复杂target-child Attribute1、其它写1。
每条body的graph、source correspondence、入口及协议均保存于result/，原canonical
及profile校验实际执行；未扩大测试，未做新全量重建或公开exact replay。

whole-program、实际环境身份、细状态/逻辑来源和OS/CUDA资源生命周期仍未验收。
没有任何优化或加速结论；本轮只推进第一阶段建模。
