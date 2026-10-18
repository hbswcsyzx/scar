# D2.4 body / cleanup / lifecycle 有限交叉复核

**STATIC_BOUNDED_PASS：当前修订未发现阻断性连接错误。** 这不是最终测试签核。
只读另一作者(root)的 fixture/tests 与已有输出；未改 tracked 文件，未运行测试/探针。
本人与 root 的公开 scope API 自测不混作这份独立交叉审查。

当前绑定：

- fixture：`cd81d881e6bb5b5b6030bc666db75ce38172e2289b5a680a51c35948bcf229f0`
- tests：`eafe223725a9b14c4771be373eb38a245be338da2bcc98072ea3bdeb3221eceb`

## 检查结果

1. **真实 body source**：组合复用既有 `resumption_cleanup_invoke_program`，包含
   active-cleanup 跨挂起、Resume 与新 Packet→PendingRaise→Replace 两路；D1
   frontier 直接产生真实 Return/Raise source，再生成各自首 publication。新 fixture
   不复制 body source、不伪造 Return 或新 producer。release.sources[0] 的正确链为
   `.commit` 原记录与 `.source.operation == commit.outcome.source`。
2. **作用域/状态分开**：`_Tail` 只向 driver Region 添加操作；原 body C1/C2B
   cleanup/context 栈与 Detach 保持。driver 的 D 包括 body world/context，而 L 为
   lifecycle 子集，release 要求全 D 当前态，不只 L；测试的严格超集断言有实际含义。
3. **helper 两路 current / partial**：真实 unknown INVOKE 消费当前 D；NORMAL 与
   RAISE 各自产生 CompletionResult→独占 landing 的全 D BlockArguments。两边
   release 的 before 集合分别等于各真实 landing 的状态集合，不退回 preinvoke。
   RAISE 的原 ExceptionPacket 仍由真实 host RAISE 使用；release 不将它传给任意
   helper、不替换成一次虚假的 NORMAL。P 仅 NORMAL 有保证，RAISE 空 P 不意味着
   未发生过部分写。F 在两边保留，故失败路径的真实释放阶段可关联先前 body 终态。
4. **来源关联**：每条 drive source 的独立 commit/owner 在对应 landing 延伸；
   helper NORMAL/RAISE 对同一路 body 终态各用同一原 publication，而不同 body
   sources 仍分别保留，不靠 source 集合混配 owner。`_Tail.finish` 更新 host
   terminal 的状态 Uses，保留原 payload/packet，未建立第二份实际状态源。
5. **反例不是无效基线假阳性**：wrong-owner 案先构造 ProgramIndex 的有效基线，
   只把 release owner 的独立 Use 值换成 dominating request Reference；类型/可用性
   不变，所测是 `terminal_release_unfinished`。stale-state 案也先验证基线，仅将
   RAISE release 某个 before Use 换成同域 preinvoke 值，所测为 `stale_state`，
   不是漏 packet/未知 ID。Suspend 案先确认 release=False 的正例，再测真实挂起
   下 release 拒绝；session COMPLETE 不被当作 body finished。
6. **未知 callback**：post after 先成立；独立 unknown helper 后 release 点 P 失效、
   同 owner F 保留，符合冻结条件模型。不从该保留推出 native 条件、仍 held 或 free。

## 实际失败与最终修订范围

`body/initial.log` 为4P/3F，原因是测试错拼 cleanup_replaces 及虚构的 index.blocks；
`body/api-corrected.log` 为5P/2F，中间又误写 `.source.source.id`。这些均是测试
API/字段访问错误，**不是产品漏洞**；原始失败日志已保留。

本审查指出额外错误 `.outcome.successor.source` 后，root 最终统一改为现有
`.source.operation`。当前文件静态已核实该修改；**未运行最终7 cases**，按 root
指令交给即将统一 component，不宣称7PASS或把前轮重叠结果相加冒充最终通过。

## 限定与尚未声称

已有 C1/C2B 基础正反图是本组合的前提；本新增文件没有穷举全部 cleanup / temporal
reentry / delegation / with/except* 路线，也未证明 native/source 对应。没有发现需要
本轮改产品的具体缺口。上述组合仅核对 canonical 源、state/owner/控制边及反例隔离，
不证明自动源码建图、M0–M2 完整、完整 C2/D2、runtime 或任何 LeWM 性能收益。
