# 当前状态

**第一阶段尚未完成。当前只做静态建模、建图与查询，不进行程序变换。**
NORMAL_SUCCESS / CPython 3.14.7；软件边界到算子/运行时API。后端设计 C++20、算子ABI v1、计划schema v1。
本阶段未运行 LeWM、导入 torch 或采集目标运行数据。以下耗时均属于分析器。

## 已落实

| 层 | 当前范围 |
|---|---|
| F0–F3 | 866材料：849 Python源与17 stub；原bytes、全部词法/语法、scope及binding |
| F4 | 882,537共享模板、3,385,528操作、4,645循环、24,159,357边；函数/循环不按调用或迭代unroll |
| F5 输入 | schema6，22,171代码scope组；独立factory依赖加入后852单元，不复制原facts正文 |
| F5 局部接口 | 852分片；8,750 iteration、709 deferred body、9,361 mapping模板、1,362 merge协议；48 worker实测68.80秒 |
| F5 接线 | 入口按需激活；参数/捕获环境/world/返回、构造/属性及同步generator；DIRECT/CLOSED_PACK/SYMBOLIC_PACK |
| F5 发布 | source-target schema12，READ_SELECTOR_V1；字段按allocation来源/class/member区分；content按相同目标邻域分解 |
| 静态字段 | 原端口literal/type/open有限域，每端口最多4个literal；已接参数/默认值/数据返回、模块成员、属性及容器内容关系，保原表行与条件 |
| 入口及builtin | 脚本输入契约；按namespace/reference解析compile/exec接口、默认参数、caller context和条件code值流 |

基础模型 artifacts/current/static/ 的manifest SHA：
601e929904dc7481693f4a0747b7e01269ecf6d1302ff1efec072627c288aba0。
压缩边表575,718,843 bytes；小引用索引231,760 bytes。本轮没有重建F0–F4。
原生声明/资源旁表已有CPU/NUMA DRAM/GPU/设备内存/SATA/NVMe候选关系，尚未做当前版本全链路重验。
引用、对象、storage、逻辑内容版本互不等价。所有may关系均不是唯一值、实际执行、纯度或变换合法性证明。

## 当前证据

以下路径相对 artifacts/current/queries/；旧结果保留其原commit及收据范围，不冒充当前读取器结果。

- **Observed / Verified：** entry-incremental-fixed/ 完整写出一次100M预算结果，严格读回通过：274加载单元、2,388活跃scope、155,674调用候选，frontier仍6,327,332。2,503.55万content关系存为11,370因子，整个结果约154MiB；总3746.02秒，发布293.75秒。它是预算前沿，不是固定点。inspection.json记录当前scope与候选概况；高密度热点包含matplotlib，粗粒度may合并仍需审查。
- **Verified：** entry-delta-selector-4m/保16张非content表及51,570条唯一(source,target,container)依赖与旧前缀相等；旧key标签依赖通知先后，已统一为read selector，不声称旧带key集合相等。默认值直连不广播为容器内容。
- **Implemented / Verified：** StaticPackShapes已接主路径：不可变escape/write/update/merge证明只计算一次，每次仍检查全部子包open及顶层values。pack-shapes-world/核全部51查询/顺序相等；单fixture核空包、escape、子包opening及后续污染。重复查询微基准约63倍，仅此协议。
- **Verified：** entry-pack-shapes-4m/verification.json核接入缓存后的18张发布表记录数与decoded SHA全部相等，并通过当前严格读取器；总126.76秒。primitive/循环/source接口的针对性检查通过，不据此宣布整图收敛。
- **Implemented / Verified：** 原生绑定重算现复用852接口摘要。binding-interface-wiring/核真实World的48 iteration及2 body，封死F4恢复入口仍通过，plan_reads=0；reader接受精确receipt并拒绝错误receipt。仅构造/读取检查，非全量native图验收。
- **Implemented / Verified：** scalar-values-world/保66个原operation、8条条件推导，单源字段固定点约2秒；4个端口发生有限域宽化。没有把singleton may集当must常量。
- **Implemented / Verified：** script-launch-current/保实际启动命令输入、原F0/F2/root及2个初始namespace读取端口。argv/environment是可变位置的初值，未列出的环境仍未知。
- **Implemented / Verified：** launcher-source-execution-current/verification.json核compile/exec两边界、一个编译上下文及一个code-use；原owner、actuals、worlds保留。mode来自原F2 literal，flags0/dont_inheritFalse/optimize-1及声明process0/inherit16777216分别记录。局部alias与shadow源码检查通过；尚未解析payload或激活exec body。
- **Implemented / Verified：** scalar-graph-world-policy/verification.json核真实World/Policy字段层：52操作、964关系组、9,455原端口字段、6条条件推导，53.07秒；压缩/解码收据及父表行、参数/返回和外层条件逐项核对通过。字段队列清空不等于4M父图固定点；未声称must常量。共享namespace/content使用线性分组；world/state、参数包及deferred creation不冒充标量引用。
- **Implemented / Verified：** scalar-graph-entry/verification.json核当前4M父图全部已准入的274单元：2,824操作、31,857关系组、646,856字段、696条件推导；构建192.64秒，完整typed流式读回148.11秒，压缩结果约16MiB。父图仍是前沿，不宣称整程序收敛。
- **Implemented / Verified：** launcher-source-text-current/保13路径表达式、5路径候选及原read_text调用；自动连到eval.py的原F0文本候选。默认UTF8、无symlink重定向、版本保持均保条件，编码/newline解释独立于PEP263；尚未绑定compile变体/body。
- **Observed：** 4b5ac5b9版本的连续接线求解已启动，launch为entry-pack-fixed.launch.json；使用--until-fixed-point，不因固定事件上限从头重算。结果以同名log/result为准，尚不能据启动记录宣布收敛。
- **Verified：** launcher-compilation-context/仅编译捕获bytes，optimize0/1/2均确认继承annotations会改变eval常量区/code_digest。相同path/bytes不足以硬接旧F4 root。有效future位不能直接OR历史feature目录位。

## 后续顺序

1. 参数包缓存已接入，继续求解至已准入工作队列清空；支持 --until-fixed-point，避免在固定事件上限退出后重算前缀。固定点与整程序覆盖分开验收，不新增优化backend。
2. 有限字段与原跨调用/内容关系已接通，继续补pack投影、捕获环境字段及generator值规则；审查跨调用合并产生的过宽候选。字段层与父图分别验收，不把slice当完整程序。
3. launcher的F0文本条件候选已建立；继续补compile payload、编译context variant和exec root绑定，再接YAML/CLI配置。当前求解入口仍为eval.py；variant缺实现，不能谎报为内在runtime UNKNOWN。
4. 贯通并验收当前native算子/资源/逻辑值及版本关系；YIELD_FROM/AWAIT等driver仍有明确obligation。最后按源码、边界和资源分母审计第一阶段；不凭计数或固定点宣告完成。

入口：python -m scar.analysis.source_interface_build --facts <facts> --out <interfaces> --jobs 48；
python -m scar.analysis.normal_targets --facts <facts> --interfaces <interfaces> --entry <entry.py> --out <fresh-out> --until-fixed-point。
