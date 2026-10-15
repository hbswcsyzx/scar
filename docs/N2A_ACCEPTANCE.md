# N2.a 验收：自动源码到类型与依赖核心

日期：2026-10-15。实现版本：`429e87e2e32fd29e9c7d0f41dd0e0207cfab95fd`。
结论：**有限函数体自动构图通过；完整 LeWM 自动恢复尚未通过。**

## 当前自动化做到了哪里

输入 `.py` 和一个函数入口，自动建立参数、局部定义、精确 use、if/else 合流、
表达式操作、正常/异常完成和条件调用接口。每个生成操作、值和 use 都有 typed
源码对应，Opcode 及有序操作数复用既有记录。同文件候选函数体自动展开，
两次调用共享 body，却保留各自 actual/formal/result 对应。

不要求用户手工制作或修复 workload IR，也不执行目标来构造这份源码图。
`scar model-program ... --entry ... --out report.json.gz` 为公共入口；
`scar check-source-program report.json.gz` 对当前源码重放所有图层和对应。
未支持的 body 保存带位置的诊断，graph=null，不输出截断的“完整图”。

这仍要求选择函数入口。跨文件依赖范围、循环、默认参数/装饰器、复杂状态和
运行对应尚未接通，因此不能称任意命令到完整程序模型已经实现。

## 自验结果

`gates/n2a.json`：**204 passed**，25.344 秒，冻结实现工作区干净，运行期间
被测文件哈希不变。六条验收条件逐项绑定实际测试，没有跳过或失败。
其中包括 N1 的 93 项兼容检查；不能把全部 204 项称为新功能测试。

冻结实现的整仓回归：**1,274 passed**，132.26 秒，2 条既有警告，无失败或
跳过。原始 XML、标准输出及 `/usr/bin/time -v` 记录均归档到
`artifacts/reports/gates/n2a-full-regression.*`。

正式记录：`artifacts/reports/gates/n2a-verified.json`，包含实现 revision、
逐文件 SHA256、命令和每条验收条件对应的案例。

## 真实外部源码压力

同一个公共命令处理以下三个**原始、明确选择的函数体**；未删装饰器或改写
测试输入。机器记录为 `artifacts/reports/gates/n2a-lewm-source-pressure.json`。

| 函数体 | 结果 | 具体范围/断点 | 分析含写入 / 峰值 RSS |
| --- | --- | --- | --- |
| `LeWM.predict` | LOWERED_WITH_GAPS | 1 region、27 operations、58 values、63 uses；5 次调用目标仍未确认 | 5.379 秒 / 44,504 KiB |
| `LeWM.get_cost` | UNSUPPORTED | 第 129 行 Assert 尚未连接；未输出核心图 | 5.188 秒 / 43,204 KiB |
| `CEMSolver.solve` | UNSUPPORTED | 第 119 行函数的默认参数/装饰器接口尚未支持；未输出核心图 | 7.673 秒 / 50,644 KiB |

三份压缩报告共 1,751,389 字节，都通过源码重放，分别耗时 13.284、13.141、
18.950 秒。重放仍需重复构建若干既有源码层，这是分析效率的待改进项；
不能将这些时间解释成 LeWM 的运行时间、profiling 或加速比。

源码 SHA256、外部 Git 状态及实现 SHA256 在测量前后均一致。没有执行或
修改 LeWM，没有人工补图，没有新 backend、已选择的变换或已验证加速。

三个相关外部文件还做了一次只读语法盘点，共 35 个同步函数、17 个 for、
42 处属性写/删除和 27 处下标写/删除。压缩清单保存为
`n2a-external-source-inventory.json.gz`，其外部源码哈希已复核。它是开发用
结构盘点，不是 SCAR 自动建图完成率，也不是性能瓶颈分析。

## 审查发现与修复

独立审查以实际 Python 调用为对照，发现：

1. return 后不可达的 import/del/except 等仍会决定 local 作用域；旧转换
   将某些 UnboundLocalError 错画成全局读取。改用 Python symtable。
2. return 后 yield 仍使函数成为 generator；增加本作用域的调用方式预检，
   排除嵌套 def/class/lambda，生成器接口尚未支持时明确拒绝同步转换。
3. `return x; global x` 语法解析可成 AST，却不是合法编译作用域；symtable
   会拒绝它。15 项独立反例也覆盖嵌套作用域、求值顺序、早退和重绑定。

以上修复前行为由审查代理实际复现；没有原始失败 XML，故不冒称已归档原始
运行日志。最小反例保留在 `tests/unit/test_source_lowering_review.py`。

开发整体验收首次为 203 passed / 1 failed：整理校验代码时误删了当前 invoke
的 completion 映射，callee 匹配用了旧映射。恢复按当前操作建立的映射，
38 项完成边反例重新通过。原始失败及修复结果分别存于
`n2a-development.json` 和 `n2a-callee-repair.xml`，之后才冻结正式实现。

## 为什么还不能依靠这份图优化 LeWM

当前未知操作共用 coarse world 状态；读写、别名和效果没有足够精度。源码
候选接口也不证明实际运行目标。即使结构图有效，仍不能证明某操作与循环
状态无关，更不能直接批准上移、复用、删除 import 或 CPU 物化。

后续先补自动依赖范围/函数接口清单，再补循环和状态，接真实运行对应，
最终以观察根的依赖闭包产生精确子图修改指导。每一步需要通用反例、自动
外部重建、失败报告和独立版本。详见 [N2_IMPLEMENTATION_PLAN.md](N2_IMPLEMENTATION_PLAN.md)
及 [AUTOMATIC_MODELING.md](AUTOMATIC_MODELING.md)。
