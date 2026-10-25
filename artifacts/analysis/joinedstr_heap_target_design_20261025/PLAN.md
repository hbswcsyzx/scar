# heap-target JoinedStr 最小方案（待 root 授权实现）

只恢复原 seq5/body `120960f8d4c167a1f1a4acbd3f058756f9d244d9d09209f66cdbe0f060599d3c` 的下一真实前沿；不重 lower 三个已接受有限图。全部四项原分母和其 OPEN 条件继续保留。此次未改生产、未运行 lowerer/目标，未读77MB composition roots；只核小归档、一个5.48MB source-layer record、一个9.58KB readonly marshal 及本地 CPython primary。

## 1. 原因与来源链

candidate03 `body-02-result.json`/`body-02-returned.json` 记录350 construction ops、无 graph，末 gap 为 eval.py82:20–33 的 `missing target-child computational semantics require a checked rule for JoinedStr`。归档源 fingerprint 为 `sha256:6584f009b40550fa0df2f8dee22b9329fbfacdfaf74464aa4fd105f464795245`，82行为 `process[f"goal_{col}"] = process[col]`。

原 SG 的 JoinedStr atom `source:atom:c96659ff1770ca1387368ba5` 对应唯一 operator `opdef:op:078f3d3677340b08faf91315`、原 output `slot:slot:6b45d7d9c0482bfb03639149`。FormattedValue、Constant、Name 也各有原 atom/唯一 output；四者旧 computational overlay 都为0。不能把 overlay 缺失改写成源不存在或新建 StaticValue。

原 compiler witness 是 CPython3.14.7、code `pycode-v2:e00fd01a3cf2a6faf55256a9bfe5d0fb7fedf4046a1a7fd10a4bd7532f0cb98c`（以机器 receipt 的完整 descriptor 为准），module `.marshal` SHA `8cedd0b79b7009dbed49717dd9ade93a08443ca2f58dc51c5f88fa17fca0a01d`、constant_path `[15]`。准确反汇编为 RHS read → receiver read → `LOAD_CONST 'goal_'` → `LOAD_FAST_BORROW col` → `FORMAT_SIMPLE`（82:27–32）→ `BUILD_STRING 2`（82:20–33）→ `STORE_SUBSCR`。完整 describe_code 与原 captured descriptor 相同，未编译/执行目标。

现 `environment_lowering.expr` 已接 `lower_joined_string`，已有 `FSTRING_CONVERT/FSTRING_FORMAT/BUILD_STRING`、NORMAL/RAISE world 和 Frame holds。实际断点是 `source_heap_lowering.expression_for_heap_target` 缺 JoinedStr 路径；只加 dispatch 仍不够，因为 `_formatted_value` 直接 `builder.expr(node.value)`，此处 Name(col) 也缺旧 overlay。旧 `validate_string_protocols` 只核 source kind/端口，不核原 AST/compiler顺序与 pending；不能把它的结构通过冒充语义复核。

## 2. 精确最小改口（四文件，无 wire 改动）

| 文件/API | 改口 |
| --- | --- |
| `source_heap_lowering.expression_for_heap_target(builder,node,cursor)` | 缺 overlay 的 JoinedStr 先用 `_source_definition` 核准确 atom、code_id/source_atoms、`OPERATOR`/`metadata.ast_type=JoinedStr`、唯一 output，再进入已有字符串 lowerer；有旧 overlay 保旧路，歧义拒绝。 |
| `source_string_lowering.lower_joined_string(builder,node,cursor, *, recover_missing_children=False)` | 新增局部 Python keyword 参数，默认兼容旧入口。仅 missing-target 路径为 True；FormattedValue.value 走现有 `expression_for_heap_target`，nested spec 递归传同一模式；不接受任意 callback。literal/child value 仍走原 ReferenceValue/Use/SourceRole，不伪造 computational value 或 SG identity。 |
| 新 `source_string_validation.validate_string_source(model,graph,interface,metadata,semantic, *, source_tree=None,options=None,structural_only=False)` | 独立读取最终图和原 AST/readonly evidence，不调用 lowerer重演；核原 SG source/唯一定义、完整 child→format→join→consumer 的有序 Uses/normal producer、compiler positions/arity/constant slot、局部 pending。无证据返回具体前沿；已发现矛盾必须拒绝。 |
| `source_language_validation.validate_language_body` | 接入上述独立检查，单列 `string_protocols` 验证结果与剩余前沿；STRUCTURE 不声称 AST/compiler 已核。原 `validate_string_protocols` 结构检查继续保留。 |

