# SCAR

State · Control · Action · Resource。

SCAR 面向程序依赖建模与自动化简。当前唯一开发任务是**整程序纯静态分析**：不运行目标，尽可能推导源码、依赖、配置和已提供材料中能够确定的事实，并建立层次化、可组合的程序图。

当前建模尚未完成。已有结构化前端和有限推理，不代表已自动完整建模 LeWM；当前没有新的优化或加速比结论。

## 当前入口

- [文档索引](docs/README.md)：当前文档的职责。
- [程序模型](docs/MODEL.md)：实体、身份、边与不确定性。
- [静态分析架构](docs/STATIC_ANALYSIS_DESIGN.md)：编译器式阶段、联合推导与存储。
- [程序展开规则](docs/PROGRAM_DECOMPOSITION.md)：每类构造如何成为子图。
- [唯一实施计划](docs/STATIC_ANALYSIS_PLAN.md)：当前优先统一跨分片图、共同推理和全范围接线。
- [当前状态](docs/STATUS.md)：已经做到什么、尚未做到什么。

## 工作区

开发只在 `~/AAA/scar` 的 `main` 进行，不再保留额外 worktree、日期版代码副本或历史实验目录。
`../le-wm` 和 `../scar-testcases` 是外部程序与测试材料，SCAR 不根据业务名称选择分析规则。
旧实验、门报告和版本说明已从工作区移除，正常 Git 历史保留。

开发使用现有 `lewm` 环境，不修改 LeWM、不升级 PyTorch/CUDA、不安装整套环境：

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate lewm
cd ~/AAA/scar
```

## 已有能力与当前边界

`scar.analysis.program_lowering.prepare_source_text` 可从源码文本生成 AST、符号表、源码模型和控制流；`lower_source` 可为支持的函数体建立规范 IR。它们读取源码，不导入目标模块。

已有共同跨分片依赖导航、首版 scalar/type/定义来源工作队列和原操作区域边界查询，保留原 ID、静态上下文、条件和证据。查询可跨已发布 call、环境/G 和 class provider 接口，不复制 callee。

这还不是完整整程序建模：模块和类的完整主体、部分 Python 协议、跨过程目标与参数绑定、别名/副作用联合推导和 Tensor 属性传播仍需按计划贯通。模块已有 BODY profile，类已有独立入口 ABI；类体的 required expansion 不能算成主体已展开。已有运行见证不能充当纯静态完成依据。

现存 trace、profiler 和 backend 实现当前冻结；这一阶段不调用它们，不新增 detector 或程序变换。
已提供纯静态入口，目标源码不会被导入或执行：

```bash
python -m scar.cli static ../le-wm --jobs 4
python -m scar.cli static ../le-wm --expand --jobs 4
python -m scar.cli static ../le-wm --link-calls --max-call-bodies 80
python -m scar.cli static ../le-wm --link-classes --max-class-bodies 40000
python -m scar.cli static ../le-wm --inventory-dependencies \
  --dependency-root "$CONDA_PREFIX/lib/python3.14" \
  --dependency-root "$CONDA_PREFIX/lib/python3.14/site-packages" \
  --dependency-root "$CONDA_PREFIX/lib/python3.14/lib-dynload"
python -m scar.cli static ../le-wm --expand-dependencies --jobs 8
python -m scar.cli static-query --file solver/cem.py --name solve --dependencies --limit 5
```

统一图查询使用完整原 ID，`--file/--name/--kind` 需选中唯一规范主体：

```bash
python -m scar.cli static-query --program-graph --file solver/cem.py \
  --name solve --kind FUNCTION --node program_value:88861ecb4513a932687daf0cb519ba4b \
  --max-points 96 --max-edges 256 --max-depth 20
```

真实已发布 class 接口也可查询（同一 `--file`，父 module）：

```bash
python -m scar.cli static-query --program-graph --file solver/cem.py \
  --name '<module>' --kind MODULE --node program_use:b88799427b898a642ea4e7c4e1d17161 \
  --direction outgoing --relation ARGUMENT --max-points 4 --max-edges 8 --max-depth 2
