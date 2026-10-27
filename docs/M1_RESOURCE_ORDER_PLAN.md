# R2.2：事件代次与到消费者开始的条件顺序

起点：R2.1 `9c7a913`；R0 关系合同及 R2 总计划继续适用。
本门实现执行关联及机械检查，不增加 detector、backend、source lowerer，
不运行新的 LeWM profiling，不提前宣称 R2.3 ready 或 M0–M2 完成。

## 模型与原图的连接

- WorkStart/WorkEnd 是同一 WorkTicket 的资源执行边界；不是 host enqueue
  的 BEFORE/AFTER。PrefixEnd 表示这个确切 persistent prefix 的完成前沿。
- QueueOrderProfile 以原 queue 实例和 through prefix 限定 FIFO 协议的声明
  适用范围。仅在该 prefix 的已知祖先链上导出前项 End→后项 Start；没有
  profile 时，链本身只描述提交成员关系，不能推出该设备顺序。
- EventRecordID 表示一次 record，event ResourceInstanceID 表示实例生命周期。
  RecordedPrefix 引用确切队列/前缀；已知 marker 必须是该队列上真实关联的
  queued work，其前项必须与 capture 一致。pending marker 无须 Outcome。
- generation 引用原 StateAccess 或实际 INVOKE completion state。event_access
  回到原 ResourceUse/requirement/实例，generation 的 location 必须属于这个
  原 resource。不会根据变量名、模块名或地址相似性构造 event。
- QueueWait 是真实 queued ordering work，引用准确 EventRecordID。selection
  回到原事件状态 Use；沿实际 CFG formal→原 predecessor Use 追溯，必须到该
  record 的确切 post-state。未知写或缺失传递不能当作仍是同一个代次。
  重录不修改旧 wait；如果 wait 的实际输入已是 r2，却指定 r1，则关联矛盾。
- 外部 native 事件可以带明确 Unresolved，不强迫捏造 core 操作、work、状态
  或队列。缺少对应时保留精确 gap，不能拿字段存在冒充 native 证明。

## 条件顺序及边界

派生图包含 work 本身的 Start→End、已声明 dependency 的 End→Start、
profile 范围内的 FIFO、prefix 完成前沿、record capture 和 exact wait。
路径同时保存原关联及协议条件，合并检查循环；不凭 ID、表顺序、host 时间
或 Python 调用顺序推断跨队列顺序。循环的严格顺序关联无效；原始运行证据
仍在独立 EvidenceGraph 中，不删死锁或失败观测。

查询区分 CONDITIONAL 与 UNRESOLVED，并设遍历预算。CONDITIONAL 只表示
在所列关联及协议适用条件成立时存在路径，不表示 Completed、输出已产生、
host 可读、其他队列可见、可 free、已持久化或可变换。FAILED/CANCELLED 的
内容生产义务由 R2.3 独立判断，不用顺序路径消除它们。

## 验收顺序

1. 严格 frozen records/ID/FK/queue/run/原资源端口及实际状态选择；保留首次失败。
2. pending 同队列及跨队列、r1/r2、缺 profile/缺 selection、错误 queue/run、
   ConsumerEnd 不能替代 ConsumerStart、混合来源循环及查询预算。
3. execution wire v3 能力声明；v1/v2 原字节兼容，独立从 `bb1b402` 生成
   历史 v2 golden，禁止新字段降级丢失。
4. 独立复审、组件 gate；源码/文档提交冻结后一次完整 regression，期间不编辑
   源码/文档、不并行运行其他测试。归档原日志、hash、结果及局限并提交推送。

子代理分工：records/IDs/model、codec/历史样本、canonical fixture/反例；
root 负责 validator/query、整合及验收。R2.2 完成后继续 R2.3，再到 R3；
完整建模阶段结束时先向用户讲解模型，尚未进入自动化简性能结论。
