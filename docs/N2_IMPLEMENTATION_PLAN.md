# N2：从源码记录构造程序类型与依赖图

状态：N2.a 有限函数体门已冻结验收，见 [N2A_ACCEPTANCE.md](N2A_ACCEPTANCE.md)；
N2.b0 的入口范围与接口清单也已有限验收，见 [N2B0_ACCEPTANCE.md](N2B0_ACCEPTANCE.md)；
完整 N2 尚未完成。允许按反例调整模型，调整须同步
类型、构图规则、测试和报告。N2 不新增 backend，不改外部 testcase 源码。

N2.entry 的运行来源桥接也已有限验收：429 gate / 1,477 回归，原外部入口
自动生成和严格重放通过。实际覆盖见 [N2_ENTRY_ACCEPTANCE.md](N2_ENTRY_ACCEPTANCE.md)。
只有一个来源候选定义接到核心区域，不能据此接受整个 N2。下一门先按
[N2_SIGNATURE_PLAN.md](N2_SIGNATURE_PLAN.md) 处理全局调度与 formal/定义/绑定接口。

当前自动化能力、公共命令与后续自验要求见
[AUTOMATIC_MODELING.md](AUTOMATIC_MODELING.md)。完成方式和源码连接的实现协议见
[N2_COMPLETION_AND_LOWERING.md](N2_COMPLETION_AND_LOWERING.md)。

N2.b0 外部清单已显示两个必须先处理的连接问题：动态执行的入口源码不在
import 闭包内；按文件导入距离安排的 256 次 body 预算覆盖不到多数函数。
N2.entry 已将通用运行代码来源接回候选范围；完整 loader 和沿入口调用/use
接口安排全局预算仍未完成，不能用手工文件列表替代。签名/定义时接口与函数体分离，循环设计
见 [N2B1_PLAN.md](N2B1_PLAN.md)；当前仅为提案。实测范围与优先级见
[AUTOMATION_PROGRESS.md](AUTOMATION_PROGRESS.md)。

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

### 本轮审计后的细化顺序

N2.a 的公共入口仍需用户选择函数体；这不是目标中的运行命令到全程序自动恢复。
LeWM 三个外部核心文件的只读 AST 盘点包含 35 个函数体，暴露循环、属性/下标写、
默认值、装饰器和运行时注入调用等缺口；它不是自动构图成功率，也不是性能证据。

1. **N2.b0 自动范围与接口清单**：从入口建立模块/定义/候选依赖索引，自动列出
   每个函数体、调用边界及未覆盖构造；区分源码可达候选与本次运行确认范围。
   多文件快照统一绑定；参数默认值和装饰器的定义时操作不能混入 body。
   验收：改名无关、模块重绑定、同名方法、缺源码、动态注入均有定位明确的
   报告；不能需要用户逐个点名函数或手工修复图。
2. **N2.b1 循环与表达式控制**：有限循环体、零次路径、回边、break/continue/else，
   再接短路与推导式的作用域。验收逐前驱值/状态绑定和异常完成，不把循环
   静态节点视为跨迭代相同值，不以展开 trace 代替循环。
3. **N2.b2 状态精化**：属性、下标、容器和 Tensor 的读写位置及别名范围，逐步
   将 coarse world 分成可核对域；加入 try/with 的退出、finally 和异常抑制。
   验收原位写、共享内存写、部分覆盖、隐藏状态和外部效果不能丢。
4. **N2.c/N4 运行对应**：针对清单中的实际断点连接现有运行实例或最小采集，
   确认动态目标/代码版本、值 occurrence、实际 transfer 和完成顺序。每次只
   为可明确验收的缺失事实采集，不重新制造大体积 profiler 数据。

每一步均先设计强类型记录和不变量，再写连接规则、通用反例和外部自动重建报告。
不先增 detector/backend；依赖和效果可用后再接 N3/G7 的化简指导。

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
