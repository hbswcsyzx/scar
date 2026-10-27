# Body preservation：独立架构复核

日期：2026-10-16。状态：**设计审查；新能力未实现、未验收。**

只读审查基线：`/tmp/scar-call-windows-qx_qw6dk`，提交
`8a300eb068d992b3737eee0bdf43fa2bf8c8aea1`，源码指纹
`38dfe6c34545b405fa5e8f08e2828f7357c862527500a6a1f2b3d97072796574`。
本次未运行测试、源码分析任务或 LeWM，未修改被冻结的输入。

## 结论与方案比较

推荐**新增版本化 `STRUCTURED_BODY_V1`，在共同的 core 中递归生成真实 CFG**。
下一门先实现普通同步函数的局部绑定、if、for/while、break/continue/else、循环内
有序 call operands；保留每个局部未知操作的效果与完成边界。不要以单个 opaque
loop/try 包装替代其内部调用。没有正确控制规则的结构必须列明未连接的内部 Call。

| 方案 | 判断 |
| --- | --- |
| 直接改变 `BOUND_FRAME_V1` | 不采用。它既决定旧源码报告重放，又约束 frame 生命周期和 return payload 规则；扩展之后旧 unsupported 报告会改变，旧来源检查也可能被放宽。 |
| 新版本 profile，共同 core/ID/Use/CFG | 采用。为新绑定类型、循环规则和局部未知操作建立独立校验入口；原来源 ID、自动发现、需求队列及 budget 复用。旧 profile 按旧算法重放。 |
| 独立结构图 | 不作为本门交付。现有 inventory/legacy control overlay 已有大量结构；再建 AST 图仍不能给 call routes 提供规范 Operation、Use 和 completion。以后若要求所有死代码/未知控制子树也拥有非执行 core 结构，需要明确类型与 schema，不能偷偷把结构边当执行边。 |

四个顶层类型仍是 `Operation / Value / StateLocation / Region`。新增局部绑定是
Value 的强类型变体；循环是 Region/Block/Operation 的组合及有类型的控制合同。
“结构覆盖、语义精度、执行对应、变换权限”必须分别报告。

## 已查实的连接断点

1. **一个不支持节点删除整个 core body。** `program_lowering.py:_Builder.run`
   捕获 `_Unsupported` 后清空 graph、operation/value/use links、call targets、
   interface 和 frame（约 724–783 行）。`_check_frame_statements` 和 `function`
   在更早阶段拒绝 loop、try/with、复杂赋值、closure、generator/async。
2. **已有 source inventory 可复用，但不等于 core。**
   `program_inventory.py:_Inventory.walk/define` 保存完整源码 atoms、CallInventory、
   definition-time inputs 与执行 owner；`_body_connections` 只要 atom 被任一
   metadata link 引用就计 connected。这个一般计数不足以证明某个 Call 有独立
   core Operation 和全套 ordered Uses，下一门必须另做逐 call 双射检查。
3. **v2 core 不是任意 AST 容器。** `model.py:Region` 必须有 entry/blocks；
   `validation.py` 要求所有 block 从 entry 可达（约 270 行）、SSA 支配、完整状态
   端口、私有 INVOKE completion 目标。循环回边本来就能表示；错误的是把 AST
   子节点顺序摊平成一次执行、加假分支让不可达源码通过可达性校验。
4. **frame 合同不能原样套到新普通操作。**
   `frame_validation.py:validate_frame_model` 要求普通非 terminator 操作恰好是
   frame transitions；entry 恰好为 formals 加 world。LocalBinding 操作要有新
   profile 的显式允许集合和对应规则，不能全局削弱旧 frame validator。
5. **查询真正需要 core 端点。** `call_edges.py:_Sources._call_site/_operand/result`
   要求 source Call→唯一 Operation→callee/actual Use→INVOKE normal result；
   `_Core.return_root` 还要求真实 frame EXIT/RETURN payload。source span 匹配成功
   不代表这些连接存在；`CallSiteLink.status=VERIFIED` 仍可能带 CORE_CALL_MISSING。
6. **新 loop 图不能自动扩大动态查询范围。**
   `call_operand_routes.py:query_operand_routes` 用 `(invocation, ValueID)` 查 normal
   result，仅唯一 completion 才追溯。同一调用点循环执行两次就有两个动态来源；
   branch phi 不同 SSA 来源同样停在 CONTROL_SELECTION_UNVERIFIED。需要未来的
   动态 block/iteration occurrence 才能选择，不能按相同 reference token 猜测。
7. **comprehension 有额外 owner 对齐问题。** inventory 给 comprehension 独立
   execution owner；当前 call-site matcher 要求它等于 code_link.definition。
   CPython 内联 comprehension 可能没有独立 CodeType。即使补出内部 Call，仍需
   源码编译结构证明 lexical owner→实际 code owner，不能按 filename/名字强接。

## 最小可靠实现形状

- 新 `LocalBindingValue/LocalBindingType` 携带精确 slot；`BindingDefinition` 区分
  BOUND/UNBOUND/UNKNOWN，`BindingRead` 连接 token、正常引用和异常路径。零次循环
  后未赋值不是 `None`，也不是可正常使用的 unknown ReferenceValue。
- 预先从 symtable 建固定局部槽顺序，loop header/merge/出口按逐前驱传 binding
  tokens 与当前 world；首次赋值不读取旧未绑定 token。重复 `leaf(x, x)` 有两个
  actual UseID，读取同一绑定不代表两个发生位置可以合并。
