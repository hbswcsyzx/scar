# 当前架构与迁移边界

唯一开发主线是纯静态程序建图，流程及展开规则分别以 [STATIC_ANALYSIS_DESIGN](STATIC_ANALYSIS_DESIGN.md) 和 [PROGRAM_DECOMPOSITION](PROGRAM_DECOMPOSITION.md) 为准。

## 复用现有代码

| 模块 | 当前用途 | 需补齐的边界 |
|---|---|---|
| `scar/analysis/source_discovery.py` | 不执行目标的源码/import 候选发现 | 从源材料形成完整静态目录，不以捕获调用入选 |
| `scar/ir/frontend_v2.py`、`source_semantics_v2.py`、`control_flow_v2.py` | 版本化源码、绑定/操作语义、CFG 与查询 | 源码层与规范图之间保持显式对应 |
| `program_lowering.py`、`structured_lowering.py`、`source_*_lowering.py` | 源码文本到规范结构化 IR | 扩展纯静态入口与语言构造，不强制运行见证 |
| `scar/ir/program/` | Operation/Use/Value/State/Region/Resource、验证、查询、codec | 作为唯一规范程序结构；不创建平行权威图 |
| `constants_v2.py`、`import_values_v2.py` | 有限静态常量与导入值推导 | 扩展到上下文相关的抽象事实与约束传播 |
| `effects_v2.py` | 已有效果维度与显式摘要组合 | 增加以静态定义为范围的自动摘要推导，不伪造运行 ObservationScope |
| `scar/store/` | 分片、ID 引用和已有序列化能力 | 复用可用部分，不要求数据库或巨型单文件 |

源码层、规范程序图和分析事实是不同职责的视图/记录，通过明确 ID 对应，不能各自重建互相矛盾的 producer/state 图。

## 冻结的实现

`scar/trace/`、运行证据图、旧 candidate/planner/backends 当前不开发、不调用，也不作为静态完成前置。当前仍被 CLI、规范模型或兼容接口引用的实现不能仅凭文件名批量删除；删除需先查清依赖。
历史 gate 配置、实验脚本副本、旧报告和额外 worktree 已清除。通用 `scripts/run_gate.py` 仍被已有工具导入，因此保留其有效代码，而不保留失效的 gate 清单。

## 静态入口的关键改动

`prepare_source_text` 已不需要目标执行。现有 source-entry worklist 的 CapturedCode/CodeWitness 入选规则属于运行对应路径，不应被新静态目录继承。
静态定义来自源码及显式上下文；纯源码可推导的编译结构直接记录，实际加载身份留空。
现有受支持语言 lowerer 优先复用；要求真实代码对象身份的路径必须拆出源码规则，不能靠伪造运行见证通过。

## 当前缺口

整程序纯源码目录和逐文件源码图已接通，词法作用域与 import 候选索引可查询；完整语言展开、跨过程候选绑定、抽象堆/别名、自动效果摘要、联合不动点、Tensor 属性/关系传播和统一静态导出尚未贯通。已有局部验证不代表这些能力完成。

## 当前静态命令实现

`scar static` 走 `static_program.main`，不进入历史 capture 工作流。
`static_sources` 管源材料，`static_lexical` 管原 AST/symtable 目录；源材料和目录不是第二套程序图。
`static_program` 按文件复用原 frontend/source-semantics/CFG，四进程可并行；`static_imports` 连接原 source/unit/initializer 候选；`static_query` 读取原记录。
源文件文本保存一次，分片附 stored/decoded SHA。细化通过同一 current 目录发布，复用未变化图，不创建历史副本。
当前 import 索引尚未解析缺少的外部库源码和导出绑定，源码图中的协议缺口也未消除，不能作为全程序 ModRef 或内容等价证明。

`static_compilation` 是不执行目标的编译布局来源，`static_rules` 从原AST选择已有规则及前提；`static_body` 复用原源片增量构造canonical子图。静态编译与捕获见证是有标签的独立来源，语言overlay的普通validator仍校验对应接口和协议，不把编译器布局当成运行身份或纯性。
