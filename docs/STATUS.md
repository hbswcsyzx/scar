# 当前状态

**第一阶段尚未完成：当前只做程序建模、建图与查询。**
NORMAL_SUCCESS / CPython 3.14.7；软件边界到算子/外部动作接口。后端设计为 C++20、算子 ABI v1、计划 schema v1。
本轮仅执行 SCAR 静态分析器，没有运行 LeWM、导入 torch 或实施程序变换。下面的加速只涉及分析器。

## 已落实

| 层 | 当前范围 |
|---|---|
| F0–F3 | 866份材料，849 .py与17 .pyi分开；原字节、词法/语法、作用域及binding |
| F4 | 按源码单元存储882,537共享模板、3,385,528操作、4,645循环、24,159,357边；函数/循环不按调用或迭代unroll |
| F5 事实 | schema6，22,171代码作用域组；849源的强类型、事实范围及body_scope原ID核对通过 |
| F5 局部接口 | schema1，852单元分片；8,750 iteration、709 deferred body、9,361 mapping模板/1,362 merge协议；沿用原端口和owner |
| F5 接线 | 入口按需激活；参数/捕获环境/world/返回；DIRECT/CLOSED_PACK/SYMBOLIC_PACK；构造协议、属性及同步generator驱动 |
| F5 发布 | source-target schema12；实例字段保原站点/owner/class；content按相同目标邻域分解，key统一为读取selector |
| 独立字段层 | 复用既有builtin求值器，原端口挂条件literal/type/open字段；每端口最多4个literal，反馈循环宽化；尚未接入跨调用求解 |

原端口及共享body保留；函数引用不是内容版本，may候选不证明运行路径、对象/数据身份或变换合法。
同一源码分配点可返回多类，字段按allocation来源、receiver class和member区分。YIELD_FROM/AWAIT等未完成驱动仍保obligation。
factory依赖可由原inventory独立走前端，再以不可变引用加入852单元facts集合；没有复制已有事实正文或修改基础模型。
已有原生声明/资源旁表保留算子条件候选、CPU/NUMA DRAM/GPU及设备内存/SATA/NVMe关系，不声称实际placement/copy/kernel已发生。

基础模型为 artifacts/current/static/，manifest SHA：
601e929904dc7481693f4a0747b7e01269ecf6d1302ff1efec072627c288aba0。
原压缩边表575,718,843 bytes，小引用索引231,760 bytes；本轮均未重建。

## 最新实测与证据

以下路径相对 artifacts/current/queries/。

