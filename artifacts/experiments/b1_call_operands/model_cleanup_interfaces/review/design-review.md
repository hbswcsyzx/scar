# C1 route / stack 架构独立审查

状态：**Proposed；有条件接受修订方向，不是实现验收**。只读旧
NEXT_CLEANUP_IMPLEMENTATION、NEXT_CLEANUP_UNCERTAINTY_ADDENDUM、control.py、
control_validation.py、core INVOKE/状态校验及控制协议 §4–5；没有修改产品或运行实验。

## 1. 旧方案的确定缺口及新路由

root 指出的缺口成立：outer finalbody 中的 inner cleanup 产生 Return/Raise，inner
完成后仍需 Replace outer 保存的 pending/context。不能再 Enter outer，也不能直接
最终 dispatch。因此下一站必须可为 Enter、Replace 或最终 C0 dispatch。

推荐重算顺序：从本次来源的 lexical scope 向外扫描，结合当前 active stack；遇到
需要退出的 active cleanup，先 Replace；遇到尚未执行的 enclosing protected 义务，
先 Enter。每次只做最近一项动作，再以动作后栈/当前 token 重算；不是先做完所有
Enter 再做 Replace。原目标 port 只决定最终目标，不能充当 token 身份。

## 2. 冻结 API 前须明确的检查点

### A．stack 必须是操作点 transfer，不只是 block 标签

每 block 唯一 incoming stack 可行，仍须推导 action 前/后的 stack：Enter 前不含 C，
执行后 push；Resume/Replace 执行前 top=C，执行后 pop。entry 的物理 scope 已是 C，
而第一操作前尚未 push；不能用“scope 包含 C iff incoming stack 含 C”一律判断。
动作后紧随唯一 continuation terminator；不允许用户操作夹在 pop 与 route 之间。
route 的目标 Enter/Replace 必须是该 block **第一项可执行操作**，不能仅是第一项
“协议”操作而让普通写入/调用先执行；最终 dispatch block 只含 C0 dispatch。

### B．已 pop 义务是本次退出事实，不能按 scope ID 永久跳过

正常 Resume 的来源物理上仍在 C 内，但扫描必须跳过本次刚 pop 的 C，否则会错误
Replace/reenter；若使用中转 route block，必须证明它位于无用户操作的 post-pop
转移走廊。不能仅因 active stack 中没有 C 就允许任意 CFG 边闯入 C 的普通 body。
循环下一轮可合法再次进入同一 C：旧 pop 标记必须失效，重新捕获 context 和 pending。
所有普通边、INVOKE 两边及 region 出口都检查；不能只核对声明 route 的边。

### C．Resume 的载荷与 Replace 的 saved/new 三者分别接线

inner 正常 Resume 的 token 可能是 Fallthrough 到 outer finalbody 后续语句；此时只
pop inner，outer pending/context 保持活跃，不能把 inner token 当 outer 原 pending。
若 inner Resume 恢复的是已离开 outer C 的 Return，才进入 outer Replace。
目标 Replace 的 new pending 必须逐路径接本次 route selector，saved_pending/context
分别 must-copy 到该 outer activation 的锚；三者不能按相同 port 或 constructor 合并。
保存值可沿两条互斥完成边转发；不能用全图“一次 Use 消费”模拟动态一次退出。

### D．local loop 与最终 C0 dispatch 的 lexical owner

finalbody 内局部 break/continue 的目标仍在 C 内时不 Replace C；若穿过内层 protected
P，应先 Enter 该 P 的 cleanup，再回局部目标。是否离开按目标实际 block containment，
而非 port.kind 或 port.scope 是否包含 C；function exit 视为离开全部本地 scopes。
C0 当前 target_active 对 constructor 和最终 dispatch 检查 nearest LOOP。这个规则
不能直接套在被保存 pending 的每个中途 Use 上；外层 Break token 可以穿过 finalbody
的内层循环而尚未交付。需要把“生成合法目标”与“保存/转发既定目标”分开检查。
所有 case 共用最终 dispatch 不是无条件可行：共享 block 的 lexical owner 仍须满足
各 case 的 C0 active-target 条件；不满足时分开 shims，不能放宽 nearest-loop。

