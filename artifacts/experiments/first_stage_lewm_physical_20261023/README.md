# 原LeWM命令：补齐Tensor/provider allocation字段

2026-10-23。状态：**Observed / Verified：完整episode采集成功、收据关闭与共同坐标通过；联合模型导入另验**。
run.sh保持已成功原pusht policy权重/完整CEM/单episode配置；新增通用采集flag
`--tensor-physical`，不修改LeWM或添加业务优化规则。Git身份、原始日志、OS
strace与所有collector/provider原档均独立保存。不使用插桩墙钟计算加速比。

本次只在完整关闭后导出同一profiler的event_tree物理字段，不重跑forward，
不存Tensor数值。命令returncode0、episode成功并生成视频，collector完整性及原始
成员核验通过；`first_stage_joined_physical_20261023` 正用import-capture连接同一
Run/Process/Thread与原ValueGraph物理记录，当前尚未完成。
物理allocation_id、LogicalVersion、ETO token、RF与TID不互换；未知关系仍OPEN。

上一份record_shapes=False的实际采集保持不变，新字段不从旧原档伪造。CPU案例
物理桥实际通过是启动本次的前置证据，不作为LeWM GPU验收的替代。

## 实际结果

- 未修改LeWM（前后git status干净），原revision `f70fed80288462ca4d006cb3607ec6da6eaa851f`。
- 原命令保留完整CEM/一episode配置，capture nonce `72816598bfa183a810428fe30a7873ff`。
- 100,438 entered calls，39,796 dispatch，119,388 dispatch sidecar rows；零drop/error/gap。
- 物理导出79,592 marker nodes、109,288有序Tensor槽；108,682槽通过物理epoch资格并已导入，606槽未资格化。
- 52,853 allocation receipts（37,449 birth、15,404 free），traversal/marker qualification完整，gaps/error为0。
- 独立coordinate preflight核1,170,866,107 raw bytes、266members、253 OS artifacts/
  1,067,773 lines、5processes/252threads，含新物理文件的原hash/O_EXCL成员证据。
- 仅自有生成原档261文件做hash往返压缩：1,170,850,470 raw bytes →54,862,125 gzip bytes；
  只在校验后删除相同plaintext副本，`archive-index.json`保留原logical URI与SHA。
- 插桩wall643.2943s、日志CEM138.3862s。均不是clean benchmark，不报告加速比。

record_shapes会保留部分Tensor引用，可能改变本次观测到的free/lifetime；这些数量
不能用于宣布原程序内存泄漏或原始生命周期不变。provider物理epoch不是LogicalVersion，
`physical-frontiers.json`逐实际metadata核606槽全部为零元素形状的空CPU Tensor，provider
allocation ID为92，但storage_data_ptr为None，不是缺少ID。没有伪造非零分配或读取
Tensor内容；空表示的模型接口仍需与逻辑/物理生命周期区分。逻辑来源、写失效、
ready及完整资源关系仍保留OPEN。
