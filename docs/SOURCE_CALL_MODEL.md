# 通用 kwargs 调用建模

2026-10-25。Implemented，并在原保留源码上获得三个有限合格图；完整程序仍 OPEN。
规则依据 Python AST、原 SG、编译见证和有序端口，不含 workload/function 名称判断。

`f(a, **m, k=v)` 分解为 callee、位置参数及tuple、完整named-keyword runs、dict、
DICT_MERGE、CALL_FUNCTION_EX，各有normal/raise world。DICT_MERGE保留原callee用于
异常语义；不能用dict display的DICT_UPDATE替代。重复引用保留有序持有次数。
原SG的OPAQUE/ast_type=Call与Opcode.CALL分别核验，详见[类型层](TYPE_LAYERS.md)。

SourceProgram结构读取新增显式`source_texts`，仅STRUCTURE模式使用。现有source/CFG
validator继续核fingerprint并重算；缺key不回退live文件。默认策略及旧wire不变，
SOURCE_REPLAY不接受该覆盖。CodeWitness、AST及局部pending另行验证。

| 原AST规则选中的序列 | 实际结果 |
| --- | --- |
| 4 | 92 ops原图复用；结构、AST/CodeWitness、局部pending通过，未重lower |
| 5 | 新lower返回350 construction ops；越过kwargs，停于JoinedStr，无返回图 |
| 10 | 新图85 ops；结构、AST/CodeWitness、局部pending通过 |
| 12 | 新图217 ops；同层次检查通过 |

四项全部保留。三个图的完整call cleanup、外层lifetime、实际runtime/effects尚未证明。
CodeWitness compile、fresh prepare、target exec均0。实际门曾分别暴露错误枚举、旧reader
读取live源码、256MB输入预算及终检allowlist遗漏，原失败不改写。末窗口52.887s/exit1
发生在两个图完成验证之后；独立postflight0.245s/exit0仅补原源码SHA/27stat及存储SHA
终检，不能称原窗口exit0。没有再次lower两个已返回图。

公共SourceLanguageOptions保原三能力默认；高层自动SourceFrontend明确列出四个已支持
能力（含kwargs），通过既有plan/work key及producer记录传递。能力不再随enum增长自动
启用。此policy已做导入/默认值检查，本轮没有重新执行全2217项自动planner。

准确来源和失败在`codex/source-call-model`的
`artifacts/experiments/source_call_kwargs_bodies_20261025`；main应用收据在
`artifacts/experiments/source_call_model_applied_20261025/receipt.json`。
新图尚未正式发布进843源码快照，也未重派原运行的attachments/ports；不能把图返回
说成当前snapshot已增至846。下一步批量正式准入和连接，JoinedStr继续作为独立缺口。
