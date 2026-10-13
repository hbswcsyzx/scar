# N2：从源码记录构造程序类型与依赖图

状态：规划已完成，待实现；N1 已验收。允许按反例调整模型，调整须同步
类型、构图规则、测试和报告。N2 不新增 backend，不改外部 testcase 源码。

## 已核对的实现基础

| 现有代码 | 复用内容 | 必须新增的连接 |
| --- | --- | --- |
| `scar/ir/frontend_v2.py` | SourceAtom、函数和参数槽、READS/WRITES_SLOT | slot 到每条路径实际值的映射 |
| `scar/analysis/source_semantics_v2.py`、`scar/ir/semantics_v2.py` | typed Opcode、有序 OperandUse、StaticBinding/BindingUse | 参数初始化、逐前驱 merge、调用后绑定 |
| `scar/analysis/control_flow_v2.py` | suite、statement/control/exit 骨架和缺口 | 新 Region/Block/精确参数绑定 |
| SourceSnapshot、现有 replay checker | 源码版本、位置及重放核对 | 新旧 operation/value/source 的 typed correspondence |

实际代码当前故意不为函数参数种入精确 binding；if 后清空精确环境，call
形成 barrier。CALLS 是候选目标，不是确定的运行绑定。这些不能通过把
UNRESOLVED 标记改为 EXACT 来解决。

## N2.a：有限自动源码转换

选择调用方指定的普通同步函数入口，读取提供的源码，不 import 或执行目标。
支持普通必需参数、builtin scalar literal、Name、单目标局部赋值、return，
逐步接入有限 if/else 合流与同模块明确绑定的普通调用。

转换器读取同一快照的 statement AST 以连接控制，表达式类型和位置优先使用
现有 OperationSemantics。每个生成节点记录其来源，不新写一套按名称猜测
含义的表达式分析器。

第一个正例必须从真实 `.py` 自动构造：参数 → 分支局部定义 → 合流 → 返回。
第二个正例是不同调用位置共享函数体，实际输入和返回 use 保持独立。测试
不得在构图之后手工补参数或合流节点以获得通过。

### 保留具体操作身份

N1 Operation.behaviors/label 只表达结构及行为类别，不指定 ADD 或 MUL。
N2 用强类型对应记录连接：

```text
Program OperationID
    -> existing OperationDefinitionID / OperationSemantics
    -> Opcode + ordered operands + dispatch
    -> SourceReference + SourceSnapshot
```

合流、参数和退出等生成节点也要有可追溯来源。复用旧 Opcode，不再复制
第二套枚举；不能把关键关系塞进无约束 metadata。

### 不隐藏类型、目标与完成方式的缺口

- annotation 不是运行类型证明。类型可来自可证明的 literal/call 输入，或
  明确且标为 DECLARED 的类型条件；报告区分来源和可信度。
- `if x` 可能调用 truth conversion。没有精确 bool 来源时，明确报告转换
  与效果缺口，不偷补 builtin bool。
- opcode 确定不代表 dispatch、效果或异常确定。未知部分按字段报告。
- 直接调用需要目标绑定条件。不能仅因同文件存在 helper 定义，就当作不变
  callee；重绑定必须改变结论。
- 保留既有 MAY_RAISE 边。N1 无 invoke lowering 的场合，先报告未覆盖完成
  方式并拒绝输出“完整函数图”；effects_complete=False 不能代替异常路径。

普通分支与调用确实需要的控制/接口类型可以扩展，但必须先增加针对反例。
不为保持 N1 API 原样而丢弃必要关系。

## N2.b：循环和明确状态访问

在 N2.a 通过后接入循环参数/回边/零次路径；对可核对规则支持的位置访问
构造 StateLocation、read/write、alias 和状态合流。动态 descriptor、loader、
反射以及一般 PyTorch dispatch 若尚未支持，保留具体边界及源码定位。

该门产出应能区分“操作已分类”“依赖已恢复”“效果已覆盖”，不能把全部源码
节点入图当成全部路径/效果已解决。具体首批状态操作按实现审计选择。

## N2.c：旧图、运行证据与覆盖报告的接口

保持 SG/EEG/OIR 分工；静态 source identity 不是已加载运行 CodeID 的证明。
建立 typed correspondence 后，再接已有 trace 的运行实例。按当前证据不足
项决定是否采集；不为完成静态转换重新扩大 collector。

## N2.a 验收标准

1. 从源码自动构图，N1 require_valid/codec roundtrip 通过；报告包含选择范围。
2. 改变量/函数名不会改变规则；ADD 改 MUL 必须改变 typed opcode 对应。
3. 分支单边未定义、未知 truth dispatch、目标重绑定、默认参数/装饰器、
   未覆盖异常调用各有明确缺口，不输出误称完整的图。
4. 重复调用 actual/formal/results 与多条分支参数不能混用。
5. 源码、旧 overlay、CFG 或新对应关系被篡改，重放必须失败；复用现有
   validate_source_semantics/validate_source_control_flow，再确定性重建新图。
6. 分别输出结构有效性、源码映射覆盖、类型/绑定条件、效果/异常覆盖；不
   输出纯性证明、优化审批或 LeWM 加速结论。

每个子门由开发代理验收、记录失败和修复、冻结实现提交、归档报告并推送。
之后进入 N3 的依赖闭包与子图化简指导。
