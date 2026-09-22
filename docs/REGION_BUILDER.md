# G6：区域构造、来源回溯与跨层依赖

状态：**Implemented，待 G6 独立验收**。G5 已通过，不解除 backend 冻结。

## 1. 建模决策

优化单位是带接口的 operation 集合。function/operator/loop/stage 是不同的
region 视图，不是彼此互斥的节点类别。一个区域能够递归展开，但原始 definition
和 invocation identity 始终保留。相同函数的两次调用不是同一个成员。

分开构造 semantic 与 execution 视图。静态 lexical parent 表示源码结构，
不证明函数体在 module 初始化时执行；动态 parent 表示实际调用包含关系，
不证明所有 branch/loop/异步工作已覆盖。两者通过 G5 correspondence 相连，
不合并成一个假定完整的图。

区域构造有三个不同结论：

1. 已知节点和跨界边被完整列出；
2. 在明确 scope 下，值、消费者、alias、效果和控制的语义闭合；
3. 某个替换符合 Q 且有收益。

G6 负责第 1 项，并保留第 2 项的证据与缺口；第 3 项由后续规则/planner 判断。

## 2. 接口与严格身份

OIR port 要能引用静态 `ValueSlotID`，不能为了填满接口而伪造动态版本。
另外需要显式 effect target/occurrence 引用。输入、输出、状态、控制、资源、
escape、ordering、effect 分开描述。同一个值可以同时出现在多个必要端口。

每个 `OptimizationRegion` 有唯一对应的 typed construction record，至少记录：

```text
view / scope / mode
roots / direct members / children
boundary dependency edges
per-facet completeness / evidence / gaps
```

不把这些信息藏进无类型 metadata。序列化、dangling refs、重复身份、错误 scope
和跨视图成员混用必须被拒绝。每个 region 有 original NO-OP，G6 不创建 REWRITE。

已知跨界输入来源于 region 外部，或无法证明其内部定义；输出包含对外消费者和
未闭合的潜在逃逸。不能通过 `reads - writes` 删除先读后写依赖。缺少消费者
不构成输出 dead 证明。G5 的开放 effect boundary 直接成为区域缺口。

## 3. 自顶向下构造

从 root operation 向下按需展开；先报告外层 region，再报告子 region。构造
instruction、operator、function、loop-body、dataflow-subgraph、pipeline-stage
需要不同的成员/控制见证；没有循环见证时不从重复次数猜 loop。

明确 member 集合的查询允许部分重叠。不会枚举所有节点子集。批量验证一次，
使用临时父子/slot/occurrence/dependency 索引；可变图不能永久标记“已验证”。

## 4. 第八层到第三层：回溯不等于上移许可

沿实际版本 provenance 与显式 invocation/slot binding 回溯来源，逐段列出
版本、producer、materialization、copy/view/transform/mutation 和证据。
外部 origin 没有 producer 时要明确报告，不能拿首次看见它的 invocation 冒充。

传参可以保持版本，物化可以保持逻辑版本，mutable copy 可以从共同祖先分叉，
transform 生成派生值。共同祖先不是 exact equality，也不是 loop invariance。
绑定区间含糊、过期或未知时保留缺口；shape/前缀值不参与身份归并。

上移查询输出目标位置、跨越的区域、新增/删除的边界依赖、生命周期延长和待证
义务。即使全部输入来自第三层，仍要检查参数/隐藏状态/RNG、控制支配、零次循环、
异常时机、autograd、alias 和 readiness。单条动态路径不能证明所有路径可上移。

## 5. 重叠与冲突

成员重叠、集合包含、语义冲突分别查询。两个不相交区域仍可能写同一个状态或
共享 storage。未闭合 alias/effect 只允许报告可能冲突，不能说无冲突。跨 view
先使用 correspondence，不能直接比较 definition 与 invocation ID 字符串。

## 6. 验收

验收由开发代理执行，并生成绑定 commit/hash 的报告：

- 各类已知接口和缺口都有显式表示，非法引用拒绝。
- 父到子的展开保留 identity，静态包含与动态调用不混淆。
- 通用八层传参 fixture 回溯到第三层；copy/transform/mutation/缺失绑定为反例。
- motion delta 列出跨界依赖与义务，不宣称允许 MOVE。
- nested、partial overlap、disjoint-but-shared-state 和 unknown alias 均有测试。
- deterministic JSON；所有 region 只有 NO-OP，零 backend invocation。

通过后自动进入 G7 report-only 图化简，不请求用户阶段验收。

## 7. 已实现 API 与实际限制

```bash
scar regions-v2 /project/program.py --view semantic --max-depth 1 --out /tmp/source-regions.json.gz
scar regions-v2 /path/to/trace --view execution --root-limit 8 --max-depth 0 --out /tmp/runtime-regions.json.gz
```

默认选取单个观察范围中最大的已观察调用子树，至多八个 root；相同时按稳定 ID
排序。报告列出全部可选 scope、选中 root、成员数量和未展开子项。原始图完整
保留，这个投影不代表 whole-program 优化分析已完成。

`RegionInventory.region(members, ...)` 接受显式非连续成员；`build_regions`
按父→子构造。`RegionConstruction` 与 OIR region identity 一一对应，记录
scoped effects、跨界依赖和每一类边界缺口。静态端口引用真实 ValueSlotID；
动态端口引用版本/物化；控制依赖可引用外部 definition 或 invocation。

OIR schema 2 显式读取并升级旧 schema 1。旧 schema 意外允许的 value 型
ORDERING port 会被拒绝，而不会被静默解释为新含义。构造校验会根据原始
图重新检查投影，删除已知依赖/端口/效果记录不能以“没有 dangling ref”蒙混通过。

当前 source data ports 是保守的可能输入/输出集合，可能包含内部临时值。
这避免通过 reads-minus-writes 丢失先读后写依赖，但不是精确 SSA interface。
未有 operation 归属的数据↔数据 alias 边仍可在原图查询，区域标记 alias
缺口，不能声称完整 alias closure。G7 需要进一步的绑定版本与操作语义。

`RegionQueries.origin_for_region(...)` 把 G4 显式 binding 与真实 execution
region 关联；第八层→第三层 fixture 使用受验证 producer 见证。共同来源、
输入/输出捕获和 materialization producer 不会自动变成 logical producer。
`motion(...)` 返回 REPORT_ONLY、已知边界依赖变化和七类待证义务。它既不改图，
也不宣布允许 MOVE。没有 capture 时不会在 LeWM 旧 trace 中杜撰这些见证。

`compare_regions(...)` 分别输出成员重叠与效果/数据依赖。对比预算耗尽、未知
alias、开放终点或效果覆盖不足时保留可能冲突。纯读集合使用线性筛选避免
无用的全配对扫描。已知共同 target 与实际 storage-region overlap 可提供
明确依赖证据；不同 descriptor 字符串不是 disjoint 的普适证明。
