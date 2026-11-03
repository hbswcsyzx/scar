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
`0e20fdf697d3a39fc26fd870a908ec356d2161bc185ab6ff908f4da420ec9403`。

| 范围 | 数量 |
|---|---:|
| 源码单位 / 词法入口 | 866 / 36,706 |
| 有规范图的入口 / 主体产物 | 8,098 / 8,829 |
| 无主体产物声明 | 27,877 |
| 规范操作 | 1,264,142 |
| CALL 分片 / 已枚举调用 | 6,697 / 35,747 |
| 有条件目标候选的调用 | 270 |
| 压缩分片 / 总大小 | 21,666 / 2,457,568,321 bytes |

旧 CALL/class/import 发布仍只覆盖原 basis；新增源码及主体未重跑全量静态链接。
source/body expansion分别保留PRIOR_SOURCE/BODY_BASIS_ONLY覆盖，不能用旧索引代表最新闭包。
图规模、调用枚举结束都不证明完整建模。
主体产物包含graph=None诊断；文件存在不等于已有规范主体。

## 实际核验

外部 CEM probe 使用人工 quadratic cost、2轮×4候选、CUDA输出 `[1,2,2]`；不是训练模型或episode。
81次CALL均有类型事实，61个METHOD_DEF；原29条OTHER中28条已补实际原生描述符信息，余1条NumPy dispatcher。
81次调用均对应原静态CALL，Python函数接口9条；不靠名称或行号猜目标。
ABI保留条件布局，不把monitor arg0当源码receiver或声明defaults当当前值。

复用保存trace离线建立61个原生调用协议接口，共享18个模板；模板按ABI/参数形状共享，实际callable作输入。
442条协议声明边：137参数、61目标、183状态、61正常返回；全图580边通过公共双向查询。
异常引用包保留适配缺口，61条已知异常world出口独立接通；协议端口不生成native Invocation或完成观测。
目前图只表达Python侧调用协议与条件C ABI声明，原生实现体、实际C参数和kernel尚未连接。
当前文件只按完整Code限定作用域对应；原plan有文件指纹而冲突时仍拒，未升级父模块/环境事实。
本轮静态模型与trace未改；离线补图/导出82.05秒，v4为130,168 bytes；这是工具耗时，不是加速比。
fresh核验68.00秒：9个接口均选中原正常返回，新增cleanup后的object/world两条边；原136条Python边保留。
18个native模板内容未变，原trace重建与v4读回相等，原return备选及静态providers保持。
证据：`artifacts/current/queries/lewm-native-callables/{cleanup-return-run.json,graph-cleanup-returns/validation.json}`。
局部构建支持模块Dict/动态Assert、单sync子句的有序genexpr filters；filter不在创建时执行。
旧无图诊断可经fresh收据/作用域核验后补建，保留旧owned input；同cache key也不覆盖原诊断，已有图不替换。
本轮4个聚焦用例通过（13.06/28.95/3.23秒），诊断准入收紧后单例7.39秒；未执行LeWM。

CEM189行循环已有492操作、6,343成员端点、30回边端口及控制/状态边界，查询129.63秒；
证据在 `artifacts/current/queries/lewm-observed-calls/loop-boundary-result.json`。效果与资源仍未闭合。

## 缺口与接下来的顺序

1. **组合控制与入口**：_lazy_init的filter障碍已去，当前首堵是with→try/finally→for→try/except。
   普通def-yield仍缺独立创建/恢复适配器，不能接成即时函数调用；这两处已明确报告static rule缺口，未盲目重试。
   编译器跳转/handler合流的返回来源仍OPEN；无条件finally覆盖另有unreachable shim构图缺陷。
   常量折叠Assert、lazy BoolOp等仍需各自适配，不能将上述局部能力当全语言覆盖。
2. **继续跨层接线**：已知Python receiver与原生协议端口已支持，仍需类调用、延迟体、C参数/实现体、
   异常包适配及runtime/kernel关系；C ABI条件声明不代表已进入实现或实际copy。
3. **联合推理**：接通逐地址状态、别名、效果、逻辑值provenance与Tensor属性反馈，
   不把同对象/同Storage或SSA转发当作内容不变证明。
4. **资源及整图覆盖**：补Python→native/runtime/kernel和CPU/GPU/DRAM/HBM/storage/stream
   的可控制边界，覆盖加载→推理/规划→保存；不展开OS FD表或指令。

验收必须同时覆盖实体、结构、跨层连接及字段/效果精度；不能用一次局部查询或某次运行代替整程序完成。
