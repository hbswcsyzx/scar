# Python 3.14 静态协议目录

本目录规定整程序静态图应表达的语言范围，不是现有前端全部支持的声明。
建图只读取源码与显式配置，不导入或执行目标，不依赖调用捕获、运行见证或 profiler。
运行时才能确定的值、目标和资源保留为符号、候选、条件或 `UNKNOWN`。

统一实体见 [MODEL](MODEL.md)，层次拆分见 [PROGRAM_DECOMPOSITION](PROGRAM_DECOMPOSITION.md)，
开发范围见 [STATIC_ANALYSIS_PLAN](STATIC_ANALYSIS_PLAN.md)。
仅使用 canonical `Operation / Value / StateLocation / Region / Resource`；
端口、Use、CFG 与状态关系引用原实体，不另建一套权威图。

## 协议归属

| 协议族 | Python 构造 | 必须保留的静态语义 |
| --- | --- | --- |
| 源单元 | Module、Interactive、Expression、FunctionType | 源版本、解析模式、作用域；模块体与专用签名语法分开。 |
| 函数定义 | FunctionDef、AsyncFunctionDef、Lambda、arguments、arg | defaults、decorators、annotations、closure 与 body 分阶段。 |
| 类定义 | ClassDef | bases、keywords、metaclass、prepared namespace、类体及装饰器。 |
| 类型定义 | TypeAlias、TypeVar、ParamSpec、TypeVarTuple | annotation scope、惰性求值与访问触发条件。 |
| 绑定更新 | Assign、AnnAssign、AugAssign、Delete、NamedExpr | 求值与 store 次序、局部绑定、heap 状态、部分失败。 |
| 访问与调用 | Name、Attribute、Subscript、Slice、Call、keyword | 查找、descriptor、索引、参数准备、目标候选与调用接口。 |
| 运算 | BinOp、UnaryOp 及相应 operator marker | 特殊方法、反向分派、结果与可能异常；不默认纯。 |
| 短路与比较 | BoolOp、IfExp、Compare、boolop、cmpop | 条件路径、选中值、中间 operand 单次求值与 truth。 |
| 容器 | List、Tuple、Set、Dict、Starred | 有序构造、展开、hash/equality、别名及构造失败。 |
| 推导式 | ListComp、SetComp、DictComp、GeneratorExp、comprehension | 隐式作用域、嵌套迭代、filter、eager/lazy 阶段。 |
| 分支与循环 | If、While、For、AsyncFor | CFG、零次路径、回边、循环携带、break/continue/else。 |
| 控制转移 | Return、Raise、Break、Continue | 所属边界、payload、异常上下文与介入 cleanup。 |
| 异常与清理 | Try、TryStar、ExceptHandler、With、AsyncWith、withitem | handler、pending completion、逆序退出、抑制及部分状态。 |
| 挂起与驱动 | Yield、YieldFrom、Await | 创建、驱动、lazy body、Suspend/Return/Raise 与恢复条件。 |
| 模式匹配 | Match、match_case 与全部 Match* pattern | subject、结构提取、capture、guard、失败及异常。 |
| 导入 | Import、ImportFrom、alias | 静态依赖候选、包上下文、初始化与名称绑定协议。 |
| 文本构造 | JoinedStr、FormattedValue、TemplateStr、Interpolation | 转换、format spec 与模板消费阶段。 |
| 字面量 | Constant | 精确值描述与源码归属；内容相等不推出对象同一。 |
| 其他语句 | Expr、Assert、Pass、Global、Nonlocal、TypeIgnore | 结果生命周期、assert 编译选项、作用域声明与纯元数据。 |

`Load / Store / Del`、操作符 marker 和辅助 AST 节点选择所属协议，
不各自制造无条件执行的计算。AST 字段顺序不能替代语言求值顺序。

## 分册与组合

- [数据与定义](model/PYTHON_DATA_DEFINITION_PROTOCOLS.md)：源码、定义、访问、调用与值状态。
- [控制协议](model/PYTHON_CONTROL_PROTOCOLS.md)：条件 CFG、异常、cleanup 与挂起恢复。
- [资源协议](model/RESOURCE_PROTOCOLS.md)：CPU/GPU、内存、存储及程序 I/O 接口。

一个调用或语法定义只保存一份规范 body；使用处以限定引用和条件端口连接。
静态 may-call、may-return、may-allocate 不生成 Invocation 或实际 allocation。
状态与异常语义可以完整表达在静态图中，不必先发生一次执行。

## 实现边界

语法清单、规则说明、lowerer 实现与可查询 canonical 关系是不同成果。
未实现协议须指出缺失的构造、字段、阶段及端口，保留已有合法子图。
未知运行值不等于不支持语法；缺源码、动态目标未解与预算未覆盖也须分开。
不能用 OPAQUE 标签、空效果集合或节点数量替代缺失的程序操作与依赖。
兼容旧 AST 名称或手工 AST 的入口须另有合法性规则，不算新增语言支持。
