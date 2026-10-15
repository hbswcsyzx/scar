# C1 函数对象、绑定来源与环境：独立设计审查

日期：2026-10-15。基线：`42cfab13273119afce13512e32c0afd230c1069e`。
状态：**Proposed；设计结论，不是已实现/验收能力**。
本次只读产品源码，只在本 artifact 目录写简报和标准 Python 小探针。
未执行 LeWM、依赖包、全仓测试，未修改 scar/tests/gates，未提交。

## 1. 推荐结论

**分开交付 C1a 调用证据绑定、C1b 环境读取、C1c 环境写/创建，最后由 C2 投影逐调用 core。**
C1a 应产生可遍历的、有确定来源角色的条件绑定边；不能只是增加一个
`function_environment=UNKNOWN` 记录，也不能以 C1a 替代完整 C1。

四类 core 节点足够。FunctionObject 是 ReferenceValue 的运行指称；code 是其
某时点属性所引用的代码对象/结构指纹；globals/defaults/cell 是存储与状态；
body 是 Region。**源码定义、函数对象实例、代码版本、一次调用四者不得合并。**
环境需要独立的隐式入口引用，但不是 Python formal，不由用户手工传参标注。

当前代码中的真实断点：

- `ir/program/functions.py:BodyEntryInterface` 只有 parameters/world；
  `analysis/function_interfaces.py:71` 和 `ir/program/frame_validation.py:124`
  强制 entry 为全部 formal 后跟唯一 world。
- `analysis/program_lowering.py:expr` 将无 local 定义的 Name 当全局读取；
  `function` 在 free/nonlocal 符号存在时整体拒绝。因此直接去掉拒绝会把闭包读错建成 global。
- `ir/program/frames.py:FrameEnter` 仅持有 formal；frame validator 将所有普通
  非终结操作都要求为 frame transition。这是旧 profile 的规则，不能原地放宽。
- `analysis/function_binding.py:bind_call` 只解释源码声明 defaults；它不能用于
  已改写 `__defaults__` / `__kwdefaults__` 的实时绑定。
- `ir/program/call_edges.py:FrameEntry` 没有函数对象或实际 operand load 事件；
  `ReferenceIdentityRoute` 只允许同 token 的身份边，并固定禁止环境/effects 升权。
  `analysis/call_edges.py` 因此在 PARAMETER 停于 `ARGUMENT_ROUTING_UNVERIFIED`，当前是正确行为。

## 2. 最小必需接口及 core 对应

以下是字段责任，不要求照名字增加一套平行图。

| 记录/关系 | 不可省字段及来源 | core 对应/不变量 |
| --- | --- | --- |
| 函数对象实例 | bundle 身份、进程、带生命周期校验的 FunctionToken | 一个运行对象；不能用 code key 或 qualname 当实例 ID |
| 函数环境观察 | 事件锚点、FunctionToken、当时 code key、globals/builtins 引用、defaults 布局、kwdefaults 项、按 closure index 排列的 cell 身份、各字段完整性 | 一次观察，不等于整个函数生命周期的固定环境 |
| 实际 callable occurrence | caller invocation、源码/bytecode site、动态 occurrence、callee 求值/加载位置、已物化 callable 类型/身份 | 对应当前 call 的 callee UseID；不是同名局部在任意晚时点的值 |
| dispatch recipe | raw function；若为已物化 MethodType，额外携 `__func__` 与 `__self__` occurrence；独立保存源码 callable 与执行 function | receiver 是独立来源，不是猜出的第一个 actual；未知 descriptor/partial 保持边界 |
| actual occurrence | 同一次 call attempt、实际 load/求值位置、源码 UseID、位置序号或 keyword、取值观察锚点 | 同一对象出现在两个 operand 仍为两条不同来源；不能按 token 去重 |
| binding route | destination invocation/formal slot；来源为 actual、receiver、default storage slot 或 pack；对应 recipe、证据锚点、尚未满足的条件 | 可以遍历的因果绑定边；不能借用仅凭同 token 的 ReferenceIdentityRoute |
| 环境入口 | source definition、body region、一个 FunctionEnvironment ReferenceValue port；capture 布局由源码/编译 code 确定 | 隐式端口；不进入 FunctionSignature.parameters，不占 Python 参数位置 |
| 环境访问规则 | core op/use/result、精确 source、字段路径或 capture index、读取/写入规则 | 引用 core 的读写/状态边，不重复保存另一份 before/after world |

