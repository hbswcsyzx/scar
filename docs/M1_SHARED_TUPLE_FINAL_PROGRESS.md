# 原 G 共享输入与最终链：进展

2026-10-19；基线 `635c9976120ef2120ce8c1e22a5437b04b03b696`。
[冻结计划](M1_SHARED_TUPLE_FINAL_PLAN.md)保留原字节。原 A–H、十六组、P5 与
M2 原113构造/196字段仍按原范围验收，不把用例数当模型完成度。

**验收：原 M1 条件结构 G 关闭。** 最终同源码1780项通过，0失败/错误/跳过；
原1747项全部保留，新增33项。846份源码 SHA
`8186b69117eba8d5df3f0ea31de12f5b5e32b2ef8a1e1d4b039a9ad0cc0eb709`
在执行前后不变，pytest563.17s、外层564.3408122751862s。
这不是全仓回归，也不是完整 M0–M2 / 自动 LeWM 建图或性能验收。

## 审查与实施状态

现有 case 图只验证 first Suspend；general/W/final/C1 已核的结构连接应如实
计入 M1。新的完整图把原 incoming、真实 caller copy-loop、共享 E/F 的两个
调用点与最终结果接在一起。原定义仍是 Operation/Value/StateLocation/Region/
Resource；循环访问与调用实例使用现有 occurrence/activation/transfer。

首轮真实 public API 已揭示并修复两处连接问题，未增规范实体或 wire 字段：

1. **Observed → Implemented → 局部 Verified**：两个互斥调用的私有 N/R
   输出到共同终端时，消费者发现有 own-source 必经路径条件，后续 payload /
   state 校验却漏传，误报 final_copy/state。core 完整图合法；原求值点必要
   边加入后，八个 own payload 和十六个 state 诊断绑定由 False 变 True。
   条件来自 source 原入口/edge-cut，不来自消费者成功或同 callee 身份。
2. **Observed → Implemented → 局部 Verified**：universal guard=None 的一条
   声明把两条原 incoming 压成 None。现在从 actual operands 的原 merge
   独立枚举 input_guard，再关联同一规范 case；没有复制 case 或删路径。

`first-red` 4F，`after-final-prefix` 4F 命中第二问题；
`after-universal-inventory` **4P**，845份稳定源码 SHA
`c6c140a7bdcb1a008870d248bd81ee05666d1355bd61b0e4112faefeb1702feb`。
这四例真实覆盖零/两 cut、helper 创建 B、copy-loop 的当前 incoming、两实例
不同 extractor 和共享 E/F own N/R/full slots/最终消费者。失败尝试与诊断
保存在 artifacts/experiments/b1_call_operands/model_shared_tuple_final/。

3. **Observed → Implemented → 定向 Verified**：真实 loop 先进入 A、再进入 B
   时，guard=A 的 link 仍从旧 visit 产生投影。仅当 link.guard 与 input_guard
   指向同一规范 merge 时，改用最近 incoming；普通历史来源/辅助调用条件
   保持原义。已检查的 links 全部不适用时报告 await_body_link_missing；未知
   guard、StaticGap 与预算未扫完各保自身未知。首红与修后复验均已归档。

作者只写新 fixtures/tests，root 独占产品与串行解释器执行；每次全部作者先
冻结。首次及后续冻结 SHA、每条命令/日志/JUnit/源码前后清单均独立保存。

有限复核又提出同一产品路径的边界：展开 method lookup 时，advance 的实际
receiver 是新 bound-method，原 iterator 在 lookup 的 receiver Use 上。
若原 merge 库存只追 advance receiver，可能把该 producer 停止误称无 merge。
该有限组件反例实际 **1F/1P**：core/full 图与准确 iterator_use 均合法，库存
却只保 None。修复让原 walk 同时从独立声明 lookup 的 OwnedUse 开始，保原
advance actuals；无声明时不从实际 producer 反选 lookup。两个组件例在后续
矩阵中均通过。它不改冻结整 G 分母、不增协议类型，也不冒充整 await 验收。

## 原 G 第6节逐项验收

独立审查未发现此有限结构格额外缺项；最终在同一源码上保留此前全部1747项。
不同原格分别验收，不以 source/native authority=False 反复重开已核
结构格；也不拿本格代替 M3/M4 自动恢复。

