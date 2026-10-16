# M1 / T1：P0 外部图来源与规范归属合同

日期：2026-10-16。**P0 组件 225 项、冻结全仓 3,139 项通过。** 本门落实
[集成设计](MODELING_INTEGRATION.md) 的来源、表示归属和有序端口合同；不是新
tracer/adapter，不关闭整个 T1、M1/M2 或第一阶段。

## 1. 为什么接到现有 core

FX/Export 的定义图、ETO/Profiler 的执行证据及 source snapshot 具有不同身份。
它们需要版本、范围和来源连接；不应各自再建一套可修改的 producer/use/state。
本门只在 ProgramGraph 增加三张声明表：

| 表 | 作用 | 不代表什么 |
| --- | --- | --- |
| `provider_envelopes` | 工具版本、原始 artifact、捕获与变换阶段、条件、覆盖和观测缺口。 | artifact 已重读、条件成立、数据恒定或没有采集副作用。 |
| `provider_regions` | 定义图的规范表示归属，或执行证据的观察范围关联。 | 不同表示等价；执行节点已经对应静态操作。 |
| `provider_bindings` | 定义层外部端点到现有 Operation/Value/Use 的来源声明。 | Python 对象、内容版本、GPU ready 或优化授权。 |

Region/Operation/Value/Use 的事实仍取已有 core；绑定不再保存 inputs、producer、
actual arguments 或前后 state。不同表示使用不同 Region 和其内部身份。

## 2. 记录合同

所有新记录 frozen/slots，ID、enum、tuple 和整数严格校验，bool 不作整数。
没有输入可写的 verified/proven/transformation-authorized 字段。

- `ProviderArtifact(uri, sha256, size_bytes, schema)`：原始字节 SHA256 为 64 位
  小写 hex，大小非负；不是 source 的 decoded fingerprint，也不触发文件读取。
- `ProviderFactReference(artifact, locator)`：事实指向带 digest 的 artifact 片段；
  外部 locator 的存在与含义由后续 adapter/replay 校验。
- `ProviderRunScope(run, process_id, window, clock, thread_id=None)`：动态来源范围；
  缺失不默认当前 run、PID 或时钟。显式数字 0 不是未知值的替身。
- `ProviderStage(name, evidence)`：保留有序捕获/变换 pipeline，不以阶段集合代替。
- `ProviderCondition(domain, evidence)`：SHAPE/VALUE/MODE/ENVIRONMENT/SCHEMA/OTHER；
  保存来源，不求值，也不把条件声明当成立。
- `ProviderCoverage(domain, completeness, evidence, reason)`：SOURCE/STRUCTURE/
  DATAFLOW/STATE_EFFECTS/ALIAS_IDENTITY/CONTROL_COMPLETION/RESOURCE_ORDERING/
  CONDITIONS 八域各一条，使用已有 Completeness。reason 非空；非 UNKNOWN 必须
  有事实引用。COMPLETE 只是 provider 声明，不证明原程序依赖完整。
- `ProviderCollectionObservation(domain, evidence, reason)`：CAPTURE_EFFECTS/COST
  两域各一条；没有引用必须保留具体缺口，不能解释为无副作用或零成本。
- `ProviderEnvelope(id, provider, provider_version, source_revision, artifact,
  kind, capture_mode, capture_scope, sources, stages, conditions, coverage, collection)`：
  version/revision 至少一个；sources 为严格 SourceVersion tuple，stages 非空。

`kind` 分 DEFINITION_GRAPH / EXECUTION_EVIDENCE，`capture_mode` 分 STATIC_ANALYSIS /
SYMBOLIC_CAPTURE / REAL_EXECUTION / REPLAY。两者是独立维度：FX/Export 定义图也可
携带捕获 run。EXECUTION_EVIDENCE 必须有动态 scope，模式为 REAL_EXECUTION/REPLAY；
这两种模式均要求 scope；STATIC_ANALYSIS 不携带动态 scope。symbolic capture 的
run 未知可以留缺口，不能编造运行身份。

