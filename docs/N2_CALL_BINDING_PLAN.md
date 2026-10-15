# 下一门：调用求值、实际绑定与函数环境

日期：2026-10-15。状态：**D0 有限验收；D1/C1/C2 尚未实现验收**。
前置：[C0 frame 验收](N2_FRAME_ACCEPTANCE.md)。不增加 detector/backend。
完整 C1/C2 和 N2.call-edges E4 保留；下面的有限子门不替代它们。

本轮 D0 实现 `39e8f22` 通过 196 门检查及全仓 2,033 项，原 LeWM 归档独立重放
通过；自动得到 421 个完整源码定义种子。它们尚未进入 inventory 调度，也不是
获批优化点。实际成本、剩余边界及报告见 [D0 验收](N2_CALL_SEEDS.md)。
下一门的 typed 来源、入口优先展开和共享源码准备见
[D1 开发计划](N2_CALL_DEMAND_PLAN.md)。

## 1. 目标和当前实际断点

目标是从调用者的具体 Use，经过实际求值、dispatch/绑定、callee 的形参和
返回，回到同一次调用的结果；值来源、状态与完成依赖分别保留。

当前有两项独立断点，不能只继续增加候选或记录字段：

1. 新 calls-only 的完整 CodeSnapshot 已核验大量 source definitions，但旧
   runtime-source scheduler 只消费旧 RuntimeTrace/CodeID，不能接收这些见证。
2. CALL 回调的 callable/arg0 不是未经变换的源码 callee/actual 列表。
   Name 中也可以放 bound method；同引用不能区分显式参数、receiver 或 default。

旧采集缺少的求值事实不能靠离线算法造出来。要增加证据，必须证明新记录怎样
对应具体输入位置，并让正反例的查询实际穿过调用边，不能只多一个 UNKNOWN 层。

## 2. 仍沿用四类结构实体

| 内容 | 在模型中是什么 | 连接要求 |
| --- | --- | --- |
| 函数定义/代码 | 有版本的定义与源码对应 | CodeSnapshot 匹配不等于函数实例相同 |
| 运行函数对象 | ReferenceValue 的实际 referent；执行图有生命周期身份 | 同 code 可有不同 globals/defaults/closure；同函数的 code 也可变 |
| globals/builtins/defaults/closure/cell 内容 | 对象/环境状态的选择器与版本 | 读当前状态，不从源码默认表达式推定实际值 |
| 一次调用求值与绑定 | Operation/Region 的动态 invocation 与输入位置 | callee、actual occurrence、adapter、绑定失败、body 入口分别对应 |
| 捕获环境/函数上下文 | Region 的隐式引用端口，不是 Python formal | 支撑自由变量/global lookup 对具体函数实例的依赖 |
| 返回引用/异常与后态 | C0 completion 的 payload/world 端口 | 返回对象相同不证明内容或效果相同 |

语法源码图、执行证据图与优化核心保持分层。C1a 先在执行证据中给出带规则和
条件的 actual→formal 对应；C2 才实例化为核心调用区域和状态接口。
规则输入必须是具体 occurrence 和位置，不能以所有值的集合或引用相等作路由。

## 3. 调用发生过程必须拆开

```text
callee expression 求值并持有结果
    -> actual expressions 顺序求值/展开
    -> 读取实际 callable / adapter / 当前函数状态
    -> packing 与参数绑定
    -> 同步 body 入口
    -> body normal/raise + 后态
    -> 同一次 caller 的 completion
```

callee 名称在 actual 求值期间可能被重绑；CALL 时重新读名称不等于之前压入的
callee。函数的 code/defaults 也可能在此期间变更：应读取 dispatch 时的当前状态，
并与进入的 code 对应，不能把 load 时的 code 或源码声明当作当前状态。

packing、绑定和 body 前失败不能连成 body raise；body 失败可能已经改状态。
async/generator 的创建与后续 resume 不是一次普通同步 body 调用。

## 4. C1a：有限求值证据与条件绑定

### 4.1 第一条可实现规则

