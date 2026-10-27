# 下一门：让已有消费者使用存储来源，再返回原协议门

2026-10-20。本批解决的是原访问上的值合同及实际声明级来源查询；完整范围仍为
[WHOLE_PROGRAM_MODEL_PLAN.md](WHOLE_PROGRAM_MODEL_PLAN.md)。没有新 optimization backend。

## G0 先判断是真缺类型，还是缺实际依据

新 query 不自动修改 ordinary copy；已有无 StoredValueRead/Write 的程序也不会
因此被推定字段恒定。先审实际 load result 到上层 caller/predicate 的原 Use/CFG/
call 路径，找需要消费 query-local recipe 的准确入口；不要另造 request 专用来源。

原 constructor 的 own 新对象在创建前不是一个输入 Use。初始化若发生在构造内部，
应沿原可展开 Region 的 allocate/init/return 接口描述，或保留准确 native 边界。
不能给同一 operation 造一个引用其 own future result 的非法输入，不能因为
`Create.body` 存在便声称已经恢复后续字段 load。若现接口确实不能表达产生后的
owner，先独立审原 native/result/address 合同，再决定是否需类型扩展。

## G1 通用消费者桥

1. 从准确 load own result occurrence 回查原 StoredValueRead，INVOKE 由实际 transfer
   和 CompletionResult→landing formal 定位；非选中完成不能制造来源。
2. 查询局部消费 `DECLARED_STORED_VALUE` recipe，与原 copy ancestry 分列，保持
   全部 store、actual occurrence、状态和区间支持。不得把候选结果塞入全局 union。
3. 同一 shared budget 下递归来源必须防循环，缓存仅在当前 fresh context/query
   内且支付原代价；预算截断或缺本实例证据不借兄弟，也不能空成功。
4. 先复用通用 payload/owner 两种来源组合及有限反例，再接既有 terminal/new-request
   消费者。没有可信 raw-slot/native 合同的边继续 Unknown，不为它增加同类手工图。

跨 deepcopy/transform/materialization 的 LogicalValue/Provenance/Version、完整
数据有效性和自动恢复仍是不同关系；不能用本批原 Reference 槽来源代替它们。

## G2 返回 F19 和原完整分母

历史 F 的当前主体连接有充分依据后，继续原 F19 的非 finished native 分支、
graceful close 的 AWAIT/HOLD 与两层 reply、illegal yield 后 same/new request、
finally、真实 F 及 release。R 完成、B 终结、active session 和物理 release 不合并。
无法验证的 native 内部保接口边界，必须区分“已有模型能表达”与“已证明对应真实实现”。

F12/F13/F14/F15/F16/F17/F18/F21/F23 九族及 await A–H 保持限定接受；
F19/F20/F22/F24/X25/X26/X27 七族、P4 component/full、P5、M2 原
113 构造/196 字段及整个 M0–M2 继续开放。整个第一阶段完成后先向用户解释类型、
连接与覆盖，再进入入口驱动 Python shell 与 FX/Export 子 Region 自动建图。

每门先设计/复现，再有限实施、自验报告、普通 commit/push；不要求用户逐门审批。
不新增 detector、backend 或 LeWM 特殊规则，不把当前测试图作为自动 LeWM 拆解证据，
也不将单元测试耗时当 LeWM wall-clock 加速。
