# 当前状态

**第一阶段尚未完成；当前到建模、建图和查询为止。**
范围：Python/PyTorch、NORMAL_SUCCESS、CPython 3.14.7；未来后端C++20，算子ABI v1、计划schema v1。本轮没有运行LeWM或导入torch/Hydra，没有程序加速比。

## 五层进度

| 层 | 当前结果 | 下一项 |
|---|---|---|
| ①统一IR/查询 | source与native共用ProgramView；原ID、可展开区域、循环和来源均保留 | 完整程序覆盖由后续层验收 |
| ②局部结构与状态 | 884单元接口盘点完成，正常环境投影缺口已补；保绑定、内容和native状态 | 异常状态暂缓，效果及实例选择不冒充已证明 |
| ③跨层连接 | 函数创建/default/cell和Python→native转换已接统一查询；CALL_TARGET带frame展开 | creator实例/内容版本、绑定方法/构造、实际选择及依赖闭包仍待接 |
| ④资源与运行证据 | 已有硬件快照、类型及候选资源路由 | 接运行I/O及必要的实际选择 |
| ⑤完整推理链验收 | 未通过 | 入口→配置→加载→planner/模型→输出的跨层覆盖 |

①接口门及②正常局部接口门已有证据；不把目录盘点、文件数或单元样例当作全程序验收。应用异常细节仍按既定范围暂缓，不能称相关节点不存在于正常清理图。

## 本轮真实结果

- **Observed：** catalog全部884单元（883 ordinary＋1 compiled）处理成功，0失败；3,090,222原操作逐项获得效果请求，涉及843,230共享模板、36,855,719规范端点和39,427,810关系。69种指令规则闭合，本批实例覆盖64种。该目录是前端材料域，不是实际调用可达性证明。
- **Observed：** 16个独立worker耗时1,374.04秒（22.90分钟），每worker虚拟地址上限8 GiB，实测最大worker峰值RSS约1,753 MiB。任务逐单元释放图，没有运行目标或求解全部61,734条可用局部绑定链。
- **Implemented / Verified：** 补齐2处ReadClassTypeParameters。它读取callback environment保留的tuple；原interface、SlotRef、owned Use、结果及world对形成带activation条件的投影，不伪造类属性、LocationID或alias。完整受影响单元重建后，其余接口计数和规范图规模不变。
- **Implemented / Verified：** 端点先查完整原anchor，省去重复摘要和owner构造；保类型冲突、反向碰撞及后写owner/record。旧gcrl状态全表重推通过：63条链、5,499版本模板、126读取选择；其20,222规范端点/21,511边也逐记录一致。这里没有宣称分析器A/B加速比。
- **Verified：** 上述两个针对性验收并行共176.84秒；受影响单元170.88秒、旧图重推107.06秒。原始失败尝试保在实验日志中，最终verification为VERIFIED；未扩跑测试套件。
- **暂缓：** EnterHandledException 2,892、ContextExceptionArguments 1,420、PrepareReraise 6,223、RestoreHandledException 8,570个地址投影请求仍有显式缺项；完整effects、当前实例、LogicalVersion及实际dispatch均未因此闭合。

覆盖分片合3,911,326 bytes，另有260,144 bytes收据索引；这是新增盘点数据大小，不是原图总大小。原F4正文及已有图继续共享，规范视图按需生成，不再保存一份全目录巨大图。修正只重建受影响单元并核旧图，未重新跑884单元。

**③新增已验：** 全父声明域581单元/48,290调用在88.95秒内产生4,643条件函数接口，表合4,408,486 bytes；4,626普通＋17 deferred，25,110参数路由、152 pack投影及各4,626 data/world返回。4,638调用接到函数候选，其余43,652调用、166,839原namespace前沿及2个签名不适配候选保留。没有重证全部父namespace或实际dispatch。打开全域索引物化0单元，查询自动接入所需单元；一个真实单元的两个callsite共享body、参数/返回配对、跨unit、错误frame拒绝和None/open前缀验收共15.49秒、峰值约350 MiB。它证明基础桥，不代表③全部通过。

**本轮③创建/状态已验：** 884单元/15,774原函数事实全部投影为创建接口，0缺规则/0失败；7,531初始default来源、2,269 cell handles、4,466 annotation operands。16进程耗时172.89秒、峰值worker约425 MiB；表合5,358,264 bytes。实际包含14,813 BuildFunction、427 lambda、534 genexpr；genexpr保5个ref结果和独立world，不混淆。小默认/闭包及lambda/genexpr原材料严格重读通过，未宣称884单元全部再读一次。

