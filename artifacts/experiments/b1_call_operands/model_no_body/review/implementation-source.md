# D2.2 实施中源码独立复审

2026-10-18；基线 `e86563a`；**实现/fixture 尚未冻结，本报告不给最终 PASS。**
本轮只读产品、records、queries、codec/CLI 接线及正在构造的 fixture/test。
没有 tracked edits、git、脚本、pytest、component、full、LeWM 模型、GPU、安装或网络操作。
因此下列发现与关闭均明确为源码审查，不冒称已有实际 IR 复现/回归输出。

## 1. 两项必须闭合的局部问题

### R1：普通 BRANCH owner forward 不应拒绝既有 UseID 子类

最初 `no_body_validation.py` SHA256
`67c21a56949aa1a51a2b43137020988f6012a52a4eb519b86b84a62ea626c387` 的 owner 检查为
`type(actual) is UseID`。但普通 `Successor` 与 `Use` 接受既有 UseID 子类；这是普通 BRANCH，
不是 D2.1 那个字段本身已要求 exact actual 的 `BodyDriveSuccessor`。
最小机制：只将 true edge 的 owner forward owned UseID 和实际端口共同换为同一派生 UseID；
其余 owner Value/role/current-state 均不变。该 core 既有可表示关系会被此 exact 检查误拒。

已先发 root，root 接受并改为 `isinstance(actual, UseID)`；源码在
`45aece50de559722624c8db0da5c856e1a971f99ec614d6850de5f479cf942bb` 可见，
后续分支修复版亦保留。只扩展旧 ID 表示兼容，不把新 result/同类型值变成 copy。
**状态：源码关闭的 false-negative 候选；未运行复现。** root 已补其 owned regression，未由本审查重跑。

### R2：guard 与 mark 之间的 BRANCH 必须声明无 callback/effects

root 提出此疑点后独立核对：旧实现只查 Test 位置、branch kind 与 condition，未约束配对 branch 的
`effects_complete` 或完整 behaviors。core `validation.py:217–218` 已拒非 INVOKE terminator 的
results/accesses/callee；Operation ctor 又约束 call/invoke/completion 字段，所以实际 StateAccess 写并非漏洞。
但 core 仅要求 CONTROL 存在，仍允许 extra MEMORY/WRITE 等行为与 `effects_complete=False`。
最小机制是一个普通 core BRANCH 在 typed Test 后携带 unknown effects 声明，进入首 mark；
若只检查相邻位置与 bool 来源，guard corridor 的无 callback 义务没有被检查。
这是声明缺口，不应通过假设所有普通 BRANCH 天然 complete 来填补，也不需要全局收紧旧 BRANCH。

root 已在配对 Test 的分支检查中增加 `no_body_branch_shape`：complete、behaviors 恰 CONTROL、
无 results/accesses/callee/call/invoke/completions，原实际 forward Uses 保留。
源码 SHA256 `22669aec4d7c608b1b60c7d161908452f1135e4a1b434b7b80fccccca12607ea`，
对应 `no_body_validation.py:117–120`。
**状态：源码关闭的 guard 合同缺口；未运行修复前反例或修复后回归。** 不能将其记录为“实测 bug 已修”。

## 2. 已核对的关系与保守边界

- `validation.py:670–686`：core/C1/body/D1/publication 通过后才调用 no-body；坏基础引用/状态不会绕过前置门。
  `no_body_errors` 是依赖这些前置条件的内部 helper，不是独立 schema 入口。
- `driver_flow.py:14–37`：只取本 driver Region 每个 block 的真实末 term 与每条 successor，统一
  `saved_actual_use`；新 CompletionResult/BodyDriveResult/ResumeInput 写 None，不按 predecessor 或 origin 集合去重。
  `driver_validation.py:208–223` 使用同一 helper，未再保留全图第二套角色 copy 算法。
- core `validation.py:357–358` 禁止真 Region.entry 的任何 CFG 前驱；固定 receiver/S seed 不会被内部回边替换。
  caller 实参不是本 Region 的普通 CFG predecessor；不同 invocation 不由静态 entry ID 合并证明动态身份。
- `no_body_validation.py:43–76`：BODY 的 B/S 为固定 entry roles 的 must-copy，E 与本次 S 是同 Value 的独立 Use，
  无 session；ASYNC_REQUEST 只固定 R/S，B/E 为真实 Reference/RAW owned Uses，不强制独立 AssociationRead。
  E 可等于 S；错关联可令真实 predicate 为 false，不作类型非法或虚构 Python 异常。
- `:78–107`：Test 仅产生自己的 bool，READ 每个 L 当前域一次，WHOLE、无 after；角色 Uses 独立且无多余输入。
  其真实 StateAccess location/currentness 与 producer 继续由 core 检查。
- `:108–121`：Test 必须紧邻本 block 的 BRANCH，condition 是原 bool 的实际 owned Use；R2 新增 complete control-only branch。
  **不存在“每个 Test 必有 Finish”的反向覆盖循环。** predicate-only 图不 seed 完成、不必有私有 mark landing。
