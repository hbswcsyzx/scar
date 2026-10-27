# S2：模型表 / v15 wire / 原端口静态查询

状态：**Implemented；自有 focused 最终 45 PASS，未执行组件或全仓**。本轮不代表整个 M1、owner/selector 自动恢复或 alias/coherence runtime 证明完成。

## 实施范围

仅修改 root 授权的 5 个产品文件与 2 个新测试文件。A 的 records/validator/fixture、root 的动态查询与旧测试未由本代理修改；没有新增 backend、detector、第二套状态 SSA 或 producer。

- model 从 `state_modes` import/re-export 唯一 AccessMode；保留旧公开 API 与枚举值。新增尾部 `state_address_refinements=()`，严格 tuple/exact row、嵌套重校验、site 唯一；不声称仅字面 site 唯一即足够，派生 `(operation,carrier)` 唯一由 A 图级 validator 检查。
- `validation.py` 挂接 A 的 `state_address_errors(graph)`，原 owned Uses、SSA/current-state、CFG、completion slots、call/context/native/resource 校验完整保留。
- codec 最大 schema 15，只有新表非空选择 v15。全部旧版本字段集显式排除该表；旧版偷带空/非空新表拒绝。v15 必须有非空能力、准确字段和嵌套本地 tags。没有新表时编码能力不升级，也不向旧图补精度。
- 复用原 `record_codec` 的局部 tags；空 owner / WholeOwner / CellContent 等不能因相同 dataclass shape 串型。新 tag 不进入旧字段词汇；正常 label 文本等于 tag 字符串仍合法，不做字符串扫描式“能力检测”。
- v1 保留既有升级至 v2 的行为；v2–v14 的独立 frozen wire 字节相同。复用既有 v14 golden/proof，额外直接对照其原 factory 生成 bytes；没有重造任何旧 golden。

## `ProgramIndex.state_address(site)` 实际接口

输入严格为 ExistingAccess 或 InvokeStateOperand，查原 operation/FK；不存在/不适用 site 拒绝，不能输入 caller proof facts。

```text
site, refinement, operation, carrier, access, before, after,
completions, effects, coarse_dependencies_retained,
address_interpretation_verified, conditions,
source_runtime_verified, transformation_authorized
```

- site/refinement、Operation、StateLocation、StateAccess、UseSite、StateVersion 均为原记录/索引对象；没有复制新 value/producer。
- ExistingAccess 的 before/after 只沿原 summary；INVOKE after=None，逐实际静态 successor 保留 `successor_index/successor/formal/argument`，不默选 NORMAL。argument 是原 CompletionResult 或独立原 forwarding UseID；不是重新创造状态。
- effects 保留 `index/effect/owner_use/resource_use/operands`。ReferenceOwner 保留原 owner UseSite；ResourceOwner 保留原 ResourceUse。UnknownOwner.operands 先保留，后接 path helper 的 selector operands，按 path 顺序且不去重。相同 Value 的两个 Use 也不合并。
- 未声明 refinement 时，原粗 site、before/after/completion 仍在；effects=() 不是无效果。conditions 明确地址精度 unknown。
- 结果字典可由调用方局部修改，不会改变下一次视图或规范图；原记录本身仍 frozen。视图从不成为 ProgramGraph wire 字段。
- `coarse_dependencies_retained=True`，其余三个 verified/authorized 属性恒 False。conditions 明确 typed path 不解释旧 Footprint 未指定的单位，DECLARED_COMPLETE 也不是 native/source/runtime applicability 证明。

## 实际命令与尝试

激活命令：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_state_locations/focus.py codec_queries tests/unit/test_program_state_address_codec.py tests/unit/test_program_state_address_query.py
```

每次 exact 子命令、Python 版本、source.before/after、stdout/stderr、JUnit、退出码及临时目录清理记录均在对应 attempt 中，未覆盖失败。

| 尝试 | 真实结果 | 归因/变化 |
| --- | --- | --- |
| compile_ready.json | AST parse + 产品 import 成功；schema15，单 AccessMode identity=True | 不执行 fixture/pytest；仅初始实现的 import 证据，最终 hash 另见 manifest。 |
| attempt001 | 44 PASS / 1 FAIL，pytest 1.21s | **自有测试构造错误**：forwardState 将 NORMAL CompletionResult 换成新 owned Use，却未从 CompletionSignature 删除对应 produced slot。原 `completion_slots` 正确拒绝；无产品 bug 或规则放宽。 |
| attempt002 | 45 PASS，pytest 1.12s | 仅修测试：去掉被转发的 produced slot，并保持剩余 CompletionResult 的位置对应；合法 forwarding Use 与 fresh RAISE state 分开。 |
| attempt003 | **45 PASS，pytest 1.06s** | root 要求增加 interpretation=False 与条件说明；同两文件/同 case 分母，补现有断言后复跑。 |

这三个 pytest 尝试不是 134 个独立用例；最终分母是 45 个 focused case。首次 44P1F 和中间结果均保留。

## 覆盖与未覆盖

已验证：唯一 AccessMode/旧 API；新能力精确 roundtrip；原 producer/access 不变；嵌套 tags/坏字段/私有篡改/重复 site 拒绝；v1 迁移、v2–14 全部 frozen bytes；v14 proof + 原 factory bytes；旧版新字段拒绝；无精化的粗依赖；原 owner/resource/operand identity；重复 Use/path 与同值独立端口；INVOKE N/R 反序、各自准确 CompletionResult 槽、独立 forwarding Use；视图局部修改不污染原图/下一次查询；错误 site 与 caller facts 拒绝。

未覆盖或本门不宣称：任意 Python key equality/hash/descriptor 执行、native effect 捕获完整性、跨 artifact object identity、单位/geometry 推断、精确多 owner ContentRead 对齐、自动 source lowering、LeWM 性能。branch/loop/call/resumption 与动态 occurrence/current-state 组合由 root 的 S3 实测及完整分母另行记录，不能拿本轮 45 个计数代替。

## 冻结指纹

`final.source.json` 保存 bytes、SHA、LF EOF/无 CRLF；`git diff --check` 自有文件通过。最终 7 文件：

```text
bb9993520ee76ab6dd5531884944f96a990379fff74d7935c81a10b818df4d61 scar/ir/program/model.py
82661bc66d8955a2dbf354282e0bd7d701e367c01777a61d3c52339075e48e8e scar/ir/program/__init__.py
81cac8e544bfab868d95b037bd8149c4e73cb9e18b128c244bdc104136084089 scar/ir/program/codec.py
277c32f7434bf1a7c08c0ac458792b5dd6971dc3b14f8b7ccbfcd50ba7923a09 scar/ir/program/validation.py
d3519de9474369bb20d25950ae7f45d151f5ca54a78d367452d6c30825116134 scar/ir/program/queries.py
e965d41e70867f2050392ec2b0aaf083a03939ad29e408e6eb7b7b4eb6ebc90b tests/unit/test_program_state_address_codec.py
1ee77e2c1fd83fa4cf7787dd9dbc25add2df07695f8b07c76279413993e1b4f4 tests/unit/test_program_state_address_query.py
```

focused 开发阶段同事可编辑其独占文件，source before/after 已如实保存；最终全局冻结和唯一 full 由 root 执行。本代理现停止自有 source/tests 写入与重复运行，等待明确的有限复审任务。