绑定目的 formal 依据**当前 code 的参数布局**与运行 default storage，而不是默认
表达式的源码文字。`default_source` 仅能作为初始定义动作的 provenance；改写后
当前 default slot 的来源应是写入/观察边界。读取 default 返回某对象引用，不证明
该对象内容自定义时未变。globals 的字典身份与条目值版本也必须分开。

必须记录 `function.__builtins__` 或明确保持 builtin lookup 边界：本机探针表明，
创建函数后替换 `globals['__builtins__']` 不改变该函数原先持有的 builtins 映射。
仅用 globals 当前该项重建环境会得到错误 lookup。

## 3. cell 身份与内容版本：禁止 id 地址充当持久身份

本机 CPython 3.14.7 观察：cell 不可 weakref，函数对象可 weakref。
同一个 cell 能被多个不同 code 的函数共享；同一个函数对象可换成另一份相同
freevar 数量的 code，而 closure tuple/cell 不变，freevar 名称却改变。

推荐使用**弱 owner 锚定、即时 `is` 复核**，不强持 cell 或应用函数：

1. FunctionToken 以 `id + weakref() is object` 校验生命周期，跨 bundle/PID 不拼接。
2. cell 锚为 `(live FunctionToken, closure_index)`。读取 exact FunctionType 的
   `__closure__`；名称来自此次 code 的 `co_freevars[index]`，不能把名称写入 cell 身份。
3. 同一 callback 内用 `is` 比较各存活 owner 的对应 cell，才建立共享关系。
   长期缓存只保留弱 owner/index；每次使用再次解析并复核。严禁把旧 `id(cell)`
   查表命中当证明，也不使用 cell 的 hash/eq/repr。
4. 代表 owner 死亡时，只能沿仍存活且已验证的其他 owner 延续身份；全部已知
   owner 死亡后失去桥接。后来再见到某 cell 应保留未知关系，不能据新 ID 推导不别名。
5. 同一 code 的不同闭包实例不合并；同一 cell 出现在同一 closure 的两个 index
   也不能按 index 推导存储独立。globals 等非 weakrefable 对象可用同样 owner 复核原则。

**观察序号不是内容版本证明。** `cell_contents` 可由 nonlocal、外部
`cell.cell_contents = ...`、回调或别的线程改写；EMPTY 是独立状态，不是 None。
相同引用的两次采样不证明中间未写，也不证明对象内容未变。若不能覆盖中间写入，
query 到达“该时点 cell 内容观察”即止，不伪造此前 writer。

core 的 StateVersionValue 仍由操作/块参数定义，表示依赖状态，不由采样哈希
替换 producer。环境样本是锚到状态使用点的证据，不能自封为 state SSA 的写入。

### 与 coarse world 的关系

C1b 第一版继续只用**当前同一个 world StateLocation**承接全部环境读写；
环境/捕获 cell 的引用为未知 targets 或只按既有 world 访问规则使用。
typed 环境字段路径说明读了哪个位置，但不引入另一个貌似独立的 cell state 域。
运行 cell 身份 registry 不是一组自动证明 disjoint 的 core LocationID。

若未来拆出独立 cell location，必须同时实现 aggregate/alias invalidation：
未知 world 写入能影响该 cell，多个 formal cell 可能指向同一运行位置，跨文件
不同 world ID 必须有明确实例映射。当前 validator 不能表达这种分离后的全部
约束，所以本门**不要同时放互不连接的 world state 与 cell state**。

