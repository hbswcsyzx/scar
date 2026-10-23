# Python 固定解包、Slice 与 comprehension 作用域补全设计

日期：2026-10-23。状态：**Implemented / Verified：两个原 source body 的有界静态建模；完整 Run/inventory 接线仍 OPEN。**
本项不增加 detector/backend，不执行 LeWM/forward，不生成新 runtime events，不修改
正在由 R2 调整的 ProgramGraph/resource/codec。完整程序建模仍 OPEN。

## 1. 已读代码与真实分母

已读 `first_stage_body_frontiers_20261023` 的 README/result/groups；
`structured_lowering.py`、`environment_lowering.py`、`source_heap_lowering.py`、
`program_lowering.py`、`source_compilation.py`；`ir/program/structured.py`、
`model.py`、`frames.py`、`functions.py`、`stored_values.py` 和 `ir/literals.py`。
仓库没有 `source_env_lowering.py`，实际环境 builder 在 `environment_lowering.py`。

**Observed：**旧 272038 来源表的 91 个实际 code groups / 2,902 次调用，属于
source 已关联但 body UNSUPPORTED。最主要同理由组为固定赋值/解包诊断
12 groups / 1,092 calls；Slice 原理由分组为 150、30、2 calls，合计 182；
`ordinary local has no parsed slot: v` 为 3 groups / 111 calls。900 次 GeneratorExp
属于另一项，不能加到固定解包收益里。所有数字是首个停止理由加权，不能预言
补一个语法后整个 body 必然成功。

只读 AST 检查显示，具有该解包诊断的原 source bodies 确有 Tuple(Store) targets，
本批看到的这些 targets 没有 Starred。审查不根据函数名生成产品规则。

## 2. CPython 3.14.7 决定的边界

参考固定 tag `v3.14.7`，与原采集 Python build 的 minor/patch 一致；滚动 3.14 文档
仅作语言参考，不冒充另一 patch 的实现已被当前运行验证。

### 2.1 解包不是一组 getitem

