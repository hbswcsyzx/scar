# D2.3 terminal E/F/T 实施交付

2026-10-18；任务基线 `817cc0b`。只修改获分配的两个新增 tracked 文件：
`scar/ir/program/lifecycle_flow.py`、`tests/unit/test_lifecycle_flow.py`。
未改其它产品、fixtures、validation、docs；没有 git、component/full、LeWM 模型或 GPU。

## API 与边界

- `derive_terminal_facts(graph, interface) -> TerminalFacts`，限定显式 DriverLifecycle 的同一 driver Region。
  调用前需 core/D1/publication/no-body/new shape 通过；模块不会调用 validate 或 ProgramIndex。
- `TerminalFacts(region,before,after,edges)`；前两表按 OperationID，edges 按 `(OperationID, successor_index)`。
  edges 是本边同时 actual→formal 改名后、目标 join **之前**的事实，供 root P 分析复用。
- `TerminalPointFacts(reachable,aliases,finished,sources)`，提供 `same_owner`、`is_finished`、`source_operations`。
  dataclass frozen/slots；所有 maps 为防御复制后的 MappingProxyType，成员集合为 frozenset。
- `reference_assignments(operation,successor,*,values,blocks)` 返回真实 Reference formal→旧 actual Value/None。
  使用 canonical owned Uses 和 saved_actual_use；保留 ordinary UseID 子类，produced boundaries 不编造 copy。

T 的来源是 seed publication/NoBodyFinish 的 operation ID，可由既有 row 回溯真实 source；
不是新 producer、world、owner 实例 ID、可写 proof 或可消费许可。

## 实际算法

第一阶段只存整数 carrier 的 canonical equality partition E 与 finished 布尔集 F。
预索引该 Region 的操作、Reference、普通结果 forget 及每一条真实 CFG 边；不同 successor 不合并。
真 entry 自反且 F=false；其它 block 从不可达 bottom 开始，有限工作队列不使用迭代上限。
每条边从同一源快照同时重绑所有 Reference formals，恢复已证 alias 闭包，然后才 E 交/F must meet。
ordinary Reference 结果先 forget 旧 incarnation，保留其他仍存 carrier 的 alias/历史。

仅本 scope 的真实 Return/Raise BodyOutcomeCommit 和 NoBodyFinish seed owner 等价类。
Suspend 不 seed；unknown callback/new gate 不撤已有历史；release 没有消费或次数规则。
结果/entry formal 重定义不从静态 ValueID、类型、端口或 constructor 集合得到旧对象历史。

第二阶段在**固定** E/F 上从空 T 开始；transfer 仅常量 seed、copy/同时 rename、forget、union 及固定 F mask。
T 不影响 F 或 release 资格。相同 terminal 站点可以覆盖解释来源，但不改变第一阶段 lattice。
最终每个 F=true carrier 均断言有非空派生来源；解释可能有多锚，不表示所有锚均执行/最新锚或 refs held。

E/F 点域有限（相等对/F 位高度有界），第二阶段 T 只在有限 seed 集上增长；没有路径/配置枚举。
公开 before/after/edge view 由稳定结果产生，复用相同 fact 对象；不写回 ProgramGraph。
当前 world/state correctness 与 P/session 支持不在本模块重建。

## 首次及后续定向证据

三次均明确 `source .../conda.sh; conda activate lewm`，仅 pytest 本 owned unit 文件；
各 attempt 目录原样保存精确 command、stdout、stderr、JUnit 与 result/hash。没有失败记录被覆盖。

| 目录 | 实际结果 | 目的 |
| --- | --- | --- |
| attempt-001 | 8 passed in 0.34s，exit 0 | 尽早落代数及已有 publication/no-body 正例，首跑即通过 |
| attempt-002 | 14 passed in 0.41s，exit 0 | 加 600 次有界 concrete E/F 传递 sound 检查、四种 resolver 边界、scope |
| attempt-003 | 4 passed, 14 deselected in 0.42s，exit 0 | 仅新增的真实 require_valid 多源共享/有锚与无锚 loop 图 |

当前 owned 文件有 18 个 pytest cases；没有把重叠执行次数当独立覆盖，也未声称已在本轮一次执行完整最终18。
attempt-002 的 600 次检查来自 100 组有界 concrete object/history ×6 变换，不是产品语义覆盖率/通用证明。

真实图先 require_valid 再 derive，确认：

- NoBodyFinish 与 BodyReturnCommit 两条不同历史来源，精确 selected owner phi 共用后继，T 保留两锚。
- 同图 self-loop 携带已 finished owner，稳定保留 F/T；无 seed 的真实 loop 不自造 F。
- 将一边改送未 finished 的 produced Reference payload，join 后 F/T 丢失，而逐 edge 仍一真一假。
- Start/Suspend 不 seed；Resume Return/Raise seed；predicate-only 不 seed。
- 同时 swap、forget 单 carrier 保留其他 aliases，未知结果不能因可能 alias 就获 F。
- CompletionResult、BodyDriveResult、ResumeInput 都是非 copy；SavedInput 与 ordinary legacy UseID 真实解析。

供 root/P 复用的同一 helper：`tests.unit.test_lifecycle_flow._shared_flow_graph`。
参数 `seeded=True,wrong_owner=False,loop=False`；返回 `(graph,ValueID('flow.join.owner'))`。
loop=False 查询 `flow.return` 前，loop=True 查询 `flow.loop` 前；两条入边操作为
`driver.no_body.return`、`driver.outcome.exit`。loop 下游 return 则使用 `flow.exit.owner`。
不需要再造第二个共享 CFG fixture。

## 撤回的审查假设与保守范围

root 曾怀疑跨 Region Reference literal 能绕过 availability，导致 carrier 未索引。
实际 core `cross_region_use` 对 value.region 无条件检查；literal 仅豁免 availability 的定义支配。
该假设已由代码反证并由 root 撤回，**不是 core-valid 产品漏洞**。未为此改 carrier、扩大域或新增伪正例。

本模块保留的是封闭 profile 条件下同对象/同 lifetime 的终结历史，不证明 native 类型/guard/字段、
no-reset、当前 session occupancy、reference 仍 held、耗尽/free、drop 保证或优化权限。
真实 source/runtime、root P 与 release shape/validation/query、wire/CLI 均由其它门负责。
测试为手写 IR/有限 oracle；没有自动前端、runtime probe 或长期 proof/store。

## 冻结 hash

- lifecycle_flow.py：`8adaa530a1801949a0706948c9aef2410148782fa95e49da18706ed5c794fae0`
- test_lifecycle_flow.py：`af4efa34a3fe50337050a6b20f08e32fdc92db47fb0f6d363dffc5414689efff`

两文件现冻结供 root 集成；后续独立审查只审 root 的 P/release/analysis/query，不将自写模块当独立审计对象。
