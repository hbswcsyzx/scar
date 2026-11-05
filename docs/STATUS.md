# 当前状态

**第一阶段未完成；只开发建模、建图和查询，不进入化简或代码生成。**
当前为 NORMAL_SUCCESS、CPython 3.14.7；软件边界到算子/外部动作接口，应用异常/引用清理暂缓。
后端设计固定为 C++20、算子 ABI v1、执行计划 schema v1，尚未交付代码生成器。
本轮未运行 LeWM、未 import torch、未采集 Tensor 数值，原仓库未改；下述时间都是 SCAR 自身耗时。

## 已建立的结构

| 层 | 已验证范围 | 尚未代表什么 |
|---|---|---|
| F0–F3 材料/词法/语法/绑定 | 866 源，原字节、官方前端字段、作用域与 binding 可追溯 | 不证明依赖全集或运行分派 |
| F4 共享子图 | 882,537 模板、889,242 子接口；3,385,528 操作、4,645 循环、24,159,357 边 | 函数和循环不按执行次数 unroll |
| F5 跨层接线 | 调用、参数、namespace、属性、容器、语言协议和原生接口已实现条件接线 | 全域来源传播尚未收敛，不能宣称完整 |
| F6 值/状态/资源推理 | 已有类型及分片/查询接口 | 逻辑来源、内容版本、shape/bytes 和寿命尚未全面贯通 |

模型仍为 `artifacts/current/static/`，manifest SHA：
`601e929904dc7481693f4a0747b7e01269ecf6d1302ff1efec072627c288aba0`。
849 份 .py 与 17 份 .pyi 分开；声明不当作运行实现。
`queries/normal-graph-complete/`引用两个 store，压缩边表共 575,718,843 bytes，小索引 231,760 bytes；不复制正文。
全分片收据/父引用已核，CEM 与 torch.nn.functional 的强类型查询已过；不是全 2,416 万边独立重放。

## 本轮修复与未通过项

以下路径相对 `artifacts/current/queries/`；原收据不改写，实现版本保存在 Git。

- **Implemented / Verified：属性接口。** GET/SET/DELETE/IMPORT_MEMBER 保留原 receiver、数据及 world 端口；property accessor 复用函数接线，setter/deleter 无数据返回边。私有名沿原 F3 投影。字段、类及模块 namespace 分型并保留 descriptor/MRO 条件。已在 `739cfb3b` 提交。
- **Implemented / Verified：参数 admission。** 原实现把 PARAMETER_INTERFACE 误作普通 STORE，漏掉 formal→lexical binding。现沿原 C2b resolution 接线并同步 private 签名；不按 self 名称猜类型。849 源新增 31,270 条绑定，其他记录计数保持，生成 192.42 秒：`normal-link-facts-parameters/{result,verification}.json`。
- **Verified：LeWM 局部路径。** CEM 新增 27 条参数绑定；原先为 0 的 property 访问现有 8 条连接，涉及 horizon/action_dim/dtype，原属性 ABI 核查通过。证据在 `normal-targets-parameters/verification.json`。它不代表整个 solve 已接通。
- **Rejected：全域固定点验收。** 参数接通后，传播达到 20,000,000 事件仍余 479,425；没有启动后续绑定/资源重建，也没有授权变换。该轮 500.55 秒：`normal-targets-parameters/result.json`。
- **Implemented：内部事实压缩。** 合并消费者不区分的 external_value 来源标签及无序 lookup history；来源边、原端口和限定符号保留，不授对象/内容等价。小依赖环核查 2,176→128 事件，投影事实与原结果相同：`parameter-transfer-quotient.json`。全域仍触及预算、余 610,387，522.32 秒；**未解决全域规模瓶颈**：`normal-targets-parameters-compact/result.json`。

**Observed：有界诊断与稀疏索引。** 5M 事件时有 5,054,983 条事实、3,751,331 个非空端口；external history 最长仅4，尚不支持其组合爆炸的推断。
最大合流来自 unittest.mock 的 self：431 个 instance 加一个 unknown。证据在 `parameter-propagation-diagnostic/result.json`。
只读 defaultdict 访问改为 get，避免数百万空集合；新跑在 2M/20M 的事实及队列计数与旧结果相同。
新跑显式限定 50M，传播443.84秒、含写出650.03秒，仍余2,961,039：`normal-targets-parameters-sparse/result.json`。
本次固定点验收仍 **Rejected**；不再提高该轮预算，不启动后续绑定/资源重建。
旧动态适配器 `source_invocations.py` 保持原样；静态接线使用 `source_function_connections.py`。

## 已定位的下一条缺口

**Observed：依赖准入预算截断。** 当前 import 图已保存装饰器的导入请求，但依赖库存按名称排序、查询 4,096 个模块后停止；
9,843 个请求中包括 torch.autograd 的后续请求未查询，相关源码未纳入，所以 factory→decorator→solve 来源链未闭合。
这是缺材料，不是装饰器等于原函数。真实端口、import ordinal、预算与 SHA 在 `dependency-admission-audit.json`。

后续按顺序：

1. 将声明图与入口驱动的激活/来源求解分开：保留全部函数/循环模板，沿原控制/调用接口提出传播需求。当前 solver 对全部模板登记调用、种入未知形参，缺少入口激活约束；不能把所有库/测试函数当执行根。先明确形式接口再实现，不按库名裁剪。
2. 将上述需求接到通用依赖续查，在新派生范围准入缺失源码，复用原 ID/分片；不覆盖冻结模型、不写业务专用装饰器规则。
3. 重新接通原生接口与资源关系，再推进 F6 和统一入口/全图验收。

最后通过的原生/资源基线在 `739cfb3b` 与 `*-attributes/` 收据：2,839 绑定定义、498 算子接口、14,691 返回类型关系；
17,630 资源来源依赖、2,637 条条件目标关系。硬件图包含 NUMA CPU/DRAM、GPU/设备内存、SATA/NVMe/存储端点共 12 节点/12 关系。
这些不是实际 allocation、placement、copy 或 kernel 观测，不能作 LeWM 加速比。

动态层后续按未决接口限量补证据，设置时间/次数/新事实预算，复用循环与函数模板；不保存每轮 Tensor 内容。
达到采集目标不等于证明全部路径；该自动采集/停止策略目前是设计约束，尚未实现。
