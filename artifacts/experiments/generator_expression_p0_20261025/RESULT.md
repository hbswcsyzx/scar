# GeneratorExp P0：一个实际 retained 主体已返回，整体仍 OPEN

Root 持有的 session18979 已 actual exit0；candidate03 outer 21.567357s、worker 21.2695613s，SELF RSS 444092KiB。原 seq1/fi140-bi7、qualified body `63baf552aebd035e2a9a32674e209bf8c590a8f23dc4087973f777629e1db0fe` 返回 **312 个静态构造操作**，状态 `RECOVERED_WITH_OPEN`。**900 是原 retained catalog 的父函数调用权重**，不是本次执行900次、generator对象数或drive/yield次数。另一个4-call guarded消费主体本轮未尝试，原UNSUPPORTED保留；未重放任何既有成功body。

实际声明的是 root + 一个同一lazy B + Start/Resume两个D + 固定解包consumer U。`ResumableCreate/CreationCapture` 保存真实compiler `.0` iterator接口和closure cells；创建不callee B。最外层iterable/GET_ITER eager，elt/global/attribute/cell内容读取延迟到B。`BodyDrive` 指向同一B的Start/Suspend successor，consumer做N项加一次excess probe。elt逃逸异常经显式非pure PEP479适配，ADVANCE的StopIteration自然耗尽另行处理。

普通SourceProgram5完整roundtrip相等、全图core校验、准确归档AST/options与readonly CodeWitness及专用Gen source/childCode/temporal分区检查均通过。实际wire沿既有字段选择core15（codec最高28），无新wire字段；`root_projection`仅临时校验视图，实际artifact保留全部B/2D/U与typed refs。通用root的`code_constant_provenance_verified=false`保持原值；专用Gen child resolver另验parent witness的准确childCode槽，未据此宣称child tuple/slice常量协议已支持。本门child标量来自AST `LiteralOrigin`，不把parent `co_consts`当child常量表。

本cap只覆盖一clause、无ifs、固定解包的当前形状。created/suspended close、throw、运行对象/代码实例、RNG/完整callee效果、内部primitive消费与outer lifetime/finalizers仍 **OPEN**。GENEXPR能力显式opt-in；library旧3和main planner旧4默认不增长。没有新LeWM episode、没有发布或ADD/current/runtime接入，既有 source858/runtime843 坐标保持。

实际retained输入 **111521958B = stored 21416597B + decoded 90105361B**。target executable compile/exec/prepare均0，CodeWitness compile0；analysis AST-only compile 5次、symtable 2次，non-target compile audit events 1174，因此不称all compile0。输入EOF SHA、355 source/142 runtime/26 stat终检通过；I/O输入/输出各256MB、4000ops、body180s/worker600s/outer660s预算未提高。

SourceProgram5 artifact stored 1021473B / decoded 10159626B，stored SHA `f951c65a4e6a7cd9b58b00c6512b5abcc8edd45d30dc39bf7faa3efd16fc004b`；原URI与decoded SHA见[RETAINED_ARTIFACTS.json](RETAINED_ARTIFACTS.json)。该graph及1260679B returned metadata留本地，不入Git。`check01`至`check12`小检查过程原样保留，最终204-op内部fixture与真实312-op窗口分列；candidate01/02仅NOT_RUN，原freeze/runner未改。final freeze SHA `bf198d1d81581c46cc6e2ca46bf9afb39f4f1a80197be94729b8652ee2f2d643`。

精确8份main应用diff与SHA见[APPLICATION_RECEIPT.v2.json](APPLICATION_RECEIPT.v2.json)、[candidate-production.v2.patch](candidate-production.v2.patch)。第9份isolated worklist仅归档默认4修复，**main应用时排除该文件**，保留main eligible-body接口/发布/native修复。root负责main接入；本提交仅隔离实现和有限证据。
