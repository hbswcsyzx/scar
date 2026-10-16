# Python 3.14 程序构造与协议清单

日期：2026-10-16。范围：本机 CPython 3.14.7 的具体 AST 构造；**设计索引，
不是所有构造的 lowerer 已实现或逐字段执行规则已验收的声明。**

完整模型的实体、端口与组合规则见 [WHOLE_PROGRAM_MODEL.md](WHOLE_PROGRAM_MODEL.md)。
本清单用于防止建模只考虑函数与 Tensor、遗漏定义阶段、语法辅助节点和控制。
它不是沿 AST children 顺序执行的算法，不能替代每种协议的字段求值规则。

## 1. 构造归属

每个具体构造在下表恰有一处归属。字段清单从目标环境的 `ast` 反射保存，
审计检查遗漏、重复和运行版本；这只能验证清单守恒，不授予执行/化简权限。

| 协议族 | AST 构造 | 输入、状态与组合要求 |
| --- | --- | --- |
| source-unit | `Module`, `Interactive`, `Expression`, `FunctionType` | 编译/运行模式、根 scope、定义与 phase；FunctionType 为专用解析模式，不伪造普通表达式执行。 |
| callable-definition | `FunctionDef`, `AsyncFunctionDef`, `Lambda`, `arguments`, `arg` | defaults/annotations/decorators/type scope 与 body 分阶段；函数对象、环境、formals、resumption 协议。 |
| class-definition | `ClassDef` | bases/keywords、metaclass/namespace、body、隐式 callbacks 与 decorators 的顺序及异常。 |
| type-definition | `TypeAlias`, `TypeVar`, `ParamSpec`, `TypeVarTuple` | 版本化 type scope、惰性求值及相关环境；不能把 annotation 当本行必执行表达式。 |
| binding-update | `Assign`, `AnnAssign`, `AugAssign`, `Delete`, `NamedExpr` | RHS/target 顺序、单次 target 求值、绑定/heap 写、解包部分失败、in-place dispatch；annotation phase 独立。 |
| scoped-transfer | `Return`, `Raise`, `Break`, `Continue` | 类型化目标、payload、当前异常上下文、cleanup 及当前后态。 |
| branch-loop | `If`, `For`, `AsyncFor`, `While` | truth、iterator/advance、零次/回边、携带 binding/state、else、异常与异步恢复。 |
| cleanup-handler | `Try`, `TryStar`, `ExceptHandler`, `With`, `AsyncWith`, `withitem` | pending completion、匹配/split/merge、enter/exit 顺序、抑制、异步挂起与部分状态。 |
| pattern-match | `Match`, `match_case`, `MatchValue`, `MatchSingleton`, `MatchSequence`, `MatchMapping`, `MatchClass`, `MatchStar`, `MatchAs`, `MatchOr` | subject 一次求值、协议 lookup、路径相关 capture、guard 与后续 case；失败后的行为依目标语言规则。 |
| import-binding | `Import`, `ImportFrom`, `alias` | module/cache/hook/init、relative/package 上下文、from/star 导出与绑定、正常/失败状态。 |
| scope-passive | `Global`, `Nonlocal`, `Pass`, `TypeIgnore` | 编译作用域或源码元数据；不制造可执行计算。 |
| expression-statement | `Expr`, `Assert` | 结果引用释放/可能 finalizer；assert 的目标编译模式、惰性 message 与异常构造。 |
| lazy-selection | `BoolOp`, `IfExp`, `Compare`, `And`, `Or`, `Eq`, `NotEq`, `Lt`, `LtE`, `Gt`, `GtE`, `Is`, `IsNot`, `In`, `NotIn` | 短路、实际 operand 结果、中间项单次求值、truth 与特殊方法；operator marker 自身不额外执行。 |
| numeric-dispatch | `BinOp`, `UnaryOp`, `Add`, `Sub`, `Mult`, `MatMult`, `Div`, `Mod`, `Pow`, `LShift`, `RShift`, `BitOr`, `BitXor`, `BitAnd`, `FloorDiv`, `Invert`, `Not`, `UAdd`, `USub` | 有序 operands、类型/反向 dispatch、状态与异常；marker 是上层操作的参数，不是纯性证明。 |
| construction-iteration | `Dict`, `Set`, `List`, `Tuple`, `ListComp`, `SetComp`, `DictComp`, `GeneratorExp`, `comprehension` | 分配/身份、元素求值与展开、dict key/value 交错、迭代/filter、scope、懒执行和异步路径。 |
| access-call | `Name`, `Attribute`, `Subscript`, `Slice`, `Starred`, `Call`, `keyword`, `Load`, `Store`, `Del` | 作用域/绑定、descriptor/index 协议、selector 与 alias；packing/绑定/entry 分开。context/keyword 是接口信息，不是独立无条件求值。 |
| suspension-delegation | `Await`, `Yield`, `YieldFrom` | resume request、当前共享状态、frame/continuation、委托、关闭与最终完成 adapter。 |
| text-template | `FormattedValue`, `JoinedStr`, `Interpolation`, `TemplateStr` | 表达式/转换/format spec 的有序协议；模板保留 interpolation 数据，不等同立即格式化。 |
| literal | `Constant` | 精确 literal 描述、构造/身份与编译合同；常量内容不许可删除其外围效果。 |

## 2. 版本与范围

- canonical sums：`mod`, `stmt`, `expr`, `pattern`, `type_param`, `expr_context`,
  `operator`, `unaryop`, `boolop`, `cmpop`, `excepthandler`。
- product nodes：`comprehension`, `arguments`, `arg`, `keyword`, `alias`, `withitem`,
  `match_case`；`TypeIgnore` 归入 type-ignore sum 的具体节点。
- `Suite`, `AugLoad`, `AugStore`, `Param` 是旧兼容类型，不作为本版本源语法。
  `Num`, `Str`, `Bytes`, `NameConstant`, `Ellipsis`, `Index`, `ExtSlice` 等兼容 API
  也不是新增的 canonical 源构造。源前端如接受手工 AST，须另有兼容/合法性规则。
- 注释、空白、token、编码与编译指令仍有 source ownership；不为它们虚构普通
 执行操作。生成代码/exec/eval 有独立源码快照、编译上下文和新定义关系。
- 原生库/扩展及系统交互不以 Python AST 内部结构冒充已展开；用同一强类型
 状态、资源和完成接口表示边界，未知内部与缺失接口分别报告。

本机清单审计和独立语言反例的证据见
[WHOLE_PROGRAM_MODEL_REVIEW.md](WHOLE_PROGRAM_MODEL_REVIEW.md)。
官方构造定义见 [Python AST 文档](https://docs.python.org/3.14/library/ast.html)。

## 3. 由清单到实际模型的验收

清单中的每族都需要后续逐字段规范：字段属于编译/定义/调用/恢复/访问哪个
phase，何时求值、是否短路、需要哪个隐式环境、可产生哪些完成、如何连接
生命周期和状态。编译与库版本也是规则输入。尚未完成逐字段规范的项目保留
未关闭状态；AST 名字齐全不能让整族进入“模型已实现”。

自动前端还要证明 source ownership、规范操作/ordered Uses、协议端口及运行
对应守恒。仅把未支持节点归为 OPAQUE 不满足这道门，不能跳到图化简。
