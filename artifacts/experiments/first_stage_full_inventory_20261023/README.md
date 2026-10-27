# 全量源码运行：拒绝自动封存策略

状态：**Rejected：自动封存未在实际调度中摊销；没有完整 inventory 产物。**

原命令见 `run.sh`，产品 `1562e97`，environment profile、4096 body/100000 ops，
基于真实成功的 89842 capture。prepare 151 个文件后开始完整的 body 调度。
实际过程中，327 个 body END 时已有310次 seal，仅38个不同文件。调度会在
不同文件间频繁切换，每次 deepcopy+完整封存校验的额外成本反复产生。

前面的6-body数据早已显示封存冷成本不划算；本次全范围进一步证明自动启用
策略不适用于该调度。没有把逐body缓存后的局部数字写成整体提速。

确认 PID270541 的 argv、启动时间和所有权后，向这一自有分析进程发 SIGTERM，
工具记录返回143；未停止 LeWM 或其它用户进程。已生成的进度/耗时保留，但该版
没有逐body图检查点，因此不能将中间成功数冒充可重放的完整图成果。

默认自动调度已恢复普通完整校验 lower；显式 seal API、集合去重及位置索引保留。
队列、预算、IR、公共读入/重放均未改变。后继运行在
`../first_stage_full_inventory_plain_20261023`，基于最新272038成功capture，并为
每次返回的body保存原graph/metadata/interface检查点；不先改模型再宣称成功。

一次只读栈诊断 `sys.remote_exec` 被本机权限拒绝，未提权、修改 ptrace 策略或
反复尝试；`stack_snapshot.py` 未在目标执行。这不是模型或目标程序的失败。
