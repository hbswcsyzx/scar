# D2.3 root session / release 集成：独立只读源码复审

2026-10-18；任务基线 `817cc0b`。**最终状态：BOUNDED_PASS，无剩余实质阻断；不代替后续统一 component/full 验收。**
本报告只独立审 root 的 session_flow、shape/analysis、validation/query/CLI 接线。
自写 lifecycle_flow 仅作为既定接口背景，不将自审冒称独立审计；该实现另见 flow/report.md。
本轮没有运行脚本、probe、pytest、component/full、LeWM 模型、GPU、git 或修改 tracked 文件。

## 1. 源审发现及关闭

### R1：精确 StateAccess.reference 被额外拒绝

最初 `session_release_validation.py` SHA256
`3dd1121494474109a003a984dd18b1d8061e28fceaf465e52b0da01ad08ba770`
对两个 ordinary intrinsic 都要求 `access.reference is None`，比最终主合同§5更窄。
机制：R/B 已有 core 可验证的 WHOLE selector/targets，访问合法指向本操作已有 role Use，
所有 current/after/域/complete/ownedUses 义务不变，仍会因非 None 额外被拒。
这不应从“coarse 可以”反推为“所有精确 reference 一律不合法”。

root 接受并明确以最终主合同为准，改为 session ∈ `{None,request,body}`、release ∈ `{None,owner}`。
实际 alias targets、footprint、完整性继续由 core 检查；tag 不授 selector/动态 owner 对应证明。
只读确认修正已落，当前 `session_release_validation.py:58–64` 使用 `(None,*role_uses)`。
**这是源码审查修正，旧实现未在本轮运行反例；不记录虚构的“修复前实测失败”。**
root 已补 core-valid 精确 selector 正反例；最终只读核对见§6。旧粗粒度建议与最终主合同的差异亦由 root 明示。

### R2：query 的真实 NORMAL 端口类型注解

`SessionPublication.normal_successor` 原注解 `Successor|None`，实际返回 INVOKE 的 CompletionSuccessor。
已发 root 并只读确认现为 `CompletionSuccessor|None`，没有新字段/producer。
这是低风险类型一致性修正，不是运行期故障复现；无需为此新跑测试。

## 2. P 的 must 关系、别名和来源

`session_flow.py:52–70,94–98,124–158` 保留有序 `(Rcarrier,Bcarrier,post)` 完整 triple。
先按固定 E 闭合 seed 的 R/B carriers，再在**各条实际边**用 canonical Reference assignment 同时改名，
最后逐 reachable incoming set intersection。源/owner 不独立 union，不按 unordered pair 或同 body 合并 request。
实际 formals 的旧 incarnation 被覆盖；None produced boundary 不携带旧 pair；普通 Reference results forget 相应 carrier。
其它仍存在 alias 的事实能继续承载。alias-closed relation 的同步 copy 保持 edge E 的闭包，未借目标 joined E 提前推配对。

COMPLETE seed 包含 ABANDON；这是一组当前谓词的蕴含，不是互斥 phase enum。
因此 COMPLETE/ABANDON 两路的交应只保留共同 ABANDON；HOLD 不因此推出 ABANDON 或 body finished。
没有 source 的 reachable loop 从空 P 开始，不能靠 cycle 自证；不可达 bottom 仍与 reachable-empty 分离。

先固定 Boolean P，随后 `source_transfer/source_edge` 在固定关系上只做常量源、copy、mask 与 union LFP。
来源不参与 P 真值，不用任意迭代上限或路径配置枚举。P 域最多三个 post×有限有序 carrier pairs，
source 域亦有限；继承/kill/固定 seed/同时 rename/meet 均是有限 must transfer。
这给出源码级算法理由，不把之前六个 focused tests 当通用证明或建模覆盖率。

## 3. 当前 support、unknown effects 与 NORMAL/RAISE

`:100–121,130–148` 的 support 直接从本 block 当前 core StateSSA 推导：READ 用 before，写域用真实 after，
真实 edge 用目标 State formals，按 interface.lifecycle 顺序返回原 StateVersionValue。
没有保存另一份 world stamp、旧 state 版本图或用户 preservation flag。

- 普通 complete READ 与不触及 L 的已声明 complete work 保持 P；Reference 结果仍需 forget。
- 触及 L 的实际写/新 state、unknown effects/callback、callee、INVOKE、BodyDrive、Suspend 默认 kill。
- 已验证 body-only BodyOutcomeCommit/NoBodyFinish 不改 request phase/association/occupancy，因此只重基已有 P 支持；不生成新 P。
- AFTER_OPERATION seed 仅绑定自身真实 after；NORMAL_COMPLETION 的 unknown helper 先清旧 P，
  仅真实 NORMAL edge seed，新 support 是那条边的 produced current states；RAISE 不 seed、仍保留其真实 partial poststates。

F 历史与 P 当前支持严格分开：unknown callback/drop 可以使 P 失效，不能仅因此否定固定 no-reset profile 的既成终结历史。
反之 F 不恢复旧 P；request COMPLETE 不把 Suspend source 变成 body terminal。

## 4. shape / release / 公开面

shape 层先检查同 scope/真实 operation/owned R/B roles、ordinary complete CONTROL/READ/WRITE、每 L 一条 WHOLE READ/RW、非空写集、
真实 after 与完整 ownedUses。NORMAL helper 是真实 unknown INVOKE，R/B 是 invoke actual，NORMAL/RAISE 都产生全 D 后态。
FrameRelease 只接受固定 ordinary READ/WRITE/MEMORY、complete=False、全 D WHOLE RW 和真实 after；宽 raising wrapper 不能贴此窄 tag。
selector 放宽后仍只可引用本 operation 的相应角色，不放宽范围、current-state 或完整性。

