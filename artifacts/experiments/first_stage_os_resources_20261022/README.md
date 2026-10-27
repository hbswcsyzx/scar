# 真实LeWM OS文件资源导入

2026-10-22；第一阶段OPEN。原成功episode的253份strace原档，通过公共
`scar import-os-resources <os_dir> --root-tid 452006 --out <fresh_dir>`导入，
不执行目标、不新增测试套件。完整命令在run-attempt2.time.txt。

## Observed

705569原始行全部有artifact/物理行定位：705564 COMPLETED、5 SIGNAL。
583199条profile内syscall观察；122365条其它系统调用仍明确outside_fd_profile。
自动得到12587独立OFD（open file description）、12588个handle代次、521个
观察到的handle结束，以及968条可确认private-table区间内的IO consumer关系。
所有成功open即使在共享未知后仍进入资源模型；不凭相同pathname合并FileEntity。
close结束的是handle，不能据此假定OFD或文件内容寿命结束。

新typed片段复用ExecutionRun/ProcessInstance/HostThreadInstance/ResourceInstance/
HandleBinding/TargetLifetimeEvent；没有伪造canonical operation/value或新建资源图。
CLONE_FILES、继承、无法解析的变更和resumed IO保留OPEN，不能按时间排全线程
再猜FD身份。路径仅保存原rendering，不能当文件内容/物理inode身份。

## 实际核对与成本

独立标准库audit.py逐原档重计/核hash、每行连续定位、全部成功open与typed资源
集合精确对应、handle目标和身份唯一性：PASS，见audit-result.json。
本档无unfinished/resumed、未知mutating return或解析frontier；新增保守continuity
保护不会改变此输入的产物，因此未为不触发的保护再跑整份导入。

首次输出因重复在每个IO中存两份长artifact记录触发512MB写上限，失败和日志保留。
改成同artifact表的精确索引/物理行定位，typed核心record仍保留完整来源。
并将JSON→gzip的微写合并为64KB。第二次exit0：61.48秒、peak1106268KiB，
产物gzip8.5MiB；没有通过扩大上限掩盖重复存储。

## 仍待连接

软件source stage/effect/native handle ValueOccurrence尚未接通；共享表、继承、
mmap/pipe/device/driver及GPU/ready等不由本fd profile完成。12587是观察到的
打开实例数，不是“全软硬件资源建模完成”的计数。无优化/变换/性能结论。
