# R3.2 组合内核有限独立源审

结论：**OPEN_WITH_SCOPE（未发现已确认的 unsafe/错端口 blocker；S1 的独立 source 展开范围待 root 对齐）**。
本报告只审他人实现：`composition_query.py`、`composition_routes.py`、`query.py::resource_composition`。
不把本人编写的 refresh/P/V 代码列为独立复审；P1 requirements 尚在收尾，本次未审。
没有新增测试文件、运行 pytest/probe/component/full 或修改产品。以下是源推断，非旧实现运行复现。

## 已核对关系

1. `query.py:61–69` 先验证 exact budget/scope/local owner，再只调用一次 `_content_context`。
   后者委托统一 fresh external helper；没有每 read 重新构造 resolver 或信任旧 external 派生的接线。
2. `composition_query.py:24–51` 的 read `pending = total - completed`，不是减 visited。
   子 V 没做完时本行标 TRUNCATED，cursor 保留 `phase=validity`；刚读 identity 无余额时也保留原 read。
   后续未开始 read 的 identity 游标与全量 `inventory.execution` 均保留。
3. 同文件 `153–158` 把同一个 budget 传 requirements、reads、production、sources、routes、lifecycle。
   没有调用公开 P/V、没有派生预算 reset；routes 的累计 `budget_used` 没有再次扣除。
   `164` 顶层只有一次 deepcopy；准备/FK/replay/复制成本明确不伪称受 4096 总 CPU 限制。
4. `composition_routes.py:48–84,163–190` 以原 predecessor op/实际 successor/argument ordinal 回查。
   ordinary/SavedInput 才有原 copy Use；CompletionResult、BodyDriveResult、ResumeInput、PendingPayload 保留 typed projection。
   BodyDrive 只引用原静态 outcome Use，dynamic occurrence 明确 None；不猜 body activation。
5. `composition_routes.py:135–160,192–230` 保留原 ValueOccurrence producer/visit/ingress 与已有 call association input/output。
   缺 call link仍是 MISSING；同 actual 的不同 Use 不合并；不构造第二套 producer/actual 图。
6. `composition_query.py:106–145` 分别列 actual host transfer、outcomes、quiescences、retentions、handles、target lifetime events。
   没有从 host Return/RAISE 产生 work terminal，没有把 terminal/quiet/borrow release/close/retire/persist 互相升级。
7. 顶层及 routes 权限维持 False；DERIVED 是已扫描所给行，不是 scope/runtime/capture 完整证明。

## S1：无 read 时的独立 source effects 展开范围（源推断，非已复现 bug）

`composition_query.py:73–103` 目前仅展开每 inventory 的 source metadata、raw_record_count 和 artifact refs。
如果某 source 原 EEG 有 ESCAPES/OVERWRITES，但模型没有 ContentRead，就不会执行任何 P/V source candidate 枚举。
这类原关系仍能通过 manifest/artifact 回查，来源没有从 inventory 删除；但返回结果没有该类 edge 的已检查/未展开计数或游标。
因此不能把此 source section 的 DERIVED 读成“独立原 source effects 已逐条扫描”。
本项不会授 unsafe ready/transform（capture_complete 与 authority 均 False），不是拿不确定事实当运行失败。
但 `design/routes.md §5` 明确要求不能依赖某个 ContentRead 偶遇 ESCAPES 才列账本，故需 root 对齐公开范围。
最小建议：保留 source 级原 edge/raw 总数与未展开计数/状态，或用同一预算做 source-only 展开；无须新 IR 图/native parser。

## 部分行计数的语义（非 blocker）

- `composition_query.py:99–101` 的 source `pending` 是尚未访问的父 inventory 数；父行展开到一半可能为 0，
  但 nested `pending_sources`、typed cursor、TRUNCATED 同时保留。
- `141–144` 的 `pending_work` 同样是未访问父 work 数；部分 outcome/quiescence/retention 在该行各自 pending + cursor 保留。
- `composition_routes.py:239–257` 的 pending 明示不含部分行，`scan_complete=False` + cursor 区分。
  API 应保留该解释；不能把这些父计数单独当作全子查询完成位。read 层已使用更强的 completed 定义。

## 测试矩阵读审边界

已只读现 `test_execution_composition_routes.py`：有真实两次 call、双 Use、缺 link/Use、N/R 反排 CompletionResult、
Suspend saved/current、C1 pending/context、BodyDrive 静态投影、loop incarnation、partial route cursor。
已只读正在落盘的 `test_execution_composition_query.py`：请求先验拒绝、单 preparation/replay/copy、detachment、semantic catalog 突变。
未把这些未由本人运行的 case 当独立实测；历史本人 16 项 P3 与作者 routes 10 项亦不替代公开组合验收。
root 联合矩阵仍须覆盖 host RAISE + pending/partial work、读级截断 pending、source/work 子行截断、cleanup release/close/persist 分离。
完整 M0–M2、runtime/native pairing、endpoint 协议和 transform 授权不由本报告关闭。

## 实际阅读 SHA256

```text
82daf1230d00da4511162b94840553722df247b85a472b6373b4128970e12159 scar/ir/execution/composition_query.py
4218b52b7f2d7f9b775011127dbca54015303ae17d062d465cc687f93a36e7ca scar/ir/execution/composition_routes.py
9e0ca23248b459be36b890b1e3b5e80139b74476550a5e7bffca99325dc6882c scar/ir/execution/query.py
f26b56470eeced476769fdefbc15f5f2939cff0f5d9380d78a7b68fe0ed1138e tests/unit/test_execution_composition_routes.py
20e84828158f76544409514cc4856c864b03a792a7a328a40ea09bfad04ebcd7 docs/M1_PIPELINE_COMPOSITION_PLAN.md
```

