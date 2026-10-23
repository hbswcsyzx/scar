# 自动 source front-end worklist

## 当前状态与历史计数纠正（2026-10-23）

**Implemented / Verified：通用自动规划和一次真实 worker window 已完成；新增 body 为 0，
完整建模仍 OPEN。** 下文是原只读设计记录，不代表本段更新后的实施状态。
`scar/analysis/source_frontend_worklist.py` 从完整静态/当前调用分母机械选派工项，
不按业务名称或旧错误字符串挑选。实际 window exit0，wall41.39s、RSS610876KiB；
全部2217 static bodies及817 groups/100438 calls保留，12 bodies/4 files实际尝试，
12个完整编译见证匹配成功，12个返回均为UNSUPPORTED，真实emitted operations1163。
没有新增graph、compile、target执行或优化，不能将这些结果称作优化审批拒绝。

原元数据投影错误地将全部 `__future__` flags 视作编译上下文，包含与CO_NESTED重叠的
结构位。生产规划改用原 `compile_cache_key`，未改旧归档。原出版前正确分母为
79 matching-variant bodies/2802 calls、10 missing-variant bodies/53 calls；两个正式
body发布后的实际window计划为77 metadata candidates/1752 calls。后者不是与旧错误
77/2751相同的一组。每次规划按准确输入重新计算，不把这些数字硬编码为选择规则。

确切producer、输入、逐attempt原返回、校正前后key及成本分别保存在
`first_stage_source_frontend_implementation_20261023` 与
`first_stage_source_frontend_automatic_20261023`。resume能力尚未单独实测；词法入口、
缺编译见证、未支持构造和未派工body仍显式保留。后继先补已定位的通用表示缺口。

## 原只读设计记录

2026-10-23。**只读设计 + 小元数据实查；未增加生产代码、恢复body或运行新gate。**
当前publication/runtime联合门的生产源码保持冻结。本项解决“下一批body由谁机械发现”，
不依据LeWM包名、qualname、变量名或旧reason字符串选择，不开始优化。

## 已核分母

仅用原partition manifest的151 source header shards、call_sources小组件、当前369749
binding/report与owned CodeWitness manifest。逐shard核physical/decoded SHA/size，binding
核report声明SHA；未打开CP图、105份依赖图、源码、UTF8 source缓存或marshal payload。
stdlib投影耗时1.52s，脚本/原输入收据/完整1377条缺body行保存在
`artifacts/analysis/source_frontend_worklist_20261023/`。

| 原静态body状态 | 数量 |
| --- | ---: |
| LOWERED_WITH_GAPS，均FUNCTION | 840 |
| UNSUPPORTED，均FUNCTION | 787 |
| NOT_ATTEMPTED | 590 |
| 全部分母 | 2217 |

590个未尝试包括CLASS301、COMPREHENSION253、LAMBDA27、FUNCTION9。不能把
NOT_ATTEMPTED一律等同“不支持该kind”，也不能用其reason决定capability。

| 1377个缺body的机械入口/见证分类 | bodies | 当前calls |
| --- | ---: | ---: |
| 同步FUNCTION，已有matching模块compile variant元数据 | 77（15files） | 2751 |
| 同步FUNCTION，模块variant未在当前owned库 | 12（10files） | 104 |
| FUNCTION，无完整CapturedCode/source见证 | 705（113files） | 0 |
| resumable FUNCTION，当前ENV入口不支持 | 2 | 47 |
| CLASS，需要class-body入口 | 301 | 260 |
| COMPREHENSION，需要comprehension/resumable入口 | 253 | 0 |
| LAMBDA，需要lambda表达式入口 | 27 | 0 |

分类使用DefinitionKind、完整CodeSourceLink/source/snapshot/definition匹配、code flags的
generator/coroutine bits、原compiler profile/future flags/optimize/module compile key。
**77是metadata可派工候选，不是77个必能成功恢复body。**manifest只证明某模块variant
被归档，不能证明任意nested CodeType已匹配；worker仍须完整describe_code匹配。

当前动态分母另列：817 groups /100438 calls = 已body74/5624、项目source-only
UNSUPPORTED91/2902、项目source-only NOT_ATTEMPTED260/260、外部source-only242/86688、
definition unresolved150/4964。后两类绝不丢弃：外部formal ref没有薄entry-kind记录或
当前project inventory admission容器，不能靠CO_OPTIMIZED或qualname猜成普通函数；
未解析definition也不能因为没有body row而退出总账。

此数据固定为联合发布前的immutable snapshot；两个新body正式发布后应从新manifest/
binding重新derive worklist，届时自然由“缺body”移至“已建图”，不手工排除两个ID。

## 队列是什么

worklist是分析任务与覆盖义务索引，**不是第二套Operation/producer图**。建议每项保存：

- 原SourceDefinitionReference，或原body/source locator；完整snapshot/context/root；
- 完整CapturedCode及CodeSourceLink/原compiler-profile见证，缺失保持缺失；
- execution entry kind/phase、adapter profile、语言capabilities版本、front-end producer版本；
- 当前Run/group关联与真实调用权重，静态未观察项也保留；
- 已有body状态、metadata readiness、独立预算、attempt历史/检查点与frontier。

身份键至少包含snapshot/context/definition、完整code variant、entry profile与caps/
producer版本。file_index是原artifact导航坐标，qualname只能在exact source已经确定后
作为旧lower API参数，不能作为选择/身份/等价性规则。