## 4. C1a：仅升级调用证据，立即产生有用来源边

有限范围：已核对源/code 的普通同步 exact FunctionType；另支持已物化 exact
MethodType，其 receiver 来源明确。第一版可只支持完整记录的显式位置 actual，
以及不需执行用户逻辑的 default slot 选择；keyword/pack 若未完整实现就输出
具体边界。不读取 Tensor 内容、不扫描 gc 查找函数对象、不重放参数表达式。

caller 参数按**实际 load/求值位置**归属当前 call attempt。若采集只有 CALL 后
locals 快照，只可接纳其间无潜在写入的受限 fast-local 读；例如
`g(x, change_x())` 的第一个 x 不能取第二个表达式执行后的 locals 来替换。
不能把这条受限规则推广为任意 Name/Attribute/Call actual。

必要的动态序列为：callee/operand occurrences → dispatch/environment sample
→ exact raw-function binding recipe → 同线程、正确父 invocation 的 body entry。
保留 pre-body 失败时没有 entry 的事实；没有 body entry 不生成 formal destination。
事件丢失、递归配对不唯一、wrapper、suspended body 均不能“就近补边”。

此门建立的强关系是“这个 invocation 的这个 formal 按已校验语言绑定规则
来自这个 actual/receiver/default slot”，并携带尚未证明的时间窗条件。
其中 function identity、code/source 对应、operand occurrence 已有实际证据；
不是把所有字段都置 UNKNOWN。query 必须能走这条边并显示剩余条件。

尚未由事件实际覆盖的条件须明确保留：operand 采样忠实、CALL 到 binder 的
code/default 环境未被并发或 observer 改写、source/code 匹配、完整捕获/配对。
body entry 的相等引用只可做一致性核查，不能反过来推导哪个来源被选中。

本机监控探针还发现：`bound(x)` 与 `obj.method(x)` 的 CALL callback 均可收到
raw function + receiver，不能仅凭 callback callable 为 FunctionType 判断无 self。
原始物化 MethodType 来源和监控归一化结果必须分别保存。采集端详细方案由另一路审计负责。

**版本：**新增 call trace/evidence/report v2，旧 v1 严格重放且保留全部原条件。
新证据/绑定关系不能放宽旧 FrameCallEdge/ReferenceIdentityRoute 的固定不变量。
这一门不改变 `BOUND_FRAME_V1`、SourceProgram v2、inventory v5，也不强插 core callee。

## 5. C1b：自动 source 环境读取，需要新 body profile

新增版本化 environment profile（建议 `BOUND_FRAME_ENV_V1`）：

- entry 顺序明确为 `全部 formal refs + environment ref + world state`；environment
  不是用户 formal，不参与实际参数个数/位置。FunctionEnvironment 关联此次函数实例；
  不能从 code 相同猜一个环境，更不能让全部 invocation 共用一次运行 frame。
- 自动依据 symtable 和匹配编译 code 的 freevars 布局建立 capture schema。
  `LOAD_DEREF` 对应当前 env 的 closure slot，`LOAD_GLOBAL` 对应 globals/builtins。
  源码解析本身不读取实际 captured contents，不 import/执行用户模块。
  该 lexical schema 不是运行 cell 创建来源：`FunctionType(code, ..., closure=...)`
  可注入别处 cell；只有创建/环境证据才能把此 cell 连到原外层局部。
- core 环境读必须消费 environment ReferenceValue 与当前 world；正常路径产生
  读取到的 ReferenceValue，空 cell/缺失名称走异常路径，再经过 C0 unwind。
  typed source rule 把这个结果解释为指定 storage read，不能依赖 op label。
- 捕获读不是入口隐式复制一份不再变的 formal。`read(); callback(); read()`
  第二次读取使用 callback 后状态，不能复用第一次结果。