| 原要求 | 精确证据（tests/unit/） |
| --- | --- |
| 两臂同 B、当前 incoming、0/多回环 | test_program_await_shared_final 的 universal 原两 incoming；test_execution_await_shared_final 的 universal 两实例、explicit_current_incoming 与 guarded-link 旧 arm 拒例。 |
| 零/两 cut 到 E/F own N/R、全槽、consumer | 原4项 universal 整链及 static explicit_whole_tuples；两个真实 extractor 引用同一 E/F 定义、各有 own 结果与当前消费者。 |
| 多 caller、错误当前值 | current_final_consumer 的旧 Reference/packet；exact_left_result_slot 的 payload/world/context 三槽；错误 receiver、core stale_state 分账。 |
| 整组 tuple，不能跨 arm 拼接 | 新整链核完整原输入/状态/输出；既有 test_program_continuation_connections::test_receiver_and_send_operand_cannot_come_from_opposite_merge_predecessors 与 test_program_method_lookup_connections::test_crossed_same_kind_method_sources_from_opposite_branch_are_rejected 核不同原数据的联合拒例。主图两臂同 raw 不伪称另造不同 raw 的负例。 |
| 删除声明后原义务 | explicit/universal/partial/missing、删 links/final adapters；删 qualification 保 Get 原键/全输出及 method scope.subject 的 None 未配对锚，不重建已删 semantic FK。 |
| 局部缺采，不能借 sibling | 两实例不同 caller；helper、child、payload、state、当前 merge transfer 缺采；准确 call/occurrence/slot 逐项保留。 |
| 预算、全缺采、失效 | budget1 与真实 region output join 中段；全 capture 删除保原键；嵌套返回 detach；fresh catalog 重核 source copy，外部 artifact 改变后拒旧快照。 |

原边界仍在：G 的 loop 是 first Drive 前真实 copy/control loop；整条 pipeline
重复求值或同 B 多次独立获取是原 E/H 的下一残项，不用本 loop 冒充。其余
A/B/C/D/E/F/H、原十六组、P5、M2 原113构造/196字段未因本格而通过。

## 执行账目

| 尝试 | 实际结果 | 用途 |
| --- | --- | --- |
| first-red | 4F，稳定845源码 | 首次发现 final payload/state 缺原 source prefix。 |
| diagnostic-final-prefix | 退出0、同源码 | 八个 own payload / 十六个 state 的原条件与补齐条件对照，属于诊断。 |
| after-final-prefix | 4F，稳定845源码 | 全图有效后准确复现 universal 缩原分母。 |
| after-universal-inventory | 4P，稳定845源码 | 首4整链局部验证。 |
| expanded-first-red | 1F/1P，稳定846源码 | 展开 bound-method 的原 iterator merge 库存。 |
| matrix-first-red | 30P/3F，稳定846源码 | 真实旧 loop-arm 产品缺陷；另两项为 NEW test 全局 scope 假设错误。 |
| after-current-link-fixes | 3P，稳定846源码 | 修复 guard 与两项准确 scope oracle 后复验失败项。 |
| verified-final | 1780P，0F/E/skip，稳定846源码 | 原1747 exact identities保留；33新增，最终SHA见上。不沿用旧绿测。 |

两项测试 oracle 修正单列：families.await 报告为全局 Get+qualification，
source_count 是2；删 Q 不保其不存在的 semanticRef 配对，而保 method scope
原 subject 锚与 await_source_row_missing。没有修改任何既有 test/fixture。

最终机器归档核原1747 testcase identities、全部原 tests/fixtures 字节、
Program23/Execution8 codecs/冻结合同与上次归档；保护两原仓库 HEAD/status。
本轮只核供应 IR 的连接，不运行新 LeWM/GPU/native probe，不产生性能结论。

## 下一步有限顺序

1. 原 M1 条件结构 G 的同源码回归通过；归档核验后提交、推送并核远端SHA。
2. 按协议合账文档核 F17/F21/F23 已有精确证据；F17只补真正缺的旧同型 item
   反例，避免再建重复 session helper。其余格按各自原要求，不由 G 代关。
3. 原 E/H 的整 pipeline 重求值与精确 source occurrence、剩余十六组 → 原组件/
   冻结 full → P5 → M2 原矩阵。M0–M2 真正齐全后按用户要求停下讲解模型。
4. 任意源码自动拆解建图、whole-LeWM 自动恢复与优化加速留在 M3/M4 后续阶段。
   下一节点的具体缺项和原 selectors 见[有限自验计划](M1_PROTOCOL_NEXT_GATES.md)。

M1 与自动恢复的证据分账见
[协议合账](M1_PROTOCOL_SCOPE_RECONCILIATION.md)。本轮尚未授任何整格通过。
