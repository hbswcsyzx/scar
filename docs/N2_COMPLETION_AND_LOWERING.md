# N2 实现协议：完成边和自动源码连接

日期：2026-10-15。状态：N2.a 范围已实现验收，见 [N2A_ACCEPTANCE.md](N2A_ACCEPTANCE.md)；
不代表完整 N2 或 LeWM 自动建图已验收。
接续 N1，实现从真实源码构图所需的完成方式与连接。

## 必要的模型调整

未知 Python 参数和普通表达式结果使用 ReferenceValue，保留未知身份和目标；
不要求用户声明其类型。精确 builtin scalar literal 也可由 ReferenceValue 的
LiteralOrigin 表示 Python 常量对象；数值载荷可知，身份仍不能随意合并。
DataValue 继续表示逻辑数据，例如控制流需要的 builtin bool。

新增以下内部接口，不新增顶层实体类别：

```text
CompletionSignature(kind: ExitKind, types: tuple[ValueType,...])
CompletionResult(index: int)
CompletionSuccessor(kind: ExitKind, block: BlockID,
                    arguments: tuple[UseID | CompletionResult,...])

TerminatorKind.INVOKE
Terminator.successors: tuple[Successor | CompletionSuccessor,...]
Operation.completions: tuple[CompletionSignature,...] = ()
Operation.invoke_arguments: tuple[UseID,...] = ()
```

INVOKE 位于块末尾，固定 NORMAL/RAISE 两条完成边和两个签名，且没有普通
Operation.results。结果经 CompletionResult 注入对应后继的 BlockArgument，
不能在 invoke 的所在块提前使用或跨完成路径使用。每个完成边暂有自己的
独立后继块，避免把结果定义混入有其他前驱的 join。

UseID 转发已存在的值；CompletionResult(index) 仅选择**本完成边**签名的
结果。每个产生的结果必须准确绑定一个目标参数，每个转发端口使用独立
UseID；数据和状态都不能漏传、重复或更改类型。

动态 Python 操作与 truth conversion 可读写 coarse opaque world 状态。
每条完成边返回自己的后状态，异常后不能回滚到操作前的状态。已知无写的
域可以通过 UseID 转发当前状态；未知效果不能标为 effects_complete。
这只是保守状态接口，不声称已恢复具体 Tensor/文件等细粒度位置。

普通 JUMP/BRANCH/RETURN/RAISE 和 N1 同步 call 保持原接口；INVOKE 才允许
completions。callee 已明确时，其正常/异常签名与 callee 的退出接口匹配。
动态调用也能保留显式 callee 引用，具体 body 对应要区分候选与已确认。

序列化升级为 scar.program-graph schema_version=2。严格读取历史 version=1
时，仅为 Operation 增补空 completions/invoke_arguments；不能在历史版本中偷带新字段。

## 自动连接器

使用既有 build_semantic_files、extract_source_semantics、
build_source_control_flow 生成并核对源码记录。根据同一快照的 AST statement
和精确 source span，连接参数、当前局部绑定、逐路径 join 和返回。
表达式 opcode/有序 operands 复用旧记录，生成节点有独立的 typed 来源说明。

第一批支持同步普通函数、必需参数、scalar literals、Name、局部赋值、
if/else、return、普通表达式调用及有限源码可展开的函数体。未知表达式类型
仍可通过 reference 和 INVOKE 表达；不通过手工参数类型获得自动化完成率。

源码 graph construction 和合法性证明分开：旧 MAY_RAISE、dispatch、绑定及
frame/namespace 条件保留；静态候选不能升级成已观察的运行 callee。若无法
完整恢复某构造，报告具体源码边界，不把正常流投影标为完整函数。

编译期作用域直接使用 Python symtable：不可达 import/del/except target 仍然
影响 local 判定。generator 即使 yield 出现在 return 后也不能当普通同步调用；
closure/cell 的状态接口尚未连接时明确拒绝。每个操作/use/value 的源对应、
条件候选接口和汇总都接受确定性重放，不能通过修改摘要获得更强权限。

## 验收

1. 自动构建有参数、两分支局部定义、真正 join 和返回的 `.py`；不手工补图。
2. 未知参数的 truth conversion、算术和 call 保留 NORMAL/RAISE 以及后状态。
3. 正常结果不能在异常路径使用；错误完成签名、参数位置、状态倒退都拒绝。
4. 两个调用位置的 callee 输入和返回独立，共享 body 的对应声明可重放核对。
5. 修改 + 为 *、改名、重绑定、源码/映射篡改有独立反例；不读 label 猜规则。
6. 记录覆盖、条件、缺口和成本；没有新 backend 或已验证 LeWM 加速声明。