- source-only query 可回到明确的 env/capture read 边界；有配对运行读证据时
  再接当时 cell 内容 occurrence。它比 opaque unknown-return 多了实际 core 依赖。
- ENTER 需持有 environment 及 formal；EXIT 继续持有 pending payload、读后态，
  不保证清空 cell/free/total。旧 NO_FRAME_INTERPOSITION 等条件不被读取证据证明。

`BodyEntryInterface` 新 schema、FrameEnter 的新版本化环境持有对应，以及
environment-access typed records 必须由同源码重放校验。新 profile 中“普通
非终结 op 只能是 frame op”的覆盖规则，应改为完整覆盖 frame 与环境操作；
旧 profile 的 validator 原样保留。不能为接环境读而全局取消 overlay 完整性检查。

**版本：**新 profile / SourceProgram v3 / inventory v6；旧 SourceProgram v1/v2
与 inventory v1–v5 重放历史路径，不给旧图补环境端口。程序图 v2 可以继续使用
已有 reference/state/operation/region；若后续增加 alias-domain 语义再单独审 schema。
新证据报告绑定精确 inventory 文档哈希，不将旧报告静默换绑 v6。

## 6. C1c 与 C2：完整目标的剩余门，不由 C1a 冒领

| 门 | 自动输入与必须得到的真实连接 | 关键验收反例/不可宣称 |
| --- | --- | --- |
| C1a 条件绑定证据 | 原始 caller/target 源码＋新 trace；formal 回到唯一 actual occurrence、receiver 或运行 default slot | 同 token 的 receiver/default/name 不串源；callee 在 actual 求值期间重绑不取晚值；旧 v1 无绑定证据仍停边；不宣称 core 已组合 |
| C1b 环境读取 | 原始闭包 getter/global reader 自动建新 profile；读结果回到 environment/cell read 和当次内容观察 | 同 code 不同 closures/globals 分开；同 owner 换 code 重新按 index/name 核对；空 cell 是 raise；未知 callback 后读保留新状态；不宣称完整写历史 |
| C1c 环境写与创建 | 原始 closure factory/getter/setter 自动建图；参数捕获 cell 创建、FunctionObject 构造、nonlocal 写、默认值定义与后来改写均成为操作/状态依赖 | 两函数共享 cell；同一 cell 多 capture index；set 后 get 的来源必须经写入及所有后续效果；外部 cell assignment/未知 finalizer 使旧 writer 推导失效；不能只新增函数环境快照计数 |
| C2 invocation 投影 | 将 C1 的 occurrence/绑定关系投到已有 body formal/environment ports，并接正常/异常及 caller 当前 world | 两文件调用返回同一正确调用点；递归/重复调用隔离；body 写后异常返回后态；pre-body 失败不接 body RAISE；旧 callee 候选不升级；完整 effects/caching/GPU 仍未解决 |

C1c 的 `STORE_DEREF` 不是普通 local BIND：它写共享位置，旧内容释放的 finalizer
还可能继续改状态；捕获参数也先进入新 cell，再供 nested function 共享。
不能只在源码中删掉 `nonlocal` 然后复用 cursor.env。
函数定义执行需要表示 default/decorator 的顺序与失败、闭包 cells 绑定及函数
对象构造；源码 `def` 名称赋值完成之前失败，不得产生已定义函数实例。
复杂 decorator/descriptor 暂未实现时必须明确边界，不能让 factory 的一半图冒充完整创建。

只知道两个 cell 采样引用相同，不能把它们之间所有 effects 消掉。
从 setter 的写入回溯到 getter 的读，需要中间完整状态链与无未知同位置写入的
依据/显式条件；遇到未知回调、finalizer、外部线程写入必须停边或保留条件。
这一要求保留了完整 C1 的共享 captured-state 目标，并不推迟到细粒度 GPU 分析。

### 完成阶段必须保持区分

