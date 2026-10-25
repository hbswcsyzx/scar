# 自动接入完整 dispatch 范围

2026-10-25。**Verified：原 LeWM 保留运行的全部 dispatch 边界端口接入；完整程序模型仍 OPEN。**
这不是全部原生库内部操作、内容版本、状态或资源 ready 已闭合的声明。

后续代码审查修正三处多余的`correlation_id == rf_id`条件：固定provider分别分配
profiler correlation和RecordFunction身份，不能按数值相等互认。原held Tensor/几何
连接已有独立owned nonce-marker、准确phase/owner/thread及逐槽合同，原资格不因此撤回。
新代码保留全部这些条件；泛native metadata仍需实际Kineto桥，不能沿用数值等式。
唯一synthetic检查使两组ID不同仍通过，同时改nonce的三个入口均拒绝；不授新运行资格，
不重跑完整native门。原样两文件来自71665a29，见
[应用收据](../artifacts/experiments/native_identity_fields_applied_20261025/receipt.json)。

## 公共实现与模型

`scar.trace.native_capture_batch.bind_native_capture_batches` 接受普通公共 binder 产生的
capture coordinates、原 capture 目录、已发布 native bundle manifest、capture-model 及
准确预期 SHA。输出目录必须全新。它不执行目标，不接受业务函数名单，不恢复旧 SQLite
会话，也不从“相同名字/shape”推出值相同。LeWM 路径只在外部实验入口中出现。

一次 owned acquisition 校验原 ETO、dispatch、physical 输入及所需既有归档，自动发现
实际所有 dispatch sequence 和版本匹配的注册 FunctionSchema。相同静态接口共用规范
ProgramGraph；实际发生分为有界 ExecutionModel shards。每个真实 Tensor 端口分别保存：

| 资格 | 记录与边界 |
| --- | --- |
| A 原生端口 | 原 native path、形式槽、有序 Use、ValueOccurrence、INVOKE/normal Return 及准确 ETO 实例/原 ordinal |
| B Python 对象 | 有 held 见证时保原 ObjectRef；native-only 保准确来源及 Unresolved，不补造 Python 对象 |
| C 存储几何 | 原 region/allocation/epoch/birth 单独核验；对象资格不代替存储资格 |
| D 内容/状态/ready | 仍未证明，不能把对象、端口或 allocation 当逻辑内容版本或完成事件 |

每个端口恰有一个 denotation；零 Tensor、全部 Unknown 的调用也必须有准确实际 producer。
静态接口和动态资格不共用缓存键。V1 的 ATen-only/16-prefix 入口保留原合同；完整 batch
显式使用 `PINNED_TORCH_NATIVE_PORT_HELD_SUBSET_V2`。

静态快照复用只作用于 SCAR 的分析：普通 codec 校验一次，证明 ProgramGraph 的传递字段
不可变后保留准确 canonical bytes。真 token 绑定该图，私有静态 ABI catalog 再绑定准确
source/Run/namespace/全部定义。每片动态端口、对象、来源及库存照常检查；新图不能借旧
token，fresh 错序图仍须经独立 ABI 检查拒绝。默认 validator 与旧 API 保持原验证路径。

归档是 typed 模型和有限 JSONL chunks。当前 importer 用 SQLite 作私有来源导航 spool；
它不是规范图或外部服务，不能恢复 owned 资格。模型输出和查询接口不以该 spool 为权威。

## 实际完整门

`native_capture_batch_attempt03_20261025` 在隔离树实际 exit0，四份相同生产字节现已应用到
main，见 `artifacts/experiments/native_capture_batch_applied_20261025/receipt.json`。
这是对原成功 episode 的保留证据进行离线建模，没有重跑 LeWM。

| 项目 | 实测 |
| --- | ---: |
| 原声明、实际枚举、已建模 dispatch | 各39796 |
| 静态接口 / 执行分片 | 127 / 156 |
| Python参考完整 / 部分的调用 | 37895 / 1901 |
| native Tensor 端口 | 111189 |
| held 对象资格 / 未定 Python 对象资格 | 109288 / 1901 |
| region/allocation 几何资格 / 缺口 | 107483 / 3706 |
| 尚未建模 dispatch frontier | 0 |
| batch / 完整 runner wall秒 | 1668.115 / 1720.893 |
| GNU wall | 28:41.75 |
| SELF/GNU peak RSS KiB | 1091472 |
| 私有 index bytes | 3973341184 |
| final report 前已发布 bytes | 4337031496 |

“Python参考完整”只指 B，不包括 C/D 或函数纯性。全部 dispatch 入账也不等于全部
ETO/Kineto/native 活动的 core 端口均已恢复；它们有自己的独立分母。实现的代码身份、
world/state、alias、逻辑来源、ready 和跨片调用关系继续保留各自义务。

最后 fresh 错序候选及9项 native-only/producer 反例均运行，使用本次真 prepared catalog；
相同 Run 新 seal 仍以 NativePortOrderError 拒绝。包括未定身份、借对象、丢 basis/source、
丢/换 INVOKE 或 normal Return binding，不能用旧 scope hash 拒绝冒充此项检查。
原 profiler API 与 V1 的必要小检查也分别保留，未跑全仓测试。

失败01在第3182次调用暴露 native Tensor 与 Python held Tensor 非一一对应；失败02在
20片后由 root 因处理成本主动中止，exit130。两者保留；成功03没有提高1800秒、4GB index、
2GiB RSS或8GB output预算。不能把中止耗时与成功耗时相除当作性能提升，更不是 LeWM
加速比。单次 codec/profile 的比较只说明 SCAR 自身分析成本，非目标 benchmark。

大 program/projection/execution/qualification 产物保留本机并有准确 receipts；Git 保存
实现、入口、冻结和小型实际结果。shared snapshot、分片发布及覆盖通过是三件事，
`whole_model_established`、`transformation_authorized` 均仍为 false。
