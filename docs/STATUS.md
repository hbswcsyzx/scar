# 当前状态

**第一阶段未完成，当前在③跨层连接；没有进入化简。**
范围：Python/PyTorch、NORMAL_SUCCESS、CPython 3.14.7。后端基线C++20、算子ABI v1、计划schema v1。
真实配置启动已运行；本轮复用其证据，未重跑目标、推理episode或报告加速比。LeWM原仓库保持干净。

| 层 | 当前证据 | 仍缺 |
|---|---|---|
| ①统一接口 | source/native共用ProgramView，原ID、端口、区域及循环可展开、追源 | 全推理链由⑤验收 |
| ②局部结构/状态 | 884单元完整接口盘点、69类效果请求；正常局部接口门通过 | 内容/实例版本与效果闭合；应用异常细节按约定暂缓 |
| ③跨层连接 | 普通/compiled/返回函数、构造/native、exec/配置接口；真实CALL现已接到callback body | 捕获创建环境及内容版本→task callback；当前namespace/导入及相关deferred/resume |
| ④资源/事实 | 196个native声明、12硬件节点及候选路由 | 实际I/O、放置/搬运/同步证据接到软件端口 |
| ⑤完整推理链 | 未通过 | 入口→配置/加载→planner/模型→输出，无未解释断边或预算截断 |

目录/接口数量不代表实际调用可达；旧全局FIFO 4M产物是未完成前缀，不能当完整图。

## 最新已核结果

- **Observed：** 已有真实`run_inference.py --config-name=pusht --cfg job hydra.job.chdir=False`采集：41.23秒、50 CALL/35 entry，无预算截断。它只覆盖配置启动，不调用推理task。前两次导入期预算截断保留；排除两个全局高频库BODY的动态采集后成功，静态子图未删除。
- **Implemented / Verified：** 从原compile请求、文本及C1/F4收据恢复编译输入：flags=16777216、显式replay dont_inherit=True、optimize=0；1原profile与真实exec root完整CodeKey匹配，2个namespace分支保持独立，未由相同code选择某branch。6.62秒/约526 MiB。
- **Verified：** 9条相关真实CALL经完整code、scope、原操作ABI和源码槽映射到原F4 callsite，映射前沿0。装饰器工厂/应用虽有相同span，仍由原ApplyDecorator槽和LOAD_CONST marker区分；没有按业务名称派发。这是选中调用域，不是全部50条或整个LeWM覆盖。
- **Implemented / Verified：** 4组run-scoped观察中，3组附到等价父接口，只有缺失的callback入口新增接口，局部集合43→44。旧Fact/frame保留、正文复制0、循环展开0。wraps的receiver布局仍有0/1两种可能，只附code证据并保前沿；不能用function类别、创建期默认值或arg0非missing就绑定self。
- **Verified：** 严格读回与34项定向查询通过；两exec分支均能进入callback共享body，data/world返回配对、错误frame拒绝，3个capture handle可查。83.14秒/峰值约1.34 GiB，包含材料恢复和查询，不是纯建图性能或目标加速。推理task body仍未贯通，handle不等于cell内容。
- **材料守护：** 原普通/compiled事实通过既有物化路由核对primitive叶；源码、syntax、frame/operand及target/meta均受守护。跨catalog profile拒绝。历史namespace前沿与本次观察分开保留，观察不授未来dispatch、纯效果或缓存合法性。

## 当前材料

均在`artifacts/current/queries/`；原正文共享，生成材料不推Git，代码及三份当前文档已版本管理。

| 路径 | 范围 |
|---|---|
| program-state-coverage-current / program-local-state-current | 884单元、3,090,222原操作盘点；局部绑定/内容分开 |
| program-function-interfaces-all-current / program-function-creations-current | 581声明单元4,643条件接口；884单元15,774个函数创建 |
| program-source-native-view-current / program-source-protocol-view-current / program-protocol-frontiers-current | source/native与构造桥；120个原member前沿挂接，不等于目标已解决 |
| program-entry-exec-current / program-configuration-view-current | 原exec分支及声明配置值；不是实际cfg内容快照 |
| program-function-leaves-current / program-returned-composition-current | 三单元小叶组合与43个父接口；不复制原body |
| program-entry-observed-prefix-current/attempt3 / program-observed-source-codes-current | 原真实配置启动证据及5条actual code→原body对应 |
| program-compiled-code-profile-current / program-observed-callsite-current | 原编译上下文、分支收据及9条CALL→原端口映射 |
| program-observed-call-bindings-current | 当前观察组/布局前沿及44接口；严格重推读回通过 |
| program-observed-callback-joined-current / program-observed-exec-joined-current | callback匹配参数/返回、capture handles及两exec分支查询验收 |
| program-source-resources-current | 类型/硬件候选路由，未证明实际分配、传输或kernel执行 |

## 后续顺序

1. **③继续：** 用已有同一weak引用的调用/正常返回证据，把callback创建点连回过去creator环境；处理原relay中的直接/跨代capture。然后连接cell READ的当前状态与creator初始绑定，不能把HANDLE当内容。继续当前namespace/导入、相关deferred/resume；不重跑目标或全局FIFO。
2. **④：** 在已接软件关系上连接相关I/O、设备/存储与最小运行事实，不采Tensor数值、不展开OS内部。
3. **⑤：** 对完整正常推理链验收共享循环、依赖、外部边界和逐字段未决项；通过后才进入化简和代码生成。

**运行输入仍缺（2026-11-10复核）：** 当前无NFS挂载，两个历史`/gpu4-share/.../lewm_data`路径仍不存在，本机未确认LeWM权重/数据副本。旧trace/resources原文件也缺失，不能用视频或历史摘要代替逐调用证据。新episode需恢复输入；当前继续可独立完成的静态与动静接图工作。

实体和边见[MODEL](MODEL.md)，分层合同见[ARCHITECTURE](ARCHITECTURE.md)。
