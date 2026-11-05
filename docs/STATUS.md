# 当前状态

**第一阶段尚未完成。范围仍是建模、建图与查询，没有进入程序化简或代码生成。**
NORMAL_SUCCESS / CPython 3.14.7；边界到算子/外部动作接口。后端设计为 C++20、算子 ABI v1、计划 schema v1。
本轮未运行 LeWM；下面的秒数是 SCAR 静态工具耗时，不是 LeWM 运行时间或加速比。

## 已完成并验证

| 层 | 当前范围 |
|---|---|
| F0–F3 | 866 份源码材料、词法/语法、作用域及 binding；849 .py 与17 .pyi 分开 |
| F4 | 882,537 共享模板、3,385,528 操作、4,645 循环、24,159,357 边；函数/循环不按调用/迭代 unroll |
| F5 作用域事实 | schema6，22,171 代码作用域组；全部849源强类型读回、事实范围覆盖、15,179函数及2,052类的 body_scope 原ID核对通过 |
| F5 入口求解 | 入口/导入/源码调用/类创建驱动激活，按需加载；模板声明不激活函数体；参数包与延迟恢复留下明确需求 |
| 命名空间规则 | 模块或接口声明支持其为namespace才继续限定名；普通对象属性保留原操作和端口，不凭字符串拼出 namespace |

原端口、别名及已有事实保持；私有名/参数名沿原 F3 投影。参数 admission 修复新增31,270条连接。
同一alias允许多个code_scope按OR准入；原C1 environment与code_scope不混用，inline comprehension复用外层code_scope。
静态接线使用 `source_function_connections.py`，旧动态适配器 `source_invocations.py` 未改。

当前模型仍为 `artifacts/current/static/`，manifest SHA：
`601e929904dc7481693f4a0747b7e01269ecf6d1302ff1efec072627c288aba0`。
压缩边表575,718,843 bytes；小索引231,760 bytes引用原store，不复制正文。

## 最新真实结果

路径相对 `artifacts/current/queries/`；实现/父材料SHA及范围保存在收据中。

- **Verified：** `normal-link-facts-scopes/` 生成201.95秒；`fact-scope-verification/result.json` 汇总4个独立分片读回，覆盖全部849源与22,171组。
- **Verified：** `normal-targets-entry-namespaces/` 对真实 `eval.py` 入口求解53.13秒，409,439事件、队列0；按需加载162单元、激活1,215作用域，保留完整849源目录。仅当前已准入约束收敛，不证明全部路径或依赖闭合。
- **Observed：** eval目前只激活scope0，业务函数体仍停在Hydra装饰器返回链；有109个body需求（102参数包、7延迟恢复），以及未决模块/调用。没有把空callee或未解析 `__call__` 静默当成不可达。
- **Verified：** `namespace-transfer-rule.json` 的属性循环收敛，原字段关系与声明过的provider成员保留，不授对象/内容等价。
- **Observed：** `source-admission-entry/` 将9639条模块需求归并为501个模块：177个source已有材料但未准入、262个查询尚未执行、20个native候选、35个记录根下未找到、7个未进入旧import索引。该工具只关联原需求与原材料，不据文件存在选择实际import目标。

曾经全库无差别传播触及50M预算；入口约束接通后又发现 `inspect` 中外部符号名错误扩展，20M时约20.5M事实为external。
修正的是namespace类型依据，不是靠删除源码或抬高预算掩盖问题。历史失败收据保留，不充当当前验收。

原生分析已按scope增量接入，schema4的增强source连接/激活/未决需求已强类型读回：`python-bindings-entry/verification.json`。
该轮91.88秒、411,389事件且队列0，46份算子声明接口；活跃native调用0，不能据此宣称业务推理已接通。
`software-target-resources-entry/verification.json`核对264条条件资源关系、849个源文件位置与12个硬件节点；实际operand来源0，未建立physical placement/copy。
硬件目录已有NUMA CPU/DRAM、GPU/设备内存、SATA/NVMe和存储端点共12节点/12关系；它们不是实际allocation、placement或copy观测。

## 第一阶段还差什么

本轮已实际准入一个缺失源码单元：`source-dependency-frontend-hydra-main/`完整经过31个前端阶段，69.03秒；旧模型指纹未变。
通用driver只接受原材料索引，不包含业务规则。`facts-entry-extension/`引用两个父store保留850单元、复制事实正文0 bytes。
`entry-extension-targets/verification.json`核对eval的两个调用已连到新增源码的原body，并能跨父展开；原点偏移不变，415,783事件/队列0，54.30秒。
业务体仍未激活。下一断点已定位：当前类调用只接`__init__`，漏自定义`__new__`；另有varargs/kwargs formal容器及已知pack准入缺口。
这是通用构造/调用协议问题，不能通过跳过装饰器或将`__new__`假作默认分配来解决。

1. **接通入口的构造/调用协议。** 按类/MRO及descriptor条件派发`__new__`，连接真实分配/初始化及返回实例条件；同时给varargs/kwargs建立容器和已知pack准入。保原state顺序，不制造源码端口或业务专用分支。
2. **继续依赖补图和其它未决协议。** 消费真实材料关联，沿入口继续到policy/planner/model；再接生成器/await、外部可调用对象和动态分派。动静态补证不能把未观测当成不存在。
3. **贯通数据、状态与资源推理。** 逻辑来源、内容版本、shape/bytes、alias及寿命还没有全面接通。这是未完成功能，不是只差测试。
4. **统一自动入口和全图验收。** 检查从数据/权重加载，经模型与规划，到环境/保存输出及相关资源的跨层关系；明确未解析字段、未准入材料和缺规则。

动态采集采用静态模板加有限补证，按未决接口设置时间/次数/新事实预算，不保存每轮Tensor内容；自动停止策略尚未实现。
第一阶段完成前不新增优化backend、不变换LeWM，也不报告尚未测得的LeWM加速比。
