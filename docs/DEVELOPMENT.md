# 开发与用法

使用现有 `conda activate lewm`，只在 `~/AAA/scar` 的 `main` 开发。
不创建 worktree、日期版源码或历史实验副本；正常提交 Git，不 reset。
不修改外部 LeWM、数据/权重、CUDA/driver 或整套环境。删除实现前先查引用。

## 建图入口

```bash
python -B -m scar.cli static /path/to/program --out /path/to/model --phase bodies --jobs 4
python -B -m scar.cli static /path/to/program --out /path/to/model --expand --jobs 4
python -B -m scar.cli static /path/to/program --out /path/to/model --link-calls --max-call-bodies 80
```

`--phase sources/graph` 为材料目录/源码图，`--phase bodies` 继续构建规范主体；
`--expand` 增量补主体。显式预算仅限本次工作，不缩小完整性分母。
依赖材料可用 `--inventory-dependencies --dependency-root PATH` 定位，
再用 `--expand-dependencies` 送回同一前端；这些命令均不执行目标。

## 动态采集及离线连接

```bash
python -B -m scar.cli trace --calls-only \
  --capture-plan /path/to/plan.json --capture-plan-sha256 PLAN_SHA256 \
  --capture-transport snapshot --out /path/to/fresh-trace -- python /path/to/program.py
python -B -m scar.cli observed-calls --model /path/to/model \
  --trace /path/to/fresh-trace --out /path/to/fresh-bindings --expand-missing
```

采集计划由 `scar.trace.lean_capture.LeanCapturePlan` 对原源码/代码身份生成；具体接口以源码为准。
采集不额外执行用户 repr、descriptor 或 hook 来探测对象，不保存每次 Tensor 的完整数值。
优先复用已保存 trace；`observed-calls` 只离线连接，缺主体按完整代码身份请求原前端补建。
采集仍含 frame profile hooks，不能宣称零干扰；性能测量与建图采集分开。

## 共享图查询

```python
from scar.analysis.program_dependency_session import ProgramDependencySession

with ProgramDependencySession('/path/to/model') as session:
    ns, = session.select_bodies(file='program.py', entry='function_name', kind='FUNCTION')
    body = session.load(ns)                 # 原共享函数图及 index
    loops = session.loop_constructs(ns)     # 原成员 ID、嵌套、初始/回边端口
    if loops:
        operations = loops[0].expand(session.graph())
        boundary = session.loop_boundary(ns, loops[0])
```

不存在的 structured/主体信息保留准确缺口，不当成空子图。`ProgramDependencyBudget`
控制时间、输入、缓存和关系读取；边界查询完成仍须检查前沿和字段覆盖。
CLI 的 `static-query --program-graph` 使用原 typed ID，不按名称制造依赖。

## 维护

当前任务及验收结果只更新 [STATUS](STATUS.md)，结构变化更新 [MODEL](MODEL.md) 或
[ARCHITECTURE](ARCHITECTURE.md)；不新增专题、版本或 gate 文档。
先定位缺失的识别事实、端口、连接或推理规则，再修改负责层；只运行相关检查。
生成图仅发布到 `artifacts/current/static/`，查询只引用原 ID/收据，不另建权威程序。
