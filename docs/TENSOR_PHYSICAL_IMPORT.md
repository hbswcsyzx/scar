# 从marker槽到原ValueGraph物理表示

2026-10-23。**Implemented；一次CPU真实原档核验通过，LeWM/OS生产验收待执行。**
配合 [TENSOR_PHYSICAL_BRIDGE.md](TENSOR_PHYSICAL_BRIDGE.md)。

公共采集：`scar trace --call-operands --execution-evidence --tensor-physical -- ...`。
默认旧采集配置不变；新flag明确开启record_shapes与post-close sidecar。native
manifest先固定，dispatch meta绑定其raw SHA，再导出physical sidecar；export失败
用独立失败收据记录，不回写已关闭的hash链，也不影响原目标返回。

`import_tensor_physical(native_result, observations, metadata, coordinates=...)` 必须
先有同一次原dispatch bridge。它核元数据的schema/provider/PID/nonce，以及三项
原始输入（native manifest、dispatch meta、dispatch observations）的URI/原SHA/
字节数，完整读入独立预算内的sidecar并核final raw receipt。partial sidecar不授
物理关联；已发布报告明确OPEN。严格模式要求共同CaptureCoordinates实际进程
membership；不跟随metadata URI打开任意文件。

每个marker必须在原ETO恰好出现，双方owned marker集合一致；逐项核原dispatch
source line、sequence/phase、Python ident与native TID、有序槽数，以及同槽原ETO
descriptor的shape、strides、device和storage offset。opaque provider token、
TensorID、地址相等本身不建立对应。

新记录落在原模型中：

- StorageAllocation：result/process/device内的provider allocation_id；保存原
  birth/free receipt locator，已观测birth给nbytes，未观测birth保持未知。
- StorageRegion：该marker参数的shape/strides/dtype/device及ETO offset；同一个
  allocation可有多个view/观察，不按相同对象或shape合并。
- USES_STORAGE：原marker OperationInstance→StorageRegion；若原dispatch已有
  合格Python ObjectInstance，再记录观察点限定的Object→StorageRegion。

不制造新的OperationInstance重复计数allocator事件；不添加LogicalValueVersion或
Materialization，不把物理alias当逻辑值相同。原Kineto allocation记录保持独立，
没有公开准确locator就不强行合并代次；CPU返回、free receipt不证明GPU ready。

`import-capture` 增加可选physical阶段；坐标绑定对新文件要求原native声明、
nonce/raw SHA、三项源hash链及target-process唯一O_EXCL creation。没有新flag的
旧捕获仍走原路径。CPU实采无OS收据，因此只验证显式提供原档的一致性；生产
membership、完整LeWM和全软硬件闭包不从该小案例外推。