- `ProviderRegion(provider, external_region, region, relation)`：relation 为
  DEFINES_REPRESENTATION 或 OBSERVATION_SCOPE。
- `ProviderPathIndex(index)` / `ProviderPathKey(key)`：分别保留有序整数索引和
  文本 key；不以集合或未解析的显示标签代替参数路径。
- `ProviderElement(kind, key, path=())`：kind 为 OPERATION、DATA_VALUE、
  REFERENCE_VALUE、STATE_VALUE、BINDING_VALUE、PROTOCOL_VALUE 或 USE；操作无
  path，USE 必须有 path。值类别避免把 Export mutation 的 Tensor payload
  错当作整个 StateVersionValue；实际写回仍须原 core 的 StateAccess/版本流。
- `ProviderBinding(provider, region, external, target)`：target 分别严格为
  OperationID、ValueID 或 UseID；不包含动态 ID。值类别由图 validator 对照实际
  Value 变体检查，不能仅凭 target 的 ID namespace 放过不兼容的状态/数据类型。

## 3. 图内不变量与查询

1. 每条表引用必须存在。DEFINES_REPRESENTATION 只来自定义图，OBSERVATION_SCOPE
   只来自执行证据；每个 Region 至多一个规范 owner。观察关联可多条，但不授予
   其内部对应关系。外部定义 region 坐标在一个 envelope 内不重复；观察范围关联
   允许多对多，不因此给出 occurrence 对应。
2. binding 只出现在明确声明的表示归属内；target 的实际所属 Region 必须一致。
   Use 的 owner 由 Operation.uses 派生，值的所属及 producer 由既有 origin 派生。
3. 同一外部端点不能绑定多个 core target；同一 core target 不能折叠多个外部端点。
   端点坐标的 value-kind 变化不能绕过同端点冲突检查。一个外部操作的多个输出
   使用不同 result path；一次 Use 始终保留单独输入位置。
4. Use 绑定的 external.key 必须匹配该 Use 所属 Operation 的外部操作 key。
   OperationResult 值绑定必须匹配 producer 的外部 key，并具有 result path。
   唯一真实入边的 CompletionResult/PendingPayload 直接产生参数时，也按既有边
   关系检查其来源操作和非空投影；普通入口、Use 转发和多入边 phi 不强造 producer。
   这检查规范化来源声明，不验证外部 locator 或其端口索引的真实含义。
   合法的 `f(x,x)` 用两个路径连两个 Uses，
   二者仍引用同一个规范 Value；绑定没有复制或修改这个 Value 的 producer。
5. 同名 provider、external node、文件行、地址或 shape 都不产生自动对应。查询只
   返回声明、准确既有 Use 和覆盖缺口，缺少声明保持缺失；不能升级为逻辑值相等。

ProgramIndex 提供按 region 和 canonical target 查询的来源接口，查询结果来自
三张表及原 core。公开 check-program 报告声明数量，并固定区分结构校验与尚未
校验的 artifact replay/guard/跨表示对应/变换权限。

## 4. 自主验收节点

| 节点 | 交付与验收 |
| --- | --- |
| P0.a | 严格 records；重复域、遗漏域、伪造 ID、错误 capture scope、bool index 等拒绝。 |
| P0.b | 接原 core 的归属/端点检查与查询；重复实参保持，动态→静态错绑、跨表示共享归属、值类别和 producer/Use 错绑拒绝。 |
| P0.c | ProgramGraph v7、原 v1–v6 wire 保持；原 revision 生成 v6 golden，拒绝旧 schema 注入新字段与降级伪装；公共 CLI 不授予优化权限。 |
| P0.d | 独立审查、组件门、冻结全仓回归；记录 revision/指纹、失败、命令、终态和未关闭分母；提交并推送开发分支。 |

测试为通用手工 IR 反例，证明接口可组合和错接可拒绝，不证明自动导入真实工具。
每次失败保留；冻结后不在回归中编辑产品/测试，不重跑已有 LeWM 重型 trace。

