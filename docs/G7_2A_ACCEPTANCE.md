# G7.2a 自行验收报告

状态：**Verified，限于静态连接、条件 import 值来源与固定证明账本**。
G7.2b 正向 REUSE/MOTION、G7.3 修改计划以及 G7 总门尚未通过。

实现：`141390e`；测量修复：`603819d`。最终专项 gate **162 项通过**，整仓
回归 **940 项通过**，两项既有警告，无跳过。两份正式报告都绑定 `603819d`，
源码摘要 `8ae5ff8fd93b6392e54da0e827429eda01a8141c907a1c732ce70c32d0a20643`，
测试期间和归档前再次核对均未变化。gate 用时 13.379 秒，回归 49.053 秒。

## 模型与代码对应

- SG operation 是语义定义；invocation 是执行实例。source overlay 增加有序
  boundary 和 conditional reaching binding。条件连接保留来源，不升级为 EXACT。
- 静态值、静态 binding 与动态逻辑版本分离。IRBundle schema 2 接入独立 overlay；
  OIR schema 3 的 StaticValueSubstitution 检查真实 producer/source/binding/region。
  旧报告严格迁移，不凭迁移产生新身份或证明。
- import resolver 沿 import/module/export/re-export/attribute/index 等类型化连接
  推导不可变 builtin 值，同时列 loader、cache、初始化阶段、namespace、runtime
  的具体条件；不执行目标 import、descriptor 或用户代码。
- 固定 CONSTANT 和语义 DEAD 规则重新计算实际差量的证明义务。源码、模型、Q、
  region、scope 及差量任一变化使旧账本失效；存储的 PROVEN 不是证明来源。
  声明的 Q、coverage 与 scope 始终保留 DECLARED 属性。

## 通用外部样例实测

`testcases/static_imports` 是独立任意名称的三个源文件。入口末尾含执行哨兵异常，
分析没有执行它。规则不识别包名、变量名或 LeWM。

```text
import module → local binding → attribute → export/re-export
→ immutable tuple construction → index → index → int(7)
```

最终使用点是 `program.py` 第 4 行 RHS，结果 **CONDITIONAL**，完整来源包含
IMPORT_MODULE、ATTRIBUTE、IMPORT_EXPORT、REEXPORT 和两次 INDEX。
对应指导保留 33 条 guard/条件记录，不把它们合并为“默认纯”。

| 项目 | 结果 |
| --- | ---: |
| 选定 source files | 3 |
| 精确 builtin literal 事实 | 12 |
| 条件性值事实 | 5 |
| UNRESOLVED / BLOCKED | 3 / 1 |
| 非直接 literal 的条件指导 | 5 |
| 完整 provenance 记录 | 17 |
| 分析时间 | 0.646 秒 |
| 分析及压缩写出 | 0.702 秒 |
| 本次 executable 峰值 RSS（Linux VmHWM） | 29,312 KiB |
| gzip 记录 | 37,959 bytes |
| selected / applied transformation | 0 / 0 |

wrapper 的当前源码重放检查为 valid。内部可移植 resolver 文档仍保留
NOT_CHECKED，不把 wrapper 的调用变成可转借的证明授权；独立读者要重放给定的
源码与固定规则。三个输入哈希、报告哈希和实现版本已核对并归档。

这些时间是一轮 **SCAR 源码分析**，不是目标运行时间、clean benchmark、收益或
LeWM 加速比。值路径指导为 NOT_SELECTED/PENDING；import 删除仍为 NOT_PROVEN。
跨 import 的事实尚未接入 CONSTANT ledger，因此不把这些指导宣布为合法 rewrite。

## 反例审查与修复

1. 边界曾切断来源；现在保留 conditional binding，但不会漏过重绑定或 opaque 写。
2. 源码类型合法不能证明 SG edge 正确。AST 名称与 READ/WRITE/import 绑定槽核对，
   import requested 名与模块 edge 核对；篡改、过期源码均拒绝。
3. 相对 import 越过顶层、循环和同一初始化阶段的未来导出不能当成已存在值。
   正常 child import 与真正 cycle 分开，最终 namespace readiness 保留条件。
4. CONSTANT 不能夹带删除 IO 或动态差量；完整 premise DAG 收集逐跳 binding Q。
   bool/int、身份、资源失败和浮点环境各自检查，内容相同不代替身份证明。
5. DEAD 的内部 consumer 与外部 consumer 分开；DECLARED 空 effect coverage 和
   closed scope 各要求精确 Q acceptance，不能由空 trace 推出无效果。
6. 目标数、路径、派生工作及输出预算独立约束；超限不能截断路径后输出成功。
   固定索引和 memoization 避免每个节点重复扫描或重复求值整图。
7. 静态 CLI 不再提前初始化 Torch。测量初版 getrusage 继承启动链的 1,855,252 KiB
   高水位；`603819d` 改为当前 `/proc/self/status` VmHWM 并保留原指标及来源说明。
   初版也曾漏掉 checkout 的 PYTHONPATH；正式命令见下面，未改动整个环境。

以上是 SCAR 实现修复，不是目标程序 baseline defect 或性能优化成果。

## 复现与归档

```bash
cd ~/AAA/scar
conda activate lewm
python scripts/run_gate.py gates/g7_2a.json
python -m pytest -q
PYTHONPATH=. python scripts/measure_import_values_v2.py \
  testcases/static_imports/program.py --project-root testcases/static_imports \
  --out artifacts/reports/gates/g7-2a-import-example.json.gz
```

正式记录：`artifacts/reports/gates/g7-2a-verified.json` / `.md`、
`g7-2a-regression.json` / `.xml`、`g7-2a-import-example.json.gz` 和
`g7-2a-import-example.json.measurement.json`。目标 LeWM git 工作区仍干净。

下一步见 [G7_2B_PLAN.md](G7_2B_PLAN.md)。需要补实际证据模型和正向证明，而不是
添加 detector、backend 或把 UNKNOWN 改成 PROVEN。
