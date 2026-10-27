# Input-origin query review

范围：只读审查冻结的 `input_origins.py`，以及供协议验证/查询复用的 `ProtocolFlow`、`ProgramIndex`、`protocol_validation` 和 `protocol_query`。未运行测试或工作负载；未修改产品、测试或文档。

所读文件 SHA-256：

- `scar/ir/program/input_origins.py`: `8399eb173173d00e82d746dba1cdc0e0b20a120009f52a7396211ef7be340194`
- `scar/ir/program/protocol_validation.py`: `858433e81106487ca8f758291d58fc3c60b2c1ac1c12f4744936407087d0d8b4`
- `scar/ir/program/protocol_query.py`: `10b3e3903eb8e6047587f497f5297f58337758dbf13fc32cc2c5bb36ca8a2997`
- `scar/ir/program/protocol_flow.py`: `fd4898482a81852c6fd30668aa5dd2548dc7dfe761b9616a937d5635a0bc84af`
- `scar/ir/program/queries.py`: `b0276d00bbba98b645fcc672d69660bb961ddfdbc98b65c2fe6c8c4ed2912904`

## 结论

`input_origins` 能保留精确的原始 Use、CALL/INVOKE ordinal、CFG edge、raw-definition 与 operand 引用。现有多 caller 测试形状中，每个 recipe 单独分支，因此可以从该 recipe 找到它对应的 raw pack。但它还不足以证明一般情形下“body consumer 的 raw pack”与“该 pack 本次执行读取的 None / 非 None 输入”来自同一 caller：对普通 `OperationResult` 的停止规则会丢掉 raw-pack 所在函数的外层 caller 上下文。协议查询不能仅按 raw ValueID、pack OperationID、operand ordinal 将独立查询的两组结果连接；对无法得到相同调用路径前缀的情况必须保留 `caller_join_unresolved` 缺口。

## 1. Caller 配对边界

在 `input_origins.py:286-324`，函数入口的每个 CALL/INVOKE caller 都按原 `caller.id`、`callee`、formal ordinal 和 caller 所拥有的 actual Use 分开排入路径；不会用相同 ValueID 合并 caller。`emit` 也把每条叶子 recipe 自己的 raw definition 及原 operands 放入该 recipe (`:127-159`)。这是良好的本地关联基础。当前 fixture 的两个 raw packs 在 root 区域分别创建，因此两条 consumer recipe 的叶子分别指向不同 raw result，覆盖了这种简单情况。

一般的嵌套复用 pack 场景仍有具体缺口：

1. 函数 `A(x)` 在内部用 `x` 建立 raw pack `r`，然后在同一 A 区域调用 body driver；root 又分别以 None 和非 None 调用 A。
2. 从 driver 的 raw formal 反向查询时，跟到 `r` 的 `OperationResult` 就在 `input_origins.py:232-254` 停止。该 consumer recipe 记录 raw definition 和 pack operands，但没有 A 的两个 root caller。
3. 对 pack operand `x` 单独再查时，才从 A 的 entry formal 枚举 root 的两个 caller。此结果没有动态 activation 选择，不能用它与前一个 recipe 按 `r` 或 operand ordinal 直接做笛卡尔连接。

因此，对“同一 caller 的 raw pack 和 is-None 输入”，现 API 只能提供分离的静态线索，不能普遍完成配对。最小安全处理有两种：

- 新增联合 origin 路由查询：对 consumer raw Use 和 exact `RawRequestDefinition.operands[i]` 一起追踪，在输出中携带各路径有序的 exact CALL/INVOKE key `(caller OperationID, callee RegionID, ordinal, actual UseID)`；只有共同前缀精确匹配时才给出静态 caller join。跨函数动态 activation 仍标记 unresolved，不声称 runtime identity。
- 若暂时不增加联合查询，则协议 query 只能按 raw definition 获取其原 operand Uses，并返回 `caller_join_unresolved`；不能把独立 origin 查询的 caller 结果当已配对的 request。

`raw_requests` 中的 operand rows 是 exact原Use引用，但当前没有递归解析它们，也没有从 consumer recipe 扩展到 pack 所在 activation 的 caller context (`:131-145`)。不同 raw-kind 的 operands 语义还应由固定 `RawRequestKind` 解释，不应默认 operand 0 就是 SEND 的 value。

## 2. 与验证器 / 查询上下文集成

当前独立函数无 context 参数，并在 `input_origins.py:48,67-70` 创建 `ProgramIndex(graph)`。而 `ProgramIndex.__init__` 在 `queries.py:274-279` 调用 `validate(graph)`；`validate` 到 `validation.py:701-704` 调用 `protocol_errors(graph)`。若将公开 `input_origins` 直接从 `protocol_errors` 调用，路径会再次进入 `ProgramIndex → validate → protocol_errors`，形成验证递归。当前 `protocol_errors` 已有 `context` 参数并可复用 `ProtocolFlow` (`protocol_validation.py:287-290`)，但 `input_origins` 不接收该 context。

