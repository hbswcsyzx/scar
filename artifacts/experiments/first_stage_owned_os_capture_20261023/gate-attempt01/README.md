# Attempt01: bounded full Python-observer capture failed closed

2026-10-23，唯一实际target运行，原目录保留，不覆盖。runner **exit1**，CLI **241**，
owned strace真实return **-15**：OS_BYTES预算触发后自建process group SIGTERM，**不是
target正常退出**。wall46.96s/RSS427600KiB。未发布archive/profile/coordinates或成功资格。

新owned Popen/actual argv/intent/native关联与运行镜像回执已实际产生；运行镜像OBSERVED，
SHA准确匹配安装strace。原target native仅到WAITING_FOR_TORCH，CPU计算尚未开始。

唯一OS档64,048,967bytes，准确SHA与两个128KiB有限样本在`failure-summary.json`。
原完整raw仍在本地capture/os/；大文件可重建证据不应因目录-f被无意全部stage。完整raw
仅额外做一次stream byte hash，**未做全行语义扫描**，没有全局getpid计数。
末尾有限样本的2182完整calls全部是getpid；源码说明call_edges.profile与
call_operands.profile在event/path筛选前调用getpid，因此Torch import每个profile事件
产生大量观察器系统调用。parent的proc镜像只读一次，50ms stat轮询不在target trace中。

这验证预算守卫没有冒称成功；不是所需端到端资格验收PASS。旧full-profile必需artifact
规则未放宽，没有伪造空calls/operands。后继仅在root审查显式native-only collector profile
后才能另起fresh gate，不能抬本门预算重用目录。source freeze/producer/log/time/实际负
返回、原样本及native未关闭状态均保留。