```

当前 class/calls 已枚举发布；35,747 个规范 CALL 中仅 270 个有已连接候选，第一阶段未完成。
真实跨文件参数边的双向读回见 `artifacts/current/queries/lewm-call-interface-outgoing.json`；
CEM 规划/model 链尚未贯通。这是当前保存图的一次有界查询，不代表完整闭包。对其它主体，用普通 `static-query` 或
`ProgramDependencySession.index` 获取其原 ID。`--infer-values --node ...` 推导支持的不可变
scalar/type/来源字段；重复 `--boundary-operation program_operation:...` 查询操作集合的区域边界。
三个入口都不执行目标，导出复用 namespace/上下文/条件/证据。遍历耗尽、字段精度、未闭合项
和整程序完整性分别报告；UNKNOWN/effects 未闭合不自动变成无副作用。

默认 `ProgramDependencySession.graph()` 已自动发现原 module/class/nested factory 的
函数对象/G 引用来源，无需调用者提供 origins 或已有 CALL targets。真实 CEM `solve.G`
到 module G 的 6 条连续条件引用边记录在
`artifacts/current/queries/factory-entry-origins-automatic.json`，约 32.76 秒；入口字典内容、
调用目标尚未解决。绝对 IMPORT_FROM 已接真实 request/namespace binding 并在公共图独立
读回，真实定点查询记录在 `artifacts/current/queries/import-from/summary.json`；主发布仍为
v8，入口状态、相对导入与完整调用链待接通。未知前缀＋已核接口后缀使用独立 Open context，不能
变成闭合空栈。walk/value/boundary 查询格式当前为 3/4/3，保留 `unknown_prefix` 与
条件的有序 `operands` 引用；不能用旧格式忽略这些字段消解条件。

权威程序图只保留 `artifacts/current/static/`：每份源码共享 source/semantic/semantics/CFG/lexical 分片，常量事实和 import 候选索引连接原 ID。`queries/` 只保存引用这些原分片的派生查询及核验收据。
`--phase sources` 仅建目录；`--phase graph` 为默认源码图；`--phase bodies` 构造源图后继续规范主体展开。对已有图使用 `--expand`，无需重建源图；`--rules-only` 只发布详细规则/前提，`--max-bodies` 与 `--file` 只限制本次派工，全部入口继续计入分母。
`--refine` 使用已保留源码细化 scope/import，不重建源码图；`--refine --imports-only` 只更新 import 索引。图结构化展开与跨过程固定点仍未完成，命令成功不代表第一阶段完成。
`--entry lexical:...` 可在 `--expand` 时按原入口 key 精准派工，不改变总目录。`--link-calls` 只在保存的原图上建立条件调用/参数/完成端口关系，预算和未处理范围写入原 manifest；更新主体或目录会废弃旧调用索引。查询 `--dependencies` 可读取这些跨主体端点，不能将单一候选解释为运行目标已确定。

`--inventory-dependencies` 沿原 import 关系，在显式根下定点查找源码、stub、native 和 namespace 候选，保存为 `indexes/dependencies.json.gz`；不执行 import/hook，不扫描整个环境。`from` 导出备选、内建模块或未提供文件分别保留，不能将未找到独立文件统一叫缺依赖。该步骤只定位并版本化材料，后续仍须把源码送回前端，不能算依赖图已展开。公开读回使用 `scar.analysis.static_dependencies.read_static_dependencies`。

`--expand-dependencies` 消费已发布材料，把外部 source/stub 候选按 namespace 分别送回同一静态前端，保留原证明输入并原子更新 import/material 索引。它扩展源码图范围，不证明运行实现已选定、canonical 主体已展开或整程序依赖已贯通。当前主图接线的结构性缺口与最高优先级见 [程序分解 §3.4](docs/PROGRAM_DECOMPOSITION.md#34-主图决策与当前结构性缺口)。

调用链接将当前任务进度及成功/失败终态保存到模型旁的 `artifacts/current/static-link-task.json`，与程序图分开。`scar.analysis.static_jobs.read_static_link_task` 会核对 PID 的启动身份；进程消失且没有终态时明确报告 `STOPPED_WITHOUT_TERMINAL_RECORD`，不当作仍在运行或已经发布。`PUBLISHED` 还须区分关系枚举完成与整程序模型完成。

调用/类链接共享 `--max-link-input-bytes`、`--max-link-cache-bytes`、`--max-link-seconds`。
输入预算累计 stored 与 decoded；当前模型单次冷 call seed 下界约 19.47 GB，默认 8 GB
只适合有界分析，不足以完整枚举。全范围运行可显式给足预算（缓存仍单独有界）：

```bash
python -m scar.cli static ../le-wm --link-calls --max-call-bodies 10000 \
  --max-link-input-bytes 137438953472 --max-link-cache-bytes 8589934592 \
  --max-link-seconds 7200
```

预算不是耗时或完整性承诺；原范围、实际处理、未闭合项与终态均须读回核对。
v8 初始化条件、源码展开修复和当前产物尚存的欠账见 [STATUS](docs/STATUS.md)。

`--link-classes` 独立发布当前原图的 parent/provider/suite 接线，不执行 builder 或用户代码。类链接任务记录为 `artifacts/current/static-class-link-task.json`。主体变更使旧调用和 class 接线失效；单纯调用重链接保留不受影响的 class 索引。

C++ 绑定源码已有独立输入层 API，复用社区 parser，不执行源程序。解析工具使用 SCAR 私有
venv，避免改动目标环境（依赖版本也列在 `native-source` extra）：

```bash
python -m venv .venv/native-source
.venv/native-source/bin/python -m pip install tree-sitter==0.26.0 tree-sitter-cpp==0.23.4
```

```python
from scar.analysis.static_cpp_source import (
    read_static_cpp_source, cpp_source_to_document, cpp_source_from_document,
)

model = read_static_cpp_source(
    cpp_file, tool_python=scar_tool_python, template_grammar=code_template_file,
)
index = model.index()  # 原 SourceAtomID、SourceReference 和 SOURCE/STRUCTURE 关系
document = cpp_source_to_document(model)  # 单位内整数引用；原 ID/收据无损保留
assert cpp_source_from_document(document) == model
```

普通 C++ 输入可省略 `template_grammar`；CodeTemplate 输入传入其原定义文件。模板孔、
解析错误、同名定义候选和未确定字段不会被吞掉。此 API 是源码前端，不证明 C++ 类型、
重载、Python/native ABI 或 wheel binary 对应；接入整程序 canonical 图仍在推进。
