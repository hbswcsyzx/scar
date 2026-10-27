# M1 S：原状态依赖上的 owner/selector 地址精化

基线：干净 `78dbac3dcd7a303d84ce645a68f52a6a4cf8f1a2`。
R3.3的722组件、5,055冻结全仓已通过；本文件是本门计划，不是通过报告。
第一阶段M0–M2未完成；本门后继续literal、C2/D3与M2原完整分母。
不新增detector、backend、lowerer、LeWM规则或重型profiling。

## 1. 审查后冻结的原则

StateLocation是唯一版本化coherence carrier，字段/key/cell/元素不是另开的SSA链。
相互可能alias的访问使用同一个原carrier；粗写→细读和细写→粗读都必须消费其
当前版本。不同LocationID/ReferenceValueID/Region/resource definition不证明隔离。
本门不增加partition/overlap关系，不能用描述新建两条不同步的粗细状态链。

一个atomic op可read x/read y/write out；每个原summary有多个地址effect，原
before/after仍只存在StateAccess/INVOKE原端口。地址、实际效果、物理内容/来源
对应不同：Python属性、getitem/hash/eq/descriptor仍需原操作/Uses/异常出口；
字段名不能授纯性、disjoint、恒定或完整捕获。

## 2. 规范接口（实施合同）

新增ProgramGraph.state_address_refinements，成员为：

```text
StateAddressRefinement(site, effects, coverage, protocol=None)
site = ExistingAccess(operation,index) | InvokeStateOperand(operation,state_use)
AddressEffect(owner,path,mode:AccessMode,stage:int|None=None)
owner = DomainOwner | ReferenceOwner(use) | ResourceOwner(requirement)
      | UnknownOwner(reason,operands)
path = nonempty tuple of selector steps
selector = WholeOwner | NamespaceKey(keyUse) | ObjectField(name)
         | DynamicField(nameUse) | CellContent | Element(indexUse)
         | Slice(startUse|omitted,stopUse|omitted,stepUse|omitted)
         | StorageRange(unit,startUse,countUse) | UnknownSelection(reason,operands)
coverage = PARTIAL | DECLARED_COMPLETE
unit = BYTE | ELEMENT | ABSTRACT
```

mode复用同一个AccessMode；必要时将原enum机械提取至state_modes.py并在model原API
re-export，不造第二个mode定义。新嵌套variant使用明确本地wire tag，新增能力选择
program v15；空新表必须保持v1–v14旧能力的字段/编码，不给旧模型补精度证明。

所有动态owner/key/index/slice/range operand引用该op原owned Use；不能复制Value。
key/index可以是Data或Reference，不能假定是unboxed int或执行转换。省略slice bound
与实际传入None的Use不同。StorageRange单位不解释旧Footprint整数单位，不复制
v2 allocation/Mat/shape/stride/dtype几何算法。protocol只为原scoped FactRef，未解析
不成为证明。stage仅声明可能的内部分期，不证明异常时哪些阶段已执行或work完成。

ExistingAccess必须选择原summary，唯一路径key由op+派生carrier确定。模式不得超出
原READ/WRITE/RW；DECLARED_COMPLETE需mode union一致，但不升级effects_complete。
原reference非None时地址不能越其已声明引用/envelope；aggregate reference=None
允许多个原Reference Uses。新selector不可把局部whole-owner写当成coarse root的
full_overwrite；细写仍须保留STATE_CONTENT旧依赖。

InvokeStateOperand必须是该INVOKE原invoke_arguments中的StateVersion Use；其它
地址operand也必须是实际invoke_arguments，不能借仅successor forwarding的Use。
NORMAL/RAISE的before/after从原端口派生，不在新row存after、不默选NORMAL、不把
fresh完成state当实际物理写；删除地址声明不得删粗依赖/opaque/source威胁。

## 3. 连接和公开查询

静态query从原site返回canonical access/invoke state input、before/after（INVOKE
各个完成边分开）、owner/key等原UseSite。动态query复用resolve_canonical_effect、
UseOccurrence、当前carrier、实际completion和denotation/resource binding，按本次
activation/visit解析；不使用同静态ID或同字符串来猜object identity。

