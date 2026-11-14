# 当前状态

**第一阶段未完成；当前只做建模、建图和读回。没有应用加速比结论。**
LeWM未修改；本机无可用GPU，外部CPU testcase为Sunfish、Gray–Scott、Cirq。后端约定仍为C++20 / 算子ABI v1。

## 当前按层推进

| 层 | 已实现 | 尚未通过的部分 |
|---|---|---|
| 输入识别 | F0字节、F1 token、F2语法、F3作用域/编译对应 | 版本化材料须按当前producer验证，旧收据不重签 |
| 共享局部图 | 表达式、函数、类、分支、循环、deferred正文；原端口和world | 局部图不等于真实跨层连接完整 |
| 跨层连接 | 静态接口及实际CodeID/CALL、native/callback对应 | root/import路径、恢复实例及全部协议的必需关系尚未统一闭合 |
| 状态/资源 | binding/content/effect接口及CPU、DRAM、存储、GPU接口 | 库存不等于实际placement、allocation或transfer证明 |
| 组合/存储 | 原ID分片组合、按需展开、入口查询和独立读回 | 整图验收仍受上述缺口阻挡 |

实体为Operation / Value / StateLocation / Region / Resource；函数和循环共享正文，不按迭代unroll。
未知字段、条件关系、缺失规则、缺边和查询预算停止分别记录，不互相替代。

## 本轮：修正“按样例补线”的方法

- **Implemented：** 从真实类型定义机械枚举69种指令、41个Enum域/316个值，以及C3的12个role、4种projection。没有按workload名称派发。
- **Implemented：** C1三个开放分类字段已收为Owner/Scope/EvaluationRegion的封闭Enum；字符串wire不变，未知值及跨域Enum拒绝。
- **Implemented：** 独立连接契约穷举20个region引用字段，区分子图入口和控制目的地；环境handle与五类正文入口分别保原ABI。分母来自类型声明，不共享producer的边枚举。
- **Verified：** 新前端完整24阶段已通过，41.972s；140份recipe、541条指令、188个region，190/190必需局部入口关系、7个正文接口通过。原材料在artifacts/current/experiments/connection-layer-current/frontend/。
- **Verified：** 新门槛检查既有Sunfish、Gray–Scott的局部recipe，分别6906/6906、1392/1392关系通过；这不是旧材料在新producer下的完整重新准入。最终独立重放7193份recipe、8488/8488关系，22.576s。
- **Verified：** 6项针对性检查通过，包括“producer及旧validator同时漏分支，新门槛仍拒绝”的反例。未扩展为大量测试。

原Sunfish/Gray组合流程已完成，433.226s/647.588s；这是原版本的组合与读回结果，非当前整图闭合证明。
原Cirq静态材料有173单元；真实补采689个CodeID、5719 CALL、35请求有直接caller，8/8流完整、零丢弃。
原发布中5719 CALL全有对应，但root等整类关系缺口未被该旧门槛识别。
其独立reader已检查100个interface分片，后续全目录重复检查过慢；已停止本次SCAR自有验证进程，保日志，未标记通过。
C1声明已更新，旧producer材料保留原收据；新完整验收需要重放，不能手改hash。

## 下一步

先以完整协议类型域定义统一跨层入口/出口契约，再按契约接静态正文与动态选择，机械核对每个必需参数、环境、world及完成关系。
root/import、class、evaluation request、普通/可挂起正文不能互相伪装成普通函数；对整类关系实施，不再逐程序补丁。
随后核对状态/资源接口与入口到输出的读回。上述各层通过后才报告第一阶段完成；不新增detector或optimization backend。

可复核实测收据集中在artifacts/baseline/formal-frontend-results.json；建模方法见[ARCHITECTURE](ARCHITECTURE.md)，实体关系见[MODEL](MODEL.md)。
