# Python 3.14 数据与定义协议

本文描述纯静态建图所需语义；现有前端仅覆盖子集，规则列出不表示已实现。
统一实体见 [MODEL](../MODEL.md)，范围见[协议目录](../PYTHON314_PROTOCOL_CATALOG.md)。
只生成 canonical Operation、Value、StateLocation、Region、Resource 及原端口关系。
不执行目标定义、导入、decorator、annotation 或函数体，不要求运行 CodeWitness。

## 1. 来源、阶段与状态

源码字节、编码、路径、版本、解析模式、future/优化选项和词法作用域是静态输入。
解析或编译约束失败与运行时可能抛异常分开；不合法源码不生成假正常 body。
定义、参数准备、body、属性访问和恢复是不同阶段，以 Region/接口有条件连接。
Operation 保留有序 Uses、结果、正常/异常状态端口及来源；同值实参也不合并 Use。
局部绑定用 SSA/绑定关系；可别名观察的 globals、cell、对象与容器用 StateLocation。
后态沿各 CFG 边传递；前序副作用不因后续异常回滚，UNKNOWN 不等于无读写。
符号创建站点只描述可能的新对象，不生成实际对象身份或动态发生记录。

## 2. 模块、根与名字

Module body 是有序语句 Region；遇到 def/class 时连接其定义阶段，非立即执行函数体。
Expression 根返回表达式结果；Interactive 的展示接口与普通 exec 模式分别保留。
FunctionType 是专用签名解析形式；注释、TypeIgnore、Pass 不制造目标计算。
Global/Nonlocal 与 symtable 共同确定 slot；未绑定不同于绑定 None。
函数局部、module namespace、class prepared mapping、free cell 和 builtins 查找不可混同。
类体的 free-name 查找可先经 prepared namespace；方法通常不捕获整个类 namespace。
环境来源不明时保留候选查找与异常；名字相同不证明引用同一对象。

## 3. 函数、闭包与 lambda

FunctionDef 的定义表达式与 body 分开；函数体以原定义 ID 引用，不复制到创建操作。
装饰器表达式从上到下求值，defaults 随后按定义规则准备，再创建函数并反向应用装饰器。
最终名称绑定 decorator 返回对象；它可能是 wrapper、非 callable 或失败结果。
任何失败截断后续步骤，保留此前状态；重复到达 def 的创建不能静态合并成一个对象。
嵌套函数捕获 cell 引用而非当前内容快照；body 读取的是其调用路径上的 cell 状态。
globals、builtins、defaults、kwdefaults 与 closure 的关系引用创建输入或明确的字段状态。
不为分析器查询函数字段虚构目标程序读操作，也不把定义时字段永久绑定到未来调用。
Lambda 采用原 body 表达式 Region：表达式求值后连接返回端口，不伪造 FunctionDef/Return AST。
AsyncFunctionDef 同样只创建 callable；coroutine/generator 的 body 阶段见[控制协议](PYTHON_CONTROL_PROTOCOLS.md)。

## 4. 签名、默认值与 annotations

posonlyargs 与 args 组成位置参数；defaults 只尾对齐这组参数，非从第一个形参开始。
kwonlyargs 与 kw_defaults 按索引配对；缺默认的标记不同于显式 None。
vararg/kwarg 接收剩余位置/关键字 pack；重复、缺失和不合法参数保留 TypeError 分支。
defaults 表达式在定义到达时求值，结果由函数字段状态持有；调用不重算默认表达式。
后续重绑 defaults 或修改默认对象必须经状态依赖，不能永远路由至最初定义值。
Python 3.14 的函数、模块、类 annotations 按其惰性注解协议建立独立求值 Region。
读取/求值接口、缓存与环境是条件状态；future annotations 的字符串化模式单独表示。
函数局部注解通常只参与作用域分析；属性/下标注解不当作模块名称注解存储。
AnnAssign 的 RHS/store 与注解阶段分开；无 RHS 的复杂 target 仍按语言规则求 owner/key。
泛型 type_params 建 annotation scope；bound、constraints、default 和 alias value 各自延后求值。
TypeVar、ParamSpec、TypeVarTuple 的未设标记不等于 None；TypeAlias 名称与 value Region 分开。
运行 typing 构造调用不是同名 AST 声明；未实现的注解访问/类型参数协议明确保留待实现。

## 5. 类定义

decorator 表达式先准备；header 的位置/星号 bases 与 keyword/`**` 按调用准备规则展开。
header 准备后连接 base resolution、`__mro_entries__`、metaclass 选择及 `__prepare__` 接口。
在 prepared mapping 中展开类体 Region；Name 读写可调用自定义 mapping 并失败。
类体定义方法只创建函数；方法的调用体另行引用，`__class__` cell 有独立绑定关系。
metaclass construction 与 decorators 之后才写最终类名；不能按类名直接选定类型身份。
若适用 type.`__new__` 路径，保留 `__set_name__`、`__init_subclass__` 等隐式调用及次序。
自定义 metaclass 可改变该路径；未知实现保留候选与 effects，不宣称这些 hook 必然执行。