旧12文件中只有 **source_heap_lowering.py、source_language_validation.py** 拟改；另外10个旧文件、main 新第13 planner、协议 enum/codec/overlay 字段都不改。`source_string_lowering.py` 是已有文件，新增 validator 是一个窄查询模块，不提取通用解释器/ownership框架。若上述原 source/Use/Frame 记录不能唯一核回，立即停止并报具体缺口，不塞 metadata。最终 join 仍是既有 synthetic PythonProtocol，保原 source atom；不把旧 SG output 伪造为旧 computational result，也不绕过旧 validator 的 `semantic_operation=None` 合同。

## 3. 求值、effects、引用边界

沿已有顺序：RHS → receiver → literal/value → conversion（若有）→ spec（若有，递归）→ format → 下一 piece → join → store。值/转换/spec/format 的任何异常都携带其自己的 post-world，不能执行后继 piece/store。`FORMAT_SIMPLE` 的 None spec 是既有协议 sentinel，不能混同实际空字符串 spec；exact-str forwarding 不等于生成新对象。既有 `!s/!r/!a` 用解释器 conversion，不造全局 str/repr/ascii lookup；`__format__/__str__/__repr__`、allocation/finalizer 和 consumer effects 都不标 pure，保持 READ/WRITE/MEMORY、`effects_complete=False`。

复用本地 pinned v3.14.7 `Python_bytecodes.c` SHA `7bf5ada874d6c8244f16c38be5c36e7a4eff1a7349e4c9a6c901d8475727e095`：BUILD_STRING1939–1951、CONVERT_VALUE/FORMAT_SIMPLE/FORMAT_WITH_SPEC5014–5046。这些路径在失败前 CLOSE/DECREF inputs（exact-str 成功为转移），故不照搬 tuple 的 success-only steal。独立 verifier 按固定 primitive 合同推导消费：conversion只消费value；simple format只消费value（None sentinel未hold）；with-spec消费value+spec；join消费有序pieces。核两completion的 FRAME_RELEASE/FRAME_EXIT 与外层 RHS/receiver prefix，并以 FRAME_HOLD operation身份计重复引用，不能按ValueID去重或信producer自报 consumed。

首门可证明局部 consumed suffix/normal continuation 和 prefix一致性；完整 outer-prefix来源、解释器监控/内联、runtime实例、全 frame lifetime/effects 仍 OPEN。未知中间 primitive 保具体 pending 前沿；明确丢失/重复/乱序不能降级 UNKNOWN。>30 pieces 的 list/append/join路径、TemplateStr 和尚无实际规则的 child 保原 UNSUPPORTED，不扩大成完整 Python 解释器。

## 4. 版本与必要门

复用已有环境 profile 字符串能力，不增加第五 capability/改 library旧3默认；无新 enum/wire/version迁移。新规则以冻结 producer SHA 和 validator policy `CPYTHON_314_FSTRING_SOURCE_V1` 明确绑定；现 `_producer` 的 source_*_lowering/source_*_validation glob会把新 verifier 纳入 work key。policy 是验证范围标识，不是新事实/metadata授权。旧 artifact 不重写、不声称曾经过新 verifier；历史结构读取保持原范围，独立 SOURCE_AND_CODE_WITNESS 结果另存新 receipt。

实现后只做必要小检查：真实 existing SG 的 missing-overlay JoinedStr+Name 路由；两completion中 wrong/missing release 或乱序piece必须拒绝。可复用原小marshal作 compiler负例，不新 compile target、不加全矩阵。首真实门从准确原失败subject/gap+AST/SG机械选 seq5，核 current report inventory/context资格，最多 lower一次；保持原256MB输入/输出、4000ops/body、180s/body、600s worker/660s outer及20s heartbeat。77MB roots 若必读均计原预算，root持有session；不重试92/85/217图、不将旧350 construction当可复用图。返回新前沿就保实档与OPEN，不自动扩语法/预算。结构、AST/compiler、局部pending分别报告；实际再遇 kwargs cleanup或其它未证不被字符串通过覆盖。

机器来源见 `SOURCE_RECEIPTS.json`（SHA256 `b5f18cff7625f6e0496aff9543f431a7c458c78ac39d3ac6b4251cbf8c82fe36`）；其中保存完整 source/body/SG/output/CodeWitness locator及本次源码SHA。未重放三个成功图、未扫全部 source、未做 Git 操作。
