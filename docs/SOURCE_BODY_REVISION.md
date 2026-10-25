# Immutable source-body revision：最小准入协议

2026-10-25补记：多body发布中，checkpoint/changed_bodies按文件与body存档，active接口
与structured集合的新增项按原plan输入顺序追加；两种顺序不是同一个合同。12图组合暴露
consumer错误地按存档顺序重建新增列表，现按已验证的expectations恢复原顺序，仍逐项
核CAS、namespace、端点与全部原前缀，不普遍排序或忽略顺序。真实组件小检查验证旧846
前缀和12引用均准确，原错误排列会被拒绝；原396.750s组合失败保留，未重publisher或
解12图。完整composition恢复结果另记，不能由本检查宣布858统一快照通过。
见[定向检查](../artifacts/experiments/source_publication_order_20261025/receipt.json)。

2026-10-23。**Implemented / snapshot发布与公共reader门Verified；runtime ancestor接线仍Proposed。**
依据当前publisher、partition reader、delta composition、SBA与same-Run source proof源码；
另以两个实际新artifact及当前parent的原CP做有界raw accounting。完整程序建模仍OPEN。
实际单门见 `artifacts/experiments/first_stage_source_body_revision_20261023/README.md`：
ADD218+REVISE65正式发布通过，active bodies843；未连接当前Run，也未授完整lifetime。

## 当前断口

`publish_source_programs`只接当前root为None的body，这个guard应保留为旧API默认。
直接去掉guard会产生至少四个错误：interfaces/structured追加重复active定义；全局计数
只加新图；已坏旧图被误要求通过新的language validator；旧namespace的activation/ports
可能被当作新图的连接。修订的是**SCAR对同一源码的模型**，不改变或优化被观察程序。

## 身份和版本：不另造图或CP语义

建议保留SourceProgram5、ProgramGraph、CP1/CP2、file wrapper2及composition3的原义。
新增`SOURCE_BODY_REVISION_V1`能力和`scar.source-program-publication/2`：

| 外层 | 明确准入 |
| --- | --- |
| 旧manifest2/header2/publication1 | exact capability仍仅SOURCE_PROGRAM5_ADMISSION_V1；只ADD_GRAPH |
| revision manifest2/header2/publication2 | exact capabilities为SOURCE_PROGRAM5_ADMISSION_V1和SOURCE_BODY_REVISION_V1；显式ADD_GRAPH/REVISE_GRAPH记录 |
| CP2 | 仍只引用一个真实新SourceProgram5的graph/interface/metadata/structured/language；previous_body作来源引用 |
| composition3 | 由实际parent及已核publication版本/能力限定；不把旧版本当作默认支持revision |

这是显式能力门控的扩展；当前旧reader/SBA的exact-capability检查会拒新组合，不会静默
解释revision。未知能力、publication2搭旧cap、publication1带REVISE均拒绝。若将来外层
record形状改变再升schema，而不是为本次新建CP3或第二份图。

每个目标用**原source-qualified definition**唯一定位：SourceSnapshot、ContextDigest/
namespace root、DefinitionID、SourceReference、entry ABI。另须绑定parent inventory
和composition的stored/decoded/canonical收据，以及原source-shard/body locator。
REVISE再要求原checkpoint完整ref、实际graph namespace和canonical graph SHA全部相等。
这是对当前active模型的compare-and-swap；bare DefinitionID或RegionID相等不够。
同源lower后的RegionID可能相同，新artifact的完整namespace仍然不同。

## 最小公共API

```text
plan_source_body_publication(base_composition, immutable_program_paths, budgets)
  -> checked target list / exact parent receipt / ADD or REVISE expectation

publish_source_body_revisions(base_composition, expectations, out_dir,
                              code_witnesses, budgets)
  -> publication2 + immutable manifest2
```

expectation是版本化准入record，不是可自证成功的dict：至少含目标qualified source key、
replacement artifact完整收据、expected parent/file/body/checkpoint、expected old namespace/
graph digest及kind。planner自动derive，无函数名/包名/错误字符串规则；publisher独立重新
核原输入、new program/source/code proof及expected previous，不接受裸成功bool。旧
`publish_source_programs`保持只新增行为；可提取共同新图准入路径，不能复制matcher。
本门通用默认预算不写死当前2body/2file，验收入口再显式收窄。

新图仍走公共SourceProgram5结构读取、完整source/context digest、独立CodeWitness与
SourceLanguageOptions、原signature/entry/world/Use检查；所有lifetime/effect frontiers
保留。当前revision能力仅支持已有STRUCTURED_ENV entry ABI，若旧active frame/profile
需要尚未声明的转换则拒绝，不留下悬空frames component。

## 旧坏图只用于来源与会计，不重新授予合法性

需要一个public、明确受限的`InventoryPartitions.historical_body_accounting(...)`：

1. 从明确parent manifest的原source shard、checkpoint、真实SourceProgram/graph locator
   读取原件，核stored/decoded SHA、source/context、body identity及namespace。
2. 仅对目标旧图读一次raw/core结构，计算ops/values/regions/locations/ordered Uses、
   interface/structured存在性、protocols/loops；与parent composition该body的core digest/
   counts交叉核定。来源record包括原producer、parent/header和统计位置。
3. 不调用新SourceProgram语言validator，不关闭validator来“让旧图通过”，也不宣称
   old source/lifetime正确。结果标签为ACCOUNTING_ONLY，不得传作typed body准入证明。
