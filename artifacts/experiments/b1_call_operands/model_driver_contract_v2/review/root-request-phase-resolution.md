# D0：request phase 的 root 复审裁决

2026-10-18。仅新增本补充报告；旧 `permit-session-proposal.md` 保持冻结。
未改产品/tests/docs/旧证据，未运行 probe/test/full/GPU，未执行 git。
本补充优先替代旧提案中通用 RequestGate 与 U/A 阶段要求，其他窄 corridor 接线保留。

## 1. 结论

**接受 root 两项意见：删除通用 U/A 系统，不强制独立 RequestGate。**
通用类型只要求 final gate 针对本次真实 R/B/S、delivered payload 和当前 state 的版本化
admission 合同。真实实现较早的 request 检查/更新继续是普通 helper/StateAccess；
它是否存在、位于何处以及是否必须先完成，属于该版本的 source 协议路径义务。
不再用一次历史 acceptance 作为 BodyDrive 的通用类型前置条件。

## 2. 旧 U/A 的明确错误

旧提案 `permit-session-proposal.md:167`–176 同时说 A 是“曾成功 admit”及 RAISE→U，
二者不相容。若 A 是历史事实，后续失败不能抹去过去；正确历史传播只能在失败边保留
进入的历史，并在 NORMAL 上加入 A。但这个历史并不能证明当前 request phase/关联/
占用仍有效，且 final gate 本就必须重查。因此不修补该 LFP，直接删除它。

如果改把 A 解释为“当前仍获准”，则 callback、state writes、部分失败与所有可触及
R/B 的操作都需精确失效/重新验证规则；这重新引入我们决定放弃的跨 CFG 许可系统。
两个解释都不值得成为通用 driver core 规则。

## 3. 最小字段裁决

保留旧提案这些 canonical 端口合同：

```text
DriverInterface(region, body, receiver_kind,
                receiver: EntryPortRef, scheduler_request: EntryPortRef,
                lifecycle: tuple[LocationID, ...], rule)

FinalBodyGate(operation: OperationID, drive: OperationID,
              body_argument: int, scheduler_argument: int,
              session_argument: int | None,
              delivery_arguments: tuple[int, ...], rule)
```

- 删除作为通用必要记录的 RequestGate；不增加 parent gate ID、accepted bit、epoch
  number 或替代私有 token。原 RequestGate 字段如用于命名真实 helper，只能是可选
  source 元数据，不获得 core admission 权限，也不必进入公共 schema。
- FinalBodyGate 不增加“前面曾 request-admit”字段。BODY 模式使用 B/S；ASYNC_REQUEST
  使用 B/S/R。R 的生命周期、R 当前关联 B、session 的当前持有者均从真实 current
  StateVersion/StateAccess/helper 接线，不从前置 helper 的名称/成功边代替。
- R 仍是本次 request-object method receiver；S 仍是本次 scheduler/send/throw/close
  原始请求；latent request L 单独由实际请求内容取得。删除 U/A 不允许 S/L 合并。
- 本补充不要求独立 RequestAssociationRead site。若真实存在此 read，复用它的
  canonical inputs/results；若整合在 helper 内，必须按最终统一合同的真实参数/
  completion projection 表达其 producer，不能发明 B/L actual。检查和 lookup 是否
  独立不应成为程序类型限制。旧“来自 AssociationRead”应读作有实际关联读取来源，
  不能固定为必须存在该名字的一行记录。

## 4. final gate 必须承诺的当前语义

成功 NORMAL 针对本次实际 inputs/current state 承诺：

1. 当前 receiver/request phase 可按本版本规则接受 S；有 latent request 时按真实
   当前 request 内容解释，而不是将旧读取或上次 host call 的资格沿用。
2. ASYNC_REQUEST 下 R 当前关联所用 B，且 body/session 占用允许本 R；其他 R 不因
   同 body code 或同 StateLocation 获准。BODY 模式执行该 family 的直接驱动条件。
3. 选定 Start/Resume target 与该实例当前 continuation 的声明合同相容；payload 已
   由真实路径完成必要校验/归一化。gate 端口对应只证明该 payload 原样交付，不证明
   任意 packet 自然等于 S/L 的正确 normalization，后者需生产者/规则/source 对应。
