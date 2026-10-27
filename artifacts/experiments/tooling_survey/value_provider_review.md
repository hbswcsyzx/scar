# 事实归属与不可合并身份：最小检查单

2026-10-16。基于现有代码、文档及已保存小探针；本轮只读，未抓网、采集或测试。
**P0 来源声明已实现；下列 adapter/动态对应/P1 边界尚未完成。**

## 1. 现成事实填哪里

| 来源 | 当前 Program core 的规范落点 | v2 的证据/物理落点 | 不能直接填成 |
| --- | --- | --- | --- |
| FX / Export 图 | 每份表示独立的 Region/Operation；Value.origin；逐 args/kwargs occurrence 的 Use；P0 ProviderEnvelope/Region/Binding 引用来源。 | 若需索引，OperationDefinition/ValueSlot 只作来源视图，不另维护一套可修改 actuals。 | Python 完整效果、LogicalValueID、对象/存储身份。 |
| Export signature / call spec | native 输入/输出分类与树结构；通过 P1 连接已有 entry/exit、call/invoke、ReferenceValue/StateAccess，不能提前冒充已接通。 | provenance/对照证据；变换阶段原样保留。 | BUFFER_MUTATION Tensor payload = StateVersion；parameter target = 当前实例/不变常量。 |
| ETO | 执行证据来源及观察范围；不直接绑定为静态 Operation。 | OperationInstance 的 occurrence/parent/process/thread；Tensor tuple、shape/stride/type/device 保留来源 metadata；有生命周期依据后才连接 StorageRegion/Materialization。 | ETO TensorImpl ID = Python ObjectID；data-pointer ID = allocation generation；同 tuple = 同内容版本。 |
| Profiler / Kineto | 物理事实仍走执行证据，不把 key_averages 当调用。 | OperationInstance 时间/范围、MeasurementRecord、runtime/kernel/copy 证据和限定资源关联；保留 clock/correlation 原字段。 | host return = GPU ready；`.to()` = DMA；时间邻近 = 数据依赖。 |
| Profiler event tree / memory graph | 可补现成 allocation/schema-may-write 来源，不替换有序 core Uses。 | StorageAllocation 的 provider-scoped allocation 依据、输入描述与 memory-version metadata；缺字段保留缺失。 | 聚合 TensorKey 边 = full actuals；memory version = LogicalVersion；其 id = ETO id。 |

v2 `ValueObservation.version` 必须引用独立建立的版本；没有依据时保留原始 metadata/
明确 provisional capture，不能为填 schema 伪造跨观测等价。Materialization.ready_event
也不能填成普通 host 返回时间。

## 2. 不合并身份

- source/FX 定义 ≠ 动态 occurrence；同函数可调用多次。
- raw / functionalized / decomposed：各自 provider、Region、Operation、Value 身份。
- SSA ValueID ≠ ObjectID ≠ AllocationID ≠ LogicalValueID/ValueVersionID。
- Python object ≠ TensorImpl；同 storage 的 view 可有不同 offset/stride/对象。
- ETO ID、profiler TensorID/AllocationID 各有 provider/run/window 语义；不裸 ID join。
- 内容相同 ≠ alias/对象身份/梯度/RNG/异常合同相同；样本相同仅可预筛，不能证明相等。

## 3. 最小采集选择与可替代部分

1. **先消费已有 raw Chrome CPU 事件**，保留 profiler 动态活动与 aggregate 的区别。
   下一次确有必要采集时，优先同次 ETO+profiler，不再次执行目标采同一份数据。
2. **ETO 可替代已覆盖的自制 operator 输入/输出描述采集**
   （`RecorderMode`/`session.torch_dispatch`）；event tree 可补已有 allocation 元数据。
   验收前不删除 Python 对象对应、write guard 或生命周期 witness；它们职责不等同。
3. module/call hooks 只为 provider 未给出的实际 Python 引用/调用边界保留；
   `TensorObserver` 只补对象/lifetime/provenance 缺口，不重复导出所有已存在 descriptor。
4. **默认不保存参数/activation 内容，不逐迭代复制/哈希 Tensor。** 明显变化的数据
   沿写依赖/版本分析；确有候选需精确核对时，才显式、限额、短期使用 checkpoint。
   checkpoint 和 profiler 的引用/同步开销必须单列，不能当 clean benchmark。

仍需 SCAR 连接：source↔occurrence、actual↔entry、namespace/content 当前 state、
跨 copy/transform provenance、mutation 写回及异常后态、alias/grad/RNG 合同、
资源生命周期/ready。P0 声明与 profiler 元数据均不自动补齐这些关系。

## 4. 最小验收反例

| 反例 | 必须保持的结果 |
| --- | --- |
| `f(x,x)`、返回 `(y,y)` | 两个有序 Uses，可引用同一 Value；不只导 users/parents 集合。 |
| 两次 add_ 或 NumPy 共享 buffer 写；shape/前缀不变 | 不因 metadata/样本相同复用旧逻辑版本；外部写缺口明确。 |
| view 与 base；raw/functionalized 同名节点 | 保留独立定义/对象与 alias 关系，不合并表示身份。 |
| Export mutation payload + 第二次写回失败 | payload 不是 state token；写回经真实结果流，Raise 保留已完成写后态。 |
| 同设备 `.to()`、异步 H2D 后 host 返回 | 无物理 copy 不记 DMA；无完成证据不记 ready。 |

详细证据沿用已有 `runtime/`、`reassessment/memory-provider/`、`export_dynamo/`；
P1 接线范围与边界见[集成设计](../../../docs/MODELING_INTEGRATION.md)。不新增实验。