## 5. 必须继续完成的部分

P0 不关闭以下工作，也不将它们退化为普通 binding：

- P1：不同表示间的 BoundaryRelation，逐域说明条件及尚未证明的数值/梯度、写回、
  alias/identity、RNG/mode、异常/控制与外部历史；入口/输出 tree spec 和 native 角色
  的 typed 接口组合。它们需引用规范端口及环境/当前状态，不另建形参或状态表。
- 动态 occurrence/denotation、实际 host→runtime→GPU realization：按 run/activation/
  visit/资源域连接，不能用观察范围替代。类型合同属于第一阶段；真实证据接通属 M4。
- 其余 M1/M2：cleanup/context、挂起恢复、location/literal、资源 instance/work/ready
  及完整构造规则，见 [第一阶段完整分母](FIRST_STAGE_COMPLETION_MATRIX.md)。
- T2 以后：读取实际 artifact、工具 adapter、额外捕获的受控 replay、成本比较和
  未修改 LeWM 压力验收。遵守第一阶段完成后先汇报讲解的停止点。

本门实现不新增 optimization backend，不用人工 pure/constant/workload 名单。

## 6. 组件证据及冻结范围

组件命令：`python scripts/run_gate.py gates/m1_provider_interfaces.json --out
artifacts/experiments/b1_call_operands/model_provider_interfaces/component`，使用
`conda activate lewm`。首轮四项标准分别 54/54/103/13，通过共 224 项。
补共享 phi 反例后的终版报告为 `component-final`，54/55/103/13，共 225 项，
8.518s；源码指纹
`97a2dfe24a6e5d3c72c31ee6d3cb94dc6e8bc9d8dad35e3e9bb4e21ebf3f4b0b`，367 文件。
原 v6 golden 来自隔离的 `git archive 624560e` 与原 codec，非用新类型重建；原
wire SHA256 为 `03fe4ff31daf44a390be8f6ab30f4201a55706e581594be84fb27f116e9fcf20`。

独立审查首次实证 4 个 INVOKE 完成参数来源错绑被接受。原 probe/报告保留，
修复从既有 CompletionResult/PendingPayload 边推导来源操作；新增正反例覆盖
正常/异常/后态、投影及普通转发。外部显式 CFG 参数仍需要 P1 的原生来源合同，
不能以本 P0 规范化来源规则断言第三方图本身错误。

首次冻结 `35469f0` 的全仓回归启动后，只读复核发现新增 PendingPayload 推导
对共享落点采用 last-wins，会随 operations 元组顺序变化。先向本次独占 driver
发 SIGINT，再确认其子进程终止、临时目录清理后修改源码。原 `full/` 保留
228.805s、returncode=-15、FAIL 的中止记录；不能算作回归通过或一个测试断言失败。
修复仅从唯一真实入边推导；新增合法双 dispatch 共用 exit shim 的顺序无关测试。
终版组件通过后重新冻结，并在独立新目录运行最终全仓回归，不覆盖第一次证据。

证据目录：[model_provider_interfaces](../artifacts/experiments/b1_call_operands/model_provider_interfaces/)。
最终冻结实现 `b14070820ceb37731dce5fb6d430eaabc2f0c649` 的 `full-final/`：
3,139 PASS、0 fail/error/skip，3 个既有 warnings；driver wall 424.444s，峰值
1,026,828KiB。HEAD、clean worktree、367 个源码文件哈希及 15 个 fixture 哈希
前后一致，本次独占临时目录已清理。该时间是验收成本，不是 LeWM benchmark。

独立审查两次缺口、原 probe、初版门、被中止的 full 及终版门/完整回归均保留。
本 P0 自主验收关闭；测试结果不作为 T1、M1/M2、自动导入或变换完成的依据。
下一步先落实 P1 原生端口/tree 与 BoundaryRelation 的逐域合同，继续遵守第一阶段
完成后先停下来汇报的边界。LeWM 原仓库仍为干净 `f70fed8`，本门未启动 LeWM。