4. 无旧graph时取真实零图计数；不能把缺失或不可核的旧graph当零。旧CP1记录的
   construction_operations可作其已存测量；CP2的None继续UNKNOWN，图大小不是成本。

新canonical typed body永远来自新artifact的完整公共验证。历史统计不是producer替身，
不会创建旧模型的activation、State或Value。未知/冲突old accounting必须拒绝发布。

## Active组件必须替换，历史通过parent保留

一次读取interfaces/structured（必要时frames）组件，建立normalized exact checkpoint-ref
索引。REVISE必须在其应存在的active组件找到**唯一原CP**并在原位置替换为新CP；ADD
必须没有该body的active entry才可追加。接口/structured的选择不能仅按DefinitionID。
同一qualified body出现两个active CP或expected CP不存在，一律拒绝。

signatures、bindings、issues和其顺序保留，实际formal/value IDs由新图正规接口提供。
旧active CP不再留在新组件中；旧artifact只由parent manifest、revision previous_body和
明确history收据保留。无任何删除/覆盖旧文件。新CP2.previous_body须与publication2中
核过的expected previous完全一致。一次batch中一个qualified body最多出现一次。

call_source_scope仍复用`derive_call_source_admission`，以新公共typed body为输入。原origin
分母与顺序不变。对于root bareID未变的REVISE，admission数据可能相等，但publication
仍须记录body-reference变化，后续binding不能据此复用旧namespace的RegionActivation。

## 计数必须逐项减旧加新

对每个active指标X：`new_total = parent_total - old_target_X + replacement_X`，所有项
检查非负，并保存原ref绑定的before/after/delta收据。至少包括graph_bodies、core ops/
values、interface bodies、structured bodies/protocols/loops；composition的regions/
locations/ordered Uses同样核算。body status是旧status减1、新status加1。

construction统计分开：从known subtotal减旧已知成本；旧为None则unknown count减1；
新CP2没有独立construction证明时unknown count加1，不用len(graph)填成本。总数遇unknown
仍为None。历史lowerer测量不重写。本次active checkpoint位置数不变；新生成CP记录数和
历史原返回数不能混作“又执行了几次lower”。

实际有界raw audit在`artifacts/analysis/source_body_revision_20261023/raw-counts.json`：

| 指标 | parent | 本批次delta | 拟发布结果 |
| --- | ---: | ---: | ---: |
| graph bodies | 842 | +1 | 843 |
| core operations | 66295 | +218 | 66513 |
| core values | 106100 | +342 | 106442 |
| ordered Uses | parent原值 | +819 | parent+819 |
| structured protocols / loops | parent原值 | +103 /+1 | 按delta |
| known construction subtotal | 99954 | -25 | 99929 |
| unknown construction bodies | 2 | +1 | 3 |

旧65图与新65图各97values/25protocols，ordered Uses180→182；旧CP在interfaces和
structured各唯一一项（实际位置841，仅为观察结果，不作选择规则）。新218图原rootNone、
旧status UNSUPPORTED、原CP1存construction cost25，active接口/structured原无对应项。
这些是raw会计事实，不是旧坏图已通过新validator。既有2217body/151file静态分母不变。

## 有界接线与需要改的接口

- `source_program_publication.py`：提取共同new-program admission；新增显式expectations、
  target CAS、旧会计、组件精确替换和逐项delta；失败BUILDING保留。
- `inventory_partitions.py`：严格识别revision cap/publication2配对；正规旧会计接口；CP2
  与真实SourceProgram namespace不改，不放宽typed_body新图检查。
- `program_composition.py`：新增cap分支及publication2父ref/目标核；复用现delta composer，
  每个changed file只组合一次，其余source rows/CP refs原样继承。151份小header最多扫一遍，
  不prepare151，不对每个revision再解全840图或100438次调用。
- runtime的SBA/publication-header capability分支明确接新cap；actual body/ports从新的
  active composition选择。不得把schema number伪装成旧8或借old CP宣称新body已核。

same-Run source proof需要区分**definition membership报告的ancestor snapshot**与
**compiler code_source_origin**。当前`require_composition`的立即parent canonical及
`origin.inventory == priorReport.inventory`等式不能盲用于连续publication。应对成对
parent inventory/composition receipts有界遍历，找到实际已核source-report snapshot，核
该body修订只改active graph attachment、原source/context/definition refs与compiler
origin完整相同；仅复用精确静态membership。当前Run/当前raw仍由现public orchestrator
独立核验。旧RegionActivation/Use routes不能作为新namespace的事实复用。

修复batch发布后再运行一次统一source→dispatch→SBA/current-raw接线，完整groups/calls/
operand/environment分母保留。不能每修一个body就扫描100k raw或重建依赖图。

## 独立验收设计

只使用现已归档两个新artifact：一次显式ADD218+REVISE65发布，old65仅会计读取。
source/code验证按两file缓存；compile/prepare/target均为0。独立公共reader核新active
两图、实际namespace、source/entry/语言字段；旧65 artifact保持字节原样但不作为active
legal body。组件各qualified body唯一，修订CP保序替换、ADD追加；上述delta与unchanged
source/component refs逐项核，code_source_origin完整dict相等。

最小有意义的拒绝检查是：stale expected namespace/CP被拒；一个篡改old统计或重复active
组件项被拒。用小准入record负例即可，不另造目标、重lower或跑测试suite。然后按root
统一门一次绑定同capture，检查新active namespace与原真实InvocationKey各归各位，保留
原有缺口/UNKNOWN，不因某body已恢复而声称整个程序闭合或可优化。
