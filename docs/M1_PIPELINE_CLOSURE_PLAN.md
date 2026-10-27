# R3.3：完整通用流水线的模型组合与 OS 见证

基线：干净 `bccefcfb65dcdba71c050cbbecadd3b2f30f3fa2`。
前门 [R3.2](M1_PIPELINE_COMPOSITION_ACCEPTANCE.md)为 677 项组件、冻结 `31bf2e4`
的 5,011 项全仓通过。本文件是实施计划，不是通过报告。仍属 M0–M2，第一阶段
未完成；不新增 detector、backend、lowerer、LeWM 规则或 GPU profiler。

## 1. 本门完整分母

在同一个 ProgramGraph 与 ExecutionModel 中表达：

```text
root
  load → prepare/materialize → submit → wait/consume → save → flush/close
    └──── 各自原 Region / Use / state / resource / completion ────┘
```

load/prepare/run/save/close 的函数调用要有准确 caller→child activation 与原端口，
而不是将几份独立 fixture 的结果放在同一报告。raw、normalized、computed、
serialized 是独立值/来源；同版本多个物化与同 storage 的 view 保持原独立身份。
输入、参数/必要状态、输出及外部效果根共同列账，不只选择最终 Tensor。

本机见证进一步否定了第一版“save.write 直接产出最终 file endpoint”的模型：
buffered write 接收 8 字节时，绕过 Python 缓冲的同 fd pread 仍看到 0。默认完整
fixture 因此必须分开 CPU buffer Mat 与 file endpoint Mat，由 buffer 状态读取
产生原 DataValue，再通过 flush 的原 Data Use/ContentRead 和 write contribution
连接到文件。最终 Q root 放得晚不能掩盖中间缺边；缺 flush 或过早观察须有反例。
RAISE+pending 路径也必须在 submit 之后、wait/consume 之前选择异常边，不能在
执行完整成功流水线后才用标签补一个异常。这些是实施审查发现，不是验收已通过。

正常、RAISE、partial、pending 与 cleanup 都使用原实际控制路径。同步 host 的
函数返回不填 WorkEnd；WorkOutcome 不填 quiescence、borrow release、handle end
或 persistence。完整 Q 分母仍由 R3.2 保留，facet 目标/基数未定义不在本门偷闭合。

## 2. 独立审查后的实施决定

三份 P0 源审位于 `artifacts/experiments/b1_call_operands/model_pipeline_closure/design/`：
endpoints、pipeline、witnesses。报告区分已有能力、缺口与 Proposed，没有执行测试。

### 2.1 跨同步调用 host 顺序

当前 `point_precedes` 只处理同 activation，导致跨 helper 的 host 写→读只能留下
顺序缺口。使用已校验 CallActivation 派生入口/返回桥：

- caller BEFORE → 准确 entry block 的首个规范操作已捕获 occurrence BEFORE；
- child 实际 RETURN/RAISE AFTER → CALL 的 AFTER，或 INVOKE 的准确 taken EDGE。

入口、首操作、completion 或 actual transfer 未捕获时不任选替代，不默认 NORMAL。
只有准确已知、相同 host thread 才出同步桥。与原 local CFG 联合求路径，保留原
同 activation True/False/None 语义；嵌套/兄弟/递归使用不同 activation，不串线。
桥是原关系的派生索引，不是新事实表；P/V 中遍历计入同一预算。声明路径不证明
runtime 对应，也不连成 GPU terminal。

### 2.2 端点 byte profile

复用 ProviderFactReference、ProtocolSelector 和 ExternalSnapshots.payload，
固定闭合、版本化、限大小的 whitelist profile；不打开 URI 或执行自定义 decoder。
复用 BytePrefixWrite 的原 raw/count/result 校验，将 source buffer 与 destination
endpoint 分开。读取需求范围必须来自独立 consumer 原端口/selector 定义，不能从
producer 的实际前缀倒推。请求 8、实际 4 的差额必须保留。

只有 target incarnation、原 Use/Access、源 Mat/version、请求与实际范围、准确
result/source、完成/状态/顺序链都对上，才解释选定的 byte-prefix/read-after-write
声明关系。profile 标签本身不填 MATCHED；未知动态范围、错 locator/schema、缺源、
别的端点或 alias 都留准确未决/矛盾。Endpoint 不能伪造成 allocation 或 RegionRef。
其它设备/端点协议仍有明确 unsupported 范围；不把 close/flush 解释成持久化。

### 2.3 真实见证

新增两项必需见证，采用独占临时目录和独立子进程总超时：

1. 文件读取→准备→计算→buffered write→flush→fsync-return→close；另有 save 后
   异常、finally close 的路径，分别记录缓冲前后可见数据及实际返回/异常。
2. host 提交包装器 RAISE 时 worker 仍 pending；通过有界事件继续实际部分写，
   再观察 FAILED 与显式 memoryview release。host 异常不代替 work 完成。

真实短写复用既有有界 nonblocking pipe 见证，不再重造；queued cancellation 不是
原 R3 必需分母。Future.result 的超时不能单独保证 executor.shutdown 有界，因此
外层子进程到期终止并等退出，父进程随后只清理自己的 mkdtemp。原始事件/count/hash
保存为机器可读证据，不记录每次 Tensor 全数值，不访问用户数据或共享缓存。

OS 观测和手工模型对应分别标注；不称自动源恢复/native 捕获或电源故障耐久性。
官方协议依据：Python [io](https://docs.python.org/3.14/library/io.html) 与
[os.fsync](https://docs.python.org/3.14/library/os.html#os.fsync) 分别定义缓冲处理和
系统同步；Linux [close](https://man7.org/linux/man-pages/man2/close.2.html) 也不保证
持久化。具体系统返回仍由本机见证记录。

## 3. 自主验收与版本节点

| 节点 | 交付 | 失败条件 |
| --- | --- | --- |
| P0 | 三项独立源审与此计划；明确原图归属。 | 仅有 profile 标签或多独立模型拼接；依赖靠业务名字。 |
| P1 | 准确同步 host 顺序；局部/跨调用有界查询。 | 缺端点仍补桥、默认 NORMAL、串 activation、host return 授 GPU 完成。 |
| P2 | 有独立读取范围的固定 byte profile 接原 P/V。 | 短写缩小需求、仅凭同 FactRef 成功、错物化/端点/源被绕过。 |
| P3 | 单一完整多函数流水线、真实 OS 正反见证及公共报告。 | 只跑孤立 helper；只测试成功路径；虚构 native/write/durability 证明。 |
| P4 | 独立复审、有限必要兼容/组件、干净实现提交、一次全仓。 | 原 5,011 case、69 fixture、567 source 丢失；源码在冻结运行期间改变。 |
| P5 | 精确验收、失败原样保留、守恒/保护/工件指纹、归档推送。 | 以测试耗时声称 LeWM 加速，或将 R3 完成当成完整 M0–M2 完成。 |

focused development 记录全部 registered source，允许 agent 编辑各自文件；只有
统一组件与全仓源冻结才是联合验收。具体问题关闭后停止可选重复测试。
完整 R3 验收后继续 selector/literal、C2/D3 与 M2 全构造分母；完整 M0–M2
完成再按用户要求停下讲解，自动全程序恢复与化简仍按后续阶段推进。
