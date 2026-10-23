# ONE 272038 分片 source/body 参数、返回、环境路由验收

状态：**原 attempt1 已按根授权因分析吞吐中止**；第一阶段 OPEN。
session 98266 实际 exit 130，Python PID 456184 已确认退出。没有执行或弄坏目标。

仅消费已 PASS 的 `first_stage_partitioned_composition_bindings_20261023`
composition/source-bindings 与原 `first_stage_lewm_dispatch_20261023` 272038 capture。
不混 369749，不执行 LeWM/GPU，不 prepare 151 文件，不组 full inventory JSON。
首次 CodeWitness 编译键上限 20，所有 source/CodeType/CP/端口引用保持原身份。

`prepare.py --phase prepared/frozen` 只存 stdlib 收据、源码快照与 HEAD patch，不 import
SCAR、不加载目标/图。`run.sh` 只允许新目录单次启动；先生成 frozen 生产者快照，
再独立 time/RSS 记录实际入口。`run.py` 在开始和完成核 frozen 源码 SHA 全部一致。
异常保存 failure/progress/stderr，不覆盖、不自动重跑。

预期守恒分母：817 entered code groups / 100,438 frame entry/exit /
312,812 operand events / 16,403 environment events。正路由数量尚未知。

产物为一个 `to_dict` 的有界 gzip 分表（每片最多 16 MB decoded / 1,000 rows）及
小 manifest，不重复写巨型完整报告。保存原 canonical-document SHA/大小与单次
to_dict、分片归档实际成本；分表只是报告存储，不增加规范图或 producer。

root 曾在实际 import 前暂缓一次以冻结共享缓存修正；prepared 收据保留为历史准备。
收到新 freeze 后正式启动这一唯一实档。frozen 收据保存当前真正 producer SHA、
原输入与74CP物理收据；执行中的真实阶段/预算以 progress.jsonl 为准。当前不提前
宣称路由验收通过。

## 实际中止与保留

原 frame/operand reader 在 140.18 秒完成，817 groups / 100,438 entry/exit /
312,812 operand 守恒。首次 20 编译键全部完成，source 文本共 262,715 字节；
原74body已加载，CALL_MODEL_LINKED 于299.31秒输出。

随后原 routes 的 `issue()` 采用保序列表线性成员检查。100,550 attempts 中最多
4,069 个握手，至少96,481个唯一attempt issue需至少4,654,243,440次列表比较。
root授权性能中止；先核/proc cmdline/cwd，仅SIGINT我们自己的456184，等真实退出。
routes在中止前已运行764.42秒，进程异常记录于1063.72秒，峰值RSS1,616,424 KiB。
GNU time wall为17:49.54，记录signal2且其Exit status字段为0；实际exec session退出
码130及KeyboardInterrupt才描述本次中止，不能把time字段写成验收通过。

SIGINT保留的真实异常栈位于`call_operand_routes.py:314 if value not in issues`和
dataclass比较。此前root的外部remote_exec诊断请求被PermissionError拒绝，目标没有
执行探针且无stack-observation；异常栈来自这次授权停止，不冒充探针结果。

所有原档未覆盖：`failure.json`保留runner通用FAILED/KeyboardInterrupt字段；
本README及`stop-request.json`/`stop-confirmation.json`明确这是有意性能中止，
不是LeWM运行失败。20模块/20source的只读复用档位于`result/code-witnesses`，manifest
42,283字节，SHA `56355f7ef10d16d8ab4fb02a84988cf2f0070b75e4cd5fccbf1c86c1ea34170d`。
后续attempt02须独立目录、独立报告和时间，仅窄修保序issue set索引并只读复用此档；
没有在本目录偷偷重跑。
