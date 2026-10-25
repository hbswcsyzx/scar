# 模块顶层的建模入口

本能力已实现并在保存的真实 CPU 采集对应源码上验证；模块内部仍未完成。
它属于通用 Python 前端，未使用 workload 名称或业务规则。

函数入口不能代替模块入口。模块代码通过 locals、globals、保存的 builtins
命名空间解析名称；这些输入可能 alias，不能根据不同图端口推断对象不同。
模块根代码也可能经 exec 等途径进入，不能仅凭 `<module>` 或 root CodeWitness
推断一次 import、ModuleObject 或 sys.modules 状态。

`ModuleUnitSource` 引用原源码快照、原 namespace 和已有 MODULE initializer，
不伪造函数定义或源码 atom。独立 `module_entry_catalog` 自动枚举已有模块根；
`PreparedSource.lower_entry` 要求只读编译根见证。`MappingFrameEntry` 显式传入
三个借入命名空间和 world。区域在正常和异常两种出口分别携带完成值与 post-world；
异常不表示命名空间修改自动回滚。

SourceProgram6 使用显式 mapping-entry 类型；原 v1–5 函数路径和默认能力保留。
目前生成外层 frame 和子 body 两个 Region。子 body 仍是保守接口，记录原源码
上下文及 `REQUIRED` 展开债务，不能把 UNKNOWN effects 解释为无副作用。
9 个构造操作表示入口协议，内部语句恢复数为 **0**。

实际门使用原 586B 源码与归档代码，核对 95 source atoms、92 OperationDefinitions、
45 CFG nodes、56 edges，普通 SourceProgram6 读回通过；四项非法声明被拒绝。
worker exit0、outer 4.3214s。主树接入只追加独立 catalog，原 worklist 的全部 AST
节点保持；同一 v6 和一份既有 v5 的正常读回 exit0、4.1948s，没有重新 lower。
producer 的字段名与 census 取表错误、主树检查脚本的 witness 层级错误均保留失败记录。

后续应把内部语句按原源码/控制位置展开，接通 namespace 读写、import 及异常清理，
并保留未展开部分的明确接口。源码模型不代替实际 activation、namespace identity
或状态证据。本次没有发布新完整程序快照、运行绑定或优化，第一阶段仍 OPEN。

原门见 [REPORT](../artifacts/experiments/module_mapping_entry_g1_20261025/REPORT.md)，
主树接入见 [APPLICATION](../artifacts/experiments/module_mapping_entry_applied_20261025/APPLICATION.json)
和 [读回结果](../artifacts/experiments/module_mapping_entry_applied_20261025/RESULT.json)。
