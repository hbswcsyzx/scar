# 当前状态

**第一阶段未完成，当前推进③跨层连接；尚未进入化简。**
范围：Python/PyTorch、NORMAL_SUCCESS、CPython 3.14.7；后续宿主后端C++20、算子ABI v1、计划schema v1。本轮未执行LeWM或导入torch/Hydra，无程序加速比。

| 层 | 已实现与证据范围 | 仍缺 |
|---|---|---|
| ①统一接口 | source/native共用ProgramView，原ID、端口、区域、循环、来源和辅助接口值均可查询/展开 | 整个推理链覆盖由⑤验收 |
| ②局部结构/状态 | 884单元完整盘点，69类指令效果请求；正常环境接口缺口已补，绑定/内容/native状态分开 | 应用异常细节按既定范围暂缓；效果和实例版本未闭合 |
| ③跨层连接 | 普通/compiled函数、factory/default/cell、native、构造及原未决方法字段已接统一查询 | 相关实际目标/creator/global/builtins实例、deferred/resume、入口/配置/导入闭包与运行选择 |
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
| program-source-resources-current | 539类型投影与已有硬件的候选路由；不是实际分配或传输 |

## 接下来顺序

1. **③继续：** 现有member前沿已挂回，compiled普通函数桥已通；接入口准入、配置/导入及相关执行上下文，选择必要的类/descriptor、creator/global/builtins实例与版本，处理相关deferred/resume。静态子图配合少量动态事实，不重跑全局FIFO前缀。
2. **④：** 在已接软件关系上接相关I/O、设备与存储；候选和Observed分开，不采集Tensor数值，不展开OS内部。
3. **⑤：** 验收整个正常推理链的依赖、循环、外部边界、明确未决字段及无预算截断。通过后才进入化简和代码生成。

实体/边见[MODEL](MODEL.md)，分层合同见[ARCHITECTURE](ARCHITECTURE.md)。历史实现细节由Git和原材料保留，不另增逐门文档。

**当前运行输入缺口（2026-11-09已复核）：** 无NFS挂载，两个默认`/gpu4-share/.../lewm_data`目录不存在；已查本机cache只有模型refs，无LeWM权重/数据。旧视频、结果及Hydra日志尚在，baseline文档引用的原始trace/resources已缺失，不能作为现有逐调用/资源事件接图。已异步询问可用数据/权重路径；继续独立静态工作，动态/完整episode验收需恢复输入。
