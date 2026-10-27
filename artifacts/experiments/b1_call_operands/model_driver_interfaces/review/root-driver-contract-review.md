# Root driver 合同有限复审

2026-10-18；只读审查 `docs/M1_DRIVER_INTERFACES.md`，对应文档 SHA-256：
`42459a741f6c6ed393df2d674159711faa607b2ee891b93a409fdfd00fedf415`。
核对对象为已冻结 `claim-lifecycle-review.md` 的三组 stdlib 观测及其 gate/current-state 阻塞。
未改产品、tests、docs 或原报告/日志；未新增或运行 probe，未审查正在实施的 frontier 代码。

## 结论

**本轮限定范围通过，无须实质修订；不构成完整 D0 字段签核。**
新文档没有再把旧 claim、raw THROW 或持久 session 的错误假设列为可实施前提。
完整 gate/permit/session/lifecycle 关系仍 OPEN，故原审查“不通过完整 D0”未被本结论撤销。

| 核对项 | 当前文档及判断 |
| --- | --- |
| 1/permit ≠ 1/hostcall | `docs/M1_DRIVER_INTERFACES.md:49`–56：permit 仅当前 driver 协议内使用；每 permit 至多一次 BodyDrive；归一化/释放/lookup 回调可形成嵌套 epoch，操作及返回后态保留。正确回应异常构造器嵌套 next 的实测。 |
| 原始 THROW 与 body packet | `docs/M1_DRIVER_INTERFACES.md:35`–45：保留有序 1–3 Reference operands、omitted/None；构造/校验是实际操作；delegate 可收原参，fallback 才按真实路径归一化。现 body THROWN_PACKET 继续使用 EXCEPTION_PACKET。没有统一 gate/normalize 顺序。 |
| session 是当前普通对象 state | `docs/M1_DRIVER_INTERFACES.md:58`–66：AWAIT 短步结束不自动结束 session；同 request 继续、竞争 request 拒绝、ASYNC_YIELD 完成请求与 body 暂停分别建模。owner/request refs 加当前 StateVersion/StateAccess 或 typed native helper；不新建持久私有 token 存储。 |
| gate parent / current state 仍待闭合 | `docs/M1_DRIVER_INTERFACES.md:68`–70 明列两层 gate parent、owner/permit 合流同步、写后有效性、helper 使用位置；`docs/M1_DRIVER_INTERFACES.md:145`–153 把 exact 字段与关系固定点列入 D0/D2。`docs/M1_DRIVER_INTERFACES.md:103`–110 要求 callback/delegate 后的当前态，并否认 LocationID 等同实例/独占。没有以标签或粗域冒充证明。 |

## 保留边界

1. `docs/M1_DRIVER_INTERFACES.md:53`–54 允许未来显式续代操作产生新许可，未授权旧 permit 多次使用。若以后选择此分支，仍须冻结真实 successor-permit/cursor 结果及上一实际 outcome 的 lineage；当前文档没有声称该机制已存在。
2. `RequestAssociationRead` 仍是候选连接，不能单凭 Reference 类型或同 body code 得出 request/body 实际关联。当前 `:64`–70、`:107`–110 已保留该限制，尚未给出完整机械 validator 合同。
3. 本次未签核 creation-instance/capture occurrence、完整 admission/commit/release 后置表、全家族协议或 source/runtime 归属证明。文档 `:3`–6、`:145`–159 明确完整字段未冻结、driver 未实施、C2.0 未关闭；与本轮范围一致。
4. frontier 的查询结果只可提供候选真实 terminal sites；本次未审代码，也不把共享查询完成视为 BodyDrive 或 C2D 完成。

## 冻结材料完整性

原报告及两份日志的 SHA-256 与复审前一致：

- `claim-lifecycle-review.md`：`c3554bdb7ae1a7525eb1aa4238b165bded01ea4df9fba76508d7110a8bceadd6`
- `claim-lifecycle-probe.initial.log`：`3e2a24e3fbde112999c1d622614742a8fda85e3f552b7ac92a59ad46ad14f637`
- `claim-lifecycle-probe.raw-throw.log`：`feda7a610837e3a347f6ad8aec3166025908c5f398893e699c7e61c2fd825075`
