# 当前状态

**第一阶段未完成；当前只做建模、建图和读回。没有应用加速比结论。**
LeWM未修改；本机无可用GPU，外部CPU testcase为Sunfish、Gray–Scott、Cirq。后端约定仍为C++20 / 算子ABI v1。

## 当前按层推进

| 层 | 已实现 | 尚未通过的部分 |
|---|---|---|
| 输入识别 | F0字节、F1 token、F2语法、F3作用域/编译对应 | 版本化材料须按当前producer验证，旧收据不重签 |
| 共享局部图 | 表达式、函数、类、分支、循环、deferred正文；原端口和world | 局部图不等于真实跨层连接完整 |
| 跨层连接 | 静态接口及实际CodeID/CALL、native/callback对应 | 已实现通用root/import路径、共享正文和条件恢复接口；广域实测、具体恢复实例仍待验收 |
| 状态/资源 | binding/content/effect接口及CPU、DRAM、存储、GPU接口 | 库存不等于实际placement、allocation或transfer证明 |
| 组合/存储 | 原ID分片组合、按需展开、入口查询和独立读回 | 整图验收仍受上述缺口阻挡 |

实体为Operation / Value / StateLocation / Region / Resource；函数和循环共享正文，不按迭代unroll。
未知字段、条件关系、缺失规则、缺边和查询预算停止分别记录，不互相替代。

## 本轮：统一正文与跨层连接

- **Implemented：** 五类正文入口统一读取原scope、参数、world和全部完成端口；沿原模板连接遍历同code-scope的子图，不按调用或循环迭代复制。region/step引用带完整unit、template限定。
- **Verified：** 一次通用语言样例涵盖五类入口：15个共享接口、4个跨模板suspension、8个恢复入口。初版只扫描单模板漏掉suspension，已修正为共享图遍历，并加针对性回归检查。
- **Implemented：** 新连接器枚举全部已记录frame进入；优先复用原CALL映射，其他opcode以原CodeID、PEP657位置和作用域得到条件source-operation候选，不按应用名称派发。前后dispatcher保留未知副作用；内层返回不当成外层结果alias。
- **Verified：** 自动准入依赖后，真实trace的14/14次进入全部对应正文，13个共享activation、11个共享接口；126个必需端口、555条双向关系及13个无关返回Frame拒绝通过。初次读回因context_pop调用错误失败，已修正；原失败报告保留，未改成通过。
- **Implemented：** 端口规则分母来自IR的全部GlobalPort字段；输入、saved引用、完成、handoff均逐项核对。未知字段与缺边分别记录。新接口分片接入frontend及统一build。
- **Verified / Open：** 真实生成器trace的17个入口/恢复Frame、212个端口、2117条双向边通过；16/30次进入有源码对应，另7次项目内generic factory/嵌套正文、7次外部源码进入仍待对应，未宣称完整覆盖。
- **Running：** Sunfish正在按当前协议重新执行完整前端、自动依赖准入及动态接线，不重跑原应用。

入口命令：`scar body-interfaces --catalog DIR --out DIR`；`scar body-activations --catalog DIR --trace TRACE --project-root ROOT --out DIR`。
复核：`scar body-activations --read DIR --graph-check --out REPORT.json`。

此前Cirq173静态单元、689 CodeID/5719 CALL及Sunfish/Gray结果保留原收据，不冒充本轮协议下的完整验收。
本轮接口/观察表位于artifacts/current/experiments/body-interface-current/及body-protocols-current/。
无优化backend新增，无LeWM修改，无应用加速比结论。

## 下一步

先完成当前协议在真实CPU案例中的独立验收，再核对状态/资源及入口到输出的整图读回。
通用代码对应仍需审计generic compiler wrapper及lazy evaluator等C3角色；具体generator/coroutine实例与resume PC保持显式未决，不能冒充已实测绑定。
随后核对状态/资源接口与入口到输出的读回。上述各层通过后才报告第一阶段完成；不新增detector或optimization backend。

可复核实测收据集中在artifacts/baseline/formal-frontend-results.json；建模方法见[ARCHITECTURE](ARCHITECTURE.md)，实体关系见[MODEL](MODEL.md)。
