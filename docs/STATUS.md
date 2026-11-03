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
`fae4ac89c9b1f41a0a8e20c8fe3d4b4c57b0aeeacb93555fbbef2596048c275d`。

| 范围 | 数量 |
|---|---:|
| 源码单位 / 词法入口 | 863 / 36,168 |
| 有规范图的入口 / 主体产物 | 8,095 / 8,825 |
| 无主体产物声明 | 27,343 |
| 规范操作 | 1,263,395 |
| CALL 分片 / 已枚举调用 | 6,697 / 35,747 |
| 有条件目标候选的调用 | 270 |
| 压缩分片 / 总大小 | 21,641 / 2,440,741,530 bytes |

旧 CALL/class/import 发布仍只覆盖原 basis；新增源码及主体未重跑全量静态链接。
source/body expansion分别保留PRIOR_SOURCE/BODY_BASIS_ONLY覆盖，不能用旧索引代表最新闭包。
图规模、调用枚举结束都不证明完整建模。

## 实际核验

外部 CEM probe 使用人工 quadratic cost、2轮×4候选、CUDA输出 `[1,2,2]`；不是训练模型或episode。
81次CALL均有类型事实，61个METHOD_DEF；原29条OTHER中28条已补实际原生描述符信息，余1条NumPy dispatcher。
原22次缺口已闭合：自动追加1个版本核对通过的外部文件及3个body，修正CPython多行链式CALL/属性位置对应。
81次调用均对应原静态CALL，Python函数接口7条（含两次normalized receiver）；不靠名称或行号猜目标。
144行CALL仍保留0/1隐式前缀条件，不把monitor arg0当源码receiver或声明defaults当当前值。

复用保存trace离线建立61个原生调用协议接口，共享18个模板；模板按ABI/参数形状共享，实际callable作输入。
442条协议声明边：137参数、61目标、183状态、61正常返回；全图接口568边，全部通过公共双向查询。
异常引用包保留适配缺口，61条已知异常world出口独立接通；协议端口不生成native Invocation或完成观测。
目前图只表达Python侧调用协议与条件C ABI声明，原生实现体、实际C参数和kernel尚未连接。
本轮材料追加→body→接线→协议发布92.36秒，fresh重放63.82秒；v4导出119,978 bytes。
原21,631个分片、原unit行及calls/classes/imports publication保持，LeWM和trace未改、未执行目标。
旧协议basis已正确失效，新协议重验通过；工具耗时不是workload性能或加速比。
证据：`artifacts/current/queries/lewm-native-callables/{source-expansion-run.json,graph-source-joined/validation.json}`。
本轮材料两例19.87秒、多行/Unicode对应例16.53秒通过；旧source/basis/参数接口仍可读。

CEM189行循环已有492操作、6,343成员端点、30回边端口及控制/状态边界，查询129.63秒；
证据在 `artifacts/current/queries/lewm-observed-calls/loop-boundary-result.json`。效果与资源仍未闭合。

## 缺口与接下来的顺序

1. **材料与局部降低**：当前3个Python接口未闭合（2个库文件材料缺口、1个无直接入口）；还需隐式返回。
   无捕获全文件指纹的库文件不能冒充历史版本，可先静态建当前版本子图，再按CodeID限定作用域对应。
   模块`{}`的admission/validator及模块Assert等局部降低尚有缺口，不能用函数Assert能力替代模块支持。
2. **继续跨层接线**：已知Python receiver与原生协议端口已支持，仍需类调用、延迟体、C参数/实现体、
   异常包适配及runtime/kernel关系；C ABI条件声明不代表已进入实现或实际copy。
3. **联合推理**：接通逐地址状态、别名、效果、逻辑值provenance与Tensor属性反馈，
   不把同对象/同Storage或SSA转发当作内容不变证明。
4. **资源及整图覆盖**：补Python→native/runtime/kernel和CPU/GPU/DRAM/HBM/storage/stream
   的可控制边界，覆盖加载→推理/规划→保存；不展开OS FD表或指令。

验收必须同时覆盖实体、结构、跨层连接及字段/效果精度；不能用一次局部查询或某次运行代替整程序完成。
