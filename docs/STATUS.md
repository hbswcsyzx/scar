# 当前状态

**第一阶段未完成：仅做程序建模与动静协同建图，不做化简或目标变换。**
当前步骤按 [六层流程](ARCHITECTURE.md) 执行，LeWM 仅是外部 testcase。

## 已有能力

- 版本化源码、AST/符号表、协议识别、规范 CFG/SSA/状态及分片存储。
- 共享函数主体、循环构件展开、初始/回边/world 端口和词法嵌套，不复制调用或迭代。
- 统一跨分片依赖查询、条件调用/环境/导入/class 关系、有限值推理及区域边界查询。
- 按需 CALL 采集、原代码身份对应、观测参数/返回接口，以及缺主体自动增补。

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

## 本轮实际核验

选中原 CEM `solve` 的189行循环：492个操作、6,343个成员端点；30个内部回边端口、
121个异常终止、231条输入、30条消费者边、469条状态记录、123条控制路由均保留。
原180秒预算内完成，启动准备15.35秒、边界查询113.39秒，总计含导出129.63秒。
这是一次 SCAR 工具耗时，不是 LeWM benchmark；所有预算前沿为0，但状态/效果/资源等仍未闭合。
规范化导出281,209 bytes，JSON读回相等；主图和LeWM源码未改。
证据：`artifacts/current/queries/lewm-observed-calls/loop-boundary-result.json`、
`loop-boundary.json.gz`；7个循环的成员展开另见同目录 `loop-construct-result.json`。

本轮消除重复core验证、metadata/namespace解码及factory输入重建，保留原收据、源码/compiler、
namespace和关系核验。预算中断时不再丢弃已知边界，覆盖明确为PARTIAL。
相关codec、输入复用、路由、factory、边界及循环用例通过；最后两项为2 passed / 8.99秒。

已有真实 CEM probe 使用人工 quadratic cost、2轮×4候选、CUDA输出 `[1,2,2]`，
不是训练模型或episode。保存81次观测、59条原CALL绑定、2条函数接口/7个参数端口；
原采集286,403 bytes。本轮没有重跑采集、episode或目标性能实验，没有新的加速比结论。

## 缺口与接下来的顺序

1. **第4层动静接线**：2条观测函数接口目前仍是独立DTO，未进入共同图查询。
   下一项用原静态端口＋run scope＋InvocationKey＋attempt/event anchor接线，重验原trace、
   实际目标/入口/退出及源码端口；不注册裸context=None全局边，不猜loop迭代号。
2. **主体及跨层关系**：补未展开构造/主体、receiver/default/variadic、类产物来源、
   循环实例与携带状态、正常/异常/清理出口；动态未覆盖路径继续保留静态条件。
3. **第5层联合推理**：接通逐地址状态、别名、效果、逻辑值provenance与Tensor属性反馈，
   不把同对象/同Storage或SSA转发当作内容不变证明。
4. **资源及整图覆盖**：补Python→native/runtime/kernel和CPU/GPU/DRAM/HBM/storage/stream
   的可控制边界，覆盖加载→推理/规划→保存；不展开OS FD表或指令。

验收必须同时覆盖实体、结构、跨层连接及字段/效果精度；不能用一次局部查询或某次运行代替整程序完成。