赋值先求 RHS，再按目标的递归、从左到右顺序赋值。同层固定 arity 的解包先完成，
然后才处理该层各 target；`a, (b, c) = rhs` 的内层失败不撤回已经赋给 a 的绑定。
[语言定义](https://docs.python.org/3.14/reference/simple_stmts.html#assignment-statements)、
[3.14.7 compiler assignment_helper](https://github.com/python/cpython/blob/v3.14.7/Python/codegen.c#L3177)
明确区分这两个阶段。

generic UNPACK 取得 iterator，收集所需项，再多取一项检查是否过多；不足、过多、
不可迭代及用户迭代错误分别产生相应失败。失败会清理已取得的临时项/iterator。
因此不能用 `len` 加 N 次索引、普通 for-loop 或“先 store 一个再取下一个”替代。
[3.14.7 ceval helper](https://github.com/python/cpython/blob/v3.14.7/Python/ceval.c#L2254)
是这里的协议依据。

实际解释器也有 exact tuple/list 的 specialized 路径；它们不等于调用用户的
`__iter__`。没有实现路径证据时不能断言发生 iterator allocation、N 次 Python
callback 或零成本引用抽取。协议给出允许的实现边界，真实实现选择仍由 measurement
与 runtime evidence 决定。[3.14.7 UNPACK opcodes](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L1437)

### 2.2 Slice 键不是全局函数调用

`base[lo:hi:step]` 先求 base，再按顺序求存在的 bounds；缺省项保留为 None。
语法创建的键交给 subscription dispatch；全局变量 `slice` 被重绑定不改变这个语法。
不能提前将 step=None 改成 1、将负数 bounds 归一化，或将 step=0 一律在建键时拒绝。
这些会改变自定义 consumer 能观察到的键。
[语言定义](https://docs.python.org/3.14/reference/expressions.html#slicings)、
[3.14.7 sliceobject.c](https://github.com/python/cpython/blob/v3.14.7/Objects/sliceobject.c#L134)
将建对象与 consumer 的 index conversion 分开。

**关键实现事实：**3.14.7 compiler 对 constant Slice 使用 code constants 的 LOAD_CONST；
动态无 step 的直接 subscription 可用 BINARY_SLICE/STORE_SLICE；其余情况可用
BUILD_SLICE，再执行 subscription。因此“每个 ast.Slice 每轮分配新对象”也是错误模型。
[3.14.7 codegen selection](https://github.com/python/cpython/blob/v3.14.7/Python/codegen.c#L5000)、
[constant/build selection](https://github.com/python/cpython/blob/v3.14.7/Python/codegen.c#L5272)

动态路径的 Slice、bounds、container 都有生命周期；失败也有 cleanup 顺序和 post-world。
归一化 IR 可以展开它们，但不得把展开误称多条真实 runtime event，或延后最后引用的
释放而称行为无变化。[3.14.7 slice opcodes](https://github.com/python/cpython/blob/v3.14.7/Python/bytecodes.c#L778)

## 3. 当前 IR 足够什么，还差什么

| 当前实体/接口 | 已有能力 | 必需补口 |
| --- | --- | --- |
| Operation / CompletionSignature / CompletionSuccessor | 正常边携带任意数量 typed payload；每条边有自己的 world | 不需要新 tuple-result Value，也不需要 ProgramGraph 多结果类型 |
| StructuredBuilder.invoke | 仅单个 `result_type` 或无结果 | 增加多 payload helper，旧单结果 wrapper 不改语义 |
| PythonProtocolKind | iterator、store、frame/temp 协议已有 | 固定解包、slice build、code constant reference 的明确协议/来源 |
| LocalBindingValue / FRAME_BIND | 绑定可 UNBOUND，stateful 释放旧绑定 | 递归 target adapter，保持部分赋值和异常后的已更新 env |
| active_temporaries / HOLD / RELEASE / EXIT | pending refs 可带到失败出口，原 FrameRules 保留 UNKNOWN | 对分支、消费所有权和剩余待赋值 refs 明确协议；不能随手延寿 |
| SourceReference + SG slot | 词法 owner 和 code 来源已存在 | compiler physical local 与 comprehension 词法 slot 的对应 |
| ReferenceValue / coarse world | 可以保留 alias/effects 未证实 | 不能将元素视为 clone、新 logical version 或无副作用 |

当前 `StructuredBuilder.store` 只接受 Name；environment builder 另接 heap/global/cell，
Tuple/List 仍落入拒绝。`expr` 不能处理 Slice。通用子表达式求值也没有像 heap-target
helper 那样一致地暂存此前 operand；新 slice/tuple-key adapter 必须处理 pending refs，
不能仅加一个 AST 分支然后让异常漏掉 receiver/前一个 bound。

`FrameRules` 的 no-interposition 条件、UNKNOWN effects、MAY_NOT_COMPLETE、
NOT_GUARANTEED release 均保留。协议结构补全不等于 finalizer 行为或实际生命周期已证实。

## 4. Proposed：最小通用协议与 API

### 4.1 多结果 INVOKE helper

```text
invoke_results(cursor, source_node, ordered_inputs,
               result_types: tuple[ValueType, ...],
               failure_handler=None)
  -> normal_cursor, tuple[existing ValueID, ...], operation_id
```

正常 completion 是 `(*result_types, world)`；失败为 `(exception_reference, world)`。
landing block arguments 仍是原 CompletionResult(i) 的唯一定义，不将 N 个结果打包
成 Python tuple 再产生 N 次 getitem。现有 `invoke` 委托该 helper，维持旧返回形状。

### 4.2 UNPACK_FIXED

新增一个源协议 kind `UNPACK_FIXED`。输入为 RHS reference + world；正常结果为 N 个
有序 references + world；raise 为 exception + world。N 从目标同层的 exact AST/SG
来源与正常 signature 一起核定，允许 N=0。即使 N=0，也不能删除迭代/arity 检查。

`lower_unpack_target(builder, target, rhs, cursor)`：

1. 只接 `Tuple/List(ctx=Store)`；本 capability 不接 Starred。
2. 先一次完成本层 UNPACK_FIXED；不在协议内部提前提交语言 targets。
3. 完整设计应依次交付结果，由已有 Name/cell/global/heap store 接叶；嵌套 Tuple/List 递归。
   **本轮实现 capability 为 `PYTHON_FIXED_LOCAL_UNPACK_V1`，只接普通 local Name leaves。**
   cell/global/heap、Starred 明确拒绝；不能将这一实现称为全部 fixed unpack。
4. `for` 仍由原 ADVANCE_ITERATOR 判断自然结束，body 的 unpack 失败是 body 失败，
   不能送进原 for-exhaustion handler。
5. inner unpack/store 失败使用当时 cursor.env 和 post-world，不回滚已完成的 leaf。

协议负责自身 iterator/provisional items 的内部消费与失败清理。normal 公开的 N 个
refs 只由各自 completion 定义；后续尚未赋值的 refs 必须在 active temporary 集中。
RHS 临时持有应在 UNPACK opcode 对应消费点结束；如果 RHS 还由 local/链式赋值持有，
那些是另外的既有引用，不能通过提前释放它们模拟 stack 消费。

固定 3.14.7 generic 路径的生命周期合同还包括：成功校验后关闭 iterator，再由 opcode
消费 RHS stack reference；失败关闭按逆取得顺序保存的 provisional items，再关闭
iterator，opcode 随后消费 RHS。过多检查取得的额外项也要在失败中处理。exact built-in
路径按它自己的引用取得/消费规则建模，不能假造一个实际 iterator。所有 cleanup 的
可能 finalizer 作用归入相应 post-world；协议不是纯数据 projection。

现有 HOLD/RELEASE/EXIT 可以承载这些关系，但构造 helper 需明确每条 completion 的
pending set。失败构造不能借 normal 分支 pop/释放；不能以统一 finally 清空 list
代替图上的 cleanup。内部 finalizer/noncompletion 仍由原协议条件与 world 表示，
不把它误写成 NONE。如果未能给出正确 consumption/lifetime 规则，就保留该项 frontier。

generic iter、exact built-in fast path 是协议的 implementation alternatives。后续有
版本化 type/dispatch 证据才能细化；本次不新增 runtime callback/events 去伪造选择。

### 4.3 Slice：值键、编译表示、subscription 分开

新增源协议 `BUILD_SLICE`：存在的 bounds 顺序求值并暂存，缺省项用明确来源于语法的
None；builder intrinsic 生成键，不能生成 Name('slice') 的 global lookup。动态建键
用原 INVOKE 的 ref/world 与异常后态，不判纯，也不提前执行 consumer 的 `__index__`。

constant Slice 需要另一个通用来源 `READ_CODE_CONSTANT`，配薄 `CodeConstantSource`
见证（operation、原 source、CodeWitness artifact/hash、code fingerprint、constant path）。
它索引原 code constant reference，不扩展 PythonLiteral 去伪装一个新分配 slice，
不复制 co_consts 对象或增加另一套 producer。普通 read operation 的结果仍为原
OperationResult；code-table 来源/可能读取的 world 单独保存。

CodeWitness 的结构 fingerprint + constant path **不能证明运行中 CodeType object
instance 唯一**；同结构代码可有不同 constants 实例。因此该来源不设虚假的
referent_identity，实际 code-instance/constant-object identity 缺口明确保留。
不能因为值相同就合并两次 constant materialization 或两个运行。

`lower_slice_key` 应返回 key reference 与表示来源：code constant、dynamic BUILD_SLICE、
或 compiler two-bound combined path。已经有 CodeWitness 时可读原 dis/constant path
确认；没有则只建源层关系并保留 representation/identity frontier，不猜物理 allocation。
constant LOAD_CONST 路径不能额外生成几条“实际 bounds 求值”事件。

`lower_subscript_key` 再按左到右组装 tuple key：`[:, :T]` 是两个 key parts，
省略项/None/Ellipsis 与普通整数索引各自保留。receiver、先完成的 key parts、动态
bounds 必须跨后续可能失败的求值持有。最终沿既有 INDEX/STORE_SUBSCRIPT 协议派发，
状态地址仍是 `Element(key_use)` 的部分覆盖；不从冒号推断 tensor view、copy 或零成本。

two-bound BINARY_SLICE/STORE_SLICE 可以有一个 source composite 展开，但其输入消费、
slice 销毁和 receiver/RHS 释放必须符合固定 compiler/runtime profile。若第一轮仅
完成普通 key 物化，不应假称 combined 路径也已恢复；用明确 capability frontier
`COMBINED_SLICE_LIFETIME_UNRECOVERED` 保留它，随后复用同协议补齐。

普通 slice store 仍是 RHS→receiver→bounds→store；AugAssign 是另一种先读后改写
协议，del 也有自己的完成规则，本轮不因共用 Subscript AST 而顺带接受它们。

## 5. v 槽：已定位的作用域错接

**Observed：**只读解析三份原 source 的 stdlib symtable，没有生成 CodeType 或执行
目标；三处 v 都是 `is_local=True, is_comp_iter=True, is_comp_cell=False`。原 SG 的 v
则有明确 comprehension owner。例如 `wm/lewm/lewm.py` 133–135 的 v 是
`slot:slot:023431263823955d72728ac1`，owner 为 DictComp
`opdef:op:edd0b457afdb1c33bce0f944`，不是 enclosing get_cost 的 slot。

**Inferred from code and confirmed layout：**environment builder 将 compiler
`is_local()` 名单当作全部 enclosing lexical locals；入口对每个名字调用
`define_binding`，只查 `(function_definition, name)`。PEP709 物理内联变量因此被
错误要求存在一个外层 SG slot。不是原 parser 没有给 comprehension 的 v 建槽。
[3.14 symtable API](https://docs.python.org/3.14/library/symtable.html)、
[3.14.7 symbol inlining](https://github.com/python/cpython/blob/v3.14.7/Python/symtable.c#L758)

最小修正方向：按原 SG lexical owner 初始化 function 的真实 slots；另建只读
compiler-local classification 对照，区分普通 local、inlined comp iteration/cell、
hidden compiler locals、global/free 等。不能一律删除所有 `is_comp_iter` 名字：
同名 v 还可能是合法的外层参数/local，必须按原每次 binding/read 的 lexical owner
区分。也不能将没有外层槽的 v 降格为 global read。

尚无 comp adapter 时，应停在明确 `COMPREHENSION_SCOPE_INTERFACE_UNIMPLEMENTED`，
而不是补一个外层 v 或宣称 111 次调用都已恢复。完整 comp 需要隔离 binding tokens、
保存/恢复可能 UNBOUND 的外层 binding/cell、异常 epilogue，以及 comp 内部各轮控制。
PEP709 的 inlined list/dict/set comp 不要求新增 Python function invocation；源 Region
不等于真实 frame。[PEP709](https://peps.python.org/pep-0709/)

GeneratorExp 另保留 generator code/body、环境、creation/drive/yield/resume/close
接口；左侧首个 iterable 的创建阶段与之后惰性求值不能合并。已有 resumable/frame
实体可承载，但这不是本次固定 UNPACK 的实现目标，不生成假正常函数 root。
实际压力已由[调用协议审计](CALL_PROTOCOL_FRONTIERS.md)完整核实：945 次项目内 exact
function、无同步入口的 targets，全部属于 8 个 CO_GENERATOR code；这不证明945次成功创建。
因此本轮显式保留 `GENERATOR_EXPRESSION_CREATION_DRIVE_INTERFACE_UNIMPLEMENTED`，
不能用普通同步 entry 或将 GAP 改名消除这个缺口。

## 6. 需要变更的最小文件与验证职责

| 位置 | 最小改口 |
| --- | --- |
| `structured_lowering.py` | 多结果 wrapper；typed kind 准入；pending refs/每条 completion 校验 |
| `environment_lowering.py` | tuple/list store 与 slice/key adapter 分派；lexical/compiler locals 分离 |
| 新 `source_unpack_lowering.py` | 固定/嵌套 target 计划、顺序 store、arity/partial-store validator |
| 新 `source_slice_lowering.py` | intrinsic key、constant witness、tuple-key 与生命周期 validator |
| `source_heap_lowering.py` | 复用子表达式来源与临时持有；slice key 转交，不重做 namespace/heap 图 |
| `ir/program/structured.py` | 新 typed protocol kinds；最小 `UnpackShape`/`CodeConstantSource` 来源参数，索引原端口 |
| source program/inventory/checkpoint 封装 | 显式 language capability/version，不静默重解释旧 CP |

`UnpackShape` 只记 arity/原 child target SourceReferences；结果以 operation signature 和
既有 landing ports 为准，不能再存一份可独立修改的 producer/output 表。独立 source
验证要从 exact source text/AST witness 核这个 shape，不能只自查一个声明的 N。
可为 validator 增可选 exact-source witness（每 file parse 一次、fingerprint/atom 全核）；
缺少它时只称 graph well-formed，source shape correspondence 保持未验证。

最小来源记录可以是 `UnpackShape(operation, source, child_targets)` 与
`CodeConstantSource(operation, source, code_key, constant_path, witness_artifact)`：
arity 从 child_targets 数量与 normal signature 同时核定；这些是来源索引，不增加
ValueID/StateVersion/producer。capability 明确限制 fixed arity，Starred 不混入此记录。

validator 必须逐项核：

- 输入 roles、N+world/exception+world、原 CompletionResult/landing、来源/owner；
- 全层 unpack 完成后才出现叶 store，嵌套 failure 保留已写 env/world；
- branch pending refs、正常消费/异常 cleanup 与原 frame 条件，没有临时引用漏项；
- slice bounds/tuple parts 的有序 Uses；constant source 对应原 CodeWitness path，
  dynamic/combined 路径不冒认 constant 或省略失败边；
- alias/effects/termination/actual code-instance 缺口不被协议类型自动清除。

核心已支持多 completion payload，暂不要求改 ProgramGraph/resource/codec；不抢 R2
的 graph schema 号。source-language wrapper 需要显式升级（现 ENV SourceProgram4 /
inventory8，拟在实施时分配后继版本及新 checkpoint capability）；旧 wire/profile
保留原义。若增加字段影响公共 record codec，必须采用显式新版本而非旧字段静默默认。

## 7. 两个原 source body 的有界验收计划（待根审查）

自动从原 frontier 按 AST pattern/原 source reference 选择，不在产品写函数名规则。
两例恰在同一 `wm/lewm/module.py`，原 fingerprint
`sha256:3a6209baf30c11f77a5f6637282a1821fc62cea827438a97b23933caab51d8c7`：

| 原 body / 位置 | 机械验收目标 |
| --- | --- |
| file140/body11，91–101；原 900 calls | 第92行六个 Name 的 Tuple(Store)，一次 chunk RHS→UNPACK_FIXED(6)→六个原 slot；正常6 refs+world，失败无本层 store；后续 calls/binary ops保持未知effects |
| file140/body26，285–294；原150 calls | 第291行 `self.pos_embedding[:, :T]`：receiver先求值；tuple key首项constant Slice、次项动态 upper=T；原const path与BUILD_SLICE表示分别核，最终INDEX失败/alias保持 |

只对这一份 source 准备/复用 context 一次，并只 lower 两个 exact definitions；
优先用已归档 source 三图与现有 CodeWitness 的 module/CodeType，必要时只做本 file
编译见证，记录实际次数。不能重 prepare 151 files，不执行 forward/模型或新 episode。
初始独立构造预算可固定为1 source file、每body4,000 operations、合计8,000，
达上限保留budget frontier；不借验收产物自行抬高预算。

验收保存新原图/metadata/interface、capability、输入 SHA、独立 graph+source shape+
protocol validators、预算/time/RSS，以及仍剩余的源码/状态/lifetime/runtime 缺口。
两个 body 的静态恢复通过不等于旧900/150次调用已自动升级成闭合 activation；后续
必须正式接新 body receipt 与原 code witness，未经核验不得改旧 source binding 原档。
不加大批测试 suite，不先验收一个手写 mock graph 就宣称 LeWM 已恢复。

本轮 nested/zero-arity 的构造规则与 source validator 已实现，但不以两个平面实例
冒充所有边界行为已经实测。真实 gate 与中途两个原失败均保留，见第10节。

## 8. Implemented：显式封装、验证权限与当前限制

新增 `ir/program/source_language.py` 保存薄来源记录，`analysis/source_language.py`
提供 `SourceLanguageOptions` / `SourceCodeEvidence`；三个 lowering/validation helper
复用原 Operation、CompletionResult、frame/world、slots，未改 ProgramGraph/resource/codec。
构造入口是 `PreparedSource.lower(..., profile=STRUCTURED_ENV, expand_candidates=False,
language_options=options)`。旧默认 None 的 source-program 1–4、inventory ≤8 含义不变；
它们显式拒绝 UNPACK_FIXED/BUILD_SLICE/READ_CODE_CONSTANT，不能借 enum 扩展混入新能力。

新 standalone wrapper 是 `scar.source-program/5`，新增必需的 language overlay，
overlay 版本为 `PYTHON_SOURCE_LANGUAGE_V1`，保留 exact source namespace_root。
三个 capability 是 `PYTHON_FIXED_LOCAL_UNPACK_V1`、`PYTHON_SLICE_KEYS_314_V1`、
`PYTHON_LEXICAL_LOCALS_314_V1`；没有偷偷升级当前 inventory8/partition1/checkpoint1。
Slice 当前支持 load-key 的 constant LOAD_CONST、dynamic BUILD_SLICE 与 tuple-key，
combined two-bound 路径、slice store、AugAssign、del 保留显式 frontier。
没有 comp adapter：仅修正 compiler/lexical 分类并保留原 comprehension slots，
随后仍在 comp 本体处报告作用域接口未实现，不生成外层 v。

`SourceCodeEvidence(store, composition, captured)` 只接受正规 CompositionIndex 和只读、
owned CodeWitnessStore。它查原 call_sources 的完整 CapturedCode 与 VERIFIED
CodeSourceLink、原 snapshot/definition/source，随后从既有 SHA/build/magic 已核 archive
load 原 CodeType、再次完整 describe_code 匹配。来源记录包含原 component locator、
store manifest/artifact/hash、原 inventory 收据；不接受一个任意 witness dict 或
自称 VERIFIED 的记录作为独立 code proof。不 compile、不 exec，也不证明运行中的
CodeType/constant object instance。

保存后的 v5 有两条正规读取路径：

- `SourceProgram.read_structure(document)`：公共 core codec、原 source layers、来源索引、
  payload/store order 等结构检查；不需要 live CodeType，不 replay source。
  `validate_source_program(..., verification="STRUCTURE")` 明确报告 source shape /
  code-constant provenance 未重新验证。
- `SourceProgram.from_dict(document, language_options=independent_options)`：默认
  SOURCE_REPLAY，重新核当前 exact source 与独立 owned CodeWitness、同 namespace_root，
  按固定预算构造并比对来源/原图。没有独立 options 必须拒绝，不能由保存的 provenance
  dict 自认证。两条路径均不授 runtime code-instance identity、purity 或 effects closure。

## 9. Proposed：两 body 通过后接回 inventory/composition 的最短后继

两个 v5 body 即使通过也只是新静态来源产物；**不自动覆盖旧840 bodies，不表示当前 Run
已接入新图**。下一独立 gate 应升级 partition manifest/file/body checkpoint reader，
为新 body 分配 `scar.body-construction-checkpoint/2`（必需 language 字段与 capability），
以及显式后继 inventory source wrapper；旧 checkpoint1/inventory≤8 继续严格拒绝新协议。
reader 需解码并校验 v2 语言 overlay，复用原 SG/SourceSemantics/CFG archive、exact
snapshot/context/DefinitionID，不能 prepare151 files 或拼大 JSON。版本号须与发布者
协调后分配，当前没有发布任何这种升级。

发布新不可变 manifest，只为两个新 body 写新 SHA/来源/预算收据；其余原 checkpoint
逐项引用不复制。CompositionIndex 的 typed_body/source_body_access 正规分支按新
schema 读取，namespace 必须含新 artifact/representation/root；local IDs 不跨片合并。
原 coarse world 即使 localID 同文也不因此共享 StateLocation。

随后以现 Run 完整 raw SHA、CapturedCode/source witness 重新绑定 definition→新 CP
locator/namespace，再验 call operand/return/environment/dispatch 原端口；保存原分母与
无法闭合的控制/occurrence frontiers。旧 Run/PID/activation 不借用，旧 artifact 不重写。
这是下一接线任务，当前实现未让任意外部 v5 dict 成为本 Run 的 body activation。

## 10. Verified：实际有界验收与保留的失败

没有执行 LeWM/forward/GPU，没有 prepare151文件或构建新 runtime event。
从旧 CompositionIndex.source(140) 读取原三图，核当前文件 fingerprint，只有此file
AST/symtable重新解析；PreparedSource直接持原图，不调用prepare_source。

| 原 body | 实际结果与证明范围 |
| --- | --- |
| file140/body11 | 原 gate 恢复118 operations；单次 UNPACK_FIXED 正常6refs+world、异常exception+world；按原6个 child source 的顺序绑定，原slots/partial state保持；v5结构/原图 roundtrip、独立source/CodeWitness validator、旧v4拒新协议均执行通过 |
| file140/body26 | attempt03恢复65 operations，1 READ_CODE_CONSTANT（函数co_consts直接path[1]）、1 BUILD_SLICE、原INDEX receiver/key/world Uses上的READ/PARTIAL地址；两个validator独立核source/Use/world。v5结构读取flags=false、另行独立AST/CodeWitness核验、旧v4拒新协议与缺独立options拒source proof均PASS |

原gate在body26遇到旧env validator不接INDEX地址而退出1；没有删地址或关闭集合检查。
显式语言适配保留完整env地址集合等式，并对原Opcode.INDEX/SG INDEX/Subscript、
receiver/key/world、READ/PARTIAL逐项校验。attempt02再因重复局部OperationKind import
遮蔽原全局名退出1；该可避免实现错误按单行删除修复，原失败/freeze不覆盖。

attempt03只重构body26；body11仅回读既有原档并核STRUCTURE/canonical不变，不重复其
原producer的独立source/code proof。实测wall38.21s（内部37.153s）、RSS478140KiB，
CodeWitness compile0/module-load1/descriptor-match1/source-read0，source prepare0。
这些是离线建模成本，不是LeWM性能数据。v5 SOURCE_REPLAY的全构造重放本gate未请求；
已执行的是公共core/source/protocol检查、存档结构读取及独立原AST/CodeWitness核验。

完整报告分别见
[原gate](../artifacts/experiments/first_stage_source_language_bodies_20261023/README.md)、
[attempt02](../artifacts/experiments/first_stage_source_language_bodies_attempt02_20261023/README.md)、
[attempt03](../artifacts/experiments/first_stage_source_language_bodies_attempt03_20261023/README.md)。
对照旧900/150 calls只是选择这些真实source例子的压力证据，未将这些动态调用重新绑定
新body，也不换算总体覆盖提升、执行速度或优化收益。当前inventory≤8与checkpoint1
仍拒新能力，下一步按第9节显式发布后继receipt与reader。
