# 第一阶段研究：Python引用槽→ETO引用编号

2026-10-20。**CPU原理实验通过；不是生产collector或完整程序建模验收。**

产品基线d825a69，conda lewm / Torch2.13.0+cu132。`case/app.py` 是不依赖SCAR的
外部CPU testcase；`probe.py` 复用已有 CallEdgeRecorder 弱引用token和
TorchDispatchMode，只调用一次实际func，不启用旧Session的invocation/_version系统。

## 机械连接方式

唯一nonce的 `torch.autograd._record_function_with_args_enter(name,*tensors)`
将真实Tensor参数交给现有ETO serializer，随后用对应exit关闭。输入/输出分开
marker；“输出marker”的Tensor仍存于marker.inputs，不伪造native outputs。
sidecar按同一nonce/槽位保存已有Python weak token。双方共同持有provider自己
编码的同一观察，因此无需以_cdata、shape、变量名或Tensor值猜编号。

本次没有生产代码修改，也没有为LeWM写规则。原型直接读取recorder内部active/
_reference用于研究；生产集成应增加窄接口、所有权和预算，不能直接照搬该原型。

## Observed / Verified

- 5次实际dispatch，10个marker，6个Python Tensor weak token。
- 两处重复实参保持两个有序槽，但正确指向同一引用。
- view使用不同Tensor引用编号而共享storage地址映射编号；未据此宣称allocation
  生命周期、alias完整性或同内容版本。
- 原地写前后Tensor引用编号相同，结果确实变化；未将同编号当成内容不变。
- 一次应用调用下记录到5个包装调用上下文。按真实caller/ancestor链均回到该
  应用调用；返回locals中的view/result/loss token与dispatch输出观察一致。
- 普通结果、原地写结果及autograd梯度检查通过。没有强制no_grad或保存Tensor内容。
- 真实provider父节点是 `PythonDispatchMode`，其上层才是 `aten::view` 等；没有
  假定marker包住原ATen，或把marker的直接parent错误认成原operator。

`probe-result.json`、`audit-result.json`和原始JSON/JSONL均保留。CPU进程8.62秒，
peakRSS830,924KiB，exit0；包含Torch导入，不是workload benchmark。stderr保留
provider启停消息。原始数据约104KB，没有Tensor逐轮数值。

## 首次审核失败与修正

`audit-initial.py`/`audit.initial.stderr.txt`保留错误假设：要求所有marker的保留
上下文是同一个invocation。实际中Torch的 `_disable_dynamo.<locals>.inner` 是每次
dispatch独立发生的包装调用，五者的真实caller都指向应用调用。原型已明确把该
上下文声明为retained ancestor，不能把它提升成直接caller。

修正审核为沿真实已保存caller/ancestor链验证，未重跑目标、未删除包装调用，未
将多个InvocationID合并。输入输出marker也按真实ETO祖先链保留，未凭名称补边。

## Proposed：生产实现的门槛

1. 复用call recorder唯一的身份/弱引用目录，提供有界、只读当前frame上下文接口；
   区分direct/ancestor/missing、截断和恢复片段，不另开Session计数器。
2. collector持有mode、marker nonce、sidecar的生命周期和独立预算；只弹出自己
   所有的栈顶mode；异常、early close、foreign mode不改变原行为。
3. 固定provider格式导入marker槽，保存实际祖先/子树；marker名字不能产生大量
   假静态函数定义。未知subclass/symbolic/其它线程范围如实保留。
4. 先通过以上反例，再接LeWM真实采集。仍不产生LogicalVersion、纯性、ready或
   变换许可。此实验未覆盖这些边界，不能直接打开生产采集。
