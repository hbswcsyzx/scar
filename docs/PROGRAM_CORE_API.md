# N1 程序图接口与复现

本接口检查给定 IR 的结构与依赖声明。图合法不证明算子实现满足声明，也不
批准优化。源码自动恢复在 N2；子图化简及 proof 在 N3—N4。

## 命令

```bash
conda activate lewm
python -m scar.cli check-program examples/program_graphs/branch_state.json \
  --out artifacts/reports/program-check.json
```

退出码 0 表示 WELL_FORMED；2 表示输入不可读、格式错误或图不合法。命令
输出实体/use 数量、明确标记的效果不完整数；不执行输入程序，不重写输入图。
`examples/program_graphs/branch_state.json` 从手工 IR fixture 导出，包含三个块、
两个状态域和正常/异常出口；它不是从 Python 自动提取的分析结果。

## Python

```python
from pathlib import Path
from scar.ir.program.codec import loads
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.ids import ValueID

graph = loads(Path("examples/program_graphs/branch_state.json").read_text())
index = ProgramIndex(graph)
print(index.producer(ValueID("buffer.updated")))
print(index.consumers(ValueID("buffer.updated")))
```

`dumps/loads` 验证全部连接，不只是字段类型。`validate(graph)` 返回带
code/path/message 的错误列表；`require_valid(graph)` 遇错抛 ValueError。
`ProgramIndex.consumers` 返回准确的 UseSite，重复输入 `f(x,x)` 保留两个 use。

## 目前明确的约束

- 状态域在每个块的参数和每个出口显式传递。写入后旧版本不能成为后续当前
  状态；即使全覆盖写，也不能以旧的 STATE_ORDER 绕过先前写入的顺序。
- 已知访问范围使用同一位置坐标下的精确半开区间；未知 footprint 不产生
  覆盖证据。引用参数不能被无依据改写成另一个位置或更精确的身份。
- 调用共用函数体，各有独立实际 uses/results。N1 普通调用只接单一正常出口。
  返回引用的详细目标/selector/identity 暂保持未知，等待可验证的返回摘要。
  每个实际 use 必须绑定形参；call 和控制出口保留状态内容依赖，不能擅自
  降为仅顺序依赖。
- 分支可进入相同目标块；每条边仍独立携带参数。循环不展开成动态实例列表。
- 额外 order 边当前仅适用于同步控制范围；GPU ready、autograd 与动态资源
  生命周期尚未由本门验证。
- Operation 的行为标签和 label 不选择计算规则。N2 将通过既有源码/算子记录
  关联具体操作及版本，不能用 label 推导加法、编码或纯性。

旧 `scar.ir.ProgramGraph` 和 `scar.ir.v2` 的历史图/报告仍保留；新增规范核心
位于 `scar.ir.program`，不同 ID 命名空间不会自动混用。迁移必须有显式关联。