- **Verified：** source-interfaces-full/完整覆盖852单元目录；48个真实worker完成局部接口投影，68.80秒，累计worker CPU 2,431.63秒，摘要正文2,680,976 bytes。每源独立写出；复用原F4收据，没有重跑F1–F4或改变基础facts6。
- **Verified：** source-interfaces-world/verification.json独立核全部48迭代、2body、29mapping/3merge的原F4端口、world、owner及挂起筛选；与旧产物已有的4迭代/1body子集逐项相等。4项针对性源码检查27.88秒通过。
- **Verified：** 旧schema10的entry-local-interfaces/诊断前缀：274按需加载、2,001活跃scope、9,801调用候选、10,059字段内容边；4M事件后frontier168,070，非固定点。interface-equivalence.json核当时17张关系表与entry-batched-read-write的记录数、压缩及解码SHA完全相等。
- **Observed：** 接线137.67秒，含本次全部局部接口预处理共206.46秒，旧同输入/同4M预算为428.86秒；单次总耗时少约51.9%。并非隔离重复benchmark或LeWM加速比。
- **Verified：** F5接线完整计划解码/恢复、suspension材料发现及模板池均为0；从摘要读取22单元的35迭代、20body、28mapping接口。输入压缩片仍核字节收据。接线约20.98秒入口准备、89.23秒传播、23.55秒主发布；逐表耗时可查result。
- **Verified：** content-factors-real/verification.json：旧57,048条关系→1,814连接因子，展开集合/计数及查询过滤完全相等；compressed1,986,616→357,762 bytes。只改变存储表示，不改原程序。
- **Implemented / Verified：** 更完整求解曾在20M后因下降索引投影环递归失败，诊断留entry-content-factors-fixed.failure.json；现用内容增量队列和保约束的位置宽化处理。百万索引自环/双环单fixture5.61秒通过，另5项相关检查31.75秒通过。因子对当前关系无损，宽化本身是may过近似，不能称与旧精确位置完全相等。
- **Observed：** 旧完整诊断在80M检查点后由我主动SIGINT中止、exit130；原因是接入已验增量实现，中断栈具体定位consume→apply_item重复receiver×全部历史key扫描。日志及entry-content-cycle-fixed.interrupted.json保留；未发布result、未证明固定点，不是一次成功建图。
- **Implemented / Verified：** 独立DeltaContainerFlow将每次write引起的iterator/copy全历史重扫改为增量通知，首次订阅仍完整回放。container-delta-entry-prefix/verification.json按原2M分段准入，在4M事件核17张关系表的记录多重集，全部新增0/遗漏0；仍是诊断前缀，不证明全图收敛。传播82.30秒，旧同前缀89.23秒，未做隔离重复整体benchmark。
- **Implemented / Verified：** 增量实现现已接主路径，动态key只处理本次新候选，read订阅去重；内容key采用READ_SELECTOR_V1，消除旧标签对通知顺序的依赖。entry-delta-selector-4m/verification.json：16张非content表完全相等，51,570条唯一(source,target,container)依赖完全相等；带key记录57,048→52,369，明确不声称旧标签相等。schema12严格读回及World原25条字段边通过，总128.85秒，仍非固定点。
- **Verified：** dynamic-key-delta/verification.json用原item ABI、合成500个key和8个receiver：访问1,002,000→4,000；3次中位数2.063→0.060秒，值、邻接及本场景带标签关系相等。34.21倍仅为此协议微基准，不是整个分析器或LeWM加速。
- **Implemented / Verified：** 独立StaticPackShapes把不可变escape/write/update及merge证明与动态open/readiness分开。pack-shapes-world/verification.json核World全部51个pack查询与旧结果/顺序相等；一个源码fixture核子依赖opening、空包、escape与后续污染。5,100次重复查询的3次中位数0.517→0.00822秒；仅静态查询微基准。尚未接入正在运行的producer，不改其代码或重建852接口。
- **Verified：** 旧增量原型container-delta-evaluation/verification.json：World原端口的合成1000次mapping写入，3次中位数0.72615→0.09674秒（7.51倍），2,226带标签关系、值及邻接完全相等；仅为当时协议微基准。当前版本的key语义及新测量以entry-delta-selector-4m与dynamic-key-delta为准。
- **Implemented / Verified：** source_scalar_values.collect_unit在原常量、alias、namespace读写和LanguageOperation上建字段依赖；IR不依赖analysis模块。scalar-values-world/verification.json保World全部66个原operation，得到8条条件推导，单源字段固定点约2秒；4个端口触发有限域宽化。保原operand/result/world，既不激活body，也不宣称must常量、身份等价或变换合法。
- **Implemented / Verified：** source_launch CLI登记实际launcher的原F0/F2版本、root、argv/env及初始globals；script-launch-current/verification.json核原2个namespace读取端口、本地条件字段和codec往返。未提供的环境项保持未知，argv/environment保持可变。入口登记尚未激活launcher或接入完整求解。
- **Verified：** launcher-compilation-context/verification.json：仅编译F0捕获bytes、不exec/import目标，在optimize0/1/2均发现launcher继承的annotations位16777216改变eval常量区及code_digest；因此不能按path/bytes硬接旧eval子图。有效future位从隔离编译结果提取，不能直接OR已强制生效的历史feature目录位。
- **Observed：** entry-field-content-fixed/diagnostic.json记录一次20M事件试跑：传播1060.66秒、frontier1,113,127；已接通World._get_actions原body26，policy调用仍未接通。因旧逐条发布器在内容表输出超过100MB且未结束，主动中止自己的导出；该目录没有完整result，不能作为完整图收据。

## 剩余瓶颈与后续顺序

1. **局部接口层已验收。** 原scope/fact/port分母完整，按单元并行产出；跨单元接线不再恢复F4正文。后续新增依赖可独立补同类分片，不重建既有图。
2. **当前层：完成共享状态传播验收。** entry-incremental-fixed同一100M上限求解继续，已过50M；栈采样定位参数包整单元重扫，静态shape缓存已独立实现并核对，待本次producer终止后接入中央pins和主路径。每30秒栈日志中的Timeout是采样触发，不是程序终止。仍有必要的写×读展开，不能声称并行全局求解或第一阶段已完成。native绑定表schema5尚未重跑全量路径。
3. **随后接静态值字段。** 既有builtin evaluator、有限高度域和单源原端口投影已实现；2+3、字符串拼接及反馈循环fixture通过。下一步将它接入已准入scope的原跨调用/内容依赖，区分条件may字段与唯一值证明；当前独立字段层没有接通调用、import或资源关系。
4. **入口与编译上下文覆盖。** 成功命令入口是run_inference.py，当前完整求解仍为eval.py入口。带收据入口契约已实现；下一步接原read_text→compile→exec端口、匹配或生成编译上下文variant，再接YAML/CLI配置来源。当前eval F4不能冒充继承annotations的编译版本；缺variant是缺实现，不能写成运行字段UNKNOWN。共享formal/heap、逻辑版本/shape/资源、YIELD_FROM/AWAIT等仍未全贯通。

入口：先 python -m scar.analysis.source_interface_build --facts <facts> --out <interfaces> --jobs 48，
再 python -m scar.analysis.normal_targets --facts <facts> --interfaces <interfaces> --entry <entry.py> --out <fresh-out>。
局部接口池默认min(48, CPU affinity)，本机可用56核；worker只读不可变输入、各写本源分片，协调进程汇总收据。
第一阶段完成前不新增优化backend、不变换LeWM、不报告未经测量的LeWM加速。
