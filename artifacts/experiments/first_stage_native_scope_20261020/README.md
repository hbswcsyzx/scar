# 第一阶段：CPU provider scope 与原生活动连接

2026-10-20。局部自动连接 **PASS**；全程序建模 **OPEN**。

## 合同与实施

本轮固定 Torch `cf30153c4c131c8164ee7798e5022d810682e2cb`、其 Kineto gitlink
`094d3c1d072362d0a919a77299459eee94f97931`。7份官方源码/记录、URL、字节数和
SHA256保存在 `sources/manifest.json`，共184,235字节。

Chrome `External id` 指 linked CPU activity 的 correlation ID。CUPTI CUSTOM0
关联普通 CPU scope；USER_SCOPE 使用独立 CUSTOM1。因此只取同 capture、目标
host process、唯一 External id 的 `cpu_op` 候选，不用 user_annotation 或最近时间。
一个 scope 对应多条活动是正常情况；CPU候选冲突、ID缺失或其它进程都不借用。

新增关系 **PROVIDER_SCOPE_ASSOCIATION**，不是parent/containment/submission/
control/HB/ready。有该关系时才用evidence schema5；原能力保持3/4并可读。
旧region投影不支持该关系时拒绝，不默认为CONTROL。未新增detector/backend。

## Observed / Verified

`import-lewm.sh` 实际用 `c7ca736` 只重新处理已有真实输入，没有重跑目标/GPU。

| 项目 | 实际结果 |
| --- | --- |
| 动态记录 | 205,424，与前一验收图相同 |
| 边 | 483,425；新增54,089条scope关联 |
| runtime / driver scope关联 | 29,957 / 50 |
| kernel / memcpy / memset scope关联 | 22,457 / 543 / 1,082 |
| 原有记录、引用、父子、资源和提交边 | 独立差分审核逐项一致 |
| CPU External id实际重复 | 0，不是预设全局唯一 |
| 未报告scope关联 | 7，保留 `provider_scope_unreported`，没有补猜 |
| 导入成本 | 214.92秒wall，2,455,040 KiB peakRSS，exit0 |
| 独立审核成本 | 37.63秒wall，6,293,720 KiB peakRSS，exit0 |

原先30,007条“未核验External id合同”的runtime现在全部获得了有来源的scope
对应；另外24,082条GPU活动也获得其provider实际记录的scope对应。

`audit-scope.py`只用标准库，校验上一图已审核字节哈希，核对所有旧记录/边不变，
再对原始Kineto重建独立候选索引，重放所有54,089条新增边。没有用生产importer
或图validator代替独立核对，也没有将差分审核称为完整建模证明。

206项针对性测试通过（4.52秒）。补充“runtime自身属于另一进程”保护后19项
原生连接测试重验通过（1.92秒）。该保护在上述真实输入不改变任何关系：独立审核
已逐条确认runtime全部属于目标PID。没有为这一个拒绝条件重跑相同全量分析。

## Inferred 与未完成项

scope边依赖输入为同次capture、安装二进制实现声明源码版本；不是运行中验证过
所有provider二进制源码对应。正ID也不跨进程/重启/窗口当成无限全局身份。

本轮未建立 Python→Torch、完整source SSA、非Tensor端口、逻辑值/状态版本、
资源allocation/queue/文件生命周期或输出闭包。原5,593个provider引用依然不是
内容版本；3个设备/流selector依然不是完整资源模型。没有加速比或优化批准。

## 后续顺序

复用已有记录器和provider的带Tensor实参marker，先用CPU实验确认准确对象槽位桥
以及RecordFunction/dispatch时点，再写生产连接。source inventory保留已有源码
语义/CFG；不再造只重复FrameCallEdge/CallSiteLink的wrapper报告。
继续第一阶段，直到完整LeWM自动模型验收通过才进入图化简。
