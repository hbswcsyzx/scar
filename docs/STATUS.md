# 当前状态

**第一阶段未完成：仅做程序建模与动静协同建图，不做化简或目标变换。**
当前步骤按 [六层流程](ARCHITECTURE.md) 执行，LeWM 仅是外部 testcase。

## 已有能力

- 版本化源码、AST/符号表、协议识别、规范 CFG/SSA/状态及分片存储。
- 共享函数主体、循环构件展开、初始/回边/world 端口和词法嵌套，不复制调用或迭代。
- 统一跨分片依赖查询、条件调用/环境/导入/class 关系、有限值推理及区域边界查询。
- 按需 CALL 采集、原代码身份对应、实例限定的共同图接口查询，以及缺主体自动增补。

## 当前权威图

`artifacts/current/static/manifest.json` 的 SHA-256：
`026a200526cc34964e39c61075a5a8fc73e0e9e491f32c7ad1543cff1d3a8158`。

| 范围 | 数量 |
|---|---:|
| 源码单位 / 词法入口 | 862 / 36,164 |
| 有规范图的入口 / 主体产物 | 8,092 / 8,822 |
| 无主体产物声明 | 27,342 |
| 规范操作 | 1,262,939 |
| CALL 分片 / 已枚举调用 | 6,697 / 35,747 |
| 有条件目标候选的调用 | 270 |
| 压缩分片 / 总大小 | 21,631 / 2,440,159,572 bytes |

旧 CALL/class 发布仍只覆盖原 basis；3个新增主体未重跑全量链接。
`body_expansion.relationship_coverage=PRIOR_BODY_BASIS_ONLY`，不能用旧索引代表最新闭包。
图规模、调用枚举结束都不证明完整建模。

## 实际核验

外部 CEM probe 使用人工 quadratic cost、2轮×4候选、CUDA输出 `[1,2,2]`；不是训练模型或episode。
81次CALL均有类型事实，61个METHOD_DEF；原29条OTHER中28条已补实际原生描述符信息，余1条NumPy dispatcher。
59次对应原静态CALL；另22次未对应：17次缺源码单位，5次原规范CALL不唯一。Python函数接口仍3条。
已支持有入口证据的BOUND/NORMALIZED receiver；真实两次normalized调用因外部成本函数缺材料尚未接入。
144行CALL仍保留0/1隐式前缀条件，不把monitor arg0当源码receiver或声明defaults当当前值。

复用保存trace离线建立48个原生调用协议接口，共享15个模板；模板按ABI/参数形状共享，实际callable作输入。
新增351条声明边：111参数、48目标、144状态、48正常返回；加原82边共433条，全部通过公共双向查询。
异常引用包保留适配缺口，48条已知异常world出口独立接通；协议端口不生成native Invocation或完成观测。
目前图只表达Python侧调用协议与条件C ABI声明，原生实现体、实际C参数和kernel尚未连接。
离线构建51.07秒、fresh重放45.32秒；v4导出84,161 bytes，协议manifest+分片162,984 bytes。
静态manifest、LeWM与保存trace未改，未再次执行目标。工具耗时不是workload性能或加速比。
证据：`artifacts/current/queries/lewm-native-callables/graph-protocols/{summary.json,validation.json}`。
两个通用聚焦案例通过：receiver接口15.91秒、采集→协议图→v4读回/fresh重放14.01秒；旧v1/v2/v3兼容保留。

CEM189行循环已有492操作、6,343成员端点、30回边端口及控制/状态边界，查询129.63秒；
证据在 `artifacts/current/queries/lewm-observed-calls/loop-boundary-result.json`。效果与资源仍未闭合。

## 缺口与接下来的顺序

1. **先补材料/定位缺口**：自动将可用且能与捕获CodeID核对的外部源码纳入同一模型，补必要主体；
   再定位5次规范CALL不唯一。不能手工特判probe、函数名或业务变量，不能为找类来源无限推理。
2. **继续跨层接线**：已知Python receiver与原生协议端口已支持，仍需类调用、延迟体、C参数/实现体、
   异常包适配及runtime/kernel关系；C ABI条件声明不代表已进入实现或实际copy。
3. **联合推理**：接通逐地址状态、别名、效果、逻辑值provenance与Tensor属性反馈，
   不把同对象/同Storage或SSA转发当作内容不变证明。
4. **资源及整图覆盖**：补Python→native/runtime/kernel和CPU/GPU/DRAM/HBM/storage/stream
   的可控制边界，覆盖加载→推理/规划→保存；不展开OS FD表或指令。

验收必须同时覆盖实体、结构、跨层连接及字段/效果精度；不能用一次局部查询或某次运行代替整程序完成。