探针优先验证：局部 INSTRUCTION 在真正 LOAD_FAST/LOAD_GLOBAL 前记录 slot
观察，CALL 与实际 frame 入口握手，再按指令/actual index 路由。首批只处理
精确原生 FunctionType、固定位置 actual、未消费 default/pack/adapter 的同步调用。

这是 **pre-load slot observation**，不是声称直接观察了解释器值栈。它依赖明确
的无 frame/namespace 干预条件，以及 load→call 对应的字节码与实际路径检查。
条件未证明时，查询必须标为条件来源；不能改写为无条件 VERIFIED 或变换许可。

- 在 load 前而非 CALL 时记录原始 callable shape，防止 Name-bound method 混淆。
- CALL/entry 的对象和 code 对比用于发现矛盾，不能按同对象决定 actual 来源。
- 同值多 actual 必须保留各自 occurrence；所有 token 不同也不改变位置路由。
- 非 weakref 值的 snapshot token 不提供跨事件身份；不为验证来源保存 tensor 内容。
- 未观察入口、路径/预算截断、代码或调用约定失配必须有具体边界。

后续在同一门增加已物化 MethodType 的 immutable receiver/func 规则，再处理
当前 defaults 与 partial/placeholder/keyword/packing。每条规则单独验收；不能
用“CALL callable 为 FunctionType”排除隐藏 receiver。

### 4.2 必须有的证据关系

具体 wire 名称在实现前冻结，但至少保留：

- caller InvocationKey、源码/core call 及 callee/actual UseID 对应；
- CallAttempt 身份、各次求值 occurrence、原始记录 anchor 与指令位置；
- 观察阶段、raw callable shape、函数实例与当前 code/layout 状态；
- dispatch/adapter recipe、actual/default/receiver/pack 的明确来源位置；
- attempt→entry 握手与失败阶段，未证条件和不能提升的权限状态。

新 capture/report 必须版本分派，旧 v1 完整重放不变。纯 C1a 不改当前
BOUND_FRAME_V1/source-program v2/inventory v5 的 body 含义。

### 4.3 探针准入

本机 CPython 的 monitoring 与 setprofile 安装次序、同一 CodeType 的 instrumentation
残留会影响 INSTRUCTION 交付。必须每 trial 使用新 code/独立进程验证，不能从
没有交付事件推出没有操作；不因某次成功忽略 hook 变化或预算缺口。
先不引入 ctypes、解释器私有栈读取或 C 扩展。

## 5. C1b/C1c：环境不是代码身份的附属字段

- function owner 用生命周期 epoch；不以裸地址永久识别函数或 cell。
- cell 不可 weakref；可用活着的 function owner + closure index 锚定所属槽，
  共享 cell 的别名需要同一有效观察中确立。co_freevars 名称受当前 code 版本约束。
- function.__builtins__ 是函数创建时保留的独立映射，不能由当前 globals["__builtins__"]
  重建；该映射的内容变化仍属于world。
- defaults/kwdefaults 的当前内容与源码默认表达式不同。函数换 code 后，原 defaults
  还可能保留；不能借新 code 的源码声明解释旧函数对象的默认状态。
- 外部 cell_contents 写、nonlocal 写、共享闭包、不同 globals 的同 code 都必须
  成为状态变化或显式边界；空 cell 与 None 不同。

自动 body 环境访问需要新的隐式 FunctionEnvironment 引用端口和相应 ENTER
持有关系，不能塞进 Python 形参。当前 frame validator 的入口只有 formals/world，
因此需新 profile 与 source-program 版本；旧 profile 不静默加端口。

初版环境内容继续在同一个 coarse world 状态域中，cell/env 引用只是 selector。
禁止因为新建 CellLocationID 就宣称它与 world 不相交。只有包含/alias 和 aggregate
失效规则齐全后，才拆细状态域。C1c 再闭合环境写与声明阶段 cell/function 创建，
把运行 cell 接回正确的外层 invocation；同 source body 不共享局部 frame/cell。

## 6. 并行前置：新 code 见证进入需求队列