本机小探针分别观察到：展开失败有 expansion effect、无 body entry；绑定失败
无 body entry；body 失败已有 body effect；async 创建无 body entry，resume 才执行。
所以实际求值、packing、dispatch/binding、body execution、suspension 不能共用一个
无阶段的 raise 关系。C1a 不支持的阶段保留未知 completion，不能伪造进入 body。
C2 接上 source INVOKE 的异常边时，必须说明此次异常属于哪个已观察阶段；普通
profile return 回调的 UNKNOWN 不是已核对异常实例，必要时升级完成事件采集。

最小跨文件垂直切片是 `helper.py: def echo(x): return x` 与
`caller.py: def run(fn, x): return fn(x)`，运行时向 run 传入真正 echo 函数。
C1a query 从 echo 此次 formal 回到 run 此次 x operand；C0 body 查询从 echo
return 回到该 formal；C2 才将这两段接回同一次 caller 的 call result/return，
同时保留 frame EXIT 及逐调用 world 后态。把 fn 换成绑定方法或换默认布局的
同 code 对象，必须改变绑定 recipe 或明确停边，不能复用旧 route。
闭包切片则先只自动构建被选中的 getter body 并读其 environment；outer factory
尚未建模时应显示创建来源边界，不能将 getter 成功写成 factory 已被完整支持。

## 7. 有限门的拒绝/重放/资源验收

所有新增关系必须通过 bundle 原始文件哈希、source/code、event occurrence、
父调用及时间顺序、字段完整性和独立预算重算。特别拒绝：

- 调换两个默认 slot、把 receiver 改 actual、借同 token 补 missing operand；
- 保留 FunctionToken 却换 code/freevars 布局，或借同 code 合并两个函数实例；
- 用死 owner 的 cell 地址命中后来对象，或把未观察到 alias 当证明不 alias；
- 将 snapshot reference 跨 event/PID/bundle 拼接，把采样编号改称已证明内容版本；
- 删除环境读/写 op 与 overlay 后缝状态链，只通过结构校验不做原始源码重放；
- 预算耗尽后继续猜 target/cell/default，或报告自写条件已满足而无独立锚点。

弱 owner 数、每环境字段/closure 元素数、事件/字节、临时 live-owner 比较次数都
有全局上限。只在 callback 内短时读取 exact builtin 字段；不持久保存 cell、
frame、default 值或 traceback，不调用用户 repr/hash/eq/getattr 来猜结构。
容量不足可损失关系，但不能持有对象改变析构时机来“保住证据”。

## 8. 本次实测记录

命令：

```sh
/home/zyf/miniconda3/envs/lewm/bin/python artifacts/experiments/c1_environment_audit/probe.py
```

结果见同目录 `probe_results.json`；进程 exit 0，CPython 3.14.7。
覆盖非 weakrefable cell、共享/分离闭包、同函数替换 code、外部 cell 写/删除、
defaults 改写/删除、相同 code 不同 globals、builtins 映射保留、CALL 观察差异及
packing/binding/body/async 的阶段差异。探针是该解释器的语义观察，不是跨实现
保证，不将观察提升为 NO_FRAME_INTERPOSITION、完整效果或变换权限证明。

## 9. 版本分配纠正（以新主计划为准）

已复核 `docs/N2_CALL_BINDING_PLAN.md`：calls-demand bridge 将先使用
**inventory v6**，沿用当前 `BOUND_FRAME_V1` body profile 与 SourceProgram v2。
因此本简报第 5 节原先给环境 profile 分配 inventory v6 的建议作废：
环境 profile 应使用 **inventory v7，或届时尚未分配的下一版本**；
其 **SourceProgram 升级仍为 v3**。两项功能不得各自定义不同含义的 inventory v6。

环境版本重放须保留届时所有历史路径，包括 bridge 的 inventory v6，不能将
其旧 body 补成环境入口。call capture/evidence/report 的版本独立分派；
此次纠正不改变前文探针事实、C1a/C1b/C1c/C2 依赖顺序及条件边界。
