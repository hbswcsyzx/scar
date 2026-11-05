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
| F5 入口求解 | 按需加载；已知普通函数可在签名接受条件下激活；DIRECT/CLOSED_PACK/SYMBOLIC_PACK分开，生成器创建与恢复分开 |
| 命名空间规则 | 模块或接口声明支持其为namespace才继续限定名；普通对象属性保留原操作和端口，不凭字符串拼出 namespace |

原端口、别名及已有事实保持；私有名/参数名沿原 F3 投影。参数 admission 修复新增31,270条连接。
同一alias允许多个code_scope按OR准入；原C1 environment与code_scope不混用，inline comprehension复用外层code_scope。
静态接线使用 `source_function_connections.py`，旧动态适配器 `source_invocations.py` 未改。

当前模型仍为 `artifacts/current/static/`，manifest SHA：
`601e929904dc7481693f4a0747b7e01269ecf6d1302ff1efec072627c288aba0`。
压缩边表575,718,843 bytes；小索引231,760 bytes引用原store，不复制正文。

## 最新真实结果

路径相对 `artifacts/current/queries/`；当前source-target schema9。旧收据仅授其原版本/范围的证据。

- **Implemented / Verified：** 未知参数包不再阻断已知普通函数体。`ArgumentProjection`记录元素/余项与原包关系；条件默认值、签名接受条件及OPEN demand保留，不用包对象冒充元素。两个通用源码测试15.78秒通过，包含生成器不提前执行与必定不成立签名拒绝；目标源码未运行。
- **Verified：** `entry-symbolic-packs-fixed/verification.json`强类型读回10表，核对489个symbolic连接/1,638条投影。`update_wrapper`接通，eval scope0–4均条件激活。该850单元输入的4M事件前缀仍有208,137队列项，非固定点。
- **Verified：** 由原inventory的material946/947机械准入`_instantiate2.py`和`_internal/utils.py`；`source-dependency-frontend-instantiate/`完整31阶段569.23秒。`facts-entry-factory/`引用852单元，复制事实正文0 bytes，原manifest SHA未变。
- **Observed / Verified：** 最新`entry-factory-symbolic/`求解259.38秒，4M事件、frontier134,410；1,981活跃scope、274按需加载单元、9,846调用候选，其中426个SYMBOLIC_PACK。`verification.json`核对入口eval:94与模型loader的实例化调用均连接新源码原body并可展开。仍非固定点，不能称完整建图。
- **Inferred / Verified：** `python-bindings-symbolic-packs/verification.json`核对54份原生声明接口、2个调用位置/4个empty、zeros条件候选。输入为上面的850单元前缀；传播同样在4M预算停止。它们不是实际执行、分配或GPU kernel观测。
- **Verified：** `software-resources-symbolic-packs/verification.json`核对294条条件资源候选、4条operand来源及既有12节点/12关系的CPU、NUMA DRAM、GPU/设备内存、SATA/NVMe与存储端点；源目录范围850，物理placement/copy未获证。
- **Implemented / Verified：** 同步GENERATOR+YIELD已接创建→iterator→advance。真实图的World._run_iter/body scope24已由advance接通；yield、sent和return/exhaustion分别保原端口，当前world不从creation保存。三项源码核查22.75秒通过。YIELD_FROM/AWAIT/ASYNC_YIELD及显式驱动方法仍保obligation。
- **Verified：** `entry-generator-parallel/`的852单元/4M事件运行：32个真实spawn worker、125个并行计划任务；总耗时555.74秒，前版721.36秒，单次配对约1.30倍，仅SCAR分析器。12张既有表解压摘要逐项相同；frontier168,070、2,001活跃scope、274加载单元，仍未收敛。模板池已关闭，首次读取与发布前后父材料核对保留。

所有求解都保留目录、未决需求和预算前沿。共享formal/heap的may-union可能混合不同调用；绑定条件不证明路径可满足或内容身份。晚到的封闭形状若反驳旧symbolic条件，当前仍保条件式记录，尚无路径反驳传播。

## 下一步顺序

1. **继续接通策略调用与其数据来源。** World._run_iter已恢复；WorldModelPolicy.get_action及solver仍未完整贯通。沿实际receiver/字段/调用原端口定位，保留未完成的delegation/await驱动接口，不因看到generator就激活全部body。
2. **配置/反射目标与依赖补图。** factory源码已接通，但配置_target_及YAML组合仍未投影到cfg；不能凭CEM名称猜实例。继续消费真实模块需求，保未知目标和条件。
3. **求解前沿与数据/状态精度。** 当前预算未收敛；调用上下文、namespace版本、逻辑来源、内容版本、shape/bytes、alias和寿命仍需贯通，不能只增加预算或拿计数充当完成。
4. **统一入口与完整覆盖核查。** 数据/权重加载→规划/模型→环境/保存输出及资源关系全部贯通后，才验收第一阶段。

并发入口：`python -m scar.analysis.normal_targets --facts <facts> --entry <entry.py> --out <fresh-out> --jobs 32`。
默认上限min(32, CPU affinity)，可用56核；独立模板由多进程解析，工作数按任务懒启动，事实合并仍由协调进程处理。

动态采集采用静态模板加有限补证，按未决接口设置时间/次数/新事实预算，不保存每轮Tensor内容；自动停止策略尚未实现。
第一阶段完成前不新增优化backend、不变换LeWM，也不报告尚未测得的LeWM加速比。