### E．RAISE 到局部 handler 与异常 context 不是 route 自己推断

RAISE 目标 handler 若在当前 C 内，应保留 C 活跃；若目标在外面，再进行对应退出。
Try 的 protected 树必须覆盖 body/handlers/else 的语言规则，不能把所有 Raise 都
绑定到函数异常出口。handler 的匹配/安装/恢复尚属 C2，C1 可保守接显式边界，不能
因 containment/stack 合法就宣称 handler context 已完整实现。
新异常规范化/隐式 chaining 使用 Raise 当时 context，必须在 Replace 恢复 ambient
之前完成；ExceptionPacket 仅存传播引用，不等于当前 exception.__traceback__。
纯 C0 pack 不能替代这些状态动作；同异常对象也不意味着 packet/context 锚可互换。

### F．INVOKE 部分写与动作全域后态继续沿唯一 core 传递

现 core 的 unknown INVOKE 已要求 NORMAL/RAISE 均产生各 state 域；C1 应消费该
completion 目标 block 的当前参数，不能退回 invoke 输入。CompletionResult.index 是
完成签名位置，不是 successor 参数下标；经实际边位置解析，不另存一份 post-state。
Enter/Resume/Replace 依 uncertainty addendum 默认对 Region 所有 state 域保守推进；
effects_complete=False 本身不会替普通 action 自动生成后态。必须逐域检查 state
访问和 successor 使用 action 自己的 after，context 域仅一条 access。
释放 old pending 的回调可能改返回对象/RNG/文件；旧 pending Use 必须保留，但不能
把旧 pending 内容版本随之保留。finalizer 报错通常是 unraisable，不凭空变新 Raise。

## 3. 最小结构正反例（本轮仅提出）

| 场景 | 必须允许 | 必须拒绝 |
| --- | --- | --- |
| outer finalbody 内 inner Return | inner pop → outer Replace → 后续义务 | outer 再 Enter、直接最终 shim |
| inner 正常 Fallthrough | inner pop → outer 内后续代码 → outer Resume | inner Resume 误 pop outer；丢 outer context |
| finalbody 内循环 local break，跨 inner P | 先清 inner P，outer 保持，继续 finalbody | 按 BREAK 标签直接 Replace outer |
| finalbody Return 覆盖后继续退出 | Replace 本层，按新目标处理外层 | 复活更早 saved token、只比 port 集合 |
| 外层循环下轮再次进入同一 C | 新 entry 绑定、新 context 锚 | 全局 popped[C] 跳过；前次 context phi 冒充 |
| body INVOKE 写文件/RNG后失败 | RAISE 后态 → packet/new pending → Replace 后态 | 输入 state、NORMAL state、CompletionResult 错位 |
| control branch 汇合 | 同 incoming stack，不同 token 经精确 phi | 不同 stack 合流后取并集/任选；反向 phi |
| 合法 finalbody 发散 | 没有虚构完成边；仍检查存在的有限出口 | 要求 postdomination/total completion 才接受 |

栈分析对结构可行 CFG 做有限固定点；只在 typed route 按 canonical port facts 筛选
边，不因普通条件、名称或 producer 集合猜测某条失配边不可达。无种子的环不形成
must-copy/栈证据。单 incoming stack 是有意的规范限制，冲突时拆 block 或拒绝，
不能把多个动态 stack 折成 scope 集合。必须对 enabled Region 的全 CFG 做闭合校验。

## 4. 收束结论

未发现需要第四种 route 目标才能表达上述同步结构。需先冻结操作点栈、post-pop
走廊、锚传递与全边状态规则；仅三类目标的枚举并不能独自证明正确 unwind。
本批继续不覆盖 suspend/resume、with、except*、源码对应或运行 interposition；
C1 静态良构不提升 source/runtime/extraction/transformation 权限。