- `for` iterable/iter 求值一次，next 每轮执行；next 的 RAISE 私有后继才检查
  builtin StopIteration 及子类。body/iter/target/普通 call 抛同类异常不能当耗尽。
  while truth 每轮求值。break 绕过 else，continue 回正确内层 header。
- 未知协议、属性/下标写和动态 call 消费当前 coarse world；每个发生完成的路径
  有正确 post-world。保持 effects incomplete、可能不完成、alias unknown；不同
  文件 world ID 不能被当成已知不相交。引用 identity 不证明内容未变。
- fallback 只能使用已核对的求值/控制合同。对有序普通表达式可先递归构造 child
  calls，再发未知操作；BoolOp、IfExp、比较链不能把所有 children 提前执行。
  try/finally/with 不能用普通 NORMAL/RAISE invoke 假装其 return/break/suppression
  语义已覆盖。尚无合同的子树必须列明内部未连接 call，不能计为 covered。
- 未支持的控制结构若仍会令整个 body 不可建，报告这一真实边界；本门验收不能
  把“源 inventory 存在”或“opaque function shell 存在”算作 body preservation。
  本门应完成所声明语法范围内的实际循环/分支内调用保留，扩范围再单独验收。

## 推荐迁移与文件范围

新增 profile 必须明确分派；建议下一空闲版本为 ProgramGraph v3（新 binding
variants/规则）、SourceProgram v3、ProgramInventory v7。旧 core v1/v2、source
v1/v2、inventory v1–v6 保持原 wire 与旧 profile replay；保存的旧 summary、gap、
ID 不能用新能力自动重算。新 profile 的 core ID 包含 profile，原 SourceSnapshot、
SourceReference、OperationDefinitionID 继续沿用既有源码身份链。

相关实现文件及必要工作：

| 文件 | 必要改动 |
| --- | --- |
| `ir/program/model.py`, `codec.py`, `validation.py` | binding Value/Type/UseRole、规则记录与 slot/producer/CFG/state 校验；版本化严格 decoder。 |
| `ir/program/functions.py`, `frames.py`, `frame_validation.py` | 新 profile 与精确 entry/frame/普通操作校验分派；不放宽旧 profile。 |
| 新 `analysis/structured_lowering.py` | binding carry、循环上下文、协议 lowering、逐 child call/Use、局部边界。 |
| `analysis/program_lowering.py` | SourceProgram 新 schema/profile/source replay 的入口；旧 builder 路径保持。 |
| `analysis/program_inventory.py`, `program_expansion.py`, `function_interfaces.py` | 复用全局队列和封存源码；新 profile 的 body/interface/frame 接线、逐 call coverage 与不退款成本。 |
| `ir/program/inventory.py` 与 source metadata 相关 records | 表示精确连接/缺口范围；不以改 label 或一般 atom connected 数代替。 |
| `analysis/call_edges.py`, `call_operand_routes.py` 与相应报告 records | profile 显式准入、binding-read provenance、循环动态歧义停边；保留旧 report 的查询语义。 |
| `cli.py` | 显式 profile 可复现选择、公开建图/check；冻结后再变默认。 |

更完整的实施门计划由后续 `docs/N2_STRUCTURED_BODY_PLAN.md` 承接。本文不授予
内容/效果闭包、callee/environment completeness、GPU readiness 或变换权限。

## 自动 LeWM 源码验收：必须输出的分母与断言

原始入口、源码与 raw archive 自动输入；禁止 workload 图、函数特判、手工 purity/
constant 名单。固定源码/trace hashes、profile 和所有 budget，独立公开 replay。

1. **源索引守恒：** 所有 parsed source atoms 无漏无重；逐 phase/owner 的 Call
   分母固定。报告总 Call、可执行支持范围 Call、死代码/未知控制/预算边界 Call。
2. **body 保留：** 支持范围且预算已准入的 function definitions 中，core Region、
   interface 与对应生命周期模型有效率为 100%；循环数量/零次边/回边/else/
   break/continue 数量与独立 AST 预期一致。不能只报 body 数比旧版更多。
3. **call/use 保留：** 支持范围的每个 Call 恰好一个 source/core Operation；callee
   和每个 actual occurrence 恰好一个有角色/序号的 Use。分 loop/branch/nested
   expression 汇总，缺失和重复为 0。Opaque 容器的 span 不能覆盖子 Call 分子。
4. **未知范围守恒：** 总 Call = 已精确连接 + 明确未连接（不重不漏）；每个未连
   原因/位置可回查。budget 失败不是语法支持，source-only 不是 core-connected。
5. **执行对应另计：** strict raw/code/source 的 matched sites、有 core endpoints、
   满足 B1 binding 条件、实际 argument/completion routes 分开计；receiver/default/
   kwargs/pack 和多轮 completion 仍可为 boundary。任何来源不唯一不得接边。
6. **权限与成本：** transform authority 为 false；未知效果/状态边不可消失。
   每文件昂贵 prepare≤1、构造 operations 不退款，测峰 RSS/壁钟及队列遗漏；这是
   分析成本记录，不是 LeWM 执行加速。失败输出仍须严格可重放。

当前 windows capture 仅已知 collection 事实：312,812 sidecar events、100,550
attempts、4,069 handshakes、945 gaps、0 drops；capture 标记 NEEDS_READER_REVIEW。
读取时离线 inventory 仍 RUNNING，本文不推断 LeWM core/route 比例或验收成功。
