# SCAR

State · Control · Action · Resource。

SCAR 面向程序依赖建模与自动化简。当前唯一开发任务是**整程序纯静态分析**：不运行目标，尽可能推导源码、依赖、配置和已提供材料中能够确定的事实，并建立层次化、可组合的程序图。

当前建模尚未完成。已有结构化前端和有限推理，不代表已自动完整建模 LeWM；当前没有新的优化或加速比结论。

## 当前入口

- [文档索引](docs/README.md)：当前文档的职责。
- [程序模型](docs/MODEL.md)：实体、身份、边与不确定性。
- [静态分析架构](docs/STATIC_ANALYSIS_DESIGN.md)：编译器式阶段、联合推导与存储。
- [程序展开规则](docs/PROGRAM_DECOMPOSITION.md)：每类构造如何成为子图。
- [唯一实施计划](docs/STATIC_ANALYSIS_PLAN.md)：S0–S5，当前推进 S2 主体与跨层连接。
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

这还不是完整整程序建模：模块和类的完整主体、部分 Python 协议、跨过程目标与参数绑定、别名/副作用联合推导和 Tensor 属性传播仍需按计划贯通。模块已有 BODY profile，类已有独立入口 ABI；类体的 required expansion 不能算成主体已展开。已有运行见证不能充当纯静态完成依据。

现存 trace、profiler 和 backend 实现当前冻结；这一阶段不调用它们，不新增 detector 或程序变换。
已提供纯静态入口，目标源码不会被导入或执行：

```bash
python -m scar.cli static ../le-wm --jobs 4
python -m scar.cli static ../le-wm --expand --jobs 4
python -m scar.cli static ../le-wm --link-calls --max-call-bodies 80
python -m scar.cli static ../le-wm --inventory-dependencies \
  --dependency-root "$CONDA_PREFIX/lib/python3.14" \
  --dependency-root "$CONDA_PREFIX/lib/python3.14/site-packages" \
  --dependency-root "$CONDA_PREFIX/lib/python3.14/lib-dynload"
python -m scar.cli static ../le-wm --expand-dependencies --jobs 8
python -m scar.cli static-query --file solver/cem.py --name solve --dependencies --limit 5
```

输出只保留 `artifacts/current/static/`：每份源码共享 source/semantic/semantics/CFG/lexical 分片，常量事实和 import 候选索引连接原 ID。
`--phase sources` 仅建目录；`--phase graph` 为默认源码图；`--phase bodies` 构造源图后继续规范主体展开。对已有图使用 `--expand`，无需重建源图；`--rules-only` 只发布详细规则/前提，`--max-bodies` 与 `--file` 只限制本次派工，全部入口继续计入分母。
`--refine` 使用已保留源码细化 scope/import，不重建源码图；`--refine --imports-only` 只更新 import 索引。图结构化展开与跨过程固定点仍未完成，命令成功不代表第一阶段完成。
`--entry lexical:...` 可在 `--expand` 时按原入口 key 精准派工，不改变总目录。`--link-calls` 只在保存的原图上建立条件调用/参数/完成端口关系，预算和未处理范围写入原 manifest；更新主体或目录会废弃旧调用索引。查询 `--dependencies` 可读取这些跨主体端点，不能将单一候选解释为运行目标已确定。

`--inventory-dependencies` 沿原 import 关系，在显式根下定点查找源码、stub、native 和 namespace 候选，保存为 `indexes/dependencies.json.gz`；不执行 import/hook，不扫描整个环境。`from` 导出备选、内建模块或未提供文件分别保留，不能将未找到独立文件统一叫缺依赖。该步骤只定位并版本化材料，后续仍须把源码送回前端，不能算依赖图已展开。公开读回使用 `scar.analysis.static_dependencies.read_static_dependencies`。

`--expand-dependencies` 消费已发布材料，把外部 source/stub 候选按 namespace 分别送回同一静态前端，保留原证明输入并原子更新 import/material 索引。它扩展源码图范围，不证明运行实现已选定、canonical 主体已展开或整程序依赖已贯通。当前主图接线的结构性缺口与最高优先级见 [程序分解 §3.4](docs/PROGRAM_DECOMPOSITION.md#34-主图决策与当前结构性缺口)。

调用链接将当前任务进度及成功/失败终态保存到模型旁的 `artifacts/current/static-link-task.json`，与程序图分开。`scar.analysis.static_jobs.read_static_link_task` 会核对 PID 的启动身份；进程消失且没有终态时明确报告 `STOPPED_WITHOUT_TERMINAL_RECORD`，不当作仍在运行或已经发布。`PUBLISHED` 还须区分关系枚举完成与整程序模型完成。
