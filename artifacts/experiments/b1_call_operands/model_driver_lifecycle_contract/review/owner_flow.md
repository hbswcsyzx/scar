# D2.0 多锚 owner-flow：有限 must 算法与独立复核

2026-10-18；基线 `8ee8d02`。本报告是 Proposed 算法；Observed 仅为下列小型 stdlib 探针。
没有修改产品、docs、tests、旧证据，没有运行产品测试、LeWM 模型、GPU 或 git。

## 1. 结论与撤回

采用 carrier 索引的 must-equality `E` 与终结历史布尔 `F`；先稳定 E/F，再派生解释来源 T。
不枚举路径配置，不增加许可、owner 实例 ID、world 版本图、request 历史机或另一套 producer。
不同终结锚可经精确 phi 共用 release；release 不消费 F，重复或幂等尝试不自动非法。
这足以保守支持要求中的普通合流、别名、循环和 callback；不要求一般路径条件推理。

撤回我先前 `(anchor,owner,phase,stamp,unused)` 配置草图中的 unused/current 窗口：
它会错误拒绝“终结→unknown callback→真实 frame-drop”和第二次 release，亦暗示 refs 仍 held。
`FrameRules.release=NOT_GUARANTEED` 不授 held、已耗尽、free、ready 或一次性执行结论。
终结历史与当前 session 后置必须分开；未知写使当前后置失效，不撤销既成的终结事件。

## 2. 有限域与程序点

对一个启用 `DriverLifecycle` 的 driver 区域，取有限 canonical Reference ValueIDs 集合 V（n 个），
及本区域经过结构验证的终结 publication/no-body 站点 A（m 个）。不跟踪 StateValue 的 owner 身份。
在真实 core CFG 的每个操作前/后程序点求事实，block 内顺序执行 transfer；不另存 CFG。

- `bottom`：尚无可达执行；不同于可达但未证终结。真正 entry 是 E 自反、F 全 false。
- `E ⊆ V×V`：等价关系，表示这些当前 carrier 必为同一对象/生命周期。不同类仅表示未知。
- `F ⊆ V`：每条到达执行上，该 carrier 的当前对象都已有 continuation-finished 历史。
  F 对 E 类闭合。定义或循环重绑时，静态 ValueID 不代表旧 visit 的动态值。
- `T(v) ⊆ A`：仅在已稳定 F(v)=true 时给出可能解释来源；每条到达执行至少有其中一个见证。
  并非集合中全部站点都执行过，也不是最新锚、独立 owner 集合或可消费权利。

不可达不用于 vacuous terminal 证明。分支暂不推条件可满足性：真实 CFG 的各可达前驱都计入。
不可合法使用的 ValueID 由 core def-use/availability 拒绝；分析不借其类型补造定义或 alias。

## 3. 第一阶段：只求 E/F

工作队列初始化所有点 bottom；真 entry 注入上述无 F 初态。任何 reachable incoming 加入时重算：

1. **结果重定义**：先从 E 移除目标 v 与其他 ID 的关系，令 F(v)=false；其他 alias 保留原值和 F。
   未知 Reference 结果只得到自反关系。这里不宣称它与其他值不同，亦不推它必是新分配对象。
2. **每条实际边同时改名**：snapshot 源点 E/F，解析 canonical actual Use→formal；目标值从快照
   对应源 carrier 复制。所有目标 formal 同时重绑，不能先写 x 再从新 x 写 y。多个 formal 可同源。
   相同实际 Value 或已证 E 的实际值使目标等价；仍 live-through 的 carrier 同样进入别名闭包。
   CompletionResult/BodyDriveResult/其他非 copy 结果是新的未证值，不能按同类型当原 owner。
3. **再合流**：在每条边改名后的状态上，E 取关系交；F(v) 仅当全部 reachable incoming 的 v 都有 F。
   不能先 union owners、再 union 来源、最后任意配对；不要求全部路径来自同一个锚。
4. **终结 seed**：已验证的 Return/Raise BodyOutcomeCommit，或真实 true-edge NoBodyFinish，
   将当前 instance 的整个 E 类加入 F。source Suspend 不 seed。站点标签/端口集合相等不是 seed。
5. **普通作用与 gate**：未知 callback、状态写、新 gate 保留已有 Reference 的 F；其新结果照规则1。
   新 gate 不创造 F、不反推拒绝/死路径，不把 F 当 occupancy、session、refs-held 或当前机器 phase。
