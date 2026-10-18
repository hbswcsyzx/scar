# R2.3-D：内容、端口与消费者的连接

实施基线：`6efbe272bceb1036eba3725f11c47960fd5dd301`。
上位约束：[资源合同](M1_RESOURCE_EXECUTION_CONTRACT.md)、
[R2.3 合同](M1_RESOURCE_READY_CONTRACT.md)。本文是实施计划；验收结果另存。

## 目的与边界

把原程序中的准确端口、本次内容和实际消费者接起来。相同 host call、对象、
shape 或 storage 都不是内容相等或消费对应的证明。本门不增加 detector、backend，
不把几何覆盖、顺序或 retention 宣布为 ready；P 生产集合和 V 有效期仍独立验收。

## 事实及新增关系

| 关系 | 规范事实 | 本门新增的连接 |
| --- | --- | --- |
| 值的指代 | 原 ValueOccurrence 及 Data/Reference 类型 | scoped VersionRef 或 ObjectRef；State/Binding/Protocol 继续派生。 |
| 实际工作 | 原 WorkTicket 与精确 EEG instance | WorkEvidenceBinding，不能用同 host 调用替代。 |
| 必须观察什么 | 精确 SemanticGraph 合同 | ObservationRequirement 指准确 required output 或显式端点/必需 facet/协议关联。 |
| 观察了什么 | 原 ValueOccurrence 或资源绑定/外部端点 | ObservationRoot，含准确区间、当前状态和来源；不伪造 work。 |
| 内容读取 | 原 UseRef/AccessRef 或 ObservationRoot | ContentRead 接物化、selector、effect、state support、区间和源 basis。 |

VersionRef、ObjectRef、MaterializationRef、RegionRef 均有 hash/schema/size scope。
同裸 ID 不跨 artifact 合并。StorageContent.selector=None 表示该物化原 region
的整体；未知 selector 使用 Unresolved。EndpointContent 不伪造 allocation。

NativeInputRef 指 boundary 原 input position 和实际 initial entry visit；
NativeOutputRef 指原 output position 和实际 Return/Raise occurrence。
native position 不等于 core operand index。EEG 的 operation/value 边没有参数序号，
因此只能解析 operation-level 关系，必须报告 exact port gap。

ResourceConsumer 的 WholeWorkRead 使用保守 WorkStart..WorkEnd；NativeWorkRead
可声明更窄协议区间，但没有解析过的 native 依据不能因此缩短稳定性义务。
host/观察直接使用 ProtocolInterval，不创建虚构 ticket。

## Schema 与查询

ExecutionModel 新增五个默认空表：denotations、work_evidence_bindings、
observation_requirements、observation_roots、content_reads。出现新关系时编码 v4；
既有 v1–v3 的字段、tag vocabulary 和字节保持。ProgramGraph 不变。

外部图统一使用白名单 ValueGraph/EvidenceGraph/SemanticGraph 的严格解码快照。
每次查询新建 resolver；校验精确 bytes/hash/schema/size 后 detach，查询内复用。
URI 不读取，provider 不执行。缺图是 gap；已提供但错误的图是 issue。

公开查询返回原端口、原状态、scoped 内容/placement 和逐项缺口；结果 detached。
所有 source_runtime_verified、transformation_authorized 均为 False。

## 自行验收顺序

1. **D0 接口审查：** 冻结 records/身份/三类 consumer 与 Q root，独立复核。
2. **D1 结构与关联：** 构造、严格 codec、canonical port/state/FK、协议区间、
   exact work/source pairing 校验；保留首轮失败。
3. **D2 反例与来源：** mutable object 不沿用旧内容；同 host 多 work；错误版本、
   artifact、selector、native position/实际 completion；无伪 storage 的端点与 Q roots；
   外部图在 index 构造后发生变更必须重新校验。
4. **D3 兼容性：** 独立旧版本 golden、原 case ID/fixture 保留、component gate、
   独立复审；实现冻结到干净提交后只运行一次完整回归，期间不改源码/文档。
5. **D4 归档：** 命令/原始输出/源码指纹/退出码/计数/耗时/失败/复审和 manifest，
   记录受保护仓库状态，提交并推送、核对远端 revision。

关闭 D 不等于关闭 R2.3，也不等于全程序自动建模完成或 LeWM 已有加速。
下一门 P 必须从 source inventory 派生生产贡献，V 再核对整个读取区间及域。
