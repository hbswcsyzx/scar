# N2：从源码记录构造程序类型与依赖图

状态：规划已完成，待实现；N1 已验收。允许按反例调整模型，调整须同步
类型、构图规则、测试和报告。N2 不新增 backend，不改外部 testcase 源码。

使用目标：用户提供程序入口/运行命令，SCAR 自动拆解、抽象、建图和报告。
手工 IR 只用于测试校验器及反例；它不能成为实际 workload 的输入要求。
不得通过手工补 LeWM 图节点、连边、pure 标记或变量版本来验收自动建图。

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

## 自动 LeWM 建图的后续压力验收

通用小程序门通过后，以原始 LeWM 入口和既有成功命令执行压力验收。程序名、
包名、函数名和变量名不进入 SCAR 化简规则。采集和报告仍由通用入口执行。

1. 自动选择入口及依赖范围，绑定源码快照；实际读取/分析范围必须列出。静态
   可达范围与一次运行经过的范围分别记录，未执行分支不能从程序模型删除。
2. 自动生成参数、局部定义、逐路径合流、循环携带值、读写状态及调用接口。
   每个 executable source atom 必须对应操作/控制/定义记录，或有定位明确的
   未支持边界；comments/纯结构不能被计算成实际工作。
3. 自动关联 nn.Module/operator/runtime 调用的输入结果与静态操作，分别报告
   数据、状态、控制、alias、完成方式、资源证据的覆盖。节点数量不能替代
   正确连边率或可证明边界的数量。
4. 至少用自动生成的图回答：一个 cost 调用的输入来自哪些层；哪些输入随
   CEM 迭代变化；已有 embedding 缓存的填充和命中路径；CPU 物化结果的
   消费者；目标常量路径与 import 初始化残余依赖。失败时返回具体断点。
5. 不人工修图。任何断点由通用构图/对应规则修复，先增加通用反例，再自动
   重建 LeWM 图并比较版本。全部本门指标需产出机器可读报告。

这些是 N2/N4 的后续验收要求，当前尚未完成。覆盖边界与优化 legality 是
不同指标；保留未解析的调用并不意味着已经证明其全部读写效果。

## 关键难点与实现办法

| 难点 | 实现办法 | 验收证据 |
| --- | --- | --- |
| 参数跨层传递、重绑定和分支/循环合流 | 基于 lexical slots、逐路径定义和基本块参数连接 actual/formal；每个 use 保留位置 | 自动构图的分支、零次循环、回边与重复调用反例 |
| 同对象内容变化、不同对象共享位置或来源 | 静态引用/访问范围分析，接已有对象/分配/provenance 证据；读写推进独立状态版本 | 原位写、NumPy 共享修改、view、复制和地址复用反例 |
| 动态调用、hooks、descriptor、import 初始化 | 源码递归展开与通用库操作接口，运行时确认动态目标；不能展开时保留具体效果/目标缺口 | 重绑定、隐藏状态、RNG、异常和初始化残余依赖反例 |
| Python 调用与 GPU 实际活动不一一对应 | typed 对应和 runtime operator/kernel/copy/sync 证据，区分 host return 与 device ready | 同设备 to、expand、跨 stream 完成顺序及实际 copy 证据 |
| 能建图但不能指导化简 | 按 Q 观察根做依赖闭包，实施常量替换、子图共享、上移等精确 delta，并检查残余效果和成本 | before/after 的精确消费者改接、proof ledger 和验证范围 |

运行类型和稳定性尽量由源码/库规则/现有执行证据自动恢复。无法自动确认时
报告缺失事实和可执行采集步骤，而不是要求用户为每个 Tensor 人工标类型或
纯性。早期测试中的 DECLARED 假设必须明确标识，不计入自动推导成功数量。