`lifecycle_analysis.py` 在所有 shape 通过后派生事实；release 只检当前精确 owner 的 before-F，
不要求唯一锚、不消费许可、不因同 owner 重复 tag 判错，不从 tag 宣称 refs held/free/耗尽/ready。
validation 在此之后还执行 provider/native 门，只有全部成功才把派生 facts 交给 query collector。

`queries.py:395–461` 的 before/after/edge 返回对应真实程序点；SessionPublication 引原 R/B UseSite、
真实 access-before/after、真实 NORMAL CompletionSuccessor 与原 current support。
TerminalReleasePublication 从 owner 的派生 seed operation 回到原 BodyPublication/NoBodyPublication；不造新 producer 或 body completion。
CLI 分离 `session_release_structure_validated`、`conditional_lifecycle_facts_derived` 与仍 false 的 runtime/native/lifecycle/transform 权限。

## 5. 所审最终源码 hash 与范围

| 文件 | SHA256 |
| --- | --- |
| session_flow.py | `13e90d83f74bd46281a678c778c559ad1d6d52d3d5722137be38848f853a7387` |
| session_release_validation.py（R1后） | `b96e989a611a518630e2c33bbf61b5f69d4cc015b54166d27f78a6486482e0fc` |
| lifecycle_analysis.py | `153c309f0cd32a6b6b719f0266dbc68209a107c9746bb88c2463194d7d650dd7` |
| queries.py（R2后） | `7f119421509b7a1237304e713fb6f52d461891b802395bb46e0326e556cd1aa6` |
| validation.py | `04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264` |
| scar/cli.py | `859fa00f44644303758c0a3a8a362704d4ba38befa23c21a6d73d6513e802135` |

本报告不重审已撤回的跨 Region literal 假设，亦不再堆积无实质风险的兼容逻辑。
root 的真实 join/loop、readonly/body-only support、unknown kill、COMPLETE/ABANDON、NORMAL/RAISE、
精确 selector、共享多锚/重复 release 测试已落；本轮未独立执行，不转述为自有 PASS，后续统一 component 覆盖。
native 对象/lifetime/no-reset、真实字段、guard/alias 实现、callback/drop 对应与完整 family 状态机仍需独立 source/runtime 证据。

## 6. 最终只读闭合：真实 tests 与上述 module hash 一致

最后读取确认§5六个 module SHA 均未变化，R1/R2修正仍在；没有回退 reference core 约束或 NORMAL 类型。

- `test_program_session_release_graph.py:151–176` 的两个参数正例确实将原 owned request/owner 的已存在
  ReferenceValue 精化为 WHOLE/单 location targets，再令 StateAccess.reference 指向它并 require_valid。
  post 分支再把 targets 改 Unknown，要求 core `incomplete_alias`；不是仅以新 tag 自证 selector。
- 同文件共享 release 直接复用已合流图，在 merge/loop 后加入两次真实 release；wrong-phi produced payload
  则要求 `terminal_release_unfinished`。Suspend/request COMPLETE 也不会绕过 F；全 D/额外域 current 约束仍受测。
- `test_session_composition.py` 的十个参数图在每条真实路径上建立 SessionUpdate，明确把已知纯 forwarding
  JUMP 标成 complete，再穿越真实 merge/self-loop：COMPLETE+ABANDON 仅保留 ABANDON；一支无 post、
  HOLD/ABANDON 分歧均无共同 post；同两锚来源也不能把 wrong phi 的 R/B carrier 拼成完成 pair。
- 其余四图确实先经 validate 收集 facts：NoBodyFinish 前已有 HOLD，mark 后保留同源 P 但支持为真实新 after；
  false 实际 Drive 路径已清 P；L 内完整写 kill、D\L 完整写保持。不是只对孤立 set 算子做同义断言。
- query/CLI tests 检查原 UseSite、StateVersionValue producer、真实 NORMAL edge，以及权限 false；本轮只读，不新执行。

新增 test/fixture 绑定 SHA256：

| 文件 | SHA256 |
| --- | --- |
| tests/unit/test_session_composition.py | `b664bda17dc6acab19c447bdbdeb82a053496abf7bf83ca694744a9949d285df` |
| tests/unit/test_program_session_release_graph.py | `be938ecab794588d6aba998352a30d85b9bd054b43e37443e499de2e52367aba` |
| tests/unit/test_program_session_release_queries.py | `01985ac433023a3ca51b1793b5a5d148971b384c9f671edca0fe3800964b08c8` |
| tests/fixtures/program_session_release_graphs.py | `149dd6532e6c18b14e4ec0dd8cddd5bcd7a2132df2d182ce81d5336f00813b2d` |

只读的 root 既有证据：`composition/attempt-001` 为14 passed in 0.58s、returncode 0；
`graph/precision-002` 为2 passed in 0.39s。这些是 root 运行，不是独立重跑；构图与断言的有限复核才是本报告结论。
精确 selector 的旧实现未跑失败、P agent 最初错传 fixture 参数等记录均不改写/隐藏，也不算产品失败。
**BOUNDED_PASS 仅覆盖当前声明关系与派生接线；不授 runtime/native、family 完整性、free/ready 或变换权限。**
