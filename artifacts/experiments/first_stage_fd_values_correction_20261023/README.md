# Capture-filter correction and FD-only qualification

2026-10-23。**Verified：唯一gate实际exit0。** 这不是目标benchmark、完整FD模型或完整
第一阶段验收；没有新target/GPU/compile、百万Work重放或82MB原raw扫描。

发现的SCAR defect：旧四类strace过滤器未覆盖unshare/close_range，旧proof把观察到0
解释为absence。已撤销旧35 container continuity资格，不改变历史artifact；12110
line-range候选也没有新container资格。当前context builder/publicread fail closed。
旧FD scalar原始证据不受该前提影响；OFD coidentity/end/lifetime仍为条件性的baseline
声明，尤其未选network producer与ioctl FD输出使完整FD覆盖继续OPEN。

## 实际输入与实现

- 原R1 manifest SHA：`cbc6dcfd78ccca0961bdabecce94bc747b7b281fdbc3f49228c8b52b9b3aec14`。
- public R2 manifest SHA：`6b5e1ae12e2c05364c76364cf1b1cf7859d2f6ddb09380c8940a3980381bde5c`。
- 旧FD carrier SHA：`0ebb957e8b4fd86eafefbce6f854ff045627cface9523f06766aabab8b2e8723`。
- 旧context manifest仅作准确历史preimage：`d37eef5881d25a66c7500be2130b4f7af114586e0b8607f81a36ddd359886d84`。

`static-freeze.json`记录101个实际相关文件AST/SHA；`frozen-sources/`保存3个修改模块的
准确字节，`implementation.patch`保存两个既有模块diff。`gate-attempt01/producer.json`
保存真实启动revision、script/freeze/全部metadata输入收据；actual-imports前后99模块
SHA一致。新coverage协议尚未有旧capture的有效launch/profile；没有伪造补授资格。

## 唯一实际gate

入口：`bash artifacts/experiments/first_stage_fd_values_correction_20261023/gate-attempt01/run.sh`。
这是已完成命令记录，输出目录非fresh时不得再次执行覆盖。

真实wall **65.15s**，maxRSS **277160KiB**，exit **0**；离线有可能并行服务器负载，
不是LeWM加速比。session71578/Python667422已终态。

| 核验项 | 实测 |
|---|---:|
| 全部原HandleBinding public codec/同ID/非endpoint逐字段守恒 | 12684 |
| public R2原endpoint全部字段准确保留（container Unresolved） | 35 |
| 新schema2真实fd_ports逐行slot/selector/preimage核验 | 12649 |
| 全部container为Unresolved | 12684 |
| 旧FD payload hardlink，same inode/device与byte SHA一致 | 3 chunks |
| 原birth/前沿行 | 4 / 0 |
| 新container/Resource/Work | 0 |
| 原archive raw路径打开（本进程audit hook全部禁止） | 0 |
| 原target字段保留（不重新证明coidentity） | 12683 |
| 原selected Work/access不变 | 25 / 38 |
| 原process=None保持 | 290 |
| public legacy-context read / uncovered builder必要拒绝 | 2 |

显式`FD_VALUES_ONLY_R2` schema2：`gate-attempt01/result/manifest.json`，199812bytes，
SHA `bb0b7b16d503ea09dc95fe728c8826c302b3f8c86c79243a34070aad936ea624`。
该manifest保留旧raw extraction producer与精确raw收据，仅复用已逐整chunk验证的
carrier；没有声称此次重读raw或重新提取。新的provider selector属于这个真实manifest
namespace；原35 selector/lifetime及所有其它endpoint字段完全等于public R2。

`all-port-selector-proofs.jsonl.gz`保存全部12649准确selector/fd/source/原preimage；
`all-handle-field-proofs.jsonl.gz`保存全部12684新旧canonical-record SHA/选择状态。
这两个canonical-record SHA不是原raw-envelope SHA。`hardlink-receipts.json`记录3个
payload收据，`fail-closed-receipts.json`记录两条实际拒绝，`summary.json`为producer结果。

## 独立filter证据与解释

安装包probe：`../first_stage_strace_filter_probe_20261023/`。在独立SCAR子进程中实际
调用unshare(0)、close_range(UINT_MAX,UINT_MAX,0)，二者均返回0；原四类filter各见0次，
显式两名各见1次。这是过滤器对照，既不是旧episode补采也不证明其未调用接口。
binary/version/argv/退出/原日志均保留。

`network-filter-review.json`保存官方v6.8 native-amd64接口class字段及完整源码SHA。
TN-only socket/socketpair/accept/recvmsg等不被原四类选择，ioctl有TD但未知provider FD
效果仍未解释。没有声称这些接口实际出现在旧episode中。

完整execution model/第一阶段继续 **OPEN**，未授权变换或12110容器关联。
