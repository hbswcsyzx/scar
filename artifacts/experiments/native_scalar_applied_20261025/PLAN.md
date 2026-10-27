# 原生 scalar 来源接入

真实离线门 session94465 exit0，21.4212s：264 个输入中 4 个观测根通过、260 个
保留 frontier。4 根为两个 None、一个 Bool(False)、一个 Int(0)；不同发生和端口
保留各自版本，不能据内容相等合并身份。源、版本交换的独立反例已拒绝。

主树仅接入 freeze908d5c6c 的四份源码，先核 cb77abc8 基线与主树原字节相等。
之后读取同一个已保存 ValueGraph，经普通 typed codec/validate 回读，并检查批量
query API 和默认 capability 关闭。此检查不恢复 live owner，不重新 query scalar
证据，不生产新图，也不重跑 native batch/目标。直接读入上限 4MB、外部 60s；
它是主树兼容性检查，不作为新的完整内容、状态或 ready 资格。
