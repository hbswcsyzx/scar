# LeWM新环境/原生配置采集：FAILED before dataset load

2026-10-22，产品00bf1d9；不修改LeWM、conda、CUDA或mount。第一阶段OPEN。

run.sh原样使用曾成功的pusht checkpoint命令、25步预算与25 goal offset；
trace/run.json returncode1、wall176.7369s。错误是当前主机没有历史
/gpu4-share/data/byx/lewm_data，创建目录PermissionError（上层root拥有）。
默认NFS根亦未挂载，本地cache无dataset/checkpoint副本；已向用户询问可用路径，
不擅自挂载或改目标。原git status before/after均为空。

该attempt未进入推理，没有episode/success/性能结论。它保留启动、import与失败
路径的真实建模证据，不能替代先前成功的完整episode原档。

## 新collector实际输出

function环境272事件：209 dispatch、63 entry、零gap/error/drop；pending结束0。
profiler receipt明确记录experimental_config.adjust_timestamps=False，CLOSED且
failures空。公共import-native实际导入本窗口148条CPU memory receipt，84 births、
64 frees、20窗口末open；148条ordering_qualified，仍CONDITIONAL（仅profiler
receipt、canonical stages/effects及physical lifetime未建立）。无GPU compute证据。
独立raw/ValueGraph/lifetime audit PASS，见native-audit.json；这不是追加测试套件。

## 低磁盘保留

retain.py对184个自己生成的原档逐个gzip、解压hash/size相符后删除原始重复。
32,092,711 bytes → 2,628,477 bytes，索引retention.json保留原档SHA/行数；
现有reader可从逻辑原path解析.gz。原close-time manifest保持不变。
