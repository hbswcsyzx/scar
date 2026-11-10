# 当前状态

**第一阶段未完成，当前推进③跨层连接；尚未进入化简。**
范围：Python/PyTorch、NORMAL_SUCCESS、CPython 3.14.7；后续宿主后端C++20、算子ABI v1、计划schema v1。本轮未执行LeWM或导入torch/Hydra，无程序加速比。

| 层 | 已实现与证据范围 | 仍缺 |
|---|---|---|
| ①统一接口 | source/native共用ProgramView，原ID、端口、区域、循环、来源和辅助接口值均可查询/展开 | 整个推理链覆盖由⑤验收 |
| ②局部结构/状态 | 884单元完整盘点，69类指令效果请求；正常环境接口缺口已补，绑定/内容/native状态分开 | 应用异常细节按既定范围暂缓；效果和实例版本未闭合 |
| ③跨层连接 | 普通/compiled及返回函数、factory/default/cell、native、构造、exec分支、声明配置值与原未决字段已接统一查询 | 返回包装调用及捕获callback链仍缺；之后补当前状态、导入闭包、相关deferred/resume及运行选择 |
| ④资源/运行事实 | 已有12硬件节点、类型及候选资源路由 | 相关运行I/O、物理放置/搬运/同步的实际证据与软件端口连接 |
| ⑤完整推理链 | 未通过 | run_inference.py→配置/加载→planner/模型→输出的完整跨层查询与覆盖 |

①接口门和②正常局部接口门已有证据。目录、模板及候选数不代表实际调用可达；旧全局FIFO 4M产物是未完成前缀，不能当完整图。

## 本轮已实现并实测

- **Implemented / Verified：** 原接口域全部318个构造阶段、64个source入口及2条member连接接入统一图；4个调用单元共有320个接口、66个带原selection的body frames、1,941条依赖及760条所属关系。包含编译配置到WorldModelPolicy初始化的连接；没有按业务名称派发规则。
- **Verified：** 342个NEW_RESULT/NEW_WORLD、66个当前callable投影、各176个默认槽/状态均经typed codec及查询检查；94组公开关系检查、875个查询通过。全部connection guards保留，INIT data不转发，63个OBJECT_INIT与10个RETURN_FOREIGN的world通路补齐；不授freshness、storage alias或状态版本相等。
- **Observed：** 完整建图/检查427.73秒，峰值RSS约1.45 GiB；按unit的五类表共334,287 bytes，原body复制0。该时间包含检查，不是纯建图性能或LeWM加速比。
- **Implemented：** 中断一次自身验收并从栈定位反复解码模板表；三个调用适配器现在按unit/template批量准备，再接端口，保懒单元、原frame及guards。没有修改基础F4 producer或重建884单元；未报告分析器A/B倍数。
- **Verified：** 批量准备后的native/source共视图回归通过，21个native接口、183条边的发布字节与原验收完全一致；本次63.84秒、约516 MiB。首次回归在查询后因旧输出文件已存在而拒绝发布，改用新目录完成，原材料未覆盖。
- **新增 Verified：** 全120条member前沿已挂回7单元、720个原端口；typed记录全部保存，各单元双向查询通过，131.79秒/峰值约1.30 GiB/14,135压缩bytes。目标实际解决0、UNKNOWN节点新建0；构造桥自动注册，专用frontiers-only模式不构建已知正文。
- **新增 Verified：** compiled叶域全部76调用保完整namespace查询，6 NORMAL接口/5个源Fn，70未连接调用及281 namespace前沿保留；构建+严格读回9.29秒/约356 MiB/106,168表bytes。统一查询6frames/41关系通过，13.21秒/约380 MiB；真实两调用共享原body而返回不串线。旧581域/import索引未改，exec globals未选定。
- **仍未解决：** 78个构造、120个member目标条件仍未消解；前沿挂接不代表选定目标。namespace/MRO、callable/default实例与版本、实际dispatch与整条入口闭包仍需接通。
- **新增 Verified：** exec两分支保12协议actions、30条原边和全部guard；58辅助记录/103关系共享1个compiled root。参数与data/world返回分支配对、discard、None及全部7表严格重推通过，8.07秒/约520 MiB/31,072表bytes；不授namespace版本、激活或效果闭合。
- **新增 Verified：** 声明配置代数22表达式、52投影、3插值、5读请求及12 root版本形成119记录/244关系；canonical whole-content地址复用、None返回不混cfg、wrong scope拒绝均通过。完整10表落盘重推15.92秒/约502 MiB/54,346 bytes；不是实际运行cfg快照或计算次数。
- **实际组合缺口已验：** exec ROOT→decorator工厂可接，不能直接进入`run(cfg)`；compiled calls75/0停在返回函数及捕获callback前沿，calls59/60所属run正文也不能借ROOT前缀进入。函数声明边仅IMPLEMENTATION，不授activation。组合检查15.11秒通过的是这项不完整性结论，第一阶段仍未完成。
- **本轮新增 Verified：** 配对返回自动推得call75的创建来源，6→7接口；最新构建/读回18.84秒。另复用分析器补2个库文件/283调用的32接口，36.65秒。集合只保收据与unit路由，不复制行；第二轮来源组合去除完全相同的推导，39→43接口，保所有不同creator/路径/条件。
- **统一图 Verified：** 3单元、359声明调用、43 frames、305关系、5组返回函数来源及33 capture绑定；两exec分支均接到返回decorator及wrapper工厂，19项定向查询通过。完整构建/读回/组合查询163.74秒、峰值约1.47 GiB；新增表148,686 bytes，不是整图大小。原接口Fact保留、creator不混当前caller、cell内容/实际dispatch仍未证。
- **下一断点已定位：** call75正文返回停在ApplyDecorator call29，callee来自wraps工厂返回；普通wraps入口已接，内部partial构造call242仍有源码class与native两个候选。不能把包装当恒等函数、不能沿`__wrapped__`冒认目标。下一步用轻量动态选择补实际callable/closure，再接原静态端口；整个入口链仍未通。

