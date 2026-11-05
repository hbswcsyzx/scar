# 当前状态

**第一阶段未完成。当前只做静态建模、建图和查询，不开发化简或codegen。**
范围为NORMAL_SUCCESS、CPython 3.14.7及当前866份声明源码；应用异常/引用清理暂缓。
软件边界到算子/外部动作接口；后端目标已固定C++20、算子ABI v1、执行计划schema v1，尚非已实现的代码生成器。
本轮未执行LeWM、未import torch、未采集Tensor数值，原LeWM仓库保持不变。下列耗时均为静态工具耗时，不是LeWM性能或加速比。

## 分层进度

| 层 | 当前证据 | 边界 |
|---|---|---|
| F0–F2 材料/词法/语法 | 866源、1,961,177 token、1,511,372 occurrence，原字节及官方前端字段可还原 | 固定输入/profile，不证明运行分派 |
| F3 作用域/绑定 | 七层材料已登记；F3-D组合按866源范围验收 | 条件namespace不是实际对象绑定 |
| F4-B 源码模板 | 882,537共享模板、889,242条子接口，全866源生成并读回 | 函数/循环共享，迭代不unroll |
| F4-C 正常路径边 | 已发布582源的控制/数据/状态/声明边 | 581份.py＋1份.pyi；其余284份源码仍需补齐边表 |
| F5 跨层接线 | 849运行源的调用、容器、namespace、语言运算、原生接口与资源关系已生成 | 调用及效果仍有开放字段，未证明全程序分派闭合 |
| F6 静态推理/统一发布 | 已有分片和查询接口，尚未统一闭合 | 逻辑值、版本、shape/bytes及资源寿命尚未全面贯通 |

当前模型manifest SHA：`601e929904dc7481693f4a0747b7e01269ecf6d1302ff1efec072627c288aba0`。
849份.py与17份.pyi分开；类型声明不充当运行实现。模型目录仍为`artifacts/current/static/`。

## 当前验收结果

下列路径均相对`artifacts/current/queries/`；详细计数与实现/输入SHA保存在结果收据中。

| 输出 | 真实结果 | 生成秒数 | 证据 |
|---|---|---:|---|
| 语言/引用事实 v4 | 80,761调用点；34,569运算＝11,902二元＋16,541比较＋5,425一元＋701原地运算 | 194.11 | `normal-link-facts-language/result.json` |
| 源码目标 v4 | 52,769调用点有候选、18,997有源码目标；63,894连接，含391条实例调用，前沿0 | 289.79 | `normal-targets-language/{result,verification}.json` |
| 绑定/协议图 v3 | 2,839定义；3,575调用点/10,108生成接口候选；498份算子接口；14,691条返回类型关系 | 297.87 | `python-bindings-language/{result,verification}.json` |
| 运算协议 | 794个可推断Tensor操作上3,442条协议证据，含1,650条真实wrapper关系 | 包含上项 | 同上，`language_propagation` |
| 资源来源图 v2 | 17,630依赖＝14,532显式调用＋3,098语言协议；2,637有条件目标关系 | 28.95 | `software-target-resources-language/{result,verification}.json` |

全63,894调用连接及34,569运算接口经过类型读回，实例调用环境/self/world关系核查通过，146.82秒。
绑定及LeWM三源已连接调用/运算的原ABI核查通过，27.54秒；资源表及原实参/receiver/operand/包端口核查通过，24.76秒。
这些是各自声明范围的验收，不是全程序正确性或优化许可。

实现要点：

- 运算selector来自原F2字段；原operand/result/world端口不变。Python协议的正向/反向、NotImplemented、优先级及原地fallback分别保条件。
- `obj(...)`沿类与基类查找`__call__`，支持晚到解析及普通/static/class方法。内部lookup不发布成源码port，不把function写入原对象端口。
- Tensor声明契约、直接赋值别名及C++注册关系可追溯。注册目标按实际wrapper符号匹配，不按业务名或算子同名猜测；stub契约与wrapper依据不表示发生两次计算。
- 19项CEM源运算中，3个乘加操作已产生19条协议证据、11条wrapper关系，自动接到`aten::add.Tensor`/`aten::mul.Tensor`。CEM仍有14个显式调用点的生成接口候选，另有`.to/.cpu/.tolist`声明。
- 同一端口首次取得Tensor类型才触发协议重访，保留各来源记录；没有新增类型到对象/storage身份的证明。
- 原生材料读取按URI/SHA/大小校验并缓存。显式调用和语言协议的资源来源有独立枚举，不伪造SourceCallSite。

本轮还通过了小型通用内存solver核查：实例调用/继承/descriptor、callee不污染、运算反射/原地分支、别名/注册精确匹配、world不进入数据值以及参数包偏移。没有跑冗长测试套件。

“协议声明前沿0”只针对当前794个可推断Tensor操作，**不能外推到全部34,569运算或整个程序**。
其余标量、自定义对象、属性/descriptor及外部函数仍须继续解析。求解达到固定点也不证明这些规则已完备。

## 目标资源与交付边界

`target-hardware/result.json`保留12节点/12关系：NUMA CPU/DRAM、GPU/设备内存、SATA/NVMe及存储端点。
容量为平台报告total；GPU内存不假称HBM，PCIe max不作实测带宽，预算/实际placement/transfer仍未建立。
849份源码有存储端点关系；不记录FD表、缓存行或指令。新资源图没有创建实际ResourceUse或观测到copy/kernel。
`cpp-target/result.json`仅证明本机GCC/安装Torch头文件的C++20编译期语法基线，未证明链接/runtime ABI。

## 接下来按顺序完成

1. **补齐F4-C全域边表**：复用已发布582源，为剩余284源生成边；其中268份运行源码、16份类型声明。建立按原unit查询的统一分片索引，角色分开，不复制函数/循环正文。
2. **补F5尚缺协议**：普通对象的属性/descriptor与自定义协议，手写全局函数、NumPy、模型加载、文件/环境接口。先补原操作ABI，再接定义与效果来源。
3. **接F6值/状态/资源**：常量与符号属性、逻辑来源、状态版本、shape/bytes和寿命；从入口到外部动作汇总覆盖与未决字段，再提供完整自动建图入口。

第一阶段完成以前不增加优化backend、不变换程序。没有完整LeWM episode优化或加速比结论。
历史验收细节保留在Git和原始收据中，本页只维护当前有效范围。
