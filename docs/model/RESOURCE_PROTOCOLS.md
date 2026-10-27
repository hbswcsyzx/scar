# 静态资源与外部接口协议

本文件规定静态图中的资源要求、状态与库边界，不创建真实资源实例或执行记录。
统一实体见 [MODEL](../MODEL.md)，程序拆分见 [PROGRAM_DECOMPOSITION](../PROGRAM_DECOMPOSITION.md)。
资源关系仍附着 canonical Operation / Value / StateLocation / Region / Resource。
运行结果未知不妨碍描述动态语义；实际设备、地址、传输、完成与成本可以保持 UNKNOWN。

## 1. 资源角色与约束

Resource 描述程序所需的资源角色或类别；使用处连接原 Operation/Region 的端口。
要求可含设备类别、地址空间、容量、读写能力、可达性、共享/独占和生命周期条件。
约束输入来自源码、明确配置或版本化接口合同，不从库名/变量名猜出实际硬件。
静态创建站点可以是符号 freshness/alias 的来源，但不是实际 allocation、句柄或进程实例。
不生成 Invocation、实际 WorkTicket、物理地址、已发生的事件代次或分配 epoch。
对象引用、逻辑数据、资源角色和物理表示分开；不同静态 ID 不证明它们运行时互异。

| 资源类别 | 静态要求与必要状态 |
| --- | --- |
| CPU | 运算/控制/编码执行能力、并发条件、所需 workspace；实际核数/线程/时长可未知。 |
| GPU | 设备/上下文约束、kernel/runtime 接口、队列与同步要求；不展开驱动或机器指令。 |
| DRAM | host 地址空间、容量/对齐、共享、普通或 pinned 要求；不伪造已锁页事实。 |
| HBM/device memory | device 可访问存储与布局/容量要求；HBM 是类别，不把所有 GPU 内存都判为 HBM。 |
| SSD/storage | 容量、可读写、持久化与路径/文件角色；真实介质和布局可未知。 |
| NVMe | 可选的存储访问接口/设备约束；不因文件在 SSD 上就假定 NVMe 或特定拓扑。 |
| file | 名称解析、内容与 metadata 状态、访问能力、打开/关闭和错误。 |
| stream/event | 程序可见队列、流、同步标记和等待范围；不创建实际 stream/事件实例。 |

CPU/GPU/存储可能共享容量、带宽或地址空间；不能仅因类别不同推断互不干扰。
硬件配置未知时保留符号约束；分析不触发设备探测、目标执行或运行采集。

## 2. 操作、状态与完成

每个接口列出有序数据/引用 Uses、读写位置及 footprint、结果和资源要求。
StateLocation 可表达对象/容器 slot、文件内容、offset、buffer、RNG、mode 与外部粗状态域。
状态值及前后关系沿规范控制边传递；资源摘要不复制第二套可独立修改的版本表。
细位置未知时与其可能覆盖的粗域保留 may-alias，不能因没有 selector 就假定独立。
正常/异常出口都携带已发生部分效果的符号后态；失败不等于没有写入或提交。
Host normal return、外部工作完成、内容对消费者可见是不同条件。
使用源码协议和约束表达这些条件，不伪造“已提交”“已完成”或“已持久化”事实。

## 3. 分配、view 与数据搬运

分配接口保留 size/layout/device/allocator 输入、可能失败和新承载空间的符号角色。
同一站点在循环中可多次分配；静态图不把它们实例化，也不把它们合成同一对象。
View 关联原引用和区域几何；shape、stride、offset、dtype 与 alias 条件分别保留。
reshape 等可能 view 或 copy 的接口保留条件分支，不按 API 名字断言实际搬运。
Copy/convert 连接源内容读取、目的写入、布局/类型转换、重叠约束和资源要求。
同设备转换可返回原引用，强制复制或类型转换可走另一分支；未知条件不能抹去这些差别。
相同 shape/dtype 不证明引用、storage、内容或状态版本相同。
释放引用不是立即 free；保留逃逸、借用、finalizer 与资源承载生命周期的条件。

## 4. GPU 提交、顺序与可见性

kernel/runtime/copy 接口作为可展开 Region 或外部 primitive，保留端口和 effects。
提交操作可返回符号工作引用/结果引用；实际执行、完成时间和传输字节量仍可未知。
同一已约束队列的程序次序、跨流 event/wait 与 host 同步是不同依赖。
不能仅由源码先后或 host 返回建立跨流完成边，也不无条件插入 CPU synchronize。
record-event、query、wait、synchronize 各有独立接口及可能失败；布尔 query 结果可符号化。
wait-stream 约束相应前缀，不覆盖对方流未来工作；record-stream 的生命周期作用不同于数据同步。
异步源借用、目的写入和可见性要求延续到相应完成条件，不能由局部变量离开结束。
取消和失败可能保留部分输出、已提交工作及延迟报错，不能自动复位资源状态。
静态图只表达必要顺序和条件，不生成真实活动、时间戳或硬件执行轨迹。