先实现独立 calls-demand 桥接，复用稳定 descriptor 和源码核验，不消费或构造
完整 reference/call report。逐行严格验证 raw capture，保留 entered-code 的紧凑
分组、首末 anchor/计数和 raw 文件 SHA。按真实 entry 的 code→VERIFIED snapshot/
唯一 definition/source 对应准入；不以 filename/qualname 补缺失目标。

发现源码与 import closure 仍自动进行，所有 wrapper/frame 边界保留。需求优先级
不是 callee 环境、参数、纯性或优化证明。旧 observation_indices 不能存新 call anchor。
独立 CallEdgeBudget、InventoryBudget、ContextStoreBudget 和重放均需检查。

此桥接先占 inventory v6；环境 profile 后续版本单独迁移，避免两个改动各自
定义不同的 v6。没有可用 seed 时仍保留输入、缺口和版本，不回退旧 filename 见证。

## 7. 自主验收门

| 门 | 必须实际交付 | 关键反例 |
| --- | --- | --- |
| D0 | seed-only 严格流、稳定 code/source 对应与预算/重放 | 伪 meta/count/hash、代码失配、同名定义、截断/外部 source、不能构造 reference graph |
| D1 | v6 自动 scope/需求队列、旧v1–v5重放 | 原入口自动发现并优先实际callee；wrapper不跳过；预算失败不退款；不手输函数名单 |
| B0 | fresh-code/独立进程的 hook 与求值实验 | 安装次序、callee重绑、bound Name/优化method/partial、同ref歧义 |
| B1 | 真实两文件多层程序自动产生条件 actual→formal→return 路由 | 多 actual 同ref、递归/两个调用点、load后重绑、callee改code、slot干预、hook/预算缺口 |
| B2 | receiver/default/pack 的来源规则 | receiver与actual同对象、动态默认、partial.__setstate__/keywords/placeholder，前置失败 |
| E0 | 环境入口与自动 global/free-cell READ | 同code不同globals/cell、空cell、源与当前defaults不同、world不能假装disjoint |
| E1 | 环境写/声明/共享 cell 的版本和来源 | nonlocal/external cell写、同code不同outer调用、code变化保留cell、绑定前失败 |
| C2 | 每调用区域、完成/state映射与核心查询 | 异常后态不能回滚；实际调用结果回到唯一caller；跨文件world显式承接 |

每门：原始程序自动采集/构图 → 独立正反例 → 冻结mapped与必要回归 → 外部来源
同输入压力验证 → 报告并版本提交。若某条证据协议失败，保存原因后调整，不以
删掉原E4验收要求换取通过。F4运行期间主代码冻结；可在隔离分支继续实施。

完成连接后再接循环、细状态/provenance、观察根闭包和化简指导。当前不新增
backend，不报告LeWM TRANSFORM或加速比。

## 8. 本轮安全实验结果（不是生产C1验收）

已实际运行 `artifacts/experiments/c1_operand_audit/probe.py`，精简结果为同目录
`result.summary.json`：154个诊断事件、15个attempt、9条条件路由。两个文件的
链在distinct/shared对象两种情况下都按load occurrence/actual index回到不同
来源；global/local在实参期间重绑的例子均保留旧load对象，CALL时当前名称已不同。
这是独立原型，尚未接入SCAR的pycode-v2/source验证、弱引用/预算和公共重放。

fresh-code矩阵实测：monitor-only有5个INSTRUCTION/1个CALL；先monitor再profile
没有INSTRUCTION；先profile再配置monitor有5个INSTRUCTION/1个CALL。初次同code
复用造成两种次序都失败的判断已撤回，原始过程在探针说明中保留。该结果限于
本机CPython3.14.7，不能当成其它hook/解释器组合的保证。

`artifacts/experiments/c1_environment_audit/probe.py`及`probe_results.json`另验证
非weakref cell、共享cell、同owner换code保留cell、不同globals的同code、default
改写、builtins映射保留、packing/binding/body失败以及async创建/resume的区别。
`DESIGN_REVIEW.md`记录环境入口和版本审查。全部实验仅运行通用小fixture，
不执行LeWM，不保存Tensor内容，不产生无条件绑定证明或变换权限。
