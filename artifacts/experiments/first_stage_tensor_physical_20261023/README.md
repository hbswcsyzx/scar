# Tensor物理连接：现有CPU案例的一次实采

2026-10-23。**Observed / Verified：有界CPU范围通过；完整LeWM建模仍OPEN。**

`run.sh` 使用现有外部case/app.py，不修改case/LeWM，不增加测试套件或额外forward。
通过公共CLI `trace --call-operands --execution-evidence --tensor-physical` 采集一次。
run.json返回0；结果、view、autograd及预期异常保持原案例断言。
完整原始call/dispatch/native/physical记录保存在trace/。

## 实际结果

- 35个真实marker、39个有序Tensor槽；全部接同provider allocation_id。
- 34条Allocation receipts，17分配/17释放，17个provider物理代次。
- 独立原档审核核39槽全部shape/strides/device、重复槽3处和view槽1处，provider
  epoch与receipt的storage pointer一致，全部输入raw SHA/字节数匹配。
- native/dispatch/physical导入后公开IRBundle校验通过，新增17个allocation、39个
  StorageRegion以及观察范围内的USES_STORAGE边；原OperationInstance和逻辑版本
  集合完全相同，不把同一allocator活动重复计作一次执行。
- drop/error/frontier为0，owned mode退出；marker唯一性与参数槽完整性通过。

`audit.py` 只离线读取同一原档，不重执行目标。第一次audit因未设置PYTHONPATH
导入失败，日志保留在audit.attempt1.*；设置原worktree路径后通过。随后增加了
原dispatch source line/context精确核验，仅重读原档再审核；前一次通过结果保留
为audit-before-source-line.*，最终结果为audit-result.json。

## 身份和结论边界

物理身份为该profiler result/capture/process/device内的allocation_id。TensorID=0
是实际值且保留；它不充当LogicalValueID。Tree Result地址、RecordFunction线程
token、RF id、Linux TID分别保存。offset来自同marker同槽的ETO descriptor，shape/
strides/device逐项核对；不会从numel推分配大小。对象→storage只在该marker观察点
成立，不授长期绑定或缓存权限。

本次没有OS process-membership收据，capture_membership_verified=false；生产联合
导入还需exact nonce/raw SHA/O_EXCL进程证据。旧Kineto逐allocation对应、外部alias
写入、logical version、Materialization及resource ready仍未证明。无LeWM加速结论。

采集使用record_shapes/profile_memory=True、with_stack=False、trace_only=False、
adjust_timestamps=False。provider/集成patch和具体命令均已保存；这不是clean benchmark。