本门不引入通用alias求解或任意Python key比较器。查询明确保留完整原refinement与
未检查项，有限预算截断不变成DISJOINT。精确物理读/写仍走既有ContentRead、Mat/
Region及P/V对应；多owner ContentRead不能靠新地址文字绕过原single-reference
alignment守卫，未有准确对应时保留该具体缺口。需要更细physical对应是后续原端口
接口义务，不能把本门称为native coherence完成。

## 4. 自主验收节点与原分母

| 节点 | 必须交付 | 拒绝条件 |
| --- | --- | --- |
| S0 | 三份独立审查、原源码证据与本合同；literal独立后门 | 只加字段而不说明粗细一致性；再造state/producer。 |
| S1 | 严格records、原图FK/role/current/envelope/mode校验 | 外部Use、错root/reference、INVOKE伪access、局部full_overwrite。 |
| S2 | v15 codec、旧v1–v14守恒、静态原端口query | 新tag混入旧schema；复制/去重原Use；给旧图默认完整。 |
| S3 | 动态exact occurrence/query、粗细两向和multi-owner/INVOKE N/R组合 | 同静态Value冒运行identity；错分支后态、跨visit串线、截断删义务。 |
| S4 | 有限独立复审、最终组件、干净实现提交、一次冻结全仓 | 原5055 case/72fixtures/578sources丢失；冻结时改源或并行测试。 |
| S5 | 精确范围/原失败/预算/保护报告、指纹、归档和push | 用测试数冒全模型覆盖率或LeWM加速；门通过冒自动恢复。 |

具体反例分母复用design/state-interfaces.md §5与alias-and-coherence.md，含namespace/
object/cell/元素/storage/resource、partial未知、两向current、multi-effect mode/stage、
owned Uses、INVOKE NORMAL/RAISE、branch/loop/call/resumption原端口和effect guard。
未实测构造必须明确留为未完成，不能按狭窄正例宣布整个owner/selector完成。

## 5. 工具复用与边界

复用现StateAccess/StateVersion/CFG/Use、AccessRef/INVOKE effect resolver、ValueDenotation、
ResourceUse/RequirementBinding、v2物理范围、record_codec本地tags及有限预算控制器。
[MLIR effects](https://mlir.llvm.org/docs/Rationale/SideEffectsAndSpeculation/)将粗效果/resource
与精细地址alias分析分开；[xDSL traits](https://docs.xdsl.dev/reference/traits/)的EffectInstance
引用已有SSA值/resource，未知效果与空集合分开。本门新增Python地址接口，不重写
通用SSA/图求解，不安装框架或宣称已完成framework迁移。在线接口可能新于本机。
Python [data model](https://docs.python.org/3.14/reference/datamodel.html)定义descriptor/
custom lookup及key协议；类型/名称不同不代替这些依赖。

第一阶段完整验收后仍按用户要求先停下来讲解；现在未达到该停止点。

## S0 冻结解释补充

原StateAccess.reference不是任意一个anchor，而是summary声明的owner/envelope。
非None时RefOwner必须引用同一个canonical ReferenceValue（允许不同owned Use）；
ResourceOwner只能沿原handle指同一value。多owner的aggregate应reference=None，
不能靠新metadata放宽原ContentRead alignment。未知selector包含关系保持PARTIAL/
未证条件；本门不解释旧无单位INTERVAL，不授native完整性。

凡本门新refinement出现，ExistingAccess.full_overwrite只允许明确的单一
DomainOwner/WholeOwner/WRITE/DECLARED_COMPLETE root替换形状。A实际源码复核确认，
原core已要求INVOKE的StateVersion Use为STATE_CONTENT，STATE_ORDER一律不合法；
本门保持这个准入，不新开root替换的INVOKE ORDER正例。细读/局部写不能靠metadata
降低原内容依赖，不改既有无refinement的full_overwrite声明语义。

旧五个codec测试的最高受支持schema常量由14机械更新为15；另一个生命周期codec
测试将历史proof/schema14断言保留，再单独检查当前max15。历史文档版本、fixture
bytes/hash和原语义断言全部保留；这些测试源变更不代表历史wire迁移。