## 6. Attribute、Subscript 与运算

Attribute 先求 owner；Load 连接 `__getattribute__`/descriptor/必要 `__getattr__` 与异常。
Store/Del 使用属性写入/删除协议，不等同字典 slot 更新；动态 descriptor 目标可 UNKNOWN。
Subscript 先 owner 后 index；Slice 的 lower/upper/step 按规则求值，省略项单独表示。
读取、`__setitem__`、`__delitem__` 及高级索引可有用户调用、别名和部分更新。
BinOp 按左右顺序求值，保留普通/反向特殊方法、子类型优先及 NotImplemented 路线。
UnaryOp 也可能调用用户协议；membership 含 `__contains__` 或迭代 fallback 与 truth。
类型、shape 或同名运算符相同，均不足以推出纯度、数值相等或对象同一。
短路比较的值/条件区别见[控制协议](PYTHON_CONTROL_PROTOCOLS.md)。

## 7. 赋值、解包与删除

Assign 先 RHS，再按 targets 顺序写入；链式赋值共享 RHS 引用而非复制内容。
属性/下标 target 在自己的 store 阶段求定位表达式，不能无条件提前读取全部 target。
解包先执行本层迭代/arity 检查，再按各 target 顺序递归写；已完成的外层写入不回滚。
星号 target 接剩余序列，数量和成员未知则保留符号 pack 与失败约束。
AugAssign 只求一次 target 定位，读取旧值、求 RHS、in-place/fallback 运算，再 store-back。
in-place 修改已发生而 store-back 失败的路径仍携带修改后的状态。
Delete 左到右递归删 target；它不构造 List/Tuple，也不读取待删除名字的值。
NamedExpr 求 RHS、绑定并返回该值；推导式中的目标遵循 containing-scope 规则。

## 8. Call 与跨过程接口

先求 func，再按语言与目标版本规则准备位置/星号和 keyword/`**`，保留每个有序 Use。
星号表达式求值与 iterable 消费分开：单独 *pack 与前缀/多个 pack 的展开时点可不同。
不以 AST 字段排列或“星号立即迭代”替代具体规则；无法确定的展开路线保留条件。
`**mapping` 的 keys、读取、字符串键检查和重复名检查均可有状态与异常。
参数准备、目标 dispatch、形参绑定和 body 入口分开；绑定失败不产生 body 执行边。
已解析候选通过 caller Use→formal、callee return→caller result 和异常/状态端口连接。
wrapper、bound receiver、partial、类与 `__call__` 需各自适配，不能只按签名猜目标。
静态 may-call 不创建 Invocation；环境、目标或 pack 不明时保留未解析条件。

## 9. 容器、字面量与文本

List/Tuple/Set 元素按规则求值与展开；set/dict 插入包含 hash/equality 的 effects。
Dict 按 key→value 的成对顺序处理，`**mapping` 有独立展开接口，重复键影响最终状态。
Load 容器表达式与 Store/Del target 是不同协议；不能把解包赋值画成创建 target 容器。
推导式有词法作用域、迭代/过滤 Region 和写入关系；具体循环规则见[控制协议](PYTHON_CONTROL_PROTOCOLS.md)。
Constant 保留 None/bool/int/float/complex/str/bytes/Ellipsis 等精确描述及源码归属。
常量内容相同不证明 Python 对象 identity、interning 或可跨次复用；不存 Tensor 全值。
f-string 保留 value→conversion→format-spec→format 的求值与异常顺序。
t-string 创建保存 interpolation 值/表达式文字/转换描述；不在此处执行最终格式化。

## 10. 导入、动态源码与实现缺口

Import/ImportFrom 建静态依赖候选与初始化接口，不实际 import 目标包来解析依赖。
保留 package/relative context、sys.modules 状态、loader、模块体与按次序写入的名称。
循环导入可能读取部分初始化状态；失败不回滚全部已执行模块及外部副作用。
from-import 的属性/子模块候选与 star-export 规则分别保留；动态导出可 UNKNOWN。
exec/eval、动态 loader 或生成源码边界须明确，不能借同名磁盘文件补造其 body。
完整类/注解/动态导入/对象协议仍需逐构造实现，不以接口标签或本页条目数宣称支持。
已有路径若把动态见证当建图前置，迁移为纯静态入口仍是待实现工作。
每个缺口保留原定义、合法子图、缺失阶段/端口和原因；细状态不明可用保守域，不能省略操作。