## 5. 文件与程序 stream

路径是符号选择表达式，不等于文件身份；环境、相对根、权限和别名条件须保留。
Open/resolve 连接文件/stream 资源要求、create/truncate/append 的可能状态变化及异常。
Read/readinto 表达读取范围、返回 bytes 或目的对象写入、offset 更新、短读/EOF/失败分支。
Write 表达有序输入、可能短写、内容/长度/offset/缓冲更新；不宣称 bytes 已到介质。
Seek 只更新适用位置状态，不提供完整内容；共享 stream 的访问不能擅自当作独立。
Flush 处理 buffer，sync 是相应持久化接口；二者不可互相代替。
Close 表达 owned 资源释放与可能失败；调用方传入的 sink 是否关闭由合同决定。
包装器、codec、buffer 和底层 file 的关系保留在程序接口层，不恢复 Linux FD/OFD 表。
pipe/socket/内存 stream 等有不同能力和外部状态；同名 read/write 不保证相同协议。
程序显式子进程操作保留命令/输入输出/环境、等待及返回条件，不生成真实 PID 或内部调度。

## 6. 加载、计算与模型状态

Deserialize/decode 从符号 bytes、format、配置及环境生成可能的对象/数据描述。
解析、设备映射、对象构造、用户回调、外部代码加载和失败都需适用接口，不能默认纯。
Load/install 参数把源版本接到对象字段、parameter/buffer/alias 状态与必要 device 要求。
不能以“load 成功”标签替代逐目标状态关系，也不执行加载来得到 Tensor 数值。
Compute/module call 连接数据、参数、环境、hooks、RNG、mode 和相关资源端口。
可解析实现沿原 Region 展开；native 内部用版本化摘要，不要求还原不可控制的实现细节。
in-place 更新、输出 alias、workspace、autograd saved values 和异常分别保留。
没有结果使用者不等于操作可删，外部效果、状态推进和后续梯度 consumer 仍可约束它。

## 7. 编码、序列化与保存

编码器引用、内部历史/缓冲 StateLocation、执行资源和 sink 使用同一 canonical 模型。
Feed 读取输入并更新内部状态，可能产生零个或多个块；不能假定一帧对应一个输出。
Drain/finalize 处理剩余状态，可生成尾部内容或失败；close sink 不保证已正确 finalize。
Serialize/save 连接对象图读取、编码、write/flush/close 及错误出口，保留引用与别名条件。
格式完整性、消费者可读和介质持久化分别表示，host ack 不证明三者均成立。
输入可能被同步复制或异步借用；保留到使用条件满足前的生命周期，不只记录最终文件路径。

## 8. RNG、mode、梯度与外部边界

RNG 是按 generator/device/context 归属的状态，随机操作有符号前后版本。
相同 seed 或形状不使两次调用等价；失败路径是否推进 RNG 由具体合同决定。
train/eval、grad、inference、autocast 与 current device/stream 具有各自作用域和可变状态。
不能由 eval 名称推出关闭 autograd，也不把 mode 简化为一个全局布尔量。
若程序存在梯度消费，保留 requires-grad、view/in-place、saved 数据及梯度累积关系。
未知 callable、native 回调和外部共享写域保留输入/输出、may-effects、异常与资源缺口。
未知效果不写成 NONE；已知接口不等于内部已展开，内部不展开也不等于接口不能建模。
原生库只展开影响程序正确性、状态、资源或成本的必要边界，不扩展驱动、FD 表或指令执行。

## 9. 组合与待实现范围

读取→解码→安装状态→计算→编码→保存，通过同一 Value/StateLocation/资源端口组合。
跨 Region 摘要保留读写、alias、escape、异常、生命周期与完成条件，不能只汇总最终 Tensor。
容量、传输量、耗时和 ready 由符号约束或明确规则推导；无法确定的字段分别保留 UNKNOWN。
现有局部资源类型/接口不构成完整静态摘要；库版本适配、alias 和异步完成规则仍需逐项实现。
未实现摘要保留具体缺口，不能用资源标签数量或空 effects 冒充完整覆盖。
控制/挂起见[控制协议](PYTHON_CONTROL_PROTOCOLS.md)，引用与定义见[数据协议](PYTHON_DATA_DEFINITION_PROTOCOLS.md)。
