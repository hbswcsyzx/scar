# P0 GeneratorExp：创建与驱动最小设计（仅设计）

范围来自原 `next-frontiers.json`：seq1/fi140-bi7（900次父函数调用）和seq19/fi133-bi35（4次），不是904个generator对象/drive/yield。原源、SG、两份小readonly marshal的代码元数据与positions见 [SOURCE_RECEIPTS.json](SOURCE_RECEIPTS.json)；无raw/77MB root、compile、target或lower。两GenExp原SG定义均为 **OPAQUE+ast_type GeneratorExp**，各有原comprehension target slot；旧计算记录均opaque/0 operands，不能改成FUNCTION或伪造旧StaticValue。

| 原真实形状 | compiler证据与必须保留的差别 |
| --- | --- |
| `q,k,v=(call(t,...,h=self.heads) for t in qkv)` | nested code路径`[8,3,3]`，参数`.0`、local `t`、freevar `self`、flags51；先closure/function创建，再qkv求值/GET_ITER，再generator创建；UNPACK_SEQUENCE3驱动。`self.heads`与elt调用必须延迟到drive，捕获self的cell，不能提前读属性值。 |
| `not any(dim==3 for dim in shape)` | nested路径`[14,4,1]`，`.0/dim`、无freevar、flags51。真实3.14.7有`LOAD_COMMON_CONSTANT/IS_OP` guard的inline迭代快路及普通CALL fallback；同一源码在两分支各创建一次，必须共享一个body Region，不能按`any`拼写假定callee。 |

**三个阶段、同一body。** 创建端保实际witness顺序：代码/closure函数对象→最外层iterable eager求值及GET_ITER→创建generator handle；每步有自己的normal/raise world，失败不运行后续，均不标pure。只有外层iterable eager；内层迭代、条件、elt及全局/属性查找均在lazy body B。保存`.0` iterator而非预先展开元素；函数对象确实由MAKE_FUNCTION产生，globals/新函数saved-builtins/defaults/closure按其版本合同取得，不能假设新builtins等于父函数saved-builtins。`ResumableCreate.body=B`、完整`CreationCapture`及normal handle端口表达创建，不把创建CALL接成同步执行B。各Create有独立handle/instance Use，共享B只是共享定义，不合并运行对象。

**复用现成driver而非另造generator IR。** [drivers.py:109](../../../scar/ir/program/drivers.py#L109)已有ResumableCreate、CreationCapture、DriverInterface、BodyStart/BodyResume/BodyDrive；[resumption.py:64](../../../scar/ir/program/resumption.py#L64)已有ResumableBody、FrameContext、SavedSlot、Suspend(YIELD)/ResumeSlot；[lifecycle.py:28](../../../scar/ir/program/lifecycle.py#L28)及protocols的GENERATOR_BODY/CREATED_CLOSE/SUSPENDED_CLOSE合同区分NEXT/SEND/THROW/CLOSE、yield/return/raise与created/suspended/closed。新producer产出这些原记录；driver规则implementation指版本化合同原artifact，不充作运行证据。created-close不进入elt；throw/close注入正确resume位置；terminal release、非完成和finalizer effects保持具体条件/OPEN。B内部用原SG slot和canonical CFG/Use/world建迭代，复用ADVANCE_ITERATOR；`.0`已经GET_ITER，不能再套普通for入口重复GET_ITER。

**composite接线。** 同步consumer调用的`Operation.callee`可指consumer/driver composite U/D，U内调用D，D的BodyDrive指同一B的BodyStart或Suspend successor，创建端和两creation分支也都只指B。固定解包从已有UnpackShape机械产生N项+一次过量检查，不按业务名生成。第二项按真实compiler guard建立两路；VM common-constant的table index作为原typed Use操作数并核witness，不伪成co_consts或Python scalar对象。fallback只保动态callee+generator参数，actual consumer→drive未证则明确OPEN，不强接已知builtin；不填CallEffectExpansion冒称完整effects。原call/interface边界仍保留，内部驱动欠项不能计完成。

**最小接口改口；优先沿用SourceProgram5。** core已有全部执行字段，无需graph codec29；外层仍是同步函数的STRUCTURED_ENV，v5容器可装nested B/driver regions。显式新增非默认`GENEXPR_314_V1`能力及必要MAKE_GENEXPR_FUNCTION/CREATE协议；library旧3、main planner旧4不自动增长。新`source_generator_lowering.py`/`source_generator_validation.py`接env/heap表达式与language validator：复用CodeConstantSource定位child CodeType，按闭合const-path解析，父captured descriptor不冒充子代码运行身份。`.0`用FunctionEntryLayout/FormalPort表达真实编译器参数，slot锚定原qualified GenExp/SG定义+code artifact/const-path/ordinal，不造SG slot；target仍用原`t/dim` slot，free-cell接口复用env。内层缺旧overlay，须复用SG-backed Name/Constant/Attribute/Call恢复，并按原SG/子代码补Compare有序inputs/INVOKE；不手填计算结果。缺的是producer和source↔code/entry/capture验证，不把`.0`塞入只接受原SG slots的CompilerLocalMapping。

现检查的真实阻断须按新cap做**封闭region分区**：source_environment_validation:38硬要求全图唯一env；structured_lowering:668将FRAME_ENTER只对根入口、:748仅识别AST For/While；language_validation:237将常量强绑父code及slice/tuple/call。只让新validator核所声明B/D及其compiled参数/closure/temporal CFG，根函数旧检查照常执行，其余未归属region拒绝；不全局删guard。既有typed core/CodeConstantSource/UseSource足够索引本轮两形状，先不加language wire字段、不占class/v6；双分支创建必须与witness CFG形成唯一对应，若实现不能核回，暂停审明确typed occurrence字段，禁止塞metadata或放宽v5解码。

首门只机械重试这两原qualified主体，保完整分母，最多一次/项；分别报创建、lazy-body source连接、驱动/close展开、结构和代码验证，预算另交root审。仅越过创建前沿或保存B不代表drive已展开，更不授runtime/effects/优化合法性。class/v6继续仅保设计。