建议把实现拆成“准备好的原图上下文”上的内部派生函数，明确区分入口：

- 已验证查询：`ProgramIndex.input_origins(...)` 可传入 `self`，避免每次重跑完整 `validate`。
- 协议验证/查询：内部 resolver 接受现有 `ProtocolFlow` 与共享 `ValidityBudget`；不得构造 `ProgramIndex`。必要的 entry argument、drive input projection 和 environment-call 描述应复用或从当前 `ProtocolFlow` 增补只读方法，而不是再建 producer/use/state 表。
- `protocol_query.protocol_obligations` 已创建共享 budget 和 `ProtocolFlow` (`protocol_query.py:79-86`)，这是接入该内部 resolver 的自然位置。`protocol_errors` 若只验证声明形状，则无需调用 origin resolver；若需校验 raw request 的 None/non-None 来源，应走同一已准备 context 的路径，不能调用公开 `ProgramIndex` 构造器。

这能避免递归验证，也使 protocol obligations 与 input-origin traversal 共用预算及原始 Use/CFG 索引。

## 3. Budget 覆盖

主反向扩展有预算：initial task 和每个 origin node 计费 (`input_origins.py:170-191`)；调用者、BodyStart 和 CFG predecessor 在排入 task 前计费 (`:286-335`, `:376-383`)，cursor 保留未处理 candidate 数。这些扩展没有发现少计费的直接调用者/CFG 分支。

但预算不是当前函数的总工作上界，存在未计费扩展：

- `emit` 遍历每个 raw definition 的所有 operands，并复制所有匹配的 LiteralEvaluation (`:127-150`)。
- `ResumeInput` 分支扫描所有 `body_drives` 生成 `matching`，随后遍历每个 match 并查询每个 drive 的 bindings；这些候选没有逐项 spend (`:420-453`)。
- `ProgramIndex(graph)` 的完整验证、函数自己的全图索引构建 (`:70-100`)，以及 `ProtocolFlow` 初始化都发生在预算遍历之前/之外。

应明确预算定义为“被路由访问的候选与 fresh-copy analysis”，或补充对 raw operands、literal rows、resume-drive matches 的逐项计费与 pending cursor。若 API 对调用方承诺有界总工作，还需要把准备/验证成本纳入同一预算或要求调用者传入已准备索引；目前小 budget 不能限制上述准备成本。建议通过预索引 `(suspend, successor)` drives 避免每个 ResumeInput 扫全表，并在真正展开匹配项前扣费。

## 4. Freshness 解释

`OperationResult` 只有在 producer 与当前 anchor Use 同区时才调用 `ProtocolFlow.forwards` (`input_origins.py:232-253`)；跨区返回 `None` 并由 `emit` 添加 currentness unresolved gap (`:120-145`)。当逆向遍历 CFG Use 时，anchor 随精确 edge Use 更新；CALL/INVOKE 每一步也记录 `static_call_occurrence_unlinked`。这使 `True` 只对应某个本地 producer 到该路由 edge/actual Use 的 must-copy 检查，而不是跨 caller 的动态值同一性。`ProtocolFlow.forwards` 也要求同 region，否则返回 `None` (`protocol_flow.py:263-276`)。

Backedge 路径会保留每个原 edge，并显式添加 `cfg_visit_unselected` (`input_origins.py:117-121`)；`ProtocolFlow` 的 fresh-copy 迭代在 producer 重执行时丢弃旧结果 (`protocol_flow.py:223-260`)。据此，backedge 上 `freshness=True` 只能解释为 producer→那一个精确回边 Use 的局部事实，不能解释为将来某次 consumer visit 的同一次 evaluation。当前字典已设 `freshness_is_runtime_identity=False`、`value_identity_verified=False`，且路径保留 CFG gap，故没有源码证据显示它越权；但 `freshness` 这个短字段名易被上层误读。建议加 `freshness_target: OwnedUse` 和 `freshness_scope: "LOCAL_PRODUCER_TO_USE"`，或将它改为 `local_copy_status`，并要求聚合协议消费者不得据此消去 route gaps。

## 范围限制

本审查是代码路径推理，未运行测试或构造额外反例。它不证明 runtime caller、frame/request identity、None 的动态值、source/native 适用性或 transformation。现有 flags 都保持 False；route 的 `DERIVED` 只能理解为 supplied static recipes 已展开，不能理解为 caller inventory 穷尽。

## 后续复审与索引缓存收口

