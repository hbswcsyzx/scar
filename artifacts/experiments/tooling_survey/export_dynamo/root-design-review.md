# Root tooling/integration design review

2026-10-16. **只读设计审查；未运行新实验，未修改共享文档。**
范围：Export/Dynamo/AOT、导入与原程序的身份/状态关系、阶段边界。
不替其他审查者验收 ETO、CodeQL、LibCST 等工具的独立实验。

本次读取版本：

- `docs/TOOLING_SURVEY.md` SHA256
  `ae07fcd4d3bf68abe9c247ed788b5766da322fe1db9d7c06cef004509e0834e6`
- `docs/MODELING_INTEGRATION.md` SHA256
  `0ef02b0f912924b3234d11948a7a1053070aff7305d2badcaa687fbe5a069adc`
- 依据：本目录冻结 `REPORT.md`、`results.json`、对应 installed-source manifest。
  以下行号针对上述版本；后续修改应重新核对，不覆盖本审查的历史依据。

## 总评

**研究事实与阶段说明通过；T1 适配合同还需三处补强/纠正后冻结。**
没有发现文档把本轮工具研究冒称为已实现集成。下面前两项是新设计的可执行
约束缺口，不是声称当前已有 adapter 出错；第三项是明确的行为描述不准确。
不要求增加实验、lowerer、trace 或 backend。

## 1. 高：规范化图的来源不能直接成为原 Region 的 canonical 展开

位置：MODELING_INTEGRATION.md:27–29、73–87、91–102。

文档已正确说明 pipeline 阶段、alias/identity 限制和 many-to-many 对应，但
“Tensor 子图嵌在对应 Region”“导入后只在 canonical core 有一个规范来源”
尚未明确：**什么证明允许把 provider graph 的输入/结果关系当作原程序关系。**
适配规则存在与该规则适用条件已满足必须分开。否则仍可能把数值形式导入后，
在引用查询中静默沿用源程序的输入/返回身份。

实际反例：冻结 `mutations_and_signature` 中，原 training 图返回 view 与 x
alias=True；`run_decompositions({})` 模块输出数值相同，但该 view 与 x
alias=False。两个图的 x 同名、source stack 相同、签名也可路由，仍不能把
相应 view result 合并为一个表示原 Python 引用的 canonical Value。

最小修改建议：补一个强制规则：

> 导入节点按 `(artifact, stage, provider node)` 标识。其 canonical def-use
> 描述该 provider 表示；与原 source Region 是带条件的 correspondence。
> 只有边界的 payload/state/alias/identity/completion 对应已逐项成立，才能
> 标为原 Region 的语义展开；否则保留为带边界缺口的派生表示，禁止覆盖原
> source Value、producer 或状态链。

同一 ProgramModel 可容纳这些 Region 及对应，不需要第二套可修改的事实图。
建议边界字段分开记录：`provider_artifact/stage`、`source_region`、
`port_routes`、`preserved_domains`、`unresolved_obligations`、`evidence/rule`；
不能只靠一个 adaptation-rule 名字授予全部域的等价关系。
负例必须拒绝上述 view 的无证 identity/alias 合并；数值对应可独立保留。

## 2. 高：lifted state 的实例绑定与当前版本应为必填关系

位置：MODELING_INTEGRATION.md:62–71、94–104。

现有 envelope 明列源码/code、ordered ports 和环境 assumptions，但没有明确
要求 **lifted 参数/buffer/constant slot → 具体环境引用及规范 state use**。
“将导出状态写接到父 Region”不能仅由 signature.target 字符串完成。

反例：两个同类 Module 实例，均有 buffer 名 `b`，代码与 shape 相同，但内容、
生命周期和原位写各自不同。或者同一个 Module 先后调用时 b 已修改。把
BUFFER_MUTATION(target='b') 直接接到同一个静态位置/初始状态会错接实际依赖。
模块 clone/deepcopy 后的 exported state 也不能无证回填到原实例。

最小修改建议：将下列关系加入 T1 必须满足的字段/校验规则：

> 每个 lifted slot 绑定其 capture 的 module/environment 身份、属性/slot
> 路径、原始引用来源和调用时的规范 StateVersion Use；多路径共享对象或
> storage 的 alias 必须保留。路径名不构成实例身份，shape/guard 不构成
> 内容版本。只有 provider 状态而缺原程序对应时，保留未连接义务，不补造
> parent state；正常 mutation 输出写回与异常期间已发生效果分别保留边界。

静态 Program 声明允许每 activation 实例化；dynamic instance/version 通过
已有 occurrence correspondence 接入，不把动态实例 ID 反塞进静态类型。
这补充的是已有 state 模型的导入约束，不要求新的状态图。

## 3. 中：guard 失败不能统一描述为“原程序继续可用”

位置：MODELING_INTEGRATION.md:103–104。

该句混淆 Dynamo 的 specialization 选择与独立 ExportedProgram 调用行为。
冻结 `guards_specialization` 中 batch=2 或 flag=False 都直接抛 AssertionError。
原 Python 程序在某些未捕获路径也可能自行抛异常，不能由 guard 失败推出成功。

建议替换为：

> guard 不满足只说明当前 specialization 不适用。根据 provider 的运行
> 协议，可能重编译、回到 eager 或拒绝调用；独立导出模块不会因此自动
> 具有 eager fallback。原程序的控制、异常和状态行为仍按其自身模型保留。

依据：[Dynamo guard model](https://docs.pytorch.org/docs/2.14/user_guide/torch_compiler/torch.compiler_dynamo_overview.html)
及本机 `results.json` 的两条实际 guard rejection；两者不可混为一个执行合同。

## 已核对通过，不需扩大修改

- TOOLING_SURVEY §3.3、MODELING_INTEGRATION §4.1–3：raw export 可能保留
  mutating ATen op，USER_OUTPUT-only 不能证明无写；decomposed 阶段显式
  BUFFER_MUTATION、USER_INPUT_MUTATION、PARAMETER_MUTATION。与本机实测一致。
- AOTAutograd 的前后向角色正确；没有把旧 private aot_export_module 的
  参数 mutation 限制硬套到 public export。建议引用固定 build/source 位置
  作为实施依据，但无需重跑。当前文字没有宣称 AOT 会捕获整个 optimizer/host。
- guarded specialization 不证明 logical value 相等；Python list append 和
  global scalar 特化的说明准确；functionalize 不提供原执行身份记录。
- 有序 duplicate use、版本化 source metadata、缺失不得按名字补猜等规则正确。
- 受控 replay 独立进程并不消灭文件/网络外部效果；文档已要求外部效果边界及
  不能安全重放时保留缺口，无须额外扩展本轮采集机制。
- T0/T1 与 T2–T4 的区分清楚，第一阶段停止点明确。source/Tensor/EEG 的目标
  结构是设计要求，尚未被误报为完整自动来源。没有理由因此提前进入建图或化简。

补正上述三项后，可在本次审查范围内冻结设计。此结论不是整个工具包能力、
所有协议、全 M1/M2 或完整程序建模的验收。