- `:123–156`：仅显式 Finish 需本 driver 的声明 Test、真实 edge0、私有 target 的首 mark；incoming 按实际边计数。
  owner 是该 Test 的原 Value 或这条 branch edge 的独立 actual→formal 精确 copy；其他同类型 payload 不够。
  `_body_update_errors` 复用 D2.1 的真实 WRITE/RW/after/ownedUses 约束，允许非空 W⊆L、coarse 与未写域 current 转发。

本轮没有看到“任意 NORMAL helper=NoBodyFinish”、持久 claim、隐造 Python 错误、第二套 producer/world 或额外 schema 字段。
同一 operation 的生命周期动作及旧 driver/context 动作冲突在 `model.py` 表唯一性/角色检查中拒绝。

## 3. D1 gate corridor 仍严格

`driver_validation.py:307–311` 仍要求 final gate 的 NORMAL target 为私有，且 operations 恰 `(paired Drive,)`。
no-body 在 D1 之后运行，不能把 Test/mark 插入 gate NORMAL 与 Drive 之间再以 no-body metadata 放行。
正确组合应为 Test+BRANCH 在 final gate **之前**，false edge 进入原 gate，NORMAL 唯一 Drive；true edge 首 mark。
fixture agent 最初拟插 NORMAL corridor 的设计已经 root 否决；这不是已接受图，也不应通过宽化 D1 迁就 fixture。

## 4. query / codec / CLI 的有限源码核对

`queries.py:334–358` 的 predicate/publication view 使用原 `_uses`、bool DataValue、原 branch Successor 和
真实 StateAccess；NoBodyPublication 没有捏造 body source outcome、CompletionResult 或新的 producer。
predicate-only 的 `no_body_finish/no_body_publication` 查询不存在时返回 None，不将 true successor 自动升级为 Finish。
ProgramIndex 构造先调用 validate，不能用 view 绕过 R1/R2 或 core 前置检查。

codec 的 no-body capability 取两表任一非空，predicate-only 也走新 wire v13；它仍调用 graph validation。
CLI `no_body_structure_validated` 只报告声明 predicate/真实 branch/optional finish，
`driver_lifecycle_verified/body_runtime_verified/transformation_authorized` 仍 false。
这些仅为读源码；本轮没有给 strict codec、query identity 或 CLI roundtrip 实测签核。

helper 对每个 driver Region 求有限两次 must-forward，no-body 内按 Region 缓存；没有路径配置枚举。
它每次会重建全图 operation lookup，故仍有可见的线性准备开销，未见新的指数状态域；本轮未做性能测试，不能据此宣称大型图时延。

## 5. 快照、fixture 与未完成验收

| 文件 | 实际读取 SHA256 |
| --- | --- |
| `no_body_validation.py`（R1+R2后） | `22669aec4d7c608b1b60c7d161908452f1135e4a1b434b7b80fccccca12607ea` |
| `lifecycle_validation.py` | `49dee4e82ebe09964a1a72c0d5d19fc91b67645822e7b1abc4961d13ba381daa` |
| `driver_flow.py` | `1815918ff1419257a33d19060ec3d7ca941fb84f80af8fc8733612d4c3f244aa` |
| `driver_validation.py` | `4a195bab83850b5101c596ef92848a9081e8f3704b05374618b92d1e64a00bd3` |
| `validation.py` | `fd461dc50beee07bd214e51906eca6bb6127ab2cf25c194d80e0d0473ddbd864` |
| `queries.py` | `4b76caca361b5361b9a8511133bcff3c5ba49b70297b7c633d52eacf59dbe625` |
| `lifecycle.py` | `b6574e20a8011ebba575ae8a99af3196fe8a3e098debed89083e0342b7feedbf` |
| `model.py` | `36f7105d05712da58e003b426836eae68ef6280ecf385de1d5d0f3fd9681ba7e` |
| `codec.py` | `4be6f084d7390f7dbd8a859dae2112fd28cb4eec6b27f3c79a5945fd616dde2f` |
| `scar/cli.py` | `09a8d2c4c0c9fca515397699cb55dc2df84b8425e8beed608c58db7e6765b168` |

`program_no_body_graphs.py` 的一份未首测草稿已出现（读取 hash `1e6419ebece7dd072be0241efba4cfcb91eee7f045e3088f0b1ea8731fcf1237`）。
我将几个明显 construction/syntax/condition-role 风险发给 fixture agent，未抢跑其首 smoke、未把草稿错误算产品漏洞。
对应 `test_program_no_body_graph.py` 仍在补 regression（所读 hash `0bd057a431eceb4ede6c80a91ba3bd2d59d0d1b095b958b3ea46c2d8a6c3181a`）。
上述均不能冒充冻结正例或通过数量；待 root/fixture 首测及源码冻结后再做有限最终独立复核。

声明的 true 意义/实际关联、native Created/CLOSE guard、无 callback 实现、body 字段更新与对象 lifetime
仍需 source/runtime 证据；手写 fixture 不是自动导入或 guard 执行证明。
当前无新增已确认剩余源码阻断；**本报告不给阶段性源码检查升级为 D2.2 最终 PASS，更不签核完整 D2/D3。**
