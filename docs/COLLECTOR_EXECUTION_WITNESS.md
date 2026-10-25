# 采集器实际注册及来源证据

2026-10-25。Implemented，并在一个独立CPU样例上 Verified；第一阶段仍 OPEN。

静态代码快照不能证明旧运行实际安装了哪组hook。新增可选profile
`SCAR_COLLECTOR_EXECUTION_WITNESS_V1`，在真正的CallEdgeRecorder上生成issuer及代次，
分别记录call、operand、environment、native manager、dispatch的实际对象连接。
记录live CodeType后，用既有CodeWitness归档匹配SCAR源码；不编译或执行workload源码。
该匹配是注册时源码与代码兼容的证据，不宣称loader最初读到了相同字节。

开启方式是对普通trace命令设置`SCAR_COLLECTOR_EXECUTION_WITNESS=1`，并启用
call operands、execution evidence和owned OS采集。原trace schema、Run seed和默认行为保留。
sidecar初始Run明确UNBOUND；普通writer关闭后才绑定closed metadata。
`bind_collector_execution_witness`随后消费普通CaptureCoordinates，检查准确artifact、
process membership和dispatch nonce。call-meta的两种schema标签通过明确版本规则映射，
URI、SHA、大小、PID及路径均须相等，不普遍忽略schema。

每事件仅检查当前role的便宜身份/代码条件，注册及关闭边界检查完整链；不逐Tensor
编译或hash源码。已知hook变化停止授资格；持续无篡改及事件无丢失仍未证明。
proc start ticks与strace birth anchor分别保留，未证明二者准确对应或排除PID再用。
此profile不赋予内容版本、纯性、资源ready或跨scope对象同一性。

实际CPU CLI exit0/26.105s，原总门在schema视图绑定处exit1；失败保留。
修正consumer后，仅离线读取保存采集，postflight exit0/1.570s，GNU1.66s、RSS56080KiB。
坐标payload与原CLI保存字节完全相等；重封SHA后改变issuer generation仍被明确拒绝。
CPU累计一次，没有新LeWM/GPU/full-native门，也不补认旧LeWM采集缺失的collector源码。

代码及小型证据存档于`codex/native-scalar-model`的222b32aa，实际报告在该分支
`artifacts/experiments/collector_execution_witness_20261025/RESULT.md`。
六文件已原样应用到主开发树，见
[应用收据](../artifacts/experiments/collector_execution_witness_applied_20261025/receipt.json)。
原producer、新consumer、捕获时CodeWitness及事后源码副本分别记录；没有混写来源。
