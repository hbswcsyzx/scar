# Root gate 合同有限复审

2026-10-18；所审 `docs/M1_DRIVER_CONTRACT_V2.md` SHA-256：
`14ac0691fdf418b4bac54b11e3bf1cc291eac7011082460d6016a23abfe038c8`。
只读审查 §3.2、相关字段及 state/corridor；无新实验、代码或测试，旧提案/证据不改。
本报告检查候选字段可实施性，不要求 source 自动恢复作为冻结条件。

## 结论

**架构可实施；需补下列两组 exact 约束后通过本次 gate 字段范围。**
没有发现窄 gate→Drive 方案本身的阻塞。完整 D0、D1 实施、D2 lifecycle、D3 全 family
及 source/runtime 对应均不因本报告关闭。

## R1：将 interface 入口角色绑定到 gate，不能只绑定 gate 到 Drive

§3.2 `:116`–118 定义 receiver/scheduler 为 entry 参数；`:123`–127 只明确 gate 输入
到 Drive 的逐槽对应。缺少 gate 这些输入与 interface role 的强制关系，以及 session
的 mode 约束。`:231` 虽列 S/latent 反选为必拒，却还没有足以实现该拒绝的判据。

最小声明级反例（未实跑）：interface 声明本次 S，图中另有同类型 latent L；gate 的
scheduler_argument 改为 L，NORMAL 独立 edge Use 和 Drive.scheduler_request 也完整
转发 L。现所有局部 corridor 等式仍成立；不能从类型或 gate→Drive 一致推出它就是 S。
类似地，ASYNC_REQUEST 把 session=None，字段类型允许且现局部转发条款无法补出 R。

最小修正，直接加入 §3.2：

1. interface.receiver 是 Reference entry formal，scheduler_request 是
   RAW_DRIVER_REQUEST entry formal；两者角色独立。
2. 所有 gate 的 scheduler input 必为 interface.scheduler_request 的 must-copy。
3. BODY 模式：body input 必为 interface.receiver 的 must-copy，session_argument=None。
4. ASYNC_REQUEST 模式：session_argument 必须非 None，其 input 必为
   interface.receiver 的 must-copy；body input 是实际 B 引用。B/R 的当前关联仍由
   final gate 当前状态的版本合同检查；不要求静态恢复实际动态对象或唯一 lookup site。
5. must-copy 对真实每条 incoming actual→formal 闭合，其他入口/非复制 producer 为
   False，先 OR-LFP 限种再 AND-GFP 闭合；不以 origin 集合相等替代，也不引入 U/A。

这组约束只证明声明端口角色，非动态对象 identity/排他或 raw→payload 语义的证明。

## R2：给 delivery_arguments 唯一可实现的配对规则

字段 `:78`–84 与 `:125` 的“每个 delivered input 逐槽核对”需要明确 tuple 对应顺序。
建议规定 `BodyDrive.resume_inputs` 按 ResumeSlot.index 严格递增、完整覆盖全部非 STATE
槽；`delivery_arguments[i]` 对应该 tuple 的第 i 个 source。长度必须相同；Start 两者
均为空。不能按 Value/type 搜索匹配，也不能从 state_inputs 混入 delivered 项。

并明确 gate 的 body/scheduler/非空 session/delivery 输入角色使用互不相同的 owned
UseID，即角色索引互异；NORMAL 每个对应边槽也用独立 UseID 与独立 formal，Drive
每个实际角色/输入端口用自己的 UseID。允许多个这些 Use 指向同一 Value。
这把 prompt 所要求的“原角色独立 Use 转发”写成机器规则，避免重复角色索引被默许。

## 已符合的关键部分

- `:138`–142 正确撤回独立 RequestGate、父 permit 和通用 U/A；早期 request acquire/
  store/失败仅按真实 helper/state 和具体版本 source 路径保留。当前 admission 不依赖历史位。
- `:120`–127、`:131`–136：NORMAL 唯一前驱 landing 只有 Drive，无 callback 间隙；
  拒绝不等于本 Drive 已执行，但不抹去错误构造的 nested callback/当前 effects。
- `:128`–130、`:146`–153：gate NORMAL/RAISE 全域 poststates；body 按 LocationID
  消费 NORMAL 后 formals。mark RUNNING 不藏在无 producer 的隐含前奏。
- `:65`–67、`:91`–95、`:110`–112：lookup 正常结果是合法新 body 引用 producer；
  `:127` 只禁止把 gate 原输入 identity 以 CompletionResult 再造为“相同引用”。二者
  不冲突，无须为了原 owner copy 禁令而禁止 AssociationRead 返回新 body Reference。
- `:219`–244 保留实施/验收层次，不把字段稿或 corridor probe 当全 C2D 完成。

修正 R1/R2 不需要新增业务实体、permit、producer 图或 source 自动导入系统。
