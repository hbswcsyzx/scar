# Actual owned OS launch end-to-end acceptance

2026-10-23。**PASS_OWNED_LAUNCH_COVERAGE，实际CLI/runner/GNU exit0。**
这是同一个第二门session70729的终态；owned provider PID678900、target PID678903由
真实launch/native metadata提供。runner PID未在存活时采样，不推测。首门失败仍完整
保留；没有重用目录、扩大64MB/120s预算、降低Python collector覆盖或新增native-only协议。

入口：`bash artifacts/experiments/first_stage_owned_os_capture_20261023/gate-attempt02/run.sh`。
这是已运行命令，目录不fresh时不得再次执行覆盖。producer保存真实revision/argv/脚本、
`static-freeze-guard-revised.json`的19来源SHA与CPU环境。源码冻结前后无漂移。

wall **27.86s**；GNU进程树maxRSS **805588KiB**，runner自身report **130752KiB**。
采集provider elapsed单列launch；本次不是benchmark、LeWM运行或优化加速比。

| 真实范围 | 数量 |
|---|---:|
| archived原artifact | 11 |
| decoded / stored bytes | 8344309 / 916903 |
| OS原档 / 原行 | 4 / 81185 |
| parsed interface records / 原outside_fd_profile | 81180 / 70190 |
| 原parser frontier | 0 |
| 安全实际unshare / close_range | 1 / 1 |
| call / operand / function-environment / dispatch事件 | 26 / 43 / 3 / 12 |
| 四collector declared drops/errors | 0 |
| wrong-nonce binding实际拒绝 | 1 |

新入口真正拥有Popen(actual strace argv/target边界)，native intent与capture/native nonce
准确关联；同owned unreaped child的proc运行镜像SHA与安装strace一致。原generated
payload经现有store bounded sink压缩、roundtrip双SHA/bytes核验后保留；11档在此门又
通过public metadata+原byte receipts核验。profile2在Run/archive固定之后派生，最终
coordinate一次发布。没有修改历史Run，也没有fake ProgramSnapshot/新mutable图。

准确收据：

- coords 45674bytes，SHA `51c3d55c4492ff2f4f769d53f41ebb465a5529620b314b8d334d0f8be8ff9920`。
- profile 3114bytes，SHA `603ecfabb1c97436048d67b93960762d3ba3dd38f235b53c9f72f4f796badfea`。
- launch 3334bytes，SHA `e10d9b08fb0d89fe115400bb737b2b0613a34828ee409b55a2171648522e2f4e`。
- archive 6817bytes，SHA `6cca49aadd42121842224e9d06c00fece23ea0d83f637b4ecda603843b6f0c17`。

所有路径见summary/producer/raw-receipts及原capture元数据。只在本门新副本中翻转
coordinate binding nonce，public coverage reader实际拒绝，原coords字节保持。

**剩余前沿**：observation_completeness UNKNOWN；空selection gaps、exit0或0declared
drops不证明完整event stream、所有process/thread、canonical Python-Torch映射、FD/OFD
alias/end/contents或GPU ready。原native completeness/gaps及coordinate.open保留。
IO raw策略为明确数据接口名单，不声称理解任意未知设备协议。完整第一阶段仍OPEN。
