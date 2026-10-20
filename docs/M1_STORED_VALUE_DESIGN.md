# 存储值合同：冻结计划的审查补充

2026-10-20，依据 [计划](M1_STORED_VALUE_PLAN.md)，不覆盖其原范围。

C 指出一个实质阻塞：Write 是完成后的**最终 post**事实，两个不同 stage 不能
同时使同一个最终槽具有 P/Q 两个来源。实施必须拒绝同 write key 重复、同完成
静态可判同最终槽的多 post 声明；同一 read own result 只允许一条直接槽关系。
未知 alias 的同完成多 post 来源保持 Unknown/冲突依据，不能按附件顺序 last-wins。

查询只解释 ReferenceOwner 的一个明确直接单槽。ObjectField/CellContent 可比较；
动态字段/元素/namespace key 需实际 Data 值的原 copy 或准确 builtin literal 依据。
未知 owner/selector、range/aggregate、需要中间解引用的多级路径保留原模型但不授
来源。显式 Raw-slot 合同不等于从字段名已证明没有 getter/setter/native 行为。

候选地址不同只局部拒绝；只有找到共同原 copy 祖先时才调用 copy compatibility，
其它候选可使用独立 scoped ObjectIdentity。不能把正常不同对象写为全局 copy 错误。
Write post 的实际 AFTER/所选 EDGE 与 load BEFORE 之间复用 state_preservation。
覆盖写解释属于新来源查询，不改保持查询的任意 WRITE/RW 阻断语义。

新表从旧1–26字段集中排除。Program27独立启用已有 InvokeLiteralResult 标签，
不能要求附带 LiteralEvaluation 或 protocol profile 才能序列化 INVOKE 存取。
旧最大/未来版本断言迁移单列，所有旧 wire 版本、原回归义务和独立 oracle 均保留。
