# 已有规范程序图接口

规范结构位于 `scar.ir.program`。接口检查图的结构与依赖声明，不执行被分析程序，也不证明具体实现满足全部声明。

```python
from scar.ir.program.codec import loads
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.ids import ValueID

# text 为已保存的规范图，不是目标 Python 程序。
graph = loads(text)
index = ProgramIndex(graph)
producer = index.producer(ValueID("buffer.updated"))
consumers = index.consumers(ValueID("buffer.updated"))
```

`producer`/`consumers` 沿既有 Value/Use 查询；重复输入保留不同 Use。示例 ID 需由实际图提供。
`scar.ir.program.validation.validate` 返回结构错误；`require_valid` 对错误抛异常。
规范图具备 Operation、ordered Uses/results、Region/Block/terminator、显式 state flow、源码与语言 overlay 接口。静态建图应复用这些结构。

已有 `lower_source` 可读取某个函数源码并生成受支持的图；它不等于完整项目自动建图。`prepare_source_text` 负责共享源码层/AST/symtable，具体 entry/profile 的能力仍需逐项检查。
静态调用候选复用 `CallTarget`、`CandidateArgument`、`CandidateResult`；目标候选不是实际调用实例。

当前反序列化与 SSA/支配校验不等于通用常量传播、别名分析或循环不变量外提。新能力和接口以 [静态设计](STATIC_ANALYSIS_DESIGN.md) 及 [实施计划](STATIC_ANALYSIS_PLAN.md) 为准。
