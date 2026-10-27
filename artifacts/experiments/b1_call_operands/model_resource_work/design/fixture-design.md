# R2 work/ready：只读组合预审与最小 fixture 设计

状态：**Proposed；可据此冻结字段，尚无 R2 产品/fixture 验收。** 本轮未编辑产品、tests、docs，未运行 Python/pytest/native/GPU。Observed 仅指本次读取的源码事实。

## 1. 现有事实与复用边界

- R0 合同 `docs/M1_RESOURCE_EXECUTION_CONTRACT.md:176–226` 区分真实 work 与 host completion、普通 Access 与 INVOKE boundary；`:230–300` 要求 event record 代次、各贡献 AND/每贡献支持 OR、consumer/placement/visibility 精确对应。
- R1 `scar/ir/execution/model.py:48–69` 只有 occurrence/resource 表，尚无 work/outcome/order/ready。`coordinates.py:264` 的 AccessRef 和 `:300` 的 UseRef 可直接复用。
- `execution/flow.py:210` 明确 INVOKE 无普通共同 AFTER state；`validation.py:140–184` 已派生各实际点 current StateVersion occurrence 并拒旧 incarnation。`query.py:54` 的 formal_route 返回原 CompletionResult，而非伪造 source Use；原端口足够解析实际后态。
- `tests/fixtures/execution_paths.py:18` 的 declared_path 可复用来展开明确路径、真实 transfers 和每 visit 的值发生。`test_execution_flow.py:113` 已有 NORMAL/RAISE 分别派生 State formal 的 fixture；可参考其端口结构，R2 基础图应避免引入无关 C2 context。
- `v2/values.py:107–160` 已有 allocation、region、materialization→ValueVersion；producer 是旧 v2 OperationInstanceID，且可 None，不能把新 core occurrence 强塞进去。ready_event 字符串不能升级为 typed record。
- `v2/contracts.py:136` 的 ContractDefinition 仅有 outputs/facets/assumptions/evidence，尚无准确 endpoint/point/content 观察根；EXTERNAL/ORDERING facet 不能替代 ObservationRoot。

不需要静态 WorkSite/ReadyUse 表、新 producer、新 world、新 materialization 或修改原 operation 的返回类型。缺少的都是 execution 关联、判别分支和证据义务。

## 2. 最小可实现 canonical 静态图

建议一个通用 `queued_work_program()`，参数只控制明确 CFG 变体；不依赖 LeWM/device 库。入口带 source/destination、queue A/B、event 的 Reference formals 以及 State formals。
初版将内容域 `C`、队列域 `QA/QB`、event 域 `E` 分开；这是原 StateLocation，不是第二套执行状态。coarse world 可另作一个合法但未闭合的变体，不能因某个 world 更新推断 content 被写或完全未变。

```text
entry: submit INVOKE --actual NORMAL--> submitted --record e1--> wait --> consume --> RETURN
                    \--actual RAISE --> failure_handler --record e1--> wait --> RAISE
                                            \--可选明确部分 consume 后再 RAISE
```

1. `submit` 有原 source/destination/queue 及当前状态 Uses；invoke_arguments 使用这些原 UseID。无普通 results/accesses。两 CompletionSignature 有各自产生的 State 类型；RAISE 另有实际异常 payload。原引用的边转发使用独立 owned UseID（Value 可同），不能把转发当 CompletionResult。
2. 故意使 successors 的实际序列为 RAISE=0、NORMAL=1；两个签名可采用不同 State result 排序。测试不依赖 index0=normal、相同位置=同域。从实际 transfer 选边，再按 CompletionResult.index/目标准确 formal/Location 派生后态。
3. `record` 是真实普通 operation，读取/更新 QA 与 E，持有 event、queue 原 Uses；其 StateAccess 表示 host/protocol bookkeeping。它不产生 WorkTicket 或另一个 world，也不声称所有内容已完成。
4. queued `wait` 是真实操作，对 QB/E 的当前 state 建立关联；不是 host synchronize。另有明确 host-wait INVOKE 变体，其 NORMAL/RAISE 分别产生后态；wait 的 RAISE 不等于所等待 work 的 FAILED。
5. `consume` 有独立原 destination Reference Use 与 C 的 READ StateAccess；device 消费另有实际 QB ResourceAccessBinding。ReadyRequirement 指其精确 UseRef/AccessRef；不能因为同一个 Reference 被传递就认定 logical content。
6. 所有 block/exit 保留完整当前状态，失败分支真实存在。若运行只记录 NORMAL 或 RAISE，ExecutionModel 只展开所选路径；另一边不会出现虚假 visit/formal。

**重要时序：** record 可以在 work pending 时发生。host-wait 路径可为 submit→record→wait→此时观测 Outcome→consume；不得强制 Outcome 先于 record。device ordered 路径甚至可以完全没有 Outcome。WithinOperation 仅归属提交，不凭 host 操作的 BEFORE/AFTER 捏造物理提交点。

