# Source call port binding：实施与待验收

2026-10-26，隔离树 `source-entry-project`，四生产文件；candidate01已因缺原输入在普通 composition 读取阶段失败，未进入 consumer。candidate02已补正常依赖闭包并冻结，未运行。

`SourceCallPortBinding` 引用既有 `CallSiteLink`、两个 `CodeSourceLink`、原 attempt /
handshake / entry anchor 与双方 InvocationKey。每个 `SourceArgumentPort` 把既有
调用实际 `UseID/ValueID` 和正式 `ValueSlotID/ValueID` 限定在原 body artifact、
原 namespace、Region 与 composition 声明 locator 下；复用正常 `CandidateBinding`
和 `ParameterBinding`。这些都是有条件的源语言端口关系，不证明动态引用或内容相等。

`analysis.source_call_bindings` 只接收正常 linker 当前 `_Sources`、call model 和
operand scan。完整 attempt 分母每项恰有 binding 或具体 issue；不造 load anchor、
ValueOccurrence、CallActivation，也不以保存的报告恢复 owner。支持一般显式位置表达式；
无 star/keyword/default/隐式 receiver/variadic/kwonly/suspension。监控 `arg0` 是首个实参，
不被当成 receiver 标志；显式 AST 参数数、原 CALL n、EXACT_FUNCTION 及实际 entry
code/layout 共同限定首规则。源码、CodeWitness、capture gaps、invoke 有序 Use 与正式
端口仍由正常读者实核。

`link_call_operands` 新增显式可选 `(model, check_binding)` consumer 与 typed budget；
`connect_current_capture` 仅透传到原 owned linker。默认均 None。原 ArgumentRoute、
CallOperandReport 返回值/summary/wire/27组窄引用规则不变。

`SMALL_CHECK02.json`：15项类型/严格 codec/API 小检查通过，含 monitoring arg0 存在的
非零参数 dispatch；不授真实 source/runtime 资格。初版小检查和 receipt 原样保留。
`candidate01/API_CHECK.json` 核已有 original-code-source/ancestry API 与正常读器导入；
旧 API 检查 receipt 路径错误保留为 `API_CHECK_FAILED01.json`，未读图或 raw。

唯一真实门 `candidate01/run.sh` 复用 source858 原脚本与原数据 URIs，完整 fresh owned
orchestration；不恢复旧 owner、不重 lower/prepare/target。正常新模型全量 codec 读回，
同一 fresh session 对真实非零 binding 正核及 call-source/slot/caller/arity 四个语义反例，
再列旧27组与新端口关系的交集、遗漏具体原因和新关系全分母。2656 的新增覆盖不预估。
运行和最终结论由 Root 实际终态确定，整个程序保持 OPEN。
