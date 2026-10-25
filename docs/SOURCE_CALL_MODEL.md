# 通用 kwargs 调用建模

2026-10-25。Implemented，三个原图已正式发布进846静态快照；原总门为
FAILED_ENV_FREEZE，完整程序仍 OPEN。
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

三份原图已按普通ADD_GRAPH路径加入原843父快照，正式静态结果为846 active bodies、
2217定义/151文件，781 UNSUPPORTED、590 NOT_ATTEMPTED。原artifact URI与namespace保留，
parent准确指843且严格compiler-origin保留；新CP2的construction cost仍Unknown，不用92/85/217图
大小替代。publisher使用readonly CodeWitness归档文本；typed reader新增显式可选
source_texts，默认策略不变，没有重lower、compile或执行目标。

本次publisher/composer完成，三项公共结构/AST/CodeWitness reader实际逐项PASS；原总门
281.584s/exit1，因最后participant审计发现`_compat_pickle.py`未预冻结，状态保留为
FAILED_ENV_FREEZE。这只是首先报告的缺项，完整历史runtime字节清单仍OPEN，不能用
现在的新hash追认执行时字节。独立metadata postflight实际exit0/0.149469s，读取stored
29214490B、decoded metadata326576B，核383份文件；没有重解composition或三图，也没有
重跑producer。产物可读与原门资格分开，不能把postflight通过写成原门exit0。
见[本次产物及边界](../artifacts/experiments/source_call_kwargs_publication_20261025/postflight01/RESULT.md)
及[准确receipt](../artifacts/experiments/source_call_kwargs_publication_20261025/postflight01/receipt.json)。

最新完整runtime接线仍为843快照；846新增body尚未重派原运行的attachments/ports。
归档文本通路已补到composer的显式`source_texts`参数和SBA的CP2消费入口；CP1默认策略保留。
一次实际定向检查在禁止读取live LeWM源码时成功读取已发布92ops图，8.143s、compile0。
这是公共CP2结构消费的证据，未重跑composer或SBA runtime，不追认旧总门的环境字节。
见[定向检查](../artifacts/experiments/archived_source_consumer_20261025/receipt.json)。
后继汇总增量接线，避免每个body重扫原100438调用。
JoinedStr、完整kwargs cleanup/outer lifetime、内容/state/ready及第一阶段继续OPEN。

通用缺-overlay字符串恢复四文件现已从`codex/source-call-model`的817481c7原样接入。
真实seq5门exit0/9.882s，construction从原350推进到634，下一前沿是comprehension作用域；
仍未返回graph，不能计为新增body或该body完整数据/状态连通。33ops小fixture验证与真实
partial construction分开，完整图上的独立字符串验证未在该真实body运行。实际报告在
该分支的`artifacts/experiments/source_joinedstr_target_20261025/REPORT.md`；
主树[应用收据](../artifacts/experiments/source_joinedstr_applied_20261025/receipt.json)记录准确四源码。