**统一接线已验：** 当前default为逻辑slot在原pre-call world上的状态投影，不能直连初始表达式充当当前值；INITIAL_DEFAULT/CONDITIONAL_DEFAULT与函数体展开、caller code_scope拒绝三项验收共35.74秒。创建角色边只接原owned Use→factory操作，7创建/2default/2cell两单元验收6.50秒；不激活正文。闭包env→2个canonical cell地址→3条原cell读边验收10.16秒；地址精确复用第二层，不新增另一套cell身份。creator/outer-cell实例、mutation history及内容版本仍为明确未决字段。所有耗时均为分析器，不是LeWM加速比。

**③native桥新增已验：** 真实CEM与一个pack来源单元的21个条件接口、183条关系，225次查询双向接通；同一视图另有8个源函数接口。包含19 positional、20 keyword、41 default表达式、2 pack及3 open转换请求，保intlist聚合。原NamedMatch限定frame，错误match/无frame不混接；所有转换/包装均MAY依赖，无对象/storage alias或真实搬运断言。验收92.96秒、峰值约514 MiB；183条证据边压缩375,907 bytes，仅为本次选定关系。旧gcrl的20,222节点/21,511边按窄版本兼容完整重推通过，27.26秒、约377 MiB；原材料和通用codec未改。未运行目标，不代表③或完整推理链通过。

## 当前可用材料

均在 `artifacts/current/queries/`，本地生成材料不推送Git。

| 路径 | 用途 |
|---|---|
| program-state-coverage-current/result.json | 原884单元完整盘点，保原生产版本 |
| program-state-coverage-current/index.json | 根报告、单元报告与缺规则文件的收据索引；不冒充语义重推 |
| program-state-coverage-current/resolution.json | 根据受影响单元验收派生的修正汇总，原盘点不覆盖 |
| program-environment-state-current/verification.json | 真实环境投影与旧完整图重推结果 |
| program-unified-view-current | 3个普通/compiled源码单元的紧凑统一视图 |
| program-local-state-current | gcrl绑定/内容及按需到达定义；当前规则完整读回已验证 |
| program-native-state-current | 196个native单元、507地址、1,099状态投影、90 scoped alias声明 |
| program-declared-calls-current / program-binding-native-current | 源调用声明及196个native ABI，尚未证明实际dispatch |
| program-source-resources-current | 539类型投影与已有12硬件节点的候选路由；不等于实际搬运/分配 |
| program-function-interfaces-all-current | 581单元条件接口、全callsite/原前沿索引；共享正文不复制 |
| program-source-call-view-current/verification.json | 全域索引的自动懒接入与caller匹配查询验收 |
| program-function-creations-current | 884单元的原始函数创建、default/cell/annotation输入，分片与收据 |
| program-call-defaults-current/verification.json | framed BODY展开、caller code_scope及当前default状态验收 |
| program-creation-role-view-current/verification.json | 初始factory输入角色接原Use/操作，含closure handle |
| program-captured-cell-view-current/verification.json | 当前callee环境→原canonical cell地址→已有READ接通 |
| program-source-native-view-current | CEM/pack转换、world及包装的双向查询；frameless_read为旧图完整重推 |

## 接下来按顺序推进

1. **③调用连接：** 当前创建/default/cell与条件native转换已通；下一步接绑定方法/构造协议，选择creator/global/builtins实例及相应版本、deferred/resume，并补compiled入口、配置/导入及依赖闭包。581父声明域不是884目录或完整推理链，不重跑全局FIFO前缀。未选择的native parser/override/dispatch继续显式开放。
2. **④资源连接：** 在已接软件依赖上补I/O及必要运行选择。类型候选、源码文件位置、实际资源使用分别保存；不采集Tensor数值，不展开OS内部。
3. **⑤整体验收：** 按run_inference.py与保留配置核对跨层边、共享循环、外部边界及明确缺项。通过后才进入化简及代码生成。

实体和边见[MODEL](MODEL.md)，分层合同见[ARCHITECTURE](ARCHITECTURE.md)。历史细节由Git及原材料保留，此状态页只保当前事实。
