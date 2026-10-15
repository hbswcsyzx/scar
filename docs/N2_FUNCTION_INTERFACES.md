# N2.signature 实施协议：函数接口、绑定计划和 body

日期：2026-10-15。状态：**实现中，尚未验收**。父计划
[N2_SIGNATURE_PLAN.md](N2_SIGNATURE_PLAN.md)；前置 `9b5bba8`。

## 三个不同阶段

1. **定义阶段**：外层执行defaults/decorator表达式、创建函数对象、应用
   decorator及名称绑定；annotation时机有独立边界。保留既有DefinitionInput、
   ExecutionPhase与隐式调用，不能因为body存在而删除它们。
2. **调用绑定**：actual表达式/展开、callable及当前函数对象状态决定formal
   绑定。绑定可能在body入口前失败；source signature仅描述条件候选。
3. **绑定后的body**：全部formal引用和frame/world已可用时的执行Region。
   不在这里重算defaults，不假造*args/**kwargs对象，也不宣称调用会到达此处。

结构类别仍为Operation、Value、StateLocation、Region。接口overlay给已有
槽、值、操作和区域之间的关系，不增业务语义节点或优化backend。

## 强类型接口

`FunctionSignature`绑定定义ID、SourceReference、函数种类、canonical formals
和decorator来源。每个formal记录ParameterKind、name、源码槽、arg来源和可选
default声明来源。五种kind的顺序为posonly、poskw、varpos、kwonly、varkw。
旧frontend input_slots顺序不同，必须按name/slot对应，不能按位置zip。

`BodyEntryInterface`按完整signature显式对应formal slot→入口ReferenceValue；
world单列。入口模式是BOUND_FORMALS；async、generator和closure/cell继续有
定位明确的执行/状态边界。普通同步函数的defaults/decorator/kwonly/variadic
不再阻止其原body单独构图。

`CandidateBinding`保存call/target/source、actual来源与可用UseID、每个formal
的来源计划、issues和固定未证明条件。状态仅指**在源码raw signature及所列
条件成立时的兼容性**：CONDITIONAL（完整计划）、INCOMPLETE、INCOMPATIBLE。
它不表示实际TypeError或body被执行，不连接call/body完成边或core callee。
BOUND模式的旧CallTarget.arguments/results均为空，防止旧固定参算法误配子集。

默认路线是DEFAULT_STATE，引用默认声明以说明来源，仍需核对实际函数对象的
defaults布局和版本。修改__defaults__/__kwdefaults__会改变缺参/默认路线，即使
code witness精确匹配也不能省略这个条件。varpos/varkw路线显式表示tuple/dict
打包计划，包含空pack；不是现有容器Value，不是直接alias actual。

实际参数的`*`/`**`、decorated目标、异步/生成器调用暂存INCOMPLETE，保留来源
和effects边界。posonly同名keyword若有varkw则进入varkw；缺posonly实际值仍按
raw signature检查。任何状态都不能删掉actual求值、展开、打包或定义时效果。

## 持久化与迁移

默认inventory（有/无trace）改为v4：全局调度＋BOUND_FORMALS＋独立interfaces
overlay。无trace不制造观察记录；runtime_scope为空。v1/v2按原文件策略、v3按
原全局策略及LEGACY body规则重放，不能把旧UNSUPPORTED升级为新事实。

旧LoweringMetadata/CallTarget严格wire不增加字段；ParameterKind移公共模块并
由inventory重导出同一enum，wire值保持。PreparedSource.lower保留LEGACY默认；
BOUND只支持单根。旧model-program/source-program v1继续作为legacy诊断路径。
v4核对完整signature、参数/Use/入口/world关系及现有源码/trace/预算，并重新
构建所有接口和绑定计划；不能信报告自报的条件、profile或CONDITIONAL状态。

## 自主验收

| 门 | 必须证明的有限能力 |
| --- | --- |
| F1 类型/规则 | 五种formal、slots/ports/argument routes；strict codec、全覆盖、不相容/不完整与固定条件 |
| F2 自动body | 实际源码自动生成bound入口；defaults/decorator效果仍外置；默认值不重算；async/gen/closure明确拒绝 |
| F3 绑定 | 显式pos/kw、默认状态、posonly＋varkw、空packs；缺参/重复/过量/未知keyword；star/decorated边界；不改core callee或完成边 |
| F4 集成/迁移 | 默认单入口v4，无trace/真实trace都不手工补图；旧v1/v2/v3历史包报告重放；来源/slot/port/route/profile篡改拒绝 |
| F5 外部/版本 | 冻结gate/全仓、原LeWM入口与同一归档trace/预算自动重建和重放；逐观察候选阻断变化、真实成本、报告与commit/push |

通用反例包括可变default共享/内容写、移除/新增defaults、删除kwdefault、
decorator替换/抛异常、default求值抛异常、调用前重绑、两次调用不同actual、
绑定前求值/展开异常。只做source计划时，必须明确相关执行效果仍未闭合。

本门继续不新增detector/backend，不修改LeWM，不声称callee、effects、逻辑
值身份或完整程序可化简。完成后按真实阻断补循环、状态和跨层来源，再接化简。