第一步是全分母登记，再分类READY_METADATA、WAITING_CODE_WITNESS、WAITING_ENTRY_ADAPTER、
WAITING_SOURCE_KIND_RECORD、OUTSIDE_CURRENT_ADMISSION_SCOPE等。UNKNOWN不是NONE，不能
把等待状态当永久拒绝、dead work或已完成。原诊断可展示，但不参与派工条件。

## 当前默认能力能自动尝试什么

SourceLanguageOptions默认三项可直接用于**有正规同步function ENV入口**的候选：
PYTHON_FIXED_LOCAL_UNPACK_V1、PYTHON_SLICE_KEYS_314_V1、PYTHON_LEXICAL_LOCALS_314_V1。
它们只补普通local fixed unpack、特定load slice-key、compiler/lexical local分类，
不是整个Python grammar的支持声明。不能从一条旧UNPACK/Slice诊断推导整个body将成功。

可机械尝试上表77项；其余保留明确需求。即使routine可入队，body中仍可能有with/try、
动态签名、starred targets、combined slice、comp等尚无adapter的构造。worker按真实AST
与当前protocol adapter决定，返回Graph/metadata或原unsupported frontier；不先扫描所有
源码，也不按reason substring挑只会成功的案例。

入口义务应由一个明确registry描述kind/phase与ABI：

| entry类型 | 当前可用状态 |
| --- | --- |
| 普通同步FunctionDef/method | ENV入口已实现；需exact source/code/closure-layout witness |
| generator/coroutine/async-generator | creation与drive/yield/resume/close分离，当前普通ENV入口拒绝 |
| class body | namespace/locals/metaclass/异常完成接口未接，不能当普通function |
| lambda | 表达式return/闭包入口未接，不能按“源码是代码”硬塞FunctionDef adapter |
| list/dict/set comp | lexical scope、save/restore binding、异常epilogue与迭代控制未接 |
| genexpr | 还需creation/drive分离；CO_GENERATOR不证明已成功创建或已进入body |
| module initializer/import body | 当前DefinitionKind/body目录本身无这一类条目；需既有SG module.initializer的正规entry目录，不虚构函数root |
| 3.14 annotation/type-parameter thunk | 需要独立evaluation/namespace/时机合同；不能按普通函数或同行号匹配 |
| non-file/dynamically generated code | 需要真实source origin/creation witness，不能猜文件或借另一CodeID |

registry缺项应产生任务/接口义务，不能从worklist删除。无需现在同时实现这些adapter。

## 高效worker路径

建议新增规划API（后继任务，不在本门实现）：

```text
plan_source_frontend(composition, current_binding_report, code_witness_manifest,
                     entry_adapters, capabilities, independent_budget)
  -> complete worklist + bounded dispatch plan

run_source_frontend(worklist, dispatch_plan, explicit_owned_code_witnesses, out)
  -> attempt records + successful program_paths
```

按file分组，优先已观察/入口可用项；原lexical_owner允许自顶向下排序，调用权重用于
分析优先级，不是reuse判据。全分母不因只执行一个budget window而减少。

1. 只有派到的file才`composition.source()`，复用已保存三图与exact context；当前source
   fingerprint/CodeWitness source核后，每file一次AST/symtable，构造PreparedSource或
   复用已有sealed session。不能每body重新prepare整file，更不能prepare151files。
2. `CodeWitnessStore.resolve(...allow_compile=False)`按原完整descriptor核真实CodeType，
   同module key只load一次。缺payload、build/magic/profile变化或nested匹配缺口明确记录。
3. 使用exact definition/source与现有profile/caps lower，不执行模型。原public core、
   structured/language与source验证仍执行；不以已知metadata当成功布尔跳校验。
4. 每attempt立即保存原返回与metadata/exception、原source/context/code refs、caps/producer、
   预算、operations_emitted（若确有live lowerer return）、图节点数、时间分别记录。
   graph=None/预算到限/进程中断均留检查点；不删除失败BUILDING产物，不伪造空成功root。
5. 成功图写SourceProgram5并登记原artifact receipt，自动汇出program_paths交当前正式
   publisher；不由实验脚本手选body名称或两固定索引。CP2对旧样例缺失构造成本仍为None。
6. resume仅对新capability/producer/source/compiler见证或明确预算变化的项再派工，
   已有相同输入的失败不盲目重跑；改变来源不能借旧CodeID/Run或原producer成本。

12个缺module variant是独立evidence-acquisition demand，不得偷偷扩大compile预算或改写
原只读20-key archive。未来若增加owned witness archive，需显式多archive原basis解析，
保旧manifest/CodeEvidence identity，不能通过合并/追加库让原SourceProgram receipt失效。
705个无captured witness的静态函数仍可保留完整源模型；其compiler入口证据需求与实际
运行观察缺失分开，不编造一条Invocation来满足条件。

## 后继有界验收

先验规划：全2217静态body和817当前groups守恒；77 metadata candidates自动出现，
每项可回到原snapshot/context/definition/code/module-variant refs，不看旧reason文本。
再由独立小budget窗口自动派工，核同file AST/context/CodeWitness复用次数、所有attempt
与失败产物保留、成功program_paths自然进入publisher与当前Run。这是后继门；本次
没有跑77/1377/2217个body，没有声明新的语言覆盖或性能提升，完整程序建模仍OPEN。
