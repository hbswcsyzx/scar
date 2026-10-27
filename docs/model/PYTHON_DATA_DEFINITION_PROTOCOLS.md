# Python 数据与定义构造协议（M2）

日期：2026-10-16。目标：CPython 3.14 的源语言；本机探针运行于 CPython 3.14.7。
状态：**字段级协议规格，不表示当前 lowerer 已覆盖，也不授予化简权限。**

本文给出 Python 源码如何产生定义、求值、有序使用、绑定、状态访问和隐式调用。
控制构造、异常展开、循环携带、挂起/恢复及 cleanup 的完整端口由
[Python 控制协议](PYTHON_CONTROL_PROTOCOLS.md)定义；文件、容器、对象、资源、host/device
完成和生命周期由[资源协议](RESOURCE_PROTOCOLS.md)定义。本文只引用这些接口，不另建
平行的控制流或资源事实。

整体实体和唯一事实归属见[完整程序模型](../WHOLE_PROGRAM_MODEL.md)；构造全集见
[Python 3.14 构造清单](../PYTHON314_PROTOCOL_CATALOG.md)。本规格依赖于
[Python 3.14 语言参考](https://docs.python.org/3.14/reference/index.html)和
[AST 文档](https://docs.python.org/3.14/library/ast.html)。AST 的字段排列是序列化形状，
不是求值顺序；以下每个 protocol 明确规定源顺序、特殊顺序或 deferred phase。

## 1. 分析阶段与规范输出

每个构造至少有以下互不替代的阶段。没有发生的阶段不能伪装成空操作。

| phase | 作用 | 规范输出 |
| --- | --- | --- |
| `COMPILE` | 解码、解析、future/optimization/模式选项、symbol-table 分类、代码对象及异常。 | 带源码快照和选项的 `CompilationContext`；scope/slot 分类；compile error completion。 |
| `DEFINITION` | 执行模块/类中的语句，求 decorator、base、default 等定义表达式并建立对象/环境。 | 有序 `Operation`/`Use`；Definition 与 Binding；创建的函数/类/别名对象引用；已知状态变化。 |
| `CALL_PREPARE` | 求 callable 与实际参数，展开 `*`/`**`，执行 dispatch 与参数绑定。 | call operation、逐个 occurrence 的 ordered Uses、候选 dispatch/绑定路线、失败出口。 |
| `BODY_ENTRY` | Python 函数体或其 wrapper/descriptor 实现实际开始。 | 独立 activation/Region occurrence、形式端口、函数环境和入口状态。 |
| `ACCESS_OR_UPDATE` | Name、属性、下标、运算符、容器等访问/修改协议。 | 读/写/分配/别名/逃逸、结果引用或数据、每个完成分支上的前后状态。 |
| `RESUME_OR_COMPLETE` | coroutine、generator、async generator、iterator、context manager 等继续或结束。 | 控制文档中的 typed completion/resume 及资源文档中的 readiness/ownership。 |

建议规范 facts 只保存一次：静态 `Operation` 有精确 `SourceReference`、phase、ordered
`UseID`、typed result、状态端口、分支完成和效果完整度；`Value` 区分数据、对象引用、
状态版本和局部绑定；`Region` 具有显式入口/出口与作用域；动态执行按 occurrence 连接，
不复用静态 ID 冒充同一调用。局部 Python 名的绑定采用已有 `LocalBindingValue` 与
`BindingDefinition`/`BindingRead`；状态位置只用于真实可被别名观察或修改的 namespace、
cell、object、container 和外部状态，不能把所有 fast-local 都提升成全局 World。

每个步骤可能抛异常；异常边携带该点**已经发生**的后状态，不能回滚为入口状态。若调用
或特殊方法实现无法解析，输出精确的 protocol boundary、输入、可能的状态影响和异常/完成
范围；`unknown` 不等于纯、无写、无分配或未执行。无使用者也不等于可删除，finalizer、
weakref、对象身份和外部可见历史需由资源协议约束。

## 2. 编译根、模块和作用域

### 2.1 `Module`、`Interactive`、`Expression`、`FunctionType`

`ast.parse` 的 `mode` 是编译输入，不是 AST 遍历偏好：本机 3.14.7 探针确认 `exec`
产生 `Module(body, type_ignores)`，`single` 产生 `Interactive(body)`，`eval` 产生
`Expression(body)`，`func_type` 产生 `FunctionType(argtypes, returns)`。

| root/field | protocol |
| --- | --- |
| `Module.body` | 按模块语句顺序执行；每条完成后环境可能被后续语句读取。函数/类定义只执行其定义阶段；其 body 另建 deferred Region。 |
| `Module.type_ignores` | 解析器行号/类型检查元数据，不执行、不制造 Value 或 Operation。 |
| `Interactive.body` | 依顺序执行交互单元；表达式语句的值可经 `sys.displayhook` 等宿主路径观察，须有宿主 protocol 边界。不能直接当作 `exec`。 |
| `Expression.body` | 求值一次，正常完成携带该表达式结果；编译失败和求值异常分开。 |
| `FunctionType.argtypes`, `FunctionType.returns` | `func_type` 专用签名语法。用于 legacy type comment/签名解析；不执行成普通 Python 表达式，也不产生 runtime call。 |

compile context 必须保留 source bytes/解码结果、filename、mode、flags、optimization、
future directives、Python implementation/version，以及使用的 compile/import loader。相同
AST 在不同 flags/实现下可能含义不同。`__future__` 指令按语言规则影响编译；动态
`compile`/`exec`/`eval` 创建新的 code/source identity 和 scope，不能借用调用点的 code。
编译错误是尚未运行 source 的 compile completion。

`TypeIgnore(lineno, tag)` 是 source/type-check 元数据：`lineno` 指向该 type-ignore
注释的物理行，`tag` 保留 ignore 后的原始标签文本。二者不求值、不读写程序变量，
没有 runtime result；这里的 lineno 是该节点的 canonical field，仍需在构造守恒中
逐项归属，不能与其他节点的通用位置 `_attributes` 混为一个遗漏项。

### 2.1.1 Expr 与 Pass

普通 `Expr.value` 按 `V(value)` 求值；正常结果由 expression-statement discard
协议消费并释放临时引用，然后 Fallthrough。异常/挂起和已发生状态沿对应出口
传递。释放可能触发 finalizer、unraisable hook 或不完成，依资源/frame 协议处理，
不能将其全部当普通 Raise，也不能视为无效果。Interactive 模式的显示协议可
调用 `sys.displayhook`，不能直接改为普通 discard。

被编译器识别的首个 docstring 表达式先走 docstring/definition 协议：module/class
可写 `__doc__` namespace，function docstring 属于 code/function metadata；它不是
每次 body entry 都重新执行的普通 Expr。目标 optimization 模式也影响保留方式。
源节点继续有归属，不能因 compiler 没有生成普通求值指令就从源码模型删除。

`Pass()` 没有运行字段或数据结果；基础语言行为是当前 suite 的 Fallthrough，
不创建新 binding/state version。source/编译归属仍保留。跟踪、信号等宿主干预
按环境合同处理，不能由“pass 无业务效果”推断整个 frame 无可观察交互。

### 2.2 Scope 与 Name 绑定

scope 分类在 compile phase 由整个 code block 决定，不可从某个 `Name` 节点单独猜：
`LOCAL_FAST`、`CELL`、`FREE`、`GLOBAL`、`CLASS_NAMESPACE`、`MODULE_NAMESPACE` 和
`BUILTIN_FALLBACK` 应在 source/symbol-table/code witness 可核对时区分；无法核对则
保留 scope boundary。函数内任何绑定语法通常使该名字成为整个函数 block 的 local，
即使赋值在读取之后或只在一个分支中，读取仍可能因 unbound 抛 `UnboundLocalError`。

| source construct | 读/写规则 |
| --- | --- |
| `Name(ctx=Load)` | 消费该编译上下文对应的当前绑定。普通 function local 读取 `BindingRead`，cell/free 读取 cell state，global 先查 module globals 再查 builtins。class/annotation 上下文还需按目标 compiler/code witness 确定 namespace、free cell、globals 的查找路径；仅 scope 枚举不足以决定。读取可失败，namespace/cell 可被其他代码改动。 |
| `Name(ctx=Store)` | RHS 已求值后更新所在 binding。local 建新 binding version；global/nonlocal/class/module 写入对应 namespace/cell state。不同分支的 `BOUND`/`UNBOUND` 合流由 CFG 输入推导，不能由源码标签宣称。 |
| `Name(ctx=Del)` | 按 scope 删除 binding；删除可失败，后续读变成未绑定。local 与 global/cell deletion 是不同状态域。 |
| `Global(names)` | compile-time scope 声明；没有 runtime 名称赋值步骤。必须遵守语法位置约束；声明使 block 内相应 Name 绑定走 module globals。 |
| `Nonlocal(names)` | compile-time 向最近 enclosing function scope 解析已有 cell；没有该 cell 是 SyntaxError。执行读写作用于 cell，而非新 local。 |

Python 函数 fast-local 绑定改变不意味着其 object payload 改变；`x = y` 一般只是令
`x` 的绑定指向 RHS 的引用/数据。相反，`global_x = y`、`cell_x = y` 更新可由其他
activation 观察的位置，需进入状态接口。引用目标的可变性、身份、内容状态和 lifetime
分开表示。闭包捕获 cell 的身份在函数对象环境中固定，cell 内容可以跨调用改变。

class body 中一个 free Name 可以先查 prepared class namespace，再读 enclosing
cell；本机探针中 outer x=3、prepared namespace x=9，class 的 y=x 得到 9，
对应 `LOAD_LOCALS` / `LOAD_FROM_DICT_OR_DEREF`。method function 的 free Name
则不因此捕获 class namespace。应复用 `symtable` 的编译作用域与 `dis` 的版本化
指令/位置见证，保留真实 lookup 协议，不能自行把所有 free Name 简化为直接 cell read。
独立证据见 `artifacts/experiments/b1_call_operands/model_stage1_audit/class_namespace_free_probe.json`。

## 3. 函数、lambda 和参数字段

### 3.1 `FunctionDef` 与 `AsyncFunctionDef`

函数定义有 compile、definition、call 和（可能的）resume 阶段。3.14.7 本机事件探针
观察到：装饰器表达式按源码从上到下求值，随后 defaults 求值，再按装饰器从内到外
应用；定义时没有执行 body。无 `from __future__ import annotations` 时，参数和返回
注解也没有在定义事件中执行，第一次读取函数 `__annotations__` 才触发懒求值；future
annotations 改变为字符串化模式。规则见 [function definitions](https://docs.python.org/3.14/reference/compound_stmts.html#function-definitions)
和 [annotations](https://docs.python.org/3.14/reference/compound_stmts.html#annotations)。

| AST field | 正确 phase 与规则 |
| --- | --- |
| `name` | 最终 decorator 应用完成后，当前 namespace 绑定的是 decorator 返回对象；未装饰时是新 function object。body Region 仍属于原 code object。不能把名字绑定的 wrapper 与被装饰函数体等同。 |
| `args` | compile 阶段生成完整签名；definition 阶段绑定 defaults、annotations thunk、闭包 cell 和 globals 环境；call phase 才消费 actuals/defaults 建 frame。见 §3.2。 |
| `body` | 编译成代码/Region；普通 def 的 body 等 callable 实际进入后执行。`return`/异常出口由控制协议定义。静态存在不表示定义时执行。 |
| `decorator_list` | 表达式从上到下求值、各次调用及其效果/异常均显式化；返回的 decorator 按列表反向应用。decorator 可替换函数、构造 wrapper、返回非 callable 或抛异常。 |
| `returns` 与 `arg.annotation` | 3.14 默认 deferred annotation：建立可懒求值的 annotation protocol，在 `__annotations__`/`annotationlib` 读取时按注解的源顺序计算并缓存。`from __future__ import annotations` 按其编译模式提供字符串注解，不运行原注解表达式。注解读取自身可抛异常/观察环境。 |
| `type_comment` | 注释/source metadata；按所选 parser/type-checker 规则记录，不当作 runtime expression。 |
| `type_params` | generic scope 的有序参数声明；创建 type parameter object 与 annotation scope。bound/constraints/default 按 §4 惰性求值。 |

装饰器表达式、default、函数对象创建和最终名称绑定中任意点失败，都会截断后续定义
阶段；之前已经发生的表达式副作用保留。重复执行同一 `def` 语句会重新求 defaults、
建立函数对象并调用 decorators，不能按同一源码位置合并成单个定义 occurrence。

`AsyncFunctionDef` 同样在 definition phase 创建 async function object，不执行 body；
调用返回 coroutine，body 在 await/scheduler 驱动时进入。含 `yield` 的 `FunctionDef`
调用返回 generator，body 在首次 resume 才进入；含 `yield` 的 async function 返回
async-generator。区分原始定义 kind、call 返回值和 body activation；resume、close、cancel
与异常传播依[控制协议](PYTHON_CONTROL_PROTOCOLS.md)。

### 3.2 `arguments`、`arg`、defaults 与 call binding

`arguments` 是签名结构，不是按 `_fields` 顺序依次求值的语句。`posonlyargs` 和 `args`
连接为位置参数；`vararg` 接收 `*args` pack；`kwonlyargs` 与 `kw_defaults` 按相同下标
配对，`None` 表示该 keyword-only formal 必需；`kwarg` 接收剩余 keywords。`defaults` 是
位置参数列表尾部的一段默认值，按 positional formal 尾对齐，不能按从参数 0 开始对齐。
`arg.arg` 是名字，`annotation` 走 §3.1 deferred annotation phase，`type_comment` 是
source/type-check 元数据。

definition 执行时，各 defaults 表达式在源码参数顺序中只求值一次，结果保存在函数对象
的 defaults/kwdefaults 状态里；后续调用共享该默认对象，不重新执行表达式。调用绑定按
Python 签名逐项映射 actual：pos-only、positional、var-positional、keyword-only、
var-keyword 的规则和重复/缺失参数错误必须保留。默认路由引用 defaults state，不得把
源码 default expression 当成每次 invocation 的 actual。

源码 `*expr`/`**expr` 未被 runtime 展开事实或完整静态 protocol 精确化时，参数绑定只能
标 incomplete/conditional，不能虚构 pack 的成员。`f(x, x)` 有两个不同有序 Use，即使
两个 Use 最终是同一个对象。底层 dispatch 可能是 wrapper、descriptor、bound method、
`functools.partial`、builtin 或自定义 `__call__`；签名匹配本身不证明本次目标/环境。

### 3.3 `Lambda`

`Lambda.args` 采用同一签名/default/annotation 规则；lambda 默认表达式在 lambda 创建时
求值一次，body expression 延至调用。`Lambda.body` 是 expression result，不是 implicit
statement list；call completion 携带该 result。lambda 的代码 scope、closure cells、
globals 与函数对象 environment 必须保留；源码无显式名字不表示无 identity 或无环境。

## 4. 类型参数与别名：`TypeAlias`、`TypeVar`、`ParamSpec`、`TypeVarTuple`

Python 3.12+ 的 type parameter list 创建独立 annotation scope；Python 3.14 的 bounds、
constraints、defaults 与 type alias value 可懒求值。3.14.7 探针观察：generic function
定义和 `__type_params__` 读取未触发 bound/default/注解事件；首次读取 TypeVar
`__bound__`、`__default__`、函数 `__annotations__` 各自触发相应表达式；type alias
定义未触发 value，首次读 `__value__` 才执行并缓存。细节以
[type parameter lists](https://docs.python.org/3.14/reference/compound_stmts.html#type-parameter-lists)、
[type aliases](https://docs.python.org/3.14/reference/compound_stmts.html#type-aliases) 和
[annotation scopes](https://docs.python.org/3.14/reference/executionmodel.html#annotation-scopes)
为准。

| node/field | protocol |
| --- | --- |
| `FunctionDef.type_params`, `ClassDef.type_params`, `TypeAlias.type_params` | source-order type parameter definitions与各自 scope；同名参数不能跨 scope 合并。引用按 annotation-scope name resolution。 |
| `TypeVar.name` | 在当前 type parameter scope 声明 type variable。 |
| `TypeVar.bound` | bound 或 constraints 表达式 thunk；仅属性访问/annotation evaluation 等触发点执行。tuple-shaped constraints 仍要保留每个成员及顺序。 |
| `TypeVar.default_value` | 3.13+ default thunk；访问默认属性时执行，未设置 sentinel 和显式 `None` 要区分。 |
| `ParamSpec.name`, `default_value` | 声明可承载参数规格的 type parameter；default 的懒求值与未设置状态单独记录。 |
| `TypeVarTuple.name`, `default_value` | 声明可变长类型参数；tuple packing/unpacking 由 typing/type checker protocol 处理，不是普通 Python `*args`。 |
| `TypeAlias.name` | Store-context 的 alias name，执行 type statement 时绑定 TypeAliasType 对象。 |
| `TypeAlias.value` | alias 的 deferred value thunk；首次访问 `__value__` 等求值时执行，可能抛异常并观察 annotation scope。 |

Python 的 `typing.TypeVar(...)` 是普通 runtime call，不能因返回对象类型相同而套用
AST `TypeVar` 声明协议。上述语义只表达 runtime type object 的建立和 deferred value；
不能把 type checker 的静态兼容关系当作程序数据相等、接口调用或纯性证明。

## 5. 类定义与类体

`ClassDef` 先进行 header/definition protocol，再执行 class body 并创建 class object，
最后应用 decorators。3.14.7 探针的可复现 `type` 子类路径顺序为：decorator expressions
从上到下；base/metaclass/keyword expressions；`Meta.__prepare__`；class body；
`Meta.__new__`；`type.__new__` 内的 descriptor `__set_name__` 和 base
`__init_subclass__`；metaclass 初始化；decorators 自下而上。该具体顺序不能误写成
所有用户 metaclass 都必然调用这些 hooks；自定义 metaclass 可覆写/跳过/重排/抛错。
参考 [class definitions](https://docs.python.org/3.14/reference/compound_stmts.html#class-definitions)。

| AST field | protocol |
| --- | --- |
| `name` | class object 创建且 decorators 成功后绑定 decorator 最终返回值。 |
| `decorator_list` | decorator expression 从上到下求值；class construction 后反向应用，结果可能替换 class。 |
| `bases` | 每个 base expression 按源码顺序求值；非 type base 可触发 `__mro_entries__`；MRO 与 metaclass 选择可能失败。每个 implicit protocol call 都是有序 Use/状态/异常端口。 |
| `keywords` | keyword value 按源码序求值；`metaclass` 参与 metaclass 选择，其他 class keywords 转交 metaclass construction。不能把 keyword AST 字段顺序当表达式顺序。 |
| `type_params` | generic class type parameter/annotation scope，按 §4 处理。 |
| `body` | 在 metaclass `__prepare__` 提供的 namespace 中执行一遍。namespace 可能是自定义 mapping；class-scope lookup/Store、方法定义、descriptor 值、类 annotations、类语句的副作用和异常都接到这个状态。 |

header 跨字段复用 §9 的 argument-preparation 协议：先准备 `bases` 中的位置与
starred 部分（逐项求值并展开），再准备 `keywords` 的命名值与 `**` mapping。
合法源码即使将 keyword 写在 starred base 前，也不是全 header 的文本求值顺序。
本机 `class Header(metaclass=meta(), *base_pack()): pass` 先执行 base_pack，后求
metaclass expression。每部分内部保持语言顺序，mapping 展开/重复名/非法 key
和迭代失败保留各自异常及后态；完成 header 准备后才走 base resolution、metaclass
selection/prepare 与 body。非法语法先在 compile phase 拒绝，不制造部分执行。

若 metaclass 路径实际调用 `type.__new__`，descriptor `__set_name__` 和基类
`__init_subclass__` 可在 class creation 期间发生；Metaclass `__call__`/`__new__` 或
decorator 可改写/替换类，需为具体已证实的边建证据。类体创建的普通方法不会将 class
namespace 当 lexical closure（`__class__` cell 是专门例外）；运行期间的属性查找走类
MRO/descriptor，不等同 class body 的 Name lookup。

## 6. Import 与模块初始化

Import 是代码执行、loader dispatch 与 binding 更新的组合协议，不是静态别名重写。
按 [import system](https://docs.python.org/3.14/reference/import.html) 记录 loader、
finder、`sys.modules`、package initialization、module body、fromlist 和回滚/失败状态。

| field | protocol |
| --- | --- |
| `Import.names` / 每个 `alias.name` | 按 alias/source 顺序请求 dotted module；从缓存/查找器/loader 得到或初始化 module。父 package 初始化可能先发生，执行模块体有任意可见副作用。 |
| `alias.asname` | 决定当前 scope 新 binding。`import a.b` 默认绑定顶层 `a`；`import a.b as x` 绑定请求的 submodule 到 `x`。 |
| `ImportFrom.module`, `level` | 使用当前 package context 计算 absolute/relative target；越出 package、缺 module、循环 initialization 都有异常/部分状态路径。 |
| `ImportFrom.names` / `alias` | 先完成 package/module 加载，再从属性/子模块解析每个导出并写入目标名字。缺属性时的 submodule fallback 是 import system 行为。 |
| `from m import *` | `__all__` 或默认公开名规则可能依赖运行时模块状态；逐项绑定而非一条“wildcard 已解开”的断言。未解析 export 时保留边界。 |

失败时已初始化的父 module/side effect 不必然被整体撤销；name binding 何时写入按
实际 import protocol 的阶段分别记。循环 import 可以读到部分初始化 module。`importlib`
调用、`__import__` 覆盖、meta path finder、path hooks、namespace packages、动态
`exec` 都是可能 dispatch；无法证明 loader/模块 body 时不可把 filename 或同名 export
作为 source identity。

## 7. Name、Attribute、Subscript 与 Slice

以下表达式按 Python 的 left-to-right 规则求 primary，再按具体操作协议调用；每个结果
可为任意 Python object。对 unknown descriptor/index/operator 保留 bounded boundary。

### 7.1 `Attribute(value, attr, ctx)`

1. 求 `value` 一次；若异常则不 lookup。
2. `Load` 进行 attribute lookup：`__getattribute__`、实例/class dict、data/non-data
   descriptor、MRO、必要时 `__getattr__`。每次特殊方法/descriptor 是潜在 callback、状态
   访问或异常点；函数 descriptor 还可能创建 bound method。
3. `Store` 求 RHS 后求 owner，调用 descriptor `__set__` 或目标 `__setattr__`；
   `Del` 求 owner 后走 `__delete__`/`__delattr__`。行为不由 attr 字符串推断。

`ctx` 只选取 load/store/delete 协议；`attr` 是静态字符串，不是要读取的 Name。
属性值可来自 descriptor 动态计算，不必在对象字典中有同名字段。属性写可能有全局、
I/O、弱引用、注册/缓存等外溢影响；只有精确实现协议才可缩小 footprint。

### 7.2 `Subscript(value, slice, ctx)` 和 `Slice(lower, upper, step)`

先求 `value`，再求 `slice` 表达式。对 `Slice`，依次求非空 `lower`、`upper`、`step`，
构造 slice key；缺省边界保留缺省 sentinel。多维 `obj[i, j]` 通常以 tuple key 表达，
不是两个独立的 `__getitem__`。Load 调用 `__getitem__`；Store 在 RHS 和 target key 求值
后调用 `__setitem__`；Del 调用 `__delitem__`。对 class subscription 还可能用
`__class_getitem__`。这些方法可修改对象、alias、内容和外部状态，也可 raise。`slice`
的 selector 是值，不能未经类型/协议证明就等同静态数组 footprint。

## 8. 绑定更新：Assign、AnnAssign、AugAssign、Delete、NamedExpr

赋值规则按 [assignment statements](https://docs.python.org/3.14/reference/simple_stmts.html#assignment-statements)、
[annotated assignment](https://docs.python.org/3.14/reference/simple_stmts.html#annotated-assignment-statements)、
[augmented assignment](https://docs.python.org/3.14/reference/simple_stmts.html#augmented-assignment-statements)
定义。`Store`/`Del` context 不决定 evaluation order。

### 8.1 `Assign(targets, value, type_comment)`

1. 先完整求 `value` 一次。
2. 再按 `targets` 列表从左到右依次写入；同一结果可被多个 target 绑定。
3. target 为 tuple/list pattern 时，按 unpacking protocol 取得元素并递归写 target；迭代、
   长度检查和元素读取都可失败。失败前已写的 target 保留，不原子回滚。
4. Name target 产生新 binding；Attribute/Subscript target 执行 §7 Store；星号目标按
   unpack 协议接收剩余元素。`type_comment` 只属于 source/type-check metadata。

AST `targets`/`value` 字段顺序不能直接生成 Use 顺序。多个 target 写副作用有序且可能
中途失败。相同 RHS reference 不会合并 target BindingDefinition occurrence。

### 8.2 `AnnAssign(target, annotation, value, simple)`

若有 `value`，先按赋值规则求值/写入。3.14 annotation 走 deferred annotation scope；
在 module/class scope，只有 simple Name target 的 annotation 加入该 scope 的
`__annotations__`；attribute/subscript target 的 annotation 不执行、不存入该映射。函数
local annotation 不执行且不写 runtime `__annotations__`，但该名字仍被 compile scope
分析视为 local。3.14.7 探针验证 module/class simple-name annotations 到首次映射访问才
求值；attribute/local annotation 表达式不运行。不同 target 不得只因 field 中存在
`annotation` 就制造 annotation expression call。

`simple` 是编译选择 0/1，不求运行真值：只有未加括号的 Name target 的 simple=1
进入 simple-name annotation 收集；括号 Name 的 simple=0 不因 target 仍是 Name
而加入该映射。无 RHS 的 Name 不执行值赋值，不建立一个等于 None 的绑定，也不
覆盖已有值；它在函数中的 compile-local 归属和 module/class 的 annotation setup
分别保留。

无 RHS 的 Attribute 仍求 owner 一次，无 RHS 的 Subscript 仍依序求 owner/key，
但均不调用最终 getter/setter。组成 owner/key 的内部表达式仍可 lookup、call、
抛异常或产生效果；不能因 annotation 不求值而删掉整句。annotation setup/惰性
环境的建立也按对应 scope/compiler 协议保留。本机探针已确认该目标求值差别。

### 8.3 `AugAssign(target, op, value)`

先将 target 定位一次；Name 读一次当前绑定，Attribute 一次求 owner 并读属性，Subscript
一次求 owner/key 并读元素；然后求 RHS；再执行 `__i<op>__`，必要时按二元运算规则 fallback
至 forward/reflected operator；最后把结果写回**同一个已定位的 target**。3.14.7 probe
观察 attribute primary/read 仅一次，然后 RHS、`__iadd__`、write。与 `a = a + rhs` 不同，
augassign 的 target expression 不重复求值，in-place method 可先修改旧对象再 raise。
此时异常完成必须携带部分 mutation 的真实 post-state。

### 8.4 `Delete(targets)` 与 `NamedExpr(target, value)`

`Delete` 按 targets 顺序逐个求定位/删除；前项已删除后，后项失败不回滚。Name 删除
binding；attribute/subscript 调各自 `__delete__`/`__delitem__`。`NamedExpr` 先求 value，
再写目标并返回该值；在 comprehension 内其 target 绑定到规定的 containing scope，不能
当作 comprehension iteration local。Walrus target 结构限制与位置限制在 compile phase
验证；不合法是 SyntaxError。

## 9. Call：表达式、展开、绑定、dispatch、entry

调用协议不是单一 `CALL` 节点。语言参考：[calls](https://docs.python.org/3.14/reference/expressions.html#calls)。
positional/starred **表达式求值**与 iterator **展开**是不同步骤。即使源码把 named
keyword 写在星号前，star 表达式也在 keyword expression 之前求值；但不能据此
断言 iterable 一定立即展开。原定义协议 probe 的 star_expr 返回 list，仅记录了
构造列表的事件，没有观察其 iterator 协议，不能证明“迭代在 keywords 之前”。

| field | protocol |
| --- | --- |
| `Call.func` | 先求 callable expression 一次；Attribute/Name 等自有其访问 protocol。实际 callable 可能是函数、bound method、descriptor result、builtin、partial、class/metaclass 或 `__call__` object。 |
| `Call.args` | 按 positional-argument 规则求普通与 starred expressions；求 iterable 与逐项展开分开建模，展开阶段按目标 compiler/call-adapter 路线确定，见下表。每个 actual occurrence 有独立 Use；pack 不能按对象相等去重。 |
| `Call.keywords` / `keyword.arg` | Keyword values 按语言规定顺序求值。普通 `arg` 是显式 keyword 名；`arg=None` 是 `**mapping`。mapping 的 `keys`/读取、string-key 校验、重复名冲突和 pack 顺序可执行 user protocol。 |
| dispatch/binding | 先完成 argument expression/expansion，再由运行时目标绑定形参；缺参、多余、duplicate、pos-only 冲突等可在 body entry 前抛 `TypeError`。不产生 body activation。 |
| body entry | 只有本次运行确实进入匹配的 function code/frame 才连接 callee Region；绑定完成不证明目标身份、globals/defaults/closure 或效果。 |

本机 CPython 3.14.7 独立自定义 iterable 探针记录 `star_expr/iter/next/kw/body`，
并用 compiler/dis 见证区分路线：

| 被测 call 形式 | 实际阶段与失败影响 |
| --- | --- |
| `fn(*star(), named=kw())` | 先 star expression、kw，随后 CALL_FUNCTION_EX 路线展开 iterable，再 body。kw 失败不执行 iter；iter/next 失败时 kw 已发生。 |
| `fn(0, *star(), named=kw())` | prefix pack 的 LIST_EXTEND 在 kw 之前展开；iter 失败则不执行 kw。 |
| `fn(*star(), 0, named=kw())` | 后续 positional pack 使展开在 kw 之前。 |
| `fn(*star(), *other(), named=kw())` | 为多个 starred positional 依次构造 pack，实际展开发生于 kw 前；前项失败截断后项。 |

16 个正常/失败案例见 `model_stage1_audit/closure/call_star_probe.py` 与对应 JSON。
这些路线约束目标版本，不将四个样例推广成所有 callable/实现的相同展开策略；
tuple/list 快路、descriptor/call adapter 与 `**` 合并也按实际 compiler/协议接口
连接。实现应复用编译见证及运行 evidence，不按 AST field 顺序或“star 立即迭代”
口号补造状态/异常边。函数绑定仍等待该次参数准备完成，之前的部分效果不回滚。

无序 AST 字段、同一个 object token、同 code 或源中同名函数都不足以将一次动态 call
认定为某个定义。`*`/`**` 可能调用 iterator/mapping methods 并在 body 前失败；重复
keyword merge 也可能前置失败。若采用静态 conditional binding，所有条件（raw target、
code/source、defaults state、完成展开、帧映射、环境）要明列，且不称为 observed entry。
async/generator calls 的 host return 是 coroutine/generator reference，不是函数 body 的
最终返回值或完成；见控制/资源协议。

## 10. 运算与短路选择

### 10.1 `BinOp(left, op, right)`、`UnaryOp(op, operand)`

`BinOp` 左 operand 先求，再求右 operand，然后按 `op` 对实际类型进行 forward/reflected
dispatch。binary special method 可返回 `NotImplemented`、修改状态或 raise；子类优先规则
和 numeric tower 会影响选择。`MatMult` 等 Python 运算符与 NumPy/Torch operator 行为
之间须有版本化实现证据，不能按符号假设内核、shape、device 或 purity。

值上下文的 `UnaryOp` 先求 operand。正负/反转运算走 `__pos__`/`__neg__`/`__invert__`；`not` 先做
truth test（`__bool__`，否则 `__len__`），再生成 builtin bool。Truth method 可调用/改状态/
raise。运算符 AST marker 是所选协议参数，不单独制造运行时值。

直接条件上下文另有 `T(Not e; true, false) = T(e; false, true)`，按 continuation
取反，不先生成 V(e) 再无条件求真。V(Not e) 仍求 operand 的值、Truth 后产生
bool；两者不得合并。本机 a 恒假时，值上下文 `not (a and b)` 会调用 a 的 bool
两次，直接 `if not (a and b)` 一次。该规则只属于本次条件求值，不授予跨语句
缓存 truth 的权限，见控制分册 §0.2。

AugAssign 的 inplace precedence 与 fallback 见 §8.3。非 builtin/未核对的运算实现，效果、
身份、数据转换和异常默认为 incomplete；不能只按两个输入 value 相同合并结果。

### 10.2 必须保留的 lazy operators

虽非本文目标字段，整个数据协议需特别区分：`and`/`or` 逐项 truth-test、短路并返回最后
求值的 operand（不是强制 bool）；`IfExp` 只执行一个 arm；comparison chain 每个中间表达式
最多求值一次，前序比较的 truth 值决定是否继续，最后比较结果可以是非-bool object。
`is`/`is not` 执行身份比较不调用用户比较方法；`in`/`not in` 走 containment/iteration
protocol；`==`/ordering 走 rich comparison，可返回可再 truth-test 的对象。分支 path 与
truth/compare 异常端口由[控制协议](PYTHON_CONTROL_PROTOCOLS.md)规定。

## 11. 容器和字面量

| AST family/field | evaluation/dispatch |
| --- | --- |
| Load-context 的 `List.elts` / `Tuple.elts`，以及 `Set.elts` | 按源顺序求各 element；`Starred` 展开 iterable。建立相应 container reference/identity；set hash/equality、元素迭代和分配可触发实现协议/异常。 |
| `Dict.keys`, `Dict.values` | 成对按源顺序执行：每项先求 key，再求 value；`None` key 表示 `**` mapping expansion，需走 mapping protocol。插入期间 hash/equality 可 callback/raise，后续重复 key 会改变最终 mapping state。 |
| `ListComp`/`SetComp`/`DictComp` | 建 implicit comprehension scope 和迭代 Region；target/filter/result 的重复次数与路径见控制协议。Dict 项仍 key-before-value。Comprehension iteration target 不泄漏；walrus target 有特殊 containing-scope 规则。 |
| `GeneratorExp` | 外层 iterable 及 outer iterator 在 generator 建立时求值；生成器主体和后续 iterator/filter/yield 延至迭代/resume。不能以 generator object 的创建声称其所有元素已计算。 |
| `Constant(value, kind)` | 精确保留解析出的 None/bool/int/float/complex/str/bytes/Ellipsis 等 literal 和源位置/前缀信息。常量折叠、interning、identity、对象复用属于 compiler/runtime 行为；相同 literal spelling/value 不自动证明同一对象或可跨次缓存。 |

`List.ctx`、`Tuple.ctx`、`Starred.ctx` 选择不同协议，不是统一构造容器：

| ctx | 具体连接 |
| --- | --- |
| List/Tuple Load | 求各 elts 值/展开并创建结果容器。 |
| List/Tuple Store | 作为 target pattern 消费 RHS，执行 unpack 与递归 target Store；不读取被赋值名称、不构造 target 容器。每个 unpack 单元按目标实现先做所需元素/长度检查，再按目标顺序更新；已完成的其他 target 更新在后来失败时保留。 |
| List/Tuple Del | 按 elts 左到右递归删除 target；`del (a,b)` / `del [a,b]` 不创建容器、不读元素值，也不从 iterable 解包。Attribute/Subscript 子 target 才求其 owner/key；失败截断后续删除。 |
| Starred Load | 在合法 call/container 的展开位置求 value，迭代阶段由所属协议决定；Call 见 §9，不能统一成求 value 后立即迭代。孤立或其他非法位置由 compile 拒绝。 |
| Starred Store | 仅在合法 unpack target 中接收剩余元素，再按 value 子 target Store；约束及失败端口属于 unpack 协议。 |
| Starred Del | 不是合法删除 target；compile 拒绝，不虚构展开/删除执行边。 |

Container result 是 Python reference，内部元素关系/别名和后续 mutability 应由资源协议
建模。构造异常可能发生在部分元素已求值之后；将整个 literal 视为原子纯 constant 会
丢掉调用、分配、hash/equality、异常与身份。

## 12. Formatted strings 与 template strings

### 12.1 `JoinedStr` / `FormattedValue`

`JoinedStr.values` 按文本顺序组合 literal strings 与 formatted expressions。对
`FormattedValue(value, conversion, format_spec)`：先求 `value`；若有 `conversion`，执行
`str`/`repr`/`ascii` 转换；随后求 nested `format_spec` 表达式；最后调用格式化协议
`__format__` 并组合字符串。3.14.7 probe 对 `f"{value()!r:{width()}}"` 观察到
value-expression、`repr`、format-spec-expression 的顺序。conversion 与 format 方法可
有副作用/异常。调试文本或 literal pieces 仍需要 source ownership。

### 12.2 `TemplateStr` / `Interpolation`

`TemplateStr.values` 交错普通字符串与 `Interpolation`。构造时立即求 interpolation 的
`value` 和嵌套 format-spec 值，但把结果、源码表达式文字、conversion 和 format spec
保存在 Template/Interpolation 对象；它不会在构造点调用该 value 的 `repr`/`str`/`format`。
3.14.7 probe 观察 t-string construction 只记录 value 和 width expression，结果为
`string.templatelib.Template`，并保留 `Interpolation.expression`, `.conversion`,
`.format_spec`, `.value`。后续消费者如何格式化是另一个 call/iteration/side-effect
protocol；template 本身不能当成已格式化字符串或纯文本 constant。见
[formatted and template string literals](https://docs.python.org/3.14/reference/expressions.html#f-strings)。

## 13. 构造守恒与拒绝规则

M2 对每个 source atom 需要唯一语义归属；支持节点必须输出有序 uses、结果/绑定、状态、
控制/异常、生命周期或明确可证明不适用的端口。仅有 AST label、Operation 分类、未知
effect 字符串、OPAQUE 父节点或新增 region 不能算内部已理解。对于本规格列出的每个 field：

1. 保留精确 source/version/compile context 与其 owning scope；不按 AST `_fields` 做通用执行。
2. 明确 phase、实际求值顺序、短路/deferred edge 和隐式协议目标；重复 occurrence 不去重。
3. 所有可能的 user dispatch、部分写入、异常及后状态都连接；未建模行为设为 bounded
   boundary，而不是空 reads/writes/`pure`。
4. 不从名字、注释、类型注解、函数签名、静态 candidate 或观察缺失推导运行目标、常量、
   完整效果或无异常。
5. 单独记录静态定义、每次执行 occurrence、对象身份、绑定版本、数据版本、位置状态和
   资源完成；彼此不同，不靠相同 `ValueID` 或引用替代。
6. Native/extension protocol 如未精确版本化，不以 Python wrapper body 推断其内部；保留
   入/出端口、可能状态/异常和资源 boundary，并阻止越界化简。

支持范围需有逐字段正反例、动态/静态两侧映射及历史 wire replay。本文仅定义 M2
协议；自动覆盖和 M3/M4/M5 completeness 仍须各自验收。整体化简前置条件见
[整体模型计划](../WHOLE_PROGRAM_MODEL_PLAN.md)。

## 14. 本机探针与外部依据

轻量语言探针仅核对 CPython 3.14.7 的实际观察，不是源码解释器的完整正确性证明，也不
执行 SCAR 或 LeWM：

- [`probe.py`](../../artifacts/experiments/b1_call_operands/model_definition_protocols/probe.py)
  和 [`probe-output.json`](../../artifacts/experiments/b1_call_operands/model_definition_protocols/probe-output.json)：AST modes/字段、definition/call/lazy annotation/type parameter、class hook、call expansion、assignment、async/generator 和 f-/t-string 的可复现事件。
- Python 版本：`3.14.7 | packaged by conda-forge | (main, Sep 2 2026, GCC 15.3.0)`。
- 命令：`source /home/zyf/miniconda3/etc/profile.d/conda.sh && conda activate lewm && python artifacts/experiments/b1_call_operands/model_definition_protocols/probe.py`（在 worktree 根目录执行，输出重定向到 `probe-output.json`）。
- 规则核对：官方 [compound statements](https://docs.python.org/3.14/reference/compound_stmts.html)、
  [expressions](https://docs.python.org/3.14/reference/expressions.html)、
  [simple statements](https://docs.python.org/3.14/reference/simple_stmts.html)、
  [execution model](https://docs.python.org/3.14/reference/executionmodel.html)、
  [import system](https://docs.python.org/3.14/reference/import.html) 和
  [AST](https://docs.python.org/3.14/library/ast.html)。语言参考 3.14 文档说明语言规则；
  具体 CPython 3.14.7 packaging/version 事实由本地输出给出。探针不证明任意 implementation
  或自定义 hook 的同一事件顺序。