## 3. 五个有界 fixture 家族及验收

以下为设计分母，不是已实现或已运行计数。每个负例从同一 `require_valid` 正例最小变更，保留完整 canonical graph；不靠非法 ID 让 core 先失败。

| 家族 | 必须成立的正例 | 必须阻止/保留的反例 |
| --- | --- | --- |
| A submit 与实际 completion | 同一个静态 submit 分别展开 NORMAL、RAISE；RAISE 前仍有一个真实 WorkSubmission；普通 submit 一次可有两个 ticket | 把实际 RAISE 改连未执行 NORMAL formal；把 INVOKE effects 写成不存在的 AccessRef；把 host NORMAL 自动当 COMPLETED；尚未观测 transfer 时应 unresolved post，而非补正常边 |
| B record/queue order | ticket A→e1 record；e1 精确 wait→QB consumer。无 ResourceOutcome/host-sync 的 same-Q 顺序和跨-Q wait 均可结构匹配 OrderedVisibility | e2 后来重录同 event，不可回写早先 wait 捕获的 e1；从未 record 的 event 不支持任意 work；错 queue/consumer prefix/run 不匹配；循环自证 order 无真实建立依据只能 gap，不能凭循环可达授支持 |
| C 多贡献与复用 | 全区间有贡献 a/b：a 用 CompletedVisibility，b 用 OrderedVisibility；每项有两个替代依据也合法；同证据分别满足两个正确 consumer | 缺 b、把 a 的完成与 b 的 queue 配对交叉、一个 consumer 的 QueueVisibility 授另 queue/host；writer coverage UNKNOWN 不能凭列出一项升级完整 |
| D 版本与 placement | 原 ValueGraph 中 content v1/m1/allocation A1 精确匹配；v2/m2 可共享同一 A1；另 allocation A2 即使 raw 地址文字相同仍不同 | 当前 consumer 要 v2 或 A2，不可借 v1/A1 的旧证据；E/Q 更新可不改 C，不能粗暴使所有证据失效；真正 C 写/UNKNOWN alias 写后无当前 denotation，须给具体 gap。历史旧证据本身仍可保留，不追溯宣告无效 |
| E partial/cancel 与观察域 | FAILED/CANCELLED 可保留准确部分 effect frontier；部分区域 consumer 仅在其实际贡献足够时匹配；file endpoint materialization.region=None + 准确 ExternalObservation | FAILED/CANCELLED 贡献不足不能靠正确 order 补齐全内容；cancel 请求或 timeout 不能造实际 CANCELLED；outcome/Ready 都不能推出 quiescence/free；host visibility 不推出 endpoint flush/persistence；仅 Contract EXTERNAL facet 或 close 不产生观察根 |

辅助最小 ValueGraph：一个 logical value 的 v0/v1/v2，A1/A2 两 allocation，明确 unit/dtype 的 full/left/right StorageRegion，原 materializations。部分写以原可核对的子区域/footprint 关联，不重复保存互相矛盾的 allocation 字段；UNKNOWN 几何不按 disjoint。文件 materialization 另用 EndpointPlacement，不虚构 allocation。
直接同步 CPU 工作加一个 DirectExecution 正例；UnresolvedQueue 为另一合法有 gap 的变体，不能强迫两者共用 NoQueue 或假 stream。

## 4. 冻结机器字段前必须补的连接（Proposed）

字段名可由 root 决定，但以下信息不能在字符串 metadata 中隐去：

### 4.1 work、effects 与实际 completion

- 每次 WorkSubmission 有独立 WorkTicketID、准确 run/scope、WithinOperation(opocc,fact) 或 ExternalWorkSource(point)，以及既有 ResourceAccessBinding executor/queue。ticket 不要求是 core result；submit 后 host RAISE 尤其可能没有返回 handle。
- 普通 effect 复用 AccessRef。INVOKE effect 必须引用该 opocc 原 invoke_arguments 中的 State UseRef，再用 `actual(successor_index,result_index,landing formal occurrence)` 或 UnresolvedPost。landing occurrence 可由 transfer+原 edge 唯一推导；显式保存时校验相等，不新造 CompletionResult ValueOccurrence。
- outcome 引 ticket、真实观察点、协议结果的原 Use/Value/fact、部分 effect frontier；不能由诊断 host operation 自动反查成它引发失败。相同终结重复观察可保留来源；明确相冲突的终结不能后写覆盖。
- partial frontier、输出 materialization 和原 effect 之间需有有版本的匹配依据/coverage；INVOKE boundary 没有可继承的 READ_WRITE/footprint，未知必须保留未知。

### 4.2 event record 与 order

