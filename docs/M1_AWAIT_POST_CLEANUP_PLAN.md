# 原 await/C1 后继：两层边界与验收计划

2026-10-19；基线 `107ff11efd0d8369583b613282dfca5450692c48`，首次核对工作树干净。
上一轮为 progress：1671 affected focused、原1572 identities守恒、归档核验、
提交与远端精确 SHA 已确认。完整原 A–H / F12–F24、X25–X27 / P5 / M2 113构造
196字段保持开放，本轮不以更小的新 helper 门替代原分母。

## 1. 先校正模型边界

五类实体仍为 Operation / Value / StateLocation / Region / Resource；规范
producer、Use、current-state 和控制边不复制。同步调用完成、body Suspend、
后续 Resume 是不同控制事实，不能为测试方便合成一个模糊返回事件。

```text
内层 B 实际 Return
  → 同步 driver D：转换 own N/R → whole packet → 同步 C1/dispatch → D terminal
  → 准确 caller result / 真消费者 / E-G-F own N/R
  → 若外层 P 是 resumable body：P 原 pending/context → P 的两次 Suspend/Resume
  → P 自己的实际终点（由 P 的独立外层 driver 驱动）
```

D 经 CALL/INVOKE 进入，不能将它改标 ResumableBody 后塞 Suspend：core 明确
拒绝直接调用 resumable body；driver entry 的 RAW 也不能冒充 body Start 的
Reference 输入。C1 本身不要求所在 Region 可挂起，同步 D 可以有合法 C1。
真正两 cut 要在 P，保独立 activation/segments、context attach/detach、Drive
和本次实际 CallActivation。不能把条件性未来恢复当本次 D 调用完成。

## 2. 复用已有关系，补连接信息

`packet_continuations` 已能核 independent possible-port、当前 token、原 payload、
Replace、saved/context、known helper 与 opaque/cycle 边界。当前扁平 targets
不足以直接替换 await 的 terminal_inventory：它去重后丢来源/条件，且可以继续
走未来 Suspend 后继。不得只放开终点查询的 terminator-kind guard。

补充的是有预算的临时查询 receipts，不是新 IR/第二套执行图：

- 每个 terminal 的 HostTerminal、准确 payload Use、root source、当前 source/role、
  当前 copy 与 root-preserved copy、该 case 的原 choices、是否跨 Suspend。
- action、projection、override、check 保各自来源与 choices；原扁平输出兼容保留。
- choices 是已有 source/case/token recipe 约束，不宣称完整路径，也不枚举任意
  分支路径组合。未闭上下文、多个 caller、cycle、截断仍保明确边界。
- 同步 D 查询到 Suspend 停在明确 boundary；P 的后继查询可以沿声明恢复，但
  动态验证必须再核原实际 transfer/segment/Drive，不能由静态 receipt 赋实际发生。
- NORMAL conversion Reference 先经原 PacketDefinition.exception 接 whole packet；
  RAISE 用其自身 whole packet。合法 Replace 换源/换完成方式须独立记录，不能
  继续要求新源复制旧包或授原 BodyReturn 的最终提取语义。
- P 正常结果经 pending Return 保留 Reference，复用同一 typed continuation
  引擎，不能把 Reference 冒充 exception packet；输入/结果/state 仍分别证明。

## 3. 原单位的两段用例与分工

根独占产品、文档、所有 Python/pytest/probe/compile、归档与版本管理。作者只
新增独占 fixture/test，不动基线旧 tests/fixtures/合同/codec，不启动解释器。

1. A：同步 D 内 conversion→whole packet→真实 C1/dispatch→D terminal→准确
   parent/最终消费者的完整静态图；保留/Replace/另包/opaque/预算反例。
2. C：真正外层 P 组合。P 调用真实现有 await pipeline/helper，随后 pending/
   C1 两 cut，准确外层 driver 与实际采集；正常 Reference 与实际异常分开。
   不把同步 D 改为 body，不复制并列不相连的图。缺本实例 Resume/Use/association
   不能借另一实例。先与 A/root 冻结最小接口，再写实际完整图。
3. B：有限独立复核原分母、completed call vs future resume、replacement 源与
   有预算 receipt；只为具体发现补本轮独立反例，不扩无关矩阵。

## 4. 自主验收与原剩余范围

先独立完整例/反例冻结→root 串行首红→按真实失败修公共关系→有限独立复核→
冻结源→原1671精确 identities 守恒的受影响回归→失败与证据归档→commit/push。
每次实际执行保 command/log/JUnit（若有）及前后 source 注册表。作者错误单列，
不为它改变规范合法性或放宽旧断言。未证 Ref 身份保 PARTIAL；所有 source/
runtime/value/transform 权限标志继续 False。

同步 C1 成功不关闭父 P 两 cut；P 静态恢复不关闭实际发生；这两段成功也不关闭
原来源/资格/失败/共享 incoming/重执行的全部组合。原十六组真正齐后，才做
组件/full、P5 与 M2 总核。M0–M2 完成后按用户要求汇报讲解，再停下。
不加 detector/backend、LeWM 特例、profiling 或加速结论。
