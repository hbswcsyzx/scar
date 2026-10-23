# 实际 CALL 协议边界审计

2026-10-23。**Observed / Verified：两个原档的完整 operand 分类通过；完整建模仍 OPEN。**
本项回答原参数路由中的96,481条HANDSHAKE_BOUNDARY是什么，不修改原producer、
报告或trace，不执行SCAR模型导入/目标/源码prepare/编译，不生成优化候选。

## 原始结果

分别流读272038与369749的完整312,812条operand记录；各100,550次CALL_ATTEMPT、
4,069次ENTRY_HANDSHAKE、207,248条INSTRUCTION、945条GAP与各自原metadata逐项一致。
原codes的完整SHA/bytes核原metadata base_manifest；当前gzip另核archive中明确的
stored与decoded SHA/bytes，未猜gzip名称。新旧运行独立统计，未转移动态记录。

| 已观察到的 callable 分类 | 无唯一入口握手 | 有唯一入口握手 |
| --- | ---: | ---: |
| EXACT_FUNCTION，描述符文件位于原project root | 945 | 4,069 |
| EXACT_FUNCTION，描述符文件在project root外 | 7,320 | 0 |
| EXACT_METHOD，现协议没有该分支的code/layout | 40 | 0 |
| OTHER，现协议没有该分支的code/layout | 88,176 | 0 |
| 合计 | 96,481 | 4,069 |

每个原档中945次project-function无握手来自8个不同完整code描述符，全部同时具有
captured descriptor与dispatch layout的CO_GENERATOR(0x20)标志；其中一个code占900次。
两次原档唯一GAP理由均为PROJECT_FUNCTION_CALL_DID_NOT_ENTER，945条。具体原index、
caller invocation/thread/site、callee描述符及各code权重见result-attempt03.json。

**边界：**generator flag不证明调用成功、产生了哪个对象、参数已合法绑定或后续
哪个drive使用它；没有根据code名判断generator。OTHER不是native的同义词，不能
把88,176次全部称为C调用、Torch调用或缺少Python函数体。EXACT_METHOD也不能根据
method分类直接把self、底层函数和实际入口接起来。project-path分类只是原采集
谓词的投影，不是纯性、源代码证明或当前文件版本检查。

## 来源审查与下一项

已读trace/call_operands.py的_on_call/_on_frame_enter：只有exact FunctionType且
目标code位于project root才建立同步_pending；它没有分开generator创建与body驱动。
analysis/call_operand_routes.py先对全部attempt统一要求唯一entry handshake，故
不同协议与实际漏采混在同一问题种类。不能删掉问题就称路由已闭合。

后续必须分别建模普通函数调用、方法receiver/descriptor、通用callable派发，以及
resumable creation→object/environment→drive/resume/yield/close。当前仅是精确诊断，
没有新增这些规范关联，没有把生成器flag当创建成功，没有重写历史GAP。
详见docs/CALL_PROTOCOL_FRONTIERS.md。

## 运行收据

- attempt01：5.90s、exit1；脚本错误地要求未压缩的小metadata也出现在archive。
  失败脚本audit-attempt01.py及原stderr/time完整保留，没有改变原档。
- attempt02：修正为显式archive条目或原精确plain路径（不猜后缀），exit0，12.28s；
  原result.json及audit-attempt02.py固定该次实现与输出。
- attempt03：为回答945次是否全部generator，新增逐code/flags统计，exit0，11.80s，
  peakRSS155,872KiB；result-attempt03.json绑定当前audit.py的准确SHA。

这不是完整frame/operand公共codec验证、源码/实际参数路由或新的完整模型验收。
原已验证路由产物未修改；其他frame、source、environment关系也未重新验收。
