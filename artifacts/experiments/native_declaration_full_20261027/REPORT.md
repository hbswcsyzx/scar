# 全量原生边界构建实际终态

Observed：冻结312ab664，CLI exit0/1705.169412秒，
76/76源片、230818 operations、1030969 inputs、225532 conditional outputs，
unprocessed0、completion-selected0。共有359接口，共享program15,732,623B。
输出10,242,234,219B/1942文件；input stored187,662,077B + decoded3,508,461,101B。
准确命令/源码archive SHA在INPUTS，原终态在RESULT，root manifest保SHA与原片收据。

Verified：本次producer对全部执行片运行core validator；root全分母对账通过。
尚未对全部片再次独立normal-reader扫描，前首片普通256-op reader结果单列，
不能以本结果宣称所有cross-layer dependencies已通、normal completion或ready。
原EO分母310412=190498 schema ops+40320 nonschema CPU ops+79592 annotations+2 unknown；
annotations/unknown仍在原evidence，未假装属于230818普通算子分母。

本次为既有同Run LeWM记录的offline canonical boundary构建，不是新的完整采集，
也不是全程序建图时间或加速比。28分25秒和10.24GB均不称轻量。
metadata/内容/状态/资源依赖、新完整采集及第一阶段均仍OPEN。
