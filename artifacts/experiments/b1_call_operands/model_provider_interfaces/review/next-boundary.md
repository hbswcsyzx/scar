# P1 native boundary / BoundaryRelation：实施前风险审查

2026-10-16；产品冻结 `35469f0`。只读现有 model/environments/resources/provider
validator，以及已有 `tooling_survey/export_dynamo/REPORT.md`；未跑测试、采集或
LeWM，未改 tracked 文件。以下是需落实的接口条件，不是 P1 已实现的声明。

## 1. P0 仍未验证的事实

P0 验证的是声明内部与 canonical core 的一致性：归属、端点类型、producer/Use
owner、独立路径不折叠。它**没有读取 artifact**，因此尚未验证：

- external.key/path 是否真实存在、路径容器/kwargs/结果投影语义是否正确；
- 原生 signature 的 input/output 位置、参数角色与完整槽位分母；
- completion index 是否对应原生正常/异常结果，或与 core 返回/完成端口相符；
- ProviderCoverage.COMPLETE、条件/evidence locator 是否真实；
- representation 是否等价于原 Python 区域，或 capture 对环境产生了哪些影响。

`provider_validation.py` 对 CompletionResult/PendingPayload 的 producer 推导，
只校验 **core 中已有的投影来源**，不能证明 external path 的索引真实。P1 不应
把 P0 roundtrip、相同 key 或非空 path 作为上述事实的证明。

## 2. 最小 native boundary 字段

以下字段形状供 root 冻结；不要求另造实际参数/状态表。

| 记录职责 | 至少需要引用的字段 | 不应重复存储 |
| --- | --- | --- |
| NativeBoundary | provider、owned Region、signature fact、call/input/output TreeSpec facts、API/stage | envelope 内已有版本、原始 artifact、pipeline 的另一份可变副本。 |
| NativeInputSlot | signature position、native role/target、外部 value coordinate、来源 fact | actual ValueID 数组；canonical entry Value 由现有 ProviderBinding 唯一导出。 |
| NativeOutputSlot | signature position、native role/target、外部 use coordinate、完成端口引用、来源 fact | 独立返回值/producer 表；值从该 canonical Use 导出。 |
| CompletionPortRef | Region exit name + index，或 INVOKE operation + ExitKind + index 的严格变体 | 重新抄一份 types、state 或调用结果。具体 Use/CompletionResult 从原 core 派生。 |
| BoundaryRelation | 原 Region、representation Region、适配规则/独立 adapter Region（如需要）、限定端口对应、条件、逐域 obligations/evidence | 第二套 call_arguments、EnvironmentBinding 或 state before/after。 |

对输入/输出树必须保留空容器、None/常量、kwargs key/order、聚合结果与投影。
有序 signature position 不是 core 物理 offset。native kinds 必须版本限定，未知
kind 保留明确缺口；不能默认 USER_INPUT/USER_OUTPUT 或强行猜 state role。

BoundaryRelation 的端口对照表示**不同表示的声明接口关系**。真正某次静态 call
site 的实际路线仍由 `callee` + `call_arguments`/`invoke_arguments` 导出；动态
activation/instance 匹配另需未来证据，不借端口对照伪造。

## 3. lifted 参数 / buffer：至少连两种状态

`target='sub.weight'` 不是对象身份，也不是 LocationID。正确连接至少是：

```text
原调用的实际 module/self reference
  -> 属性/容器 lookup（消耗当前 binding/namespace state）
  -> parameter/buffer Tensor reference
  -> 内容读取（消耗该 Tensor 当前 content state）
  -> imported Region 的准确 lifted entry reference
```

上述 lookup/读取若已经在 core，BoundaryRelation 只引用准确 Operation/Use/entry
Value；状态读写仍由已有 StateAccess 表示。原 Python 函数的 self 可能是
FunctionEntryLayout 的普通 formal；不能把 EnvironmentMember.FUNCTION_OBJECT
冒充 module 实例。captured global/cell 则应沿真正环境成员引用与当前状态读取。

连接不变量：

1. parent actual Use 必须通过现有 call 路线对应 child 精确 entry ValueID；
   state 参数按 LocationID/current SSA 连接，不按 placeholder 顺序或名字猜。
2. namespace rebinding 与 Tensor content mutation 都可能失效。仅保留 capture
   时的 Tensor/weight snapshot，或仅检查 Tensor storage，并不覆盖参数重新绑定。
3. 同名 target 属于不同 module 实例时不能共享 Location。多个 formal/reference
   端口实际 alias 合法；共享 coarse world 也合法。当前 EnvironmentMember.locations
   是声明的必要域，不是完整 alias/read 集合，省略域不能解释为无依赖。
4. FX/Export lifted placeholders 不自动属于 Python FunctionEntryLayout；原函数
   环境与 imported Tensor Region 的 native 输入分类是不同接口。

## 4. mutation 输出是 payload；写回必须可定位

