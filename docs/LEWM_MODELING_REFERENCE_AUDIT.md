# LeWM 程序建模参考包审计

本报告审计用户提供的 `LeWM_程序建模_v0.1.0.zip`。它被保留为外部参考资料；不会被复制进 SCAR 核心，也不会被当成 LeWM 优化规则。审计脚本只读取 JSON 和文本，不执行压缩包中的源码。

## 结论

**Observed：机械覆盖和资料组织是可信的；语义分类只能算局部正确；单独依靠逐行表不能安全进行图化简。** 最合适的用途是静态模型审查、候选提示和反例目录。SCAR 必须把它转译成静态 hints，再用动态 Invocation/State/Effect/Resource/Measurement 事实收紧合法性。

|问题|结论|
|---|---|
|逐行登记是否真实覆盖源码？|**大体是**。validator 报告字节精确，18 份逐行表共 2803 行。|
|每行的标签是否等于实际执行效果？|**不是**。标签是静态的、保守的、可继承的提示；函数定义、控制头和跨设备语义会造成过近似。|
|六视图是否适合 SCAR？|**适合，但需要动态细化**。K/Σ/A/R/Q/M 的正交方向正确；当前包没有动态身份、版本和物理关联。|
|能否直接据此删除/缓存/hoist？|**不能**。缺少 InvocationID、StorageID/Region、LogicalVersion、完整 effects/escape/order、运行成本和等价验证。|
|是否有可复用经验？|**有**。8 个 CPU 反例应进入通用测试矩阵。|

## 机械核对（Observed）

- zip SHA-256: `3de771db372d7d43bccc48457439bfead0739cf244b02342de41fbe9564db870`；成员数 64。
- `lines.jsonl`: 2803 行、18 个源码文件；其中 473 个行记录共享 statement anchor。
- bundle validator: `passed=True`, `source_byte_exact=True`, `schema_validated=True`。
- action tag counts: STATE=1506, CTRL=1207, MEM=916, IO=489, VAL=377, REP=339, XFER=142, OPAQUE=121, ORDER=2。
- semantic probes: `all_passed=True`；GPU profile `False`；transformation equivalence proof `False`。
- 所有 2803 effects completeness 记录均为 false；每行 evidence 都声明没有完整 workload 动态观测。

## 哪些地方是正确且有用的

1. **分离六个视图。** 控制、逻辑状态、动作、物理资源、契约和测量不应压成一个类别；这与 SCAR 的 `<K, Σ, A, R, Q, M>` 一致。
2. **动作允许多标签。** `STATE` 与 `CTRL`，或 `REP` 与 `MEM` 可以同时成立；这比互斥枚举更接近 Python/PyTorch。
3. **显式 UNKNOWN。** `effects_complete=false`、成本为 null、没有 GPU 证据等写法是正确的安全边界。未知不能被当成无效果。
4. **保留物理行和源码解释。** 这对定位 CodeID、审查某条路径和建立静态 CFG 很有价值。
5. **反例选择正确。** `.to()` 同设备 no-op、`expand()` zero-stride view、NumPy 外部写入、inference tensor、动作梯度和滑动窗口重定位，都直接阻止常见的错误缓存/驻留推断。

## 哪些地方不应当直接解释为语义事实

|例子|问题|SCAR 处理|
|---|---|---|
|`def encode(...)` 被标为 `CTRL/STATE/MEM`|定义阶段确实可能创建代码对象、默认值或装饰器效果，但函数体没有执行；对所有函数定义统一加 MEM/STATE 过宽。|保留为 `CodeDef`/`K` 节点，只有默认值、装饰器、类体等 AST 子节点单独产生定义期动作；运行时调用另建 Invocation。|
|`self.encoder = encoder` 被标为 `MEM/STATE/CTRL`|在 `Module.__init__` 中注册子模块的解释有上下文依据，但一般赋值不等于 allocation，也不必然是控制动作。|将赋值的写入/别名/对象逃逸作为 `Σ` facts；allocation 只在 runtime 或明确构造语义时成立。|
|`detach().clone()` 被标为 `XFER`|`clone` 会产生新物化，但同设备 clone 不等于 CPU↔GPU 搬运。|`REP/MEM/VAL` 可作为静态 hint；`XFER` 只由 runtime copy 或明确 transfer 语义确认。|
|`torch.cat` 被标为 `XFER`|通常是新 tensor 的值计算和 allocation，未证明跨设备传输。|保留 `VAL/MEM` hint；将 `XFER` 与 Kineto memcpy 分离。|
|`for`/`if` 头继承循环体 `.to()` 的 `XFER/REP`|头部控制可达性和迭代，不执行循环体动作。|控制节点通过 `control_depends`/CFG 指向 body；不要复制 body effects。|
|`with results_path.open("a")` 被标为 `REP`|文件打开/写入/关闭的 IO 解释有意义，但 representation 不是必然动作。|保留 `IO/ORDER` 与异常清理效果；格式化计算和文件表示分成子节点。|

