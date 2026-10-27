# GeneratorExp：创建、延迟区域与消费驱动

2026-10-25。Implemented；一个真实LeWM函数体的静态source/CodeWitness/公共读回
Verified。未发布新静态快照，未连接该函数的动态调用，完整模型仍OPEN。

## 模型与实现

复用原Operation、Region、Use、环境和resumption/driver记录，未新增core wire字段。
显式选择`PYTHON_GENEXPR_314_V1`后，前端从原AST、SG和准确readonly父CodeWitness
恢复子code及入口，生成同一规范图中的五个区域：

| 区域/记录 | 实际含义与依赖 |
| --- | --- |
| 原同步函数 | 读取child code，创建函数/环境，求值最外层iterable并取得iterator，创建generator handle |
| lazy body B | 捕获`.0` iterator及closure cells；被驱动后才读取global/属性、计算元素和yield |
| start/resume两个driver | NEXT分别指向B入口及同一个suspend的后继；传递状态并发布实际body outcome |
| 固定解包consumer U | 先start、后resume，取得N个结果并多驱动一次检测元素过量；保留不足/过量异常出口 |

Create不把B接成同步callee。原SG中的GeneratorExp OPAQUE定义及target slot保持原身份；
编译器`.0`是按原定义/父code/constant slot定位的FormalPort，不伪造SG词法slot。
同一body定义可多次创建不同generator；此次静态图不合并动态对象或调用。

源码验证先检查完整core，再校验B/driver/consumer的封闭分区及source/closure/驱动对应，
最后以临时根视图复用原同步函数验证。根视图不序列化；公共SourceProgram5保存全部区域、
有序Use及原记录。未声明的额外Region/environment继续拒绝。

## 已验收范围

当前仅支持一个同步clause、无filter、Name target和直接固定解包消费者。
最外层iterable eager求值，元素计算及captured-cell/global读取延迟；iterator自然耗尽
与元素抛出的StopIteration分别处理，后者通过显式PEP479异常适配primitive。
close/throw、异常清理与finalizer、运行实例、callee完整effects/RNG仍有具体缺口。
child tuple/slice/code-constant读取未取得正确child witness时保持UNSUPPORTED。

真实门一次处理原运行中调用权重为900的一个父函数体：312个静态构造操作，
1个Create、1个lazy body、2个BodyDrive，公共SourceProgram5完整读回和独立源码/
readonlyCodeWitness检查通过。outer exit0/21.567357s、worker21.269561s、peak444092KiB；
实际输入111521958B，含stored21416597B及decoded90105361B。target执行、可执行
compile和prepare均0；分析AST-only compile5及symtable2另计。

另一guarded-consumer形状的4次父调用未进入此门，原UNSUPPORTED保留。900不是已
连接的generator实例、yield或drive数量。正式source858/runtime843及6699已连接调用
不变；该图和此前两张修复图待按批发布，不能预先增加覆盖率。

精确八文件应用及main读回见
[应用记录](../artifacts/experiments/generator_expression_applied_20261025/APPLICATION.json)。
实现位于`source_generator_lowering.py`及`source_generator_validation.py`；library默认
三能力、main planner默认四能力及`eligible_body_keys`均保留，新能力需显式选择。
原真实门保存在`codex/source-call-model`分支的
`artifacts/experiments/generator_expression_p0_20261025/candidate03/attempt01`。
