# D2.4 B：cleanup / lifecycle 有限交叉审查

**BOUNDED_PASS：最终冻结文件中未发现阻断性模型错接。** 本轮只读他人
fixture/tests、当前合同/validator与已有日志；没有 tracked 编辑、新 pytest/probe、
full/LeWM/GPU。不是本人的公开 scope/wire 代码自审，也不是完整协议签核。

最终绑定：

- fixture：`2c50833ec7571796d9c500e7a43a8daf46ada860676f4bf6203e3662cc841238`
- tests：`aae51c755e934eeaa43c88a57d4f6af16ab2c5ff779c0b37ca67dd58c7bbf5c5`

## 实质检查

1. **两 source 不是造标签**：两 builder 都复用既有 active-cleanup 跨挂起 body，
   D1 对 value landing 的真实 frontier 为 finally.return 和 finally.raise-exit.op。
   私有 landing 首 publication 保留，再分别打包原 completion payload 成 Return/
   Raise pending；没有靠 helper RAISE 重写成 body RAISE、或捏造新的 body producer。
2. **owner/source 逐边保持**：每条 publication 的准确 owner 与其 pending、request、
   current states 独立 CFG Uses 转发到 shared cleanup entry。Reference formal 的
   must-history 来自 actual→formal 相关性；多锚T合流后两个来源都可解释同一 selected
   owner。Return payload 改充一个 phi arm 的 owner 时只剩一边有F，故正确拒绝。
3. **scope 准确**：新 driver protected 与 cleanup 为同一函数的兄弟，块各有唯一
   direct owner；gate 拒绝留外侧。旧 body cleanup 在另 Region，不被改写。新 driver
   context domain 指向其 entry 已携带的规范 Location，未借共享 Location 合并对象身份。
4. **pending / context / state 分开**：Enter 输入准确 entry.pending，结果0为私有
   SAVED_HANDLED_CONTEXT；共享状态独立产生全D after。Resume/Replace 消费本
   activation 的 original pending/context，state不是保存的 world 快照；release 后
   Resume before 精确取各域最新 release result。
5. **真实 INVOKE 两边**：R/B与全D仅进入 invoke_arguments；pending/context/owner
   copies 是独立 Uses，仅在真实 CFG edges 转发。NORMAL/RAISE 用各自 CompletionResult
   提供全D当前态，RAISE另提供真实 ExceptionPacket。失败路径 packet→新 PendingRaise
   在 Enter 后构造，随后 release，再进入仅 Replace+Jump 的块；原 saved pending/context
   仍同原 Enter。Replace 后按新 selected pending pop，再 route/dispatch，不绕过清理。
6. **P 的版本失效有实际前提**：两 source 的 HOLD 经准确 R/B phi 到 Enter 前，
   Enter 的全D未知写消除P；随后 metadata 显式建立新 HOLD。helper NORMAL 在其
   final after 重建 COMPLETE/ABANDON，RAISE不建立；release、Resume、Replace 的
   未知写均不错误保留P。F按固定条件保留，但不推出当前session/ownership/物理free。
7. **反例隔离**：wrong-owner 使用已有 dominating Reference；phi错臂用真实
   produced Return payload，类型可用性仍成立；旧state仅换同域 Resume before；
   私有escape新增独立 UseID，避免以duplicate Use偷过预期guard。提前release
   则构造真实全D after并将gate切到新currentstate，不能靠后续commit借未来F。
   这些拒例断言 terminal_release_unfinished / stale_state / pending_escape /
   cleanup_context_escape，针对实际连接问题，没有用随意坏ID制造假阳性。
8. **wire / query 有界**：roundtrip仍使用既有 schema14，不新增scope实例/许可或
   状态快照；release查询回连原commit，C1 copies/stack查询来自已验canonical事实。

## 已有执行证据与界限

只读确认 attempt-001 为4P/0.53s；attempt-002、最终attempt-003均13P/1.08s。
最终 SHA 与 root 的冻结通知及 attempt-003 指纹一致。没有把重叠执行次数相加当
新的覆盖，也未在本审查重跑它们。

这些是实际建成的手工 IR 组合正反例。没有覆盖全部 nested cleanup/reentry/
with/except*/delegation/family native 路线；未证明 native source/guard/runtime 条件。
本审查没有发现需本轮更改产品的确定缺口，不为了凑数提出新模块；不宣称自动源码
恢复、全程序自动建图、M0–M2或完整C2/D2已完成，不授权变换或声称 LeWM 加速。
