# P0 provider 接口独立复审

2026-10-16；工作树 HEAD `624560e102cc655ca2dca0362af5b646e5359d01`。
结论：**需修一项规范化来源映射规则；其余已审范围未发现阻断项。**
这是声明图结构审查，不是 artifact、原程序、运行对应或变换权限验收。
只写本 ignored review 目录；没有修改产品/测试/docs 或启动采集、目标、全仓测试。

## 1. 必修：CompletionResult 注入参数漏掉规范 producer 检查

旧 `provider_validation.py` 第二遍只对 `OperationResult` 检查 producer/key 及非空
result path。INVOKE 完成结果通过 `CompletionResult(index)` 注入私有后继的
`BlockArgument`；这个参数的产生操作可从现有 canonical CFG 唯一派生，当前却
与普通入口/phi 一起跳过 producer 检查。

独立 probe 使用已有 `_invoke_graph()` 构造单个合法 INVOKE，其正常/异常分支都
拥有私有入口和完整 post-state。给 INVOKE 绑定 external key `invoke`，给正常
RETURN 操作绑定 `return`，再仅修改 provider value 来源，不修改 core：

| case | 声明变化 | 修复前实际结果 |
| --- | --- | --- |
| `wrong_producer_normal` | 正常完成 ReferenceValue 的 key 改为 `return` | validate 无 issue；v7 编解码通过 |
| `missing_projection_normal` | 正常完成结果 key=`invoke`，path 为空 | 同上 |
| `wrong_producer_raise` | 异常完成 ReferenceValue 的 key 改为 `return` | 同上 |
| `wrong_producer_poststate` | 正常完成 StateVersionValue 的 key 改为 `return` | 同上 |

正确 producer/key + 非空 result path、普通 region entry 参数、完成边以 UseID
转发的参数均合法，对照均通过。因此建议不基于名称、dominance 或“非 entry”猜
producer，只遍历真正的 `CompletionSuccessor.arguments`：遇到 `CompletionResult`
时，以目标参数位置建立临时 `ValueID -> INVOKE OperationID` 索引；来源事实仍以
现有边为准，不持久化第二份 producer。只对这些值复用 key/非空投影规则。

**这需要明确为 P0 的规范化映射规则，而非宣称所有外部 CFG 参数都是操作结果。**
若外部工具直接给显式 block-parameter 身份，当前 `ProviderElement(kind,key,path)`
没有额外 origin 类型区分它和该规范化结果。P0 应明确只接后一种映射；不能悄悄把
原生参数节点当成错误程序。普通 entry、phi、UseID 转发不受本规则限制。直接外部
CFG 参数对应及 completion kind/index 的强类型投影留给 P1；不本门硬编码 path 文本。
修复不证明 locator 真存在、不证明外部操作与原执行等价，只排除已声明关系内部矛盾。

## 2. 其余审核结果与边界

- target 的精确 ID 类型由 records 校验；Value 变体由图校验，不能用 DATA_VALUE
  绑定 StateVersionValue。Use 的 owner/Region 从 core 重算，不另存依赖。
- 两个实参 Use 可以指向同一个 Value；相同 external slot 重复绑定、同 core target
  折叠多个 external 端点会拒绝。这是 P0 规范表示的一对一映射约束，不支持融合、
  展开、跨表示同一性；此限制与 P1 待交付范围一致。
- OBSERVATION_SCOPE 多对多被允许；动态 artifact 不可定义静态表示或绑定静态
  target。definition owner 唯一，raw/normalized 不能共享规范 Region 归属。
- COMPLETE、空 conditions 不改变 core effects/state，也不会在 ProgramIndex 中
  变成 proof。CLI 固定 `transformation_authorized=False`，并另标 artifact replay、
  conditions、source/runtime 对应及跨表示等价未验证；未发现隐藏升权路径。
- external path 的真实含义/次序、artifact hash 是否属实、condition 是否成立仍未
  校验。查询返回精确的**已声明** UseID，不能将其措辞升级为真实源端口已经核验。
- v2–v6 golden 编解码逐字保持，旧 schema 注入空 provider 表也被拒绝。v1 迁移
  分支本轮仅静态检查；未增加新的重放实验。v7 要求显式 provider capability。
- ProviderFactReference 可以指向单独带 hash 的辅助 artifact；没有无依据要求它
  与主 artifact 完全相同。构造器无 artifact I/O；实际内容验证在后续 adapter。

## 3. 唯一一次 probe 与复现

工作目录 `/tmp/scar-structured-model-280qf4mi`，命令：

```bash
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 /home/zyf/miniconda3/envs/lewm/bin/python artifacts/experiments/b1_call_operands/model_provider_interfaces/review/probe.py
```

CPython 3.14.7；exit 0；工具记录 wall 0.678 s；14 个观测 case。
这是结果采集脚本，exit 0 **不表示四个负例通过了正确拒绝验收**；实际均被错误接受。
证据：[probe.py](probe.py)、[probe.result.json](probe.result.json)。JSON 保存七个被审
文件的前后 SHA256，完全相同；本次没有为了复验而第二次运行。
修复前 validator SHA256：
`e3cce08c7a2493bd256c4012b52f8fdffa4a2aec52fa1a96670cd411f036d4fc`。

Root 已收到问题并认可按 CompletionResult 实际边增加规范化约束；本报告保留
修复前依据，没有宣称补丁已完成或已复验。不因 P0 通过而关闭全部 T1/M1/M2。