4. admission 所需 request/body phase 更新与 mark RUNNING 已完成，NORMAL states
   是其真实后态；随后没有 callback 或其他操作插入，立即进入配对 BodyDrive。

这些是非空、有实际 inputs/outputs 的条件语义，并非 validator 能从 opaque state
值里解码或证明的事实。适用规则的实现/来源对应与 guard 原子性仍需独立证据。
如果某实现把两层 checks 合并，final gate 完成两者即可；如果早期 request 更新已
对外可见，必须保留其真实顺序/效果，不能为了合并而搬到 callback 之后。

## 5. 更新后的全 CFG 检查

不再运行 parent U/A 工作队列。仍完整运行 core 的 def-use/CFG/current-state，以及
DriverInterface 固定 receiver/S 的真实 copy 约束和 final gate→Drive 的逐槽对应。

- 任意普通 callback/state write/失败 completion 都按现 core 更新 current 各域。
  每个 final gate 必须消费当点 current，不能消费更早 request helper 或 gate snapshot。
- final gate NORMAL 私有 landing 只有配对 BodyDrive；owner/request/delivery 均为
  逐端口真实 forward，state 来自 NORMAL CompletionResult 的新 BlockArguments。
  拒绝边不被当作该 Drive 的 body Raise/完成；不产生任何可复用 permit。
- 普通合流不保留“当前可用许可”关系；真正合流的是 R/B/S 实际端口与 current state。
  gate 重新检查当前组合，随后 corridor 防止它检查 B1 却进入 B2。
- body outcome 后的循环需回到 final gate；不能绕过 gate 进入旧私有 landing。
  每次 gate 都有真实状态输入/后态，不用静态 site 或计数证明动态代次。
- SessionUpdate 仍只在真实当前 state 上承诺 HOLD/COMPLETE/ABANDON；request 完成
  不等于 body continuation 完成。无 body 路径继续由真实 typed helper/source 表达。

版本专属 source 审计可以额外验证“该实现先执行 helper X，callback 前更新字段 Y”等
协议路径，但这是有来源的实现符合性检查，不是所有 ASYNC_REQUEST graph 的类型规则。
如果这些步骤缺失，会阻塞该版本实现对应结论；不一概拒绝另一个合法的组合实现。

## 6. 最小正反例

| 声明路径 | 裁决 |
| --- | --- |
| 无独立 request gate；final gate 同时检查 R phase/关联/占用并生产更新状态→Drive | 合法结构；不因缺少 RequestGate 行拒绝。真实组合语义仍须版本证据。 |
| 早期 request helper 成功→callback 推进或关闭 B/R→final gate 使用最新状态 | 合法结构；current admission 可能拒绝，不靠旧 A 放行。 |
| 早期 helper 成功，后来另一 helper 失败→普通 catch→final gate | 不因抹除历史/保留历史决定成败；由真实失败后态及 final 当前 admission 决定。 |
| 早期 helper NORMAL 直接被当成许可，callback 后绕过 final gate 进 Drive | 拒绝：没有符合唯一邻接规则的 final gate。 |
| 合并检查却向 body 传入 mark RUNNING 前的 state | 拒绝：NORMAL 后态 producer/消费不匹配。 |
| source 实际先更新 request 再 callback，却在模型里将更新移到 callback 后的 final gate | 不能签核该 source 对应；current SSA 类型通过也不能覆盖真实观察顺序差异。 |

## 7. 与既有证据的边界

本次是推理修正，无新增语言实测。依据为旧提案自身 `:167`–177 的历史/失效矛盾、
当前 `docs/M1_DRIVER_INTERFACES.md:61`–73 的普通 session/current-state 与开放 gate
关系，以及 `validation.py:475`–497 的 canonical completion state 规则。
建议 root 统一合同采用本裁决，并把旧通用 RequestGate/U/A 要求明确列为已撤回，
避免两份提案被同时实现。无需新增原语或重新运行 frontier/full 才能作此设计裁决。
