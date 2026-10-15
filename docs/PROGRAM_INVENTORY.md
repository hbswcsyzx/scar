# 自动源码范围、接口与覆盖清单

日期：2026-10-15。N2.b0 已有限验收，范围与冻结证据见
[N2B0_ACCEPTANCE.md](N2B0_ACCEPTANCE.md)。完整程序模型仍未完成。
运行来源桥接 N2.entry 的设计和验收要求见 [N2_ENTRY_PLAN.md](N2_ENTRY_PLAN.md)。

## 公共入口

```bash
conda activate lewm
scar inventory-program /path/to/project/entry.py --project-root /path/to/project \
  --out artifacts/reports/program-inventory.json.gz
scar check-inventory artifacts/reports/program-inventory.json.gz
```

不需要函数列表、手工 IR 或 workload 注解。入口必须是 Python 源文件；任意
运行命令到运行配置/动态代码对象的恢复还未接通。读取项目内源码，不执行
target、setup.py、pth，也不调用 find_spec。输出不可覆盖被发现的源码。

`--source-root` 可重复给出候选根。默认从项目目录、src 和有打包标记的本地
子项目推导候选根。所有根排序以保证确定性；该 API 不模拟运行 sys.path 的
顺序优先级。project-root 是文件边界。源根推导或声明不证明 loader 会采用它。

## 连接模型

```text
source entry
  -> ImportDependency(statement + alias source, scope, deferred)
  -> ModuleCandidate(name, physical path, source root, parent initializers)
  -> DiscoveredFile(SourceSnapshot)
  -> DefinitionInventory / CallInventory / CoverageEntry
  -> BodyInventory(core graph + typed source correspondence)
```

ImportControlContext 为分支真/假、循环体/else、try/handler/else/finally、with 和
match case 保留源位置及 arm；这些是待求值的控制条件。函数体开始时不继承
定义点的活动分支条件，调用条件仍待运行/调用模型连接。

物理路径、源码版本和位置是身份依据；模块名及 qualname 是搜索/展示属性。
重复定义保留独立 ID。发现阶段保留所有物理候选，核心转换每个文件单独准备，
因此旧 frontend 的同模块名字典不能覆盖另一个物理文件。

调用连接使用 callee READ 的 BindingUseID 和对应 import binding slot，随后
沿本地 import/export 源见证到候选定义，保留整个 import 路径和固定未接受
条件。参数遮蔽、已知局部重绑定不能按同名函数连边。当前支持有限直接导入、
模块别名属性及静态重导出；任意属性链、动态注入和实际 callable 尚未确认。
核心图的 callee 不会因此被补为确定目标。
重导出采用按 (file,symbol) 去重的 BFS，每个目标保留一条确定性见证；完整
import 边仍在发现图中。见证集合不是所有路径的枚举或运行绑定证明。

## 阶段与覆盖

ExecutionPhase 区分模块初始化、函数体、class body、推导式体和 annotation。
函数默认值/装饰器表达式属于外层定义上下文，函数体使用自己的 owner。类基类
和 metaclass 表达式属于外层；class field 与方法默认值属于 class body。
推导式第一个 iterable 属外层，后续迭代、filter 和 element 属内部作用域。
注解保留声明上下文及独立阶段；eager/lazy 时机和 annotation thunk 未验证。
隐式 decorator 应用和 class construction 有单独接口记录，不伪造 ast.Call。

每个被解析的 executable source atom（与既有前端相同的 stmt/expr/arg/alias/
keyword/handler 集合）恰有一个覆盖记录，注释和结构 AST 不计执行操作。

- CONNECTED：有自动生成核心 body 图的来源对应；仍可能有未知效果/目标。
- INVENTORY_ONLY：已记录来源和上下文，尚未连接核心操作。
- UNSUPPORTED：当前转换器缺少该构造，记录具体原因和位置。

覆盖所有语法位置不代表已恢复其全部依赖。失败 body 不会导致后面的语法
位置消失；缺源码、解析/准备失败的文件留下具体诊断，不声称有完整清单。
报告分别统计发现文件、定义、源调用、覆盖状态、body 状态及核心操作。

## 预算、成本与持久化

默认上限：128 个文件、8 MB 源码、4096 个发现目录、256 次 body 尝试和
10,000 次核心操作构造，以及 4,096 条调用目标见证。可用 CLI 对应 `--max-*` 参数设置；重放器有自己的
独立上限，报告不能自行提高它。failed body 和候选回滚同样扣操作预算。
construction_operations 与最终保留 core_operations 分开统计。

按候选 import 距入口的距离确定文件处理顺序，同距离按路径排序，优先为
上层依赖花费有限构图预算。该距离不是运行频次或重要性证明。

每文件只准备一次 SG/Opcode/CFG、AST 和符号表，多个 body 共享。报告保存
这三层的内容 SHA256 和 namespace root，避免重复序列化大图；自动生成的
核心 body 图和来源对应实际持久化。重放从当前文件重新发现、准备、构图并
核对所有摘要、图、接口和对应。新出现的本地候选也会改变报告并使旧报告失效。

## 从已有运行 trace 自动补充来源

```bash
scar inventory-program /path/to/project/entry.py --project-root /path/to/project \
  --trace /path/to/trace_directory --out runtime-inventory.json.gz
scar check-inventory runtime-inventory.json.gz
```

`--trace` 接受目录、JSONL 或 gzip。按实际输入逻辑流的原始字节计算摘要，重复
调用按 CodeID 和精确进程身份去重，保留次数及首末行锚点。不导入或执行目标，
不保存新的 Tensor 数值。未观察的静态候选仍保留。

有 trace 的报告是 v2，增加 typed runtime_scope；无 trace 保持 v1。来源候选
与当前源码版本核对分开：只有原始代码摘要精确复现才有 code-only witness，
未匹配可能来自缺少编译上下文或旧 marshal 引用布局，不能断言源码一定改变。
默认离线尝试 local Python、flags=0、optimize=0/1/2，filename 来自观察假设，
不宣称恢复了原始编译配置。

运行来源定义通过 definition_index 明确定位到源码快照、SourceReference、
模块 initializer 或 DefinitionInventory；可用时再连接 body.graph.root。
代码匹配不建立实际参数、闭包、全局状态、纯性或确定 callee。源码候选/观察过
的定义可优先消耗 body 预算，优先级不构成优化许可。

trace 的解压字节、行数、单行和代码组数，以及代码编译尝试有独立上限。
CLI 提供 `--max-trace-bytes`、`--max-trace-records`、`--max-trace-line-bytes`、
`--max-runtime-codes`、`--max-compile-attempts`。验证器独立设置 ceiling；报告
不能扩大它。重放先重新读取并核对 trace，再从当前源码重新发现/构建/核对。
相对、生成、非规范、界外、链接和缺失源码都保留具体边界。

## 剩余依赖

本门不补完整 loader/运行配置解析、循环/异常控制及细粒度 Tensor 状态。
不同 body 图的 coarse world 是独立分析接口占位，不能据不同 ID 推导物理
状态互不影响；本门没有合并它们或批准跨文件 state-domain 替换。
这些仍按 N2.b1/N2.b2/N4 推进，之后才能用观察根、状态和控制依赖形成完整
子图化简指导。本门没有新增优化器或加速声明。