已有 CPU 见证：raw export 有 add_ 但输出仅 USER_OUTPUT；decomposed 后出现
BUFFER_MUTATION、USER_INPUT_MUTATION，no_grad 参数样例出现 PARAMETER_MUTATION。
因此既不能只看 raw output_specs 断无写，也不能把 mutation 输出直接当 StateVersion。

若要声明原 Region 与 representation 边界关系，写回应有可定位的 canonical adapter：

```text
mutation Tensor payload（正常返回 Use / completion result）
  + 原目标 Tensor reference
  + 当前目标 state Use
  -> 既有 write/copy Operation 的 StateAccess
  -> after StateVersion
```

若需侧面定位 access，引用 `(OperationID, access_index)` 即可，从 StateAccess
派生 location/before/after/reference；不要再保存这些字段的可变镜像。payload Use
必须确为该 write Operation 的输入，并经真实 call/result 或明确 projection 连接，
不能因为 shape/target 相同就视为同一个值。

writeback 顺序、overlap/alias、data/metadata/storage mutation、是否重新绑定目标
必须按确切 provider/stage 规则说明。第一次写成功而第二次写抛异常时，异常出口
携带第一次写后的状态；没有事务/回滚证据不能恢复为全部 before。缺 adapter 时，
保留 payload 与未闭合写回义务，不得给原 Region 授等价或清除 StateAccess。

## 5. BoundaryRelation 的逐域合同

建议每域明确 `domain + rule/fact reference + conditions + unresolved obligations`，
可记录 provider 声称结果，但没有可写的整体 verified/proven 开关。结构核验和
未来语义证明分别推导；未证明域不因别域通过而默认通过。

| 必须独立的域 | 必须明确的关系/问题 |
| --- | --- |
| value/numerics | 哪些有序结果、哪些输入/shape/value 特化范围、什么 exact/数值合同。 |
| writes/state | 哪些 namespace/content 域被读写、写回目标/顺序、正常和异常后态。 |
| alias/identity/lifetime | 输出是原输入对象、view、fresh allocation 还是别名；stride/offset、escape/retention 是否保留。 |
| autograd/gradient | grad/inference mode、requires_grad、detach、backward/joint 输出路由、hooks/saved state；forward 数值相等不足。 |
| RNG/modes | RNG engine/generator 与当前状态、消耗顺序、training/autocast 等模式依赖；guard 成立不是 RNG 恒定。 |
| completion/exceptions | 正常/异常/可能不完成、异常对象/上下文、失败前已发生状态与外部历史。 |
| external effects/history | capture 中的 Python append/hook/IO、原调用重放是否保留。 |
| resource/order/ready | allocation/stream/设备条件、异步完成与借用范围；host return 不当 GPU ready。 |

资源对照引用现有 ResourceRequirement/ResourceUse/ResourceLocation，当前静态表
没有动态 instance/work/ready 满足证明。不能用同设备或 SAME_RESOURCE 静态声明
跨不同 owner/call 激活推导动态相同资源/完成；当前约束只在同 owner occurrence /
activation 内比较。需要的动态关系保持义务，不能伪造 ready=True。

已有 alias CPU 见证尤其重要：raw 返回 view 与 input alias=True，而 decomposed
样例 view/input alias=False。该域可能明确不保留，不能以内容一致掩盖成“全部等价”。
raw/functionalized 各自 Region/SSA 身份保持独立，BoundaryRelation 不合并它们。

## 6. 最小正反例（仅建议，未执行）

| 场景 | 应有结果 |
| --- | --- |
| buffer 在首个 native placeholder，用户输入在后，core state 插在中间 | 按准确 ValueID/call Use/Location 连接；不靠 offset 重排。 |
| 两个实际参数指同一个 Tensor，或返回 `(y,y)` | 独立有序槽位/Uses，实际 alias 允许；不折叠成一个槽。 |
| 一实例 `weight` 原地写或整体 rebinding；另一实例同名同 shape | 正确依赖内容与 namespace 当前 state；跨实例映射拒绝或明确未证。 |
| functional mutation payload + 合法 writeback | payload 仍为 Tensor 引用/值；独立 StateAccess 定义 after state。 |
| mutation payload 被映射为 STATE_VALUE，或消费过期 state | 值变体/current-state 检查拒绝。 |
| 内容相同但 view/input alias 改变 | 数值域与 alias 域分别报告，严格整体替代未获证。 |
| writeback1 完成后 writeback2 失败 | Raise 后态保留已完成写，不退回入口版本。 |
| capture append/RNG/hook 与 graph replay 不同 | provider 图可结构有效；原程序效果/随机性边界不关闭。 |
| 缺原始输出槽、伪造 result path/completion index | P0 仍可能字段有效；P1 原生结构/完成端口核验必须拒绝或定位缺口。 |

本审查不关闭 P1、artifact replay、自动导入、动态绑定或第一阶段整体验收。