6. **release**：仅在当前 owner 的 F 为 true 时满足历史义务；仍须该 release 的 shape/profile 与 core
   全域 current-state 检查。transfer 保留 F，不消费锚，不禁止同 owner 后续第二个 tag。

普通未知 helper 的“返回值其实等于旧 owner”若无 canonical copy 依据，不恢复 alias/F；这是保守损失。
callee 真 entry 亦不因某一个 caller 已终结就 seed；调用点标签不能给所有调用实例授历史。

### 收敛与 must 性质

按“加入更多可能到达执行”排序：bottom 最小；E 只丢 must 相等对，F 只丢 must 真值。
snapshot copy、forget、固定 owner 类 seed、E/F meet 都是单调 transfer；entry 是固定边界输入。
每点从 bottom 首次变 reachable 后，最多丢有限 E 对/F 位，粗略高度 O(n²+n)，队列有限收敛。
不需要指数个路径配置。E/F 作为有限等价关系加闭合布尔集合足够；这是终止论证，不是探针计时推断。

以每个操作/边的归纳证明 sound：copy 保持同对象，forget 不给新值继承旧事实；seed 由真实当前
owner 的已验证 publication 提供；meet 只保留所有到达执行成立的事实。历史保持额外依赖§7合同。

## 4. 第二阶段：解释 T，不能参与 release 资格

固定第一阶段所有程序点 E/F 后，T 从空集合开始，在同一 CFG 上做有限 union LFP：
seed 的 owner E 类给常量 `{该站点}`；forget 给空；copy 用同一个 snapshot rename；合流 union；
对 F=false 的 carrier 清空 T。对非 seed 成员照常传播，不从 F 布尔本身编造来源。
固定 E 使 seed 作用的类固定，所有 T transfer 均为常量、copy、清空或 union；高度 O(nm)，必收敛。
T 不反向改变 E/F 或 release 资格；实现应断言 F=true 的最终 T 非空以发现接线错误。

**上一联合迭代草图的具体问题**：强输入 E(x,y)、F(y) 的说明为 `{b}`，terminal(x,a) 把 y 的说明
重置为 `{a}`；弱化为 x/y 未证相等但 F(y) 仍有 `{b}`，同一 transfer 的 y 说明变 `{b}`。
`{a}` 与 `{b}` 非包含序。故“联合来源集合简单单调、有限所以收敛”的论证不成立；有限并不排除振荡。
这不是已复现 E/F 错放图，也不推翻 terminal 布尔历史；两阶段消除其对 must 收敛/资格的影响。

## 5. 最小路径：必须支持与必须拒绝

| 实际路径/边 | 合流或后继结论 |
| --- | --- |
| 左 finish(x,A)→p=x；右 finish(y,B)→p=y | F(p)=true；T 可含 A、B；共用 release(p) 合法 |
| 左 finish(x,A)→p=y,q=x；右 finish(y,B)→p=x,q=y；未证 x=y | p 无 F，q 有 F；独立 owner/source union 会错放 p |
| 两条路 x、y 都已终结，然后交换送 p/q | p、q 均有 F；不能因选错单一锚而拒绝 |
| p=x,q=x；finish(p,A)；重定义 x=unknown-result | 新 x 无 F；p、q 仍有 F |
| F(x)，同时 x'=y、y'=x | 只 y' 继承 F；顺序赋值会丢失或错传旧 x |
| 一路 finish(x)，另一路未 finish(x)，均 p=x | join 后 p 无 F |
| reachable entry 无 F→自回边 p=p | 无 seed，不得因 cycle 自支撑 F |
| finish(x)→p=x→自回边 p=p→release(p) | 有 seed，必须支持 loop 后 release |
| loop 每次重新定义 p，旧 visit p 曾终结 | 新 visit 在当次 commit 前无 F；当次 commit 后有 F |
| finish(x)→unknown write/callback→新 gate→两次 release(x) | 历史 F 保留；不承诺当前 occupancy/held/free |
| Suspend publication(x)→release(x) | Suspend 本身不 seed；若无更早适用历史则未证 |
| 不可达 self-cycle | 仍 bottom，不能拿 vacuity 授 release 资格 |

post-merge bool 可能关联“这条路径恰好完成了所选 owner”；本算法不推一般关系谓词或 SAT。
显式把路径上的已完成 owner 经 actual→同一 formal 选择，能保留要求中的一般合流。
若来源把选择藏在未知 helper/条件关联内而无可检查 copy，未证即不授该窄 metadata，普通 effects 图仍可表示。

