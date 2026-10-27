# 全量源码重建：普通完整校验与持久 body 检查点

状态：**原运行已退出2，最终 inventory 未发布**。耗时33分49.09秒；失败原因为
最终JSON超过256,000,000字节的独立报告写上限，不是源码构造崩溃。
原stdout保留 `call report exceeds independent write byte ceiling: 256000000`。
1627次真实body返回的检查点均已保存，其中840次有图、787次保留null graph；
decoded检查点合计513,803,391字节。日志与原图未改写。

后续恢复实验位于 `../first_stage_full_inventory_restored_20261023/`：按原队列及
原输入逐项核验并复用原materialized返回，不再重lower；在ProgramInventory返回后、
`to_dict()`之前改用manifest/per-source/per-component分片，body直接引用本实验原
检查点。最初1GB单JSON方案已被替代且未执行。两次状态分别记录，不能把恢复写成
此原命令已经成功。

`run.sh` 固定最新成功的272038 LeWM trace、environment profile、256文件、
4096 body、100000 aggregate operations。自动发现范围，不提供业务函数名单或 IR。
底层采用普通完整校验 lower，未放宽任何未知状态、源码重放或构图预算。

实验包装器 `run_progress.py` 只观察原 prepare/lower 返回值；不改变 body 调度、
参数、算法、图或异常。每个返回值原样保存 graph/metadata/interface/structured，
失败 body 仍保存 null graph 与缺口。临时文件完成后原子发布，index记录原始内容
SHA/size、源码、序号。检查点是实际局部返回结果，不是完整 ProgramInventory。

如果任务中断，已完成的局部图仍可查；只有公开命令最终成功后才有完整inventory。
与此前89842 capture 的旧局部统计不直接相加。本轮没有执行目标或新增测试套件。