这些并不否定参考包的价值；它们说明**标签的层级必须写进 schema**：`static_hint`、`inferred` 和 `observed` 不能共用一个无来源的 action_tags 字段。

## 为什么逐行表还不能直接化简

化简需要判断一个候选子图在替换前后是否保持同一契约。逐行表缺少以下连接：

- 同一代码位置的动态 `InvocationID`、调用上下文、循环迭代和异常路径；
- Python `ObjectID` 与 Tensor `StorageID`、Region（offset/shape/stride/dtype）的别名关系；
- SCAR 自己维护的 `LogicalVersion`、写入 epoch 和多个物理 materialization；
- reads/writes/allocates/frees/aliases/escapes/RNG/raise/external/order 的完整性；
- host call 与实际 CUDA memcpy/kernel/barrier 的 correlation、stream 和 ready event；
- 可见返回值、环境/文件/日志副作用、回调和未来迭代消费者；
- guard、lookup、内存驻留和 saved work 的**实测**成本，以及 Level 1–4 等价验证。

因此一个 line row 只能产生类似下面的静态假设：

```text
physical line -> AST/statement nodes -> static CFG/data-flow hints
                              ↓
                    runtime refinement
                              ↓
             applicability -> legality -> cost -> selection
```

## 转入 SCAR 的规则（Implemented/Proposed）

1. **不复制外部注释作为核心规则。** 外部 `file,line` 只作为 provenance，SCAR 自己重建 `CodeID`、AST 节点和图边。
2. **静态标签改名为提示。** 对应字段应表达 `syntax_hints` 或 `static_hypotheses`；动态事件的 `action_tags` 和 Effect completeness 另存。
3. **物理行、语句、表达式和调用分层。** 一行多表达式时通过 `ast_contains` 分解；continuation line 不生成重复动态动作。
4. **把效果放在边和契约上。** 控制关系用 CFG/`control_depends`；读写、版本、别名、逃逸和资源关系不能靠给父节点复制标签来表示。
5. **未知阻止变换。** 静态表显示“可能是重复”时只发 Candidate；没有完整效果、版本、消费者、顺序或成本证据时结果是 `UNKNOWN`/`REJECT`，保留 NO-OP。
6. **把反例变成通用测试。** 测试不得匹配 LeWM 名字；应覆盖任意 module、view、foreign write、RNG、hidden state、gradient 和 output mutation。

## 与当前 LeWM 真实 trace 的关系

当前未修改 LeWM trace 已观察 45,888 events、543 physical CUDA copies、22,457 kernels 和 360 barriers；图有 14,609 `data_depends`、12,635 `overwrites`、80 `escapes`。事件/图候选共 2,528 条。显式证明账本把其中 960 条判为 `REJECT`（已观察到中间输入写入），其余 1,568 条保留为 `UNKNOWN`；没有选中任何变换。

这正好验证参考包的边界：静态行审查可以告诉我们应该寻找 `cat`、`expand`、`.to`、循环和返回逃逸，但只有真实 runtime 图才能回答它们实际执行了多少次、是否搬运、是否共享 storage、谁消费结果，以及优化是否盈利。

## 审计产物

- 机器可读报告：`artifacts/reports/lewm_modeling_zip_review.json`
- 本文档：`docs/LEWM_MODELING_REFERENCE_AUDIT.md`
- 可复现脚本：`artifacts/experiments/audit_lewm_modeling_zip.py`

最终判断：**参考包的建模方向正确，部分行级解释有上下文价值；但它不是运行时真相，也不是可直接化简的图。SCAR 应把它用作静态证据源，并依靠自己的动态图、效果契约、版本/别名模型、成本决策和分层验证完成化简。**