## 6. Observed：冻结脚本、环境与结果

探针 `owner_flow.py` 仅是临时 transfer 方程测试；没有产品 import，没有 ProgramGraph 或 producer/world store。
脚本 SHA256：`967f464590bf606a81e28613c39144333c6d0d738eab3e97bec61121136e6edb`。
其 `Facts` 同时携带 E 与解释集合；11 个命名情形含共享锚、交换、多 alias、forget、3 个 reachable loop
及不可达 loop。另从 1,728 个有限 concrete 状态中固定 seed=20261018 抽取 320 组，各做 6 个单步变换，
共 1,920 次 sound 检查：已证 E 必在每个 concrete 执行相等；非空说明在每个执行至少有一个同 owner 的历史见证。

这只是有限单步别名/历史语义检查；不是 exhaustive 图验证，不证明任意联合解释迭代收敛。
loop 样例实际终止不代替§3–4的两阶段有限格证明。没有测试 P、实际 StateAccess/currentness、
source/profile 适用、callback native 行为、body fields、引用耗尽、frame drop 或最终 D2 产品。

- 首跑：`/usr/bin/python3` 3.12.3，exit 0；命令/输出/JSON/hash 已保留于 `owner_flow.command.txt`、
  `owner_flow.log/.json`、`owner_flow.attempt1.manifest.json`。这是未按 conda 约束的原始尝试，保留不覆盖。
- 纠正环境：显式 `source .../conda.sh`、`conda activate lewm`；对**相同冻结字节**复制出的
  `owner_flow.lewm.py` 仅运行一次。Python 3.14.7、exit 0、`/usr/bin/time` 0.12 秒。
  独立 `.lewm.command.txt/.log/.json/.time.txt/.manifest.json` 保留，原 3.12.3 证据不变。
- 两次各为相同的 11 情形/1,920 检查，不合计为 3,840 独立覆盖，也不将跨版本设计结果当 runtime 对应证明。
  lewm 输出 SHA256：`308688ea2eff523ec84182e288cb3162794806de2fb5d26500375bc3218a2e95`。

## 7. 精确的封闭 profile 与未证事实

F 稳定性仅在以下声明适用条件下成立：实际 direct native resumable owner；same object/lifetime；
单 activation 在正常 callback 后不可被复活；没有外部 native reset/continuation 替换；
`FrameRules.NO_FRAME_INTERPOSITION`。References 的别名必须真指向同对象，不由 static ID/site/type 证明。
新分配复用同一静态 ValueID 必须 forget；对象地址复用不能给新 lifetime 搬旧历史。
未知 callback 可改变一切当前状态、drop 任意 refs、改变 session；这些都不否定“同 lifetime 曾终结”。

实际 native 对象类型/版本、单 activation/no-reset、publication 真更新何字段、selector→owner 身份、
真实 callback/无 callback、drop 位置与 FrameRules 条件，需要独立 source/runtime/provider 证据。
coarse world StateAccess 不证明动态 owner-selector 对应；current StateVersion 继续由 core 检查。
自定义 reset/wrapper 不因此不可建模；仍用普通 effects 边界，不获得本固定 profile 的稳定 F。

## 8. root §6 有限复核

复核 `docs/M1_DRIVER_LIFECYCLE_CONTRACT.md` SHA256
`94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699`：
L130–150 的 carrier E/F、先边改名再合流、entry/bottom、forget、alias seed、unknown 后 F 保留、
不消费 release 均与本探针情形及上述第一阶段一致；没有要求单锚/删合法合流。
L147–150 已明确先稳定 E/F、再固定解上求 T 的 union LFP，且 T 不参与资格；已关闭上一版
`1653297abe7eed5ee9a406590e98f23210040588bba843b5cd1ee51c342eab52` 的联合单格歧义。
本轮有限设计复核通过。该两阶段合同有§3–4的收敛论证；探针未实现两阶段产品 solver，不能声称已实测它。

L154–159 的 P 是**当前** R/B/post/L 支持，未知写后失效、body-only rebase 不生成 P、F 不补 P，
与本历史算法不冲突；本探针未覆盖其实现或多角色配对，不能替 P 的验收。
L163–172 明确分阶段实施、source/native 属 D3；因此本结论仅给 E/F/T 实施算法，不签核完整 D2。