- EventRecordID 标一次 record，不是 event lifetime；记录 event ResourceInstance + recorder 点 + 准确捕获 ticket/queue-prefix 集合 + coverage/source。
- wait 必须有 `waiting operation/point → captured EventRecordID → actual consuming queue/prefix` 关联；单独 recorder 与 OrderEdge 的两个端点不足以验证 wait 选中了哪一代。
- QueuePrefix/OrderEdge 需准确 queue identity、实际 ticket membership/消费提交边界及建立依据；不能用 tuple/ID/timestamp 顺序推断。same-Q 规则也要明确协议依据，R1 host point_precedes 不是 device order。
- order 固定点只传播有根依据的可达路径；query 返回原 chain/条件与缺口。没有观察 Outcome 可以 ordered；已知不足的失败 frontier 不能被任意路径绕过。

### 4.3 content、consumer 与有效性

- 需要 scoped MaterializationRef（准确 artifact + 原 MaterializationID），从原图派生 ValueVersion/region/allocation；另有本次 consumer 的 UseRef/AccessRef→该 content/placement 的 denotation 关联及其当前 State support、source/coverage。Reference、shape、StorageRegion 同形都不能替代该桥。
- 每个 required contribution 需与准确 work、该原 content/区域的贡献范围和 scope 同时关联；支持替代按 contribution 保存，再逐项 AND。完整集合的 coverage 是独立声明/证据，不能由枚举几条 work 自动得出。
- ReadyEvidence 的历史建立点与支持 state 和 requirement 的当前点/当前 denotation 分开；每次匹配检查 content/allocation/footprint/domain/scope 与建立后的修改。对未知 alias/图外写保留有效性缺口，不另建 world/version 图；可核对的原 StateAccess 与封闭协议关系支撑具体不变/失效。
- 未找到 denotation/coverage 的合法图：结构 valid，有精确 unresolved obligation，无无条件 ready。已知字段矛盾：issue；已有旧证据与新 requirement 不匹配：保留历史行并返回拒配原因，不把整个 execution 图判非法。

### 4.4 retention、外部根和授权边界

- R1 OwnershipHolder (`resources.py:341`) 仅 Object/Handle/Activation/Target，没有 work holder。R2 若实现 retention，须添加 typed WorkHolder 或独立 WorkRetention(ticket,原 target/Use/effect,until quiescence|Unresolved) 关联；不能把 work 伪装 ResourceInstance。Ready 不是 release authority。
- ObservationRoot 需 scoped 旧 ContractID+typed root/endpoint/point/content/protocol 与明确 contract artifact 校验入口。现仅 value_graphs/evidence_graphs catalog 不足以检查新合同外键；缺 catalog 可 gap，但不能假称旧 facet 已带根。
- StorageBacked/EndpointBacked/UnresolvedPlacement、Host/Queue/Endpoint/UnresolvedVisibility 必须判别；region=None 不选默认 backing，host_thread unresolved 不授某个 thread 的可见性。
- 测试不填写 PROVEN、不调用 legacy mark_ready 自动补新行。所有正例是明确 Declaration + MissingEvidence/provider fact locator；查询可报告“字段与条件匹配”，source_runtime_verified/transformation_authorized 仍 False，协议适用/内容正确性另列。

## 5. 有限实施顺序与停止条件

1. 先 family A + 同队列 B：一个普通/一个 INVOKE effect、实际 RAISE 与无 outcome ordered。确认原 Use/current edge ports 可查询。
2. 再 B generation + C mixed AND/OR：只增加两队列、两 record、两贡献，禁止扩大为完整调度器或完整 GPU 前端。
3. D/E 用同图最小变更验 current content/allocation、partial/cancel、域不包含及 external-root unresolved；未落实字段明确列入验收未通过，不用全部 UNKNOWN 冒称完整 R2。
4. 每轮保存首败/修复后相同 repro、脚本命令和 source SHA；只在 root 字段冻结并授权后写 owned tests。测试数不能当 denotation/native 协议覆盖率。

## 6. 本次读取的源 SHA256

| 路径 | SHA256 |
| --- | --- |
| `docs/M1_RESOURCE_EXECUTION_CONTRACT.md` | `74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729` |
| `scar/ir/execution/model.py` | `f1b9941741f48bcfafc224e50722422450e6a07ef7c606c2422395d2de274411` |
| `scar/ir/execution/validation.py` | `2c60deee43107fe0310140fcd9e73a55288a45b7ebebda22b699d238e695cdfa` |
| `scar/ir/execution/flow.py` | `2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501` |
| `scar/ir/execution/query.py` | `3fc8137359765f878f2b82476893cc6562da90f4a710144ed764280b4f027c3e` |
| `scar/ir/execution/resource_validation.py` | `3a8bcd72fc07231360b9c9bdc4b35adc9dbc21b569026bba25712d84639b1c08` |
| `scar/ir/v2/values.py` | `2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259` |
| `scar/ir/v2/contracts.py` | `c7aaae3ea0e292e425cfbe820d4508363b9e26e0c94427cefc5a4bb0ae6e15b1` |
| `scar/ir/program/model.py` | `3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1` |
| `tests/fixtures/execution_paths.py` | `f9f0023e212adfb251b5f8e33fc79c868f3aac45d076df79b58eb5d51f3f832b` |
