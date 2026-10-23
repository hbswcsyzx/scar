# 完整LeWM物理证据：同capture联合导入

2026-10-23，**Observed / Verified：import exit0，独立实档审核PASS**。
第一阶段完整程序模型仍 **OPEN**；没有执行新的目标、forward、backend或测试套件。

## 原输入与公共入口

原始成功capture来自 `../first_stage_lewm_physical_20261023`，target PID369749，
nonce `72816598bfa183a810428fe30a7873ff`。原episode/video已成功；本次只离线读取
其hash往返压缩原档，不混用272038的source绑定或旧native实例。

`run.sh`实际执行公共 `scar import-capture --schema-contracts --bundle-partitions`，
独立budget为2GB raw bytes/2M lines；脚本、base revision、所有参与module SHA、
CLI/pipeline diff、stdout、stderr与time均保留。

## 实际结果

| 内容 | 已观测/核验结果 |
| --- | --- |
| 共同capture坐标 | 266成员、1,170,866,107 raw bytes；5进程/252线程；253OS artifacts/1,067,773 lines |
| 原dispatch桥 | 39,796 dispatch，79,592 markers，109,288有序Tensor槽；480祖先缺失/383未资格化叶保留 |
| 新物理桥 | 108,682槽接37,506 provider物理allocation epochs；52,853 allocation receipts |
| 原ATen schema | 100 schemas/481 formal ports；467,756 QUALIFIED与175,022无schema槽，effects仍PARTIAL |
| 原native对应 | 310,410 CPU RF对应、24,082 runtime→GPU对应；74,574 memory lifetime points |
| OS导入 | 12,648 OFD、12,649 handle代次、570观测handle结束、1,064已连接IO |
| IRBundle分块 | 2,259,781原记录；195chunks，2,982,489,343decoded bytes→145,084,073stored bytes |
| 运行成本 | `/usr/bin/time` wall18:59.69，peakRSS7,308,272KiB；离线导入成本，不是LeWM加速 |

原bundle经producer公共 `assert_valid` 后逐条存储，不构造完整 `bundle.to_dict`。
manifest最后发布；旧OS/native-memory protocol snapshots保留兼容，不能宣称所有
输出已分片。这里2.98GB是未压缩原记录大小，不是读取或保存Tensor内容。

## 独立实档审核

`audit.py`只读取产物，不重建native/源码，不执行目标。实际wall7.87s、peakRSS
331,712KiB，`audit-result.json`为PASS：

- 209个输出artifact的stored SHA/bytes全核。
- 全部37,506物理epoch和108,682物理region经公开BundlePartitions reader核完整
  chunk decoded/stored收据，并逐项核原physical report的ID/marker/slot/allocation。
- Run/Process/Thread与共同coordinates完全一致；25,867个OS点坐标检查保留861个
  unresolved process点。
- 原逻辑versions/materializations均为0，没有将物理identity变成逻辑内容等价。
- 其余bundle表本次只额外核stored SHA；完整语义校验来源是producer的公共检查，
  本审核没有冒称独立重跑全bundle codec。

## 剩余必需断口

606个未物理资格化槽经原档 metadata核实全为空CPU Tensor，有provider allocation
ID但storage pointer为None；见原capture的 `physical-frontiers.json`。没有伪造分配。
物理epoch不是LogicalVersion，不代表内容、可变状态、alias写入或ready已闭合。

OS还有152,564条outside_fd_profile记录；共享/继承、mmap、设备协议、完整使用者/
生命周期与ready仍未闭合。source/call actual-formal/return/environment也未因
同一Run或marker祖先引用自动成立。`capture-model.json`的五类coverage obligations
继续OPEN，不用于授权优化或报告加速比。
