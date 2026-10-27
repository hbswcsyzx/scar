# 条件性值来源到既有消费者：计划与验收

2026-10-20，冻结基线 `fff1895fd3abc312409b9b95d40affa9b2c06f86`。
接[上一门](M1_STORED_VALUE_NEXT_GATE.md)，原M0–M2/七族/P4/P5/M2分母保持。
不新增detector/backend/LeWM规则，不改Program27/Execution8或原copy语义。

## G0：已确认的缺口与原义

单次own load可得完整StoredValue来源，但旧ordinary pair不能穿过它。先保存
基线公开stored查询与原pair的对照及稳定源码，不把ordinary Unknown叫语义错误。

五类实体仍Operation / Value / StateLocation / Region / Resource。新关系是
**原存储合同与状态区间条件下的值来源**，不能塞进body_original_copy_recipes、
roots或全局identity union。旧pair / pending_payloads.copy_recipe原样保留。

独立审查指出：load own result可能同时有原CallActivation copy和边界上的
StoredValueRead。通用来源walk必须保留**并行边**，不能用copy_recipe or projection
只取一个，也不能等走到原copy链末尾再找stored来源。

## G1：准确投影与有界证明图

A新增 `stored_value_projection.projection(ctx, target, shared)`：

- 从准确ValueOccurrence定位原Read。普通result核本次producer与own slot；
  INVOKE从target所属实际visit的incoming transfer、原BlockArgument位置及
  CompletionResult ordinal找ownNORMAL；forwarded Use/旧carrier不能冒充ownresult。
- 不是任何Read返回None；已识别Read但缺采保receipt/原声明及Unknown，不借兄弟。
- 仅完整stored_value_sources.matchTrue、准确source/target且未截断才给recipe；
  从不按期望source反选store。
- shared query内以(ctx,target.id)缓存，lookup及derived索引/landing扫描计费；
  fresh context不复用。ACTIVE重入返回cycle Unknown，不发布半成品。
  cycle/depth/budget导致的不稳定失败不缓存。嵌套active-cycle要有generation或
  等效依赖标记，避免把依赖未完成父证明的失败固化。
- 长无环链有显式分析深度界，触界保cursor并使共享分析截断，不靠RecursionError
  继续授成功；真实已截断不能由缓存复活True。

root新增通用 `value_sources.source_pair(ctx, source, target, shared=...)`：

- 两端及原Read/Write/operation库存先保留，用查询局部多边祖先图查共同来源。
  每个node并行考虑原copy和已充分支持的stored投影；不存新的producer/use。
- chosen support按原copy和DECLARED_STORED_VALUE区分，保独立receipt及完整条件。
  不相等的候选只局部False/None；仅在已建立原关系的路径上核兼容冲突，不能
  把正常不同owner写成全局ctx.issue。原硬冲突不被新条件分支救回。
- 同一shared预算付全部展开，cache命中付费，截断无成功前缀。自反原copy可以
  独立成立；循环本身不能当值来源证明。不重复嵌套整个证据图造成自引用。

公开 `ExecutionIndex.value_source_pair(source_id, target_id, *, budget=4096)`
验证准确ValueOccurrenceID/FK，fresh上下文，一次detached输出。
stored_values._Sources.copies复用广义来源，支持owner/key经过已证明load。
body_state_history仅ordinary None后试独立来源分支，ordinary_binding仍Unknown，
新依据与原copy/scoped identity分列，不把新的关系改名ordinary copy。

## G2：构造边界与既有消费者

原constructor的own新R不是其pre-owned输入。现类型可表达展开Region里的真实
allocate→ownNORMAL R→R-owned store→return/fullstates；不可展开native primitive
保持边界，不能从Create.body猜字段初始化，也不能造future Use。RAW latent不是
当前Data/Reference槽payload，不为本门改类型。

现finished图还有source Drive owner→Create handle及opaque/RW区间独立缺口。
若本门仅闭当前READ的stored主体，必须分别报告，不能将F19整历史翻True。
先在通用小图验证新来源闭环，再复用既有图核当前consumer与剩余独立条件；
不得为业务/协议标签增加优化规则或假identity、假纯度。

## G3：有限验收与版本管理

1. 两层payload store/load：上层结果追到原P，保两份独立存储支持；owner经load
   也可寻同槽，不补produced Ref precision/identity。
2. 原copy与stored并行边、重排NORMAL/RAISE、跨call/loop的真实occurrence，缺
   本实例association/Use/state/附件不借兄弟；原ordinary行为不变。
3. 覆盖写/opaque/未知地址、ACTIVE循环、长链深度界、tiny budget与cache刷新，
   原库存保持且不授成功前缀。只补有区分力反例，不做业务路径全乘积。
4. 先冻结基线诊断，再实施；所有作者FROZEN后root串行解释器/pytest/probe。
   保各首败、源码、命令/JUnit；直接相关选集过后停止可选扩大。独立审查、自验
   报告、普通commit/push，核远端SHA/clean及两受保护工作树。

原case目录2304是系列已知义务而非全仓；旧case/fixture不改、不迁移。source/native
自动恢复、原F19余项、七族、P4 component/full/P5/M2原113/196及整阶段仍开放。
整个建模阶段真正完成后先向用户解释，再推进自动全程序图；无新LeWM加速结论。

## 所有权

A仅新projection helper；root广义来源、query入口、stored address薄接入与body
consumer独立分支、文档/归档/串行验收/Git；B仅NEW通用fixture/test；C只读复核。
任何作者不运行解释器或Git；所有原格式与全局copy表守恒。