以下补记保留上面首次审查中的发现和源指纹，不回写旧判断。`request_inputs.py` 首次复审所依据的源码 SHA-256 为 `103c3c138e9f203b0b4c40c13d8125846993db770fe2b700ca3ae18c8a4cbdd8`；当时发现的截断 operand ordinal 越界风险已在后续源码中加了 `ordinal >= len(request['operands'])` 防护，并返回 `request_operand_inventory_truncated` 与 cursor。首次的 `input_origins.py` 审查指纹仍以上文记录为准。

本次获授权的实现只改 `input_origins.py` 和其 pair 单测。反向元数据索引现在按 `ProgramIndex` 缓存，包括原 owned-Use 映射、CALL/INVOKE callee索引、CFG incoming edges、BodyStart/BodyResume、RawRequestDefinition 与 LiteralEvaluation索引。新增索引表的映射为只读代理，分组成员为tuple；同一已验证 index 的后续 source/joint query复用同一组索引。`preparation.origin_route_index_cache` 明示 `BUILT` 或 `REUSED`，`origin_route_index_rows`记录本次构建实际扫描的原表数量。配对查询改为复用缓存的caller索引，不再为每次pair扫描全体operations。原本按查询重复计算的调用边/入边汇总也改用缓存计数。

跨调用配对继续保留精确的RawRequest operand Use、完整静态caller路由和CFG choice；它不因相同 ValueID、类型或ordinal而跨caller合并。`request_input_binding` 当前使用共同 `ProtocolFlow` 与 `ValidityBudget`，协议查询通过私有 `_flow` 将当前 context 交给它，避免每个 predicate 重新初始化流分析。它仍只返回supplied static routes：动态 activation、同一静态call site的具体实例、source/native适用性与运行时值身份均未证明，相关完整性标志仍为False。`protocol_query` 对 PARTIAL/TRUNCATED 的 binding report 会保留 unresolved gap；无binding也单独报告 unlinked gap。

缓存构建是每个 `ProgramIndex` 一次的准备成本，成本随被索引的原operations/uses/blocks/CFG边及driver/literal表行数增长；它不计入每次路由的 `ValidityBudget`。`ProgramIndex`自身的图验证和 `ProtocolFlow`初始化也不由该路由预算覆盖。返回的准备元数据明确提供表行数与缓存命中，不能把budget解释为覆盖初始全图准备或Python总执行时间。

### 终态定向证据

使用 `input-origins/focus.py origin_index_reuse` 定向运行了原 input-origin 与 pair 两个单测文件。`attempt001`为16 passed；之后把调用边与CFG入边合计也改为复用缓存计数，`attempt002`复跑为16 passed。没有失败尝试被删除。命令均为：

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_generator_matrix/input-origins/focus.py origin_index_reuse tests/unit/test_program_input_origins.py tests/unit/test_program_input_origin_pairs.py
```

`attempt002/source.before.json` 与 `source.after.json` 中列出的本次owned files和审查依赖文件指纹一致。测试时的精确快照如下；它绑定本次执行，不应被后来共享文件的版本替代：

| 文件 | SHA-256 |
|---|---|
| `scar/ir/program/input_origins.py` | `6212a9aeb8a170387f102ba02be4ae480d641075e52232ded09ac5fca4866631` |
| `tests/unit/test_program_input_origin_pairs.py` | `ef53c3e7c9e49a42f72e829b0bc9a6b55751d24e2b7011ef98dc7fb9ce1f6334` |
| `scar/ir/program/request_inputs.py` | `f92acc5fb14b51c852bd2d553cdd26c00a06f01752b0dbb032481a363dfef2b1` |
| `scar/ir/program/protocol_query.py` | `52900868b3102dae34e6e18bc21fda7527748641cc9cfcc7e2487c44d77cdb31` |
| `scar/ir/program/protocol_flow.py` | `8d378be283c7001d6b0b65546a18f499046360c224b613256fc6f43656f18ec2` |
| `scar/ir/program/queries.py` | `2a222943035c912ee71d7eb14ac2386a8df9b5e30631f78d72a8093b6cdfddc7` |

复核报告生成时，其他owner已改动两个共享文件；我只读核对了其最新接口，未重跑测试。当前观测 SHA-256 为 `request_inputs.py` `2c93d60c50f786d7e603e5a38314c77fbfb48f4d1a38f4385e05ea42da865415`、`protocol_flow.py` `b31cb6c21b73adf30b0d117d605c17686d7e8c6a814c47ebd41afe176a232a52`。当前 `request_input_binding` 接收并复用 `_flow`；协议查询把当前上下文传入，且PARTIAL/TRUNCATED的报告会传出gap。它也保留 raw operand ordinal被预算截断时的pending gap。上述两项只读结论不宣称对后来共享文件执行过本次focused测试。

本次只运行上述两个unit文件；没有运行组件门、全仓、LeWM workload、GPU或性能测试。
