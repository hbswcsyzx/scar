# 来源、真实终点与最终消费者：连接进展

2026-10-19；基线 `35b399d0d49b39b78530f571c448987170aa62a3`。
[冻结计划](M1_AWAIT_SOURCE_TO_TERMINAL_PLAN.md)与
[pending 投影合同](M1_PENDING_PAYLOAD_RELATION.md)保持原字节。
这是原 P4 的一段进展；完整 A–H、F12–F24/X25–X27、P5 和 M2 尚未完成。

## Implemented：落实的模型关系

五类实体仍为 **Operation / Value / StateLocation / Region / Resource**。
未新增 Program23/Execution8 规范记录或修改 codec；查询引用唯一原 producer、
有序 Use、原 completion/state slot 和实际 occurrence，不另建一套可变 SSA。

- **来源到持续主体。** general 的独立 A 在首次 advance 前经真实 lookup、
  bound call、helper 内 Create B、qualification 得到 I。native wrapper 在首次
  advance 前由 B 构造 W；每次 W getter 经 wrapper→driver 的准确调用进入所持
  B。一次 B activation 可跨多个 segments，各 driver 有独立 CallActivation。
- **内层返回到外层结果。** 复用 CallReturns 的 flow/project/export_bundle，
  加入准确 result 结束模式，按目标调用原 exit kind / full slot 取 summary。
  每个中间 frame 仍要求无歧义 caller，target 不能按数据倒选 caller。不同结果
  与当前状态槽分开；拷贝关系不代表执行区域纯或结果可缓存。
- **实际 pending 投影。** 本次 dispatch 的 selector 沿自己的原 token ancestry
  找准确 constructor，再引用该 occurrence 的 payload Use 与选中 port。
  Pending token 不等于 payload。receipt 保完整来源，按需计费，不免费预求
  跨实例连接；cache 不跨 context。已知 ObjectID 冲突明确 False，未知身份保 gap。
- **真实终点分类。** C1 Resume 保 Return、Replace 产生实际 BodyRaise，均经
  两 cut 保存 pending/context 后到真实 RETURN/RAISE。Return 分支接原转换与
  E/G/F 自己的 N/R 结果；BodyRaise 只传播 whole packet 到准确 host RAISE，
  不伪造 StopIteration 提取义务。
- **原始分母独立。** 预算耗尽仍保 explicit link/case 与原 Drive successor 键，
  状态为 NOT_CHECKED。删除 link 后独立 source/advance/Drive 库存仍在，未知
  ownership 总数保 None，不为呈现完整而免费构造笛卡尔积关联。

`projection.payload.binding.compatibility` 是冻结合同后的查询字段细化：paid
fresh compatibility 能拒绝已知身份冲突；原端口 copy True 不授 native/value
identity。所有 source/runtime/value/transform authority flags 继续 False。

## Verified：真实执行与结果

证据目录：`artifacts/experiments/b1_call_operands/model_await_source_terminal/`。
每次命令、日志、JUnit、源码前后注册表和两个诊断脚本均保留，失败不覆盖。

最终受影响相关回归：**1671 passed / 0 failed / 0 error / 0 skipped**。
pytest 268.51s；串行 runner 269.6029186407104s；818 个源码文件前后摘要一致：
`debd6988889dacc4ba8b8799e304747d01f6117405c7b9e34c575bc071d3d3bb`。
保留原 1572 个精确 case identities，新增独立用例 53 项，并纳入 46 项既有
composition 查询测试。这是 affected focused，不能称 full regression。

新增用例来自三位独立作者：general 17、wrapper 21、C1/pending 15。覆盖零/两
cut、depth1/2 的若干正常/异常 child 组合、完整 own-result/state 槽、两实例、
缺实际关联/Use、错源与旧状态、整 link 删除、budget1，以及多个 caller、独立
packet 和已知 pending ObjectID 冲突。**这不是所有维度的完整笛卡尔积。**

首轮 22P/28F，第一次集成 35P/15F，跨层集成后 48P/5F。产品缺口与新增作者
错误分别记录在 `attempt-notes.md`，有限审查与精确 SHA 见 `independent-review.md`。
没有修改旧 tests/fixtures 取通过，没有将新手工夹具当作自动源码建图。

### Rejected：不能用成功拷贝掩盖身份缺口

真实 diagnostic-02 表明：NORMAL slot0 的 selected、copy 和 contribution 均 True，
但 Ref 没有独立 ObjectID 声明，故路径保 PARTIAL，唯一 gap code 为
`body_reference_identity_unproved`。state slots1/2 无该缺口。新测试曾误要求
gap-free DECLARED，现改为明确核该 PARTIAL 和精确 gap；所有逐 hop、actual
terminal Use、parent result、target 与 current-state 断言保留。未删产品身份检查。

## 原验收与下一步

`original-obligations.json` 把本轮新增 selectors 填回原 A–H 的 partial evidence；
八格仍未关闭，原十六组也均 OPEN。原仓库 tests/fixtures、既有合同/codec 和
上一归档字节由 checkpoint 再核；`~/AAA/le-wm` 和 `~/AAA/scar` 原 checkout 的
HEAD/status 保持基线。未新增 detector/backend、LeWM 特例或性能结论。

接下来继续原缺项：

1. **转换之后的 C1 续接。** 本轮 C1 在实际 body terminal 之前；这不能证明
   conversion 后 CleanupRoute/PendingDispatch/Suspend 已贯通。复用既有
   `packet_continuations`，先将 NORMAL Reference 经原 PacketDefinition 接为
   whole packet，再按准确 leg/case 保可能 port、当前 token、payload、Replace
   与 actual cut，最后接 parent R/state/consumer。不可只放开裸 CFG 遍历。
2. **来源/失败/发生组合。** native/self、general/W 的实际 BodyRaise、获取或
   构造失败、共享 incoming、重执行与缺采还需按原 A–H 合账；现有正例不替代。
3. 原十六组真齐后再组件/full、P5、M2 原 113 构造/196 字段总核；M0–M2 完成
   后按用户要求停下来讲解模型，随后才推进完整自动来源恢复和化简。

重放归档核验（不启动测试/workload）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python \
  artifacts/experiments/b1_call_operands/model_await_source_terminal/checkpoint.py --check
```

运行需 `conda activate lewm`。重跑测试须新建 attempt 目录，不覆盖上述证据。
supplied-model 连接不证明自动 LeWM 全程序建图、合法变换或任何加速比。