本次审查进行时源码仍由各 owner 集成；本记录不是全局最终 freeze receipt。

## 追加：S1 窄范围关闭与公开接线 receipt

结论更新为 **PASS_WITH_SCOPE（本报告所审 P2/公开接线范围）**。上文旧 OPEN 与旧 SHA 保留，不冒充旧版运行失败。

- 新 `composition_query.py:87–108` 遍历原 source bundle EEG 的全部原 typed edges，独立于 ContentRead。
  每行收取共享 `composition_source_edge`；没有新候选/producer 图，也不复制整个 bundle 或 raw tensor。
- evidence view 有原 `instance_count/edge_count/edges/pending_edges/status`；中途耗尽时准确保留
  source inventory/source/edge 三层 ordinal cursor。已访问父行不消除未扫描子 edge 分母。
- 原未知 graph 保留 UNRESOLVED；DERIVED 不提升为 native complete capture。
  新 API §5 明确 source/work 父 pending 与子 pending、read completed 计数的区别。
- `query.py:61–69` 的入口仍只有一次 fresh 准备和一个共享 budget；调用链未增加 per-read replay/copy。
- 源码和测试只读核对；本人没有启动任何新测试。root 的 `public_boundary/attempt003` 保留 **15P/1F**，
  失败为测试访问不存在的 `model.work_outcomes`，非产品执行反例；仅修为原 `model.outcomes`。
- 已读取 `attempt004` command/source.before/source.after/stdout/report：**16 PASS / 1.02s，exit 0**。
  其中无 read 独立 EEG edge 与只展开首 edge 的准确剩余计数/cursor 正例均存在，三文件哈希与当前相符。

本次闭合版本：

```text
ffd2a66f829b2f9e956aea16f27c51f0a38c914c45d3bb00cb2fc1dbd95e7bcf scar/ir/execution/composition_query.py
4218b52b7f2d7f9b775011127dbca54015303ae17d062d465cc687f93a36e7ca scar/ir/execution/composition_routes.py (未改)
9e0ca23248b459be36b890b1e3b5e80139b74476550a5e7bffca99325dc6882c scar/ir/execution/query.py
3ae70fb341d6f7b801815701251599b2599adb15281b7a2d83fd92dc694f84b9 docs/M1_PIPELINE_COMPOSITION_API.md
c9bd665ba388ce96f62e9680c45a2392fbc518bc67cf0350601424407ad27e60 tests/unit/test_execution_composition_query.py
```

非阻断文案建议已发 root：API §5 的“一次 inventory replay”准确含义是每个不同 manifest/index
工件对在本次准备至多重放一次、不随 read 重复；`source_validation.py:20–30` 对精确工件对去重，
多个不同 inventory 仍需分别解析。不能宣称所有来源只解析一个 inventory。
P1 仍未在本报告审查；公开联合矩阵和全局 freeze 由 root 统一。没有新的 runtime/native/endpoint/
完整 M0–M2 或 transform 证明，本 receipt 不扩大前述范围。

## 追加：pre-component 最后窄修复 receipt

只读核对最终 `query.py` SHA256 `5846aeb2db281a6e6b1a70fa291c382eed18292e0facab03abbe9e31fb33e8eb`：
`ExecutionIndex.production` 仅删除外层冗余 deepcopy，直接返回已经在 public P wrapper 内 detach 的结果。
P wrapper 仍在唯一出口 deepcopy；其冻结 SHA `dd275a767d8da5f54f5abf5e67126ed6c471ba10a25ec9d00f22a773df7a1737` 未变。
V wrapper 冻结 SHA `fbf10cb04c44f0e3562b7b746b846ca2c77d09905689f9ab1adb13f43f012780` 及既有单 detach 接线未变。
本项不改预算、源候选、diagnostic 或公开 dict 布局；不将取消重复复制称作新功能或性能验收。

最终 API SHA256 `7dc55b2ff6a5c06daa76f308dba7bb3b4dd2c3f5e99d4c6edcb7416d8015e4aa`：
§5 已准确写为每个不同 manifest/index 工件对在本次准备中重放一次，不随 read 数量重复。
上段非阻断文案建议关闭。有限 PASS_WITH_SCOPE 不变，无新增运行/测试；后续统一组件由 root 执行。

## 追加：Q 预算快照最终 receipt

最后只读核对 `composition_query.py` SHA256 `ed631511a56893d419edf76c8ddbf15862761c7e851227db772348471587aa6c`：
Q 返回后立即把 observations.budget 改为普通 dict，复制当时 costs；后续阶段仍使用同一个真实 budget 控制器，
顶层 budget 仍是全查询总账。没有隐藏 reset、重复扣费或向公共结果暴露可变控制器。
source-only 修复与原 typed routes 未变，有限 PASS_WITH_SCOPE 不变。

同步核对：

```text
5846aeb2db281a6e6b1a70fa291c382eed18292e0facab03abbe9e31fb33e8eb scar/ir/execution/query.py (未改)
c6c7fa8279e24a0e6822e194c14c1bd6427b52be7d25eb5d09105609f4783e13 tests/unit/test_execution_composition_query.py
6323a5dd3ccc3247061b329305b67a438bbe66a0c4c3bc2f5e0be2dc3e89d02a docs/M1_PIPELINE_COMPOSITION_API.md
```

测试只增加现有单 preparation/detach 用例的 dict/阶段 used/成本求和断言；API 准确区分 Q 快照与总账。
本人没有运行该末次改动的测试，不挪用 attempt004 作为新 SHA 的实测；由 root 下一统一组件覆盖。
此后本 agent 全部 source/tests/report 停止写入，等待冻结归档。