## 已有材料与验收

均位于 `artifacts/current/queries/`；生成数据不推送Git，代码与当前文档已版本管理。

| 路径 | 范围 |
|---|---|
| program-state-coverage-current | 884单元、3,090,222原操作完整盘点；index保收据，resolution保受影响单元修正 |
| program-environment-state-current / program-local-state-current | 正常callback环境投影、gcrl局部状态与旧完整图重推 |
| program-function-interfaces-all-current | 581父声明单元、48,290调用、4,643条件函数接口；不等于884目录或全推理链 |
| program-function-creations-current | 884单元、15,774个原函数创建，0缺规则；含default/cell/annotation输入 |
| program-call-defaults-current / program-captured-cell-view-current | 当前默认槽及callee env→canonical cell→原READ查询 |
| program-native-state-current / program-binding-native-current | 196个native接口及状态声明，保原世界与scoped alias条件 |
| program-source-native-view-current | 真实CEM/pack的21个接口、183条关系查询；旧gcrl 20,222节点/21,511边完整重推 |
| program-native-batch-view-current | 批量准备后的native/source回归与原边字节一致验收 |
| program-source-protocol-view-current | 本轮全部原构造接口及2条已知member边；graph为分片图，verification为验收，interrupted.log为重复读取诊断 |
| program-protocol-frontiers-current | 原120前沿的字段映射、720端口及双向查询验收；graph为分片记录 |
| program-compiled-function-interfaces-current / program-compiled-call-view-current | 显式compiled上下文的76调用材料及6函数接口的统一查询验收 |
| program-source-exec-view-current | exec原分支、actions及共享正文的匹配查询与7表重推 |
| program-configuration-view-current / program-configuration-unified-current | 声明配置→canonical receiver内容候选，全部typed记录/关系重推 |
| program-entry-composition-current | exec/compiled视图真实组合；验证Root到工厂已通、callback到run仍缺接口 |
| program-returned-functions-current / program-function-leaves-current | 首轮返回接口与不复制行的3单元集合 |
| program-wrapper-declared-calls-current / program-wrapper-function-interfaces-current | 精确补2个库文件的声明与32个普通函数接口，未重建581域 |
| program-returned-composition-current / program-returned-unified-current / program-entry-exec-current | 去重后的返回来源组合、统一查询及当前exec分支材料；包装/callback链未闭合 |
| program-source-resources-current | 539类型投影与已有硬件的候选路由；不是实际分配或传输 |

## 接下来顺序

1. **③下一项：** 动静结合接包装callable/capture：静态保留共享body和协议候选；短动态运行只补实际调用选择、code对应与closure handle。先验真实启动前缀，再打通ROOT→decorator→captured callback→run；无观测路径不删、一次选择不外推未来。之后接配置/导入的当前状态及相关deferred/resume；不重跑全局FIFO前缀。
2. **④：** 在已接软件关系上接相关I/O、设备与存储；候选和Observed分开，不采集Tensor数值，不展开OS内部。
3. **⑤：** 验收整个正常推理链的依赖、循环、外部边界、明确未决字段及无预算截断。通过后才进入化简和代码生成。

实体/边见[MODEL](MODEL.md)，分层合同见[ARCHITECTURE](ARCHITECTURE.md)。历史实现细节由Git和原材料保留，不另增逐门文档。

**当前运行输入缺口（2026-11-09已复核）：** 无NFS挂载，两个默认`/gpu4-share/.../lewm_data`目录不存在；已查本机cache只有模型refs，无LeWM权重/数据。旧视频、结果及Hydra日志尚在，baseline文档引用的原始trace/resources已缺失，不能作为现有逐调用/资源事件接图。已异步询问可用数据/权重路径；继续独立静态工作，动态/完整episode验收需恢复输入。
