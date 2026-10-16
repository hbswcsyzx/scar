# M1：词法作用域、异常包与待完成控制值

日期：2026-10-16。状态：**C0 组件354项及冻结全仓3,027项通过；C1仍未实施。**
基准 `618cf83`，承接 [完整性清单](FIRST_STAGE_COMPLETION_MATRIX.md) 的控制缺口。
第一阶段仍为模型类型/组合与协议，自动 source lowering、运行采集和化简不在本批。

终版组件源指纹 `06773c8c8863910cffb70d5859e5019dc040f0a5e8903799abeb837bb52d4a53`
（356个产品/测试/门文件），driver 18.876s，四准则132/91/69/62项均PASS。
原始报告：`artifacts/experiments/b1_call_operands/model_control_interfaces/component/`。
新schema为 `scar.program-graph` v6；v5原始wire从 `618cf83` 隔离导出，旧v2—v5精确
roundtrip且v1 reader保持原合同。两项静态审查缺口已修：最近LOOP选择，以及已知callee
INVOKE的局部后继转发不等于跨Region实参。首次ProtocolValue类型漏接和runner/fixture
失败均保留，终态报告不覆盖原记录。C0不是完整finally，也不授权优化。

冻结 implementation `54eb7ec43f53218b968db5f8015c8187c88f40a9` 单次全仓回归：
3,027 PASS / 0 failed / 0 error / 0 skipped，driver 410.615s、峰值1,029,132KiB、
三项既有警告。前后HEAD、干净工作树、356文件源指纹及11个fixture hash一致。
只清理该driver专属临时目录；此为验收成本，不是LeWM benchmark。
证据位于上述根目录的 `full/`，终态范围见 `acceptance.json`。

## 1. 分批理由与完成边界

独立语言探针在 CPython 3.14.7 实跑19组：return载荷先求值，finally重绑定不替换
原引用，内容写入仍可见；cleanup保留原转移时用后态，新转移覆盖；局部loop控制、
异常context和bare raise也不可混同。探针不import SCAR，不证明产品已实现。

- **C0 本批：** canonical词法scope/强类型控制port、packet/pending协议Value、唯一
  构造表、共享入口/循环沿原CFG传递与case固定点、专用dispatch/载荷投影、严格wire。
- **C1 随后：** 完整cleanup入口/正常恢复/覆盖与handled-exception context状态协议，
  包括局部loop不覆盖外层pending、嵌套unwind、context安装/恢复和异常部分效果。
- **C2 随后：** with抑制、handler/except*等组合；suspend/resume仍需独立接口。

C0可声明CLEANUP词法scope，但没有可执行cleanup adapter，也不证明必须执行的
finally已接线。公开query/CLI的cleanup/unwind/context授权由代码固定为false，
不能从输入文档自报true。各批完成不替代整个M1/M2。

## 2. 唯一规范表达

```text
ControlScope(id, region, parent, kind, source, directly-owned blocks)
ControlPort(id, scope, completion kind, target block OR existing region exit)

ProtocolValue(id, region, OperationResult|BlockArgument, protocol)
ProtocolValueType(protocol)  # PENDING_COMPLETION / EXCEPTION_PACKET

ExceptionPacketDefinition(value, exception UseID, propagation-traceback UseID)
PendingCompletionDefinition(value, port, payload UseID or absent)

PendingDispatchTerminator(pending UseID,
    PendingSuccessor(port, block, ordered UseID|PendingPayload arguments) ...)
```

port.kind是唯一tag来源，不在Value和每条CFG边另存可修改的kind/payload副本。
ControlScope与ControlPort是既有Region/Block/exit的接口索引，不是新增业务节点或
另一套控制图；ProtocolValue是Value变体，pack/dispatch仍属于Operation。
ProtocolValue是SSA协议变体，不是Python对象、bool或普通数值。Return载荷是
Reference；Raise载荷是ExceptionPacket；其他变体无伪造None载荷。
packet显式引用本次传播的exception与traceback；合法None必须是实际引用，不能
用None掩盖未知来源。cause/context属性及handled-exception context属于当下状态，
不被packet或旧world快照冻结。C1会落实它们的完整状态协议。

scope是静态词法索引，不另建一张CFG。每个启用该能力的Region恰有一个FUNCTION根，
scope直接拥有的blocks不交且覆盖全部block，嵌套关系不得跨Region/成环。source
引用只是声明，非源码恢复证明。Return/函数Raise的port指向已有正确kind的exit；
Break/Continue属于最近活动LOOP，并分别指向该loop外/内。构造/dispatch点目标scope
必须活动；真正源语言目标及LoopInterface对齐仍需后续adapter见证。

## 3. 传递与dispatch

构造表只定义OperationResult；BlockArgument的pending来源由真实前驱的有序参数
推导。每个构造操作只pack协议载荷，不重复执行Python、不造额外state chain。
所有Use、producer、domination、当前StateVersion与逐边参数继续由原core校验。

对pending值按CFG做单调固定点，得到可能到达的ControlPort集合；专用dispatch的
case必须与该集合完全一致。不能Value自填union，不能遗漏、增加或按显示名匹配。
PendingPayload在相应case内投影已选载荷，Return→Reference，Raise→Packet；其他
kind不得投影。投影引用保持未知identity/alias，不能凭投影获得来源或纯性证明。
同一实际值跨不同边仍用独立Use。当前state通过原state参数继续传递，不塞进pending。

C0不猜跨region/外部pending边界的case全集；没有明确来源合同的pending不得用于
被认可的dispatch。packet native/invoke边界仍是声明，不证明exception有效性。
跨调用case合同、完整cleanup路由与handler上下文属于后续必需项。

## 4. 自主验收

| 门 | 证据 | 必须拒绝 |
| --- | --- | --- |
| C0.0 语言与records | 独立19组语言见证、严格constructor/enum/ID测试。 | bool位置、错namespace、错目标组合、重复端口。 |
| C0.1 core组合 | Return/Raise共享入口与state更新、循环fixed point、实际Use/producer查询。 | 错scope/跨区/循环owner、无定义token、缺/多case、错投影、错误port路由、旧world。 |
| C0.2 兼容与公开入口 | 从旧revision隔离生成v5 wire；旧v1—v5严格重放；新v6及CLI false授权。 | 旧schema夹带协议能力；packet/pending混用；输入自报cleanup已验证。 |
| C0.3 冻结验收 | 逐准则报告、独立审查、源fingerprint及全仓回归、版本归档。 | 组件数冒充整模型或LeWM建图/优化覆盖。 |

证据目录：`artifacts/experiments/b1_call_operands/model_control_interfaces/`。
原始失败保留；第一阶段仍未完成，不增加detector/backend，不修改LeWM。

## 5. 下一批C1的具体入口

[C1合同](../artifacts/experiments/b1_call_operands/model_control_interfaces/review/NEXT_CLEANUP_IMPLEMENTATION.md)
及[不确定效果补充](../artifacts/experiments/b1_call_operands/model_control_interfaces/review/NEXT_CLEANUP_UNCERTAINTY_ADDENDUM.md)
是Proposed设计。C1先定义当前handled-context保存/读取/恢复、相对本次entry anchor的
逐边must-forward与显式cleanup路由，再检验全出口覆盖及LIFO。port/constructor集合相同
不能证明载荷保持；普通最终dispatch不充当中间unwind路由。默认未知retention/回调
效果在所有已声明状态域产生保守后态，缩域须有证据或条件，不把未列域当NONE。
这些尚未实施，也不改变本批C0的source/runtime/cleanup权限为未证明。
