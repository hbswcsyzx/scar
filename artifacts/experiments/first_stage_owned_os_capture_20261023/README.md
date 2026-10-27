# Owned OS capture checkpoint

2026-10-23。Implemented + bounded CPU Verified；完整程序/资源模型仍OPEN，未跑新LeWM。

- `gate-attempt01/`：真实full-profile首门，64MB OS预算终止own group，非正常target
  退出。runner1/CLI241/provider-15，46.96s/RSS427600KiB；不授coverage。原64MB raw
  仍在本地，精确SHA/有限样本与失败收据保留；**staging-list明确排除此大raw**。
- `guard-reorder/`：root审查授权的两个PID guard无动作前筛。保原源/补丁与语义表；
  一个真实profile/monitoring/fork行为门exit0，不是规范图/完整语义证明。
- `gate-attempt02/`：独立fresh full-profile门，原同64MB/120s预算，exit0，27.86s。
  owned Popen→native intent→原格式归档→Run/profile2→一次coordinate发布→公共回读及
  错误nonce拒绝均通过。无降采calls/operands或native-only新协议。

`static-freeze*.json`/frozen-sources保存各启动时版本，不覆写首失败producer。
`completion-receipt.json`覆盖95个小artifact及准确终态（后续本README/staging自身另存）；
`staging-list.json`为明确源码/文档/小证据清单，不是自动Git操作。provider/native运行
PID来自真实metadata；成功runner PID未取到，不凭邻近数值推测。

selection coverage不证明event无丢失。当前native/coordinates所有原completeness/gaps、
FD/OFD/lifetime/contents/ready与source对应前沿均保留。产品说明见
`docs/OS_CAPTURE_LAUNCH.md`。没有任意代码变换、backend、假ProgramSnapshot或LeWM规则。
