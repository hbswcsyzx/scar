# 当前状态

**第一阶段未完成；已转为五层主链优先，统一构建/存储/读回流程已实现；没有进入化简。**
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

## 统一主链（2026-11-10）

`scar build` 现优先组合匹配入口的 F4 材料，普通/compiled/返回函数、观察选择、exec、创建、native、构造协议、配置、绑定及属性/索引内容、资源全部进入同一个 `ProgramView`。保留原ID、共享函数/循环正文；只读原材料，不重跑旧全局求解队列。`--model` 仍可显式选择旧路线。

**Implemented / Verified：** `program-build-f4-current/` 构建、保存及重新打开展开通过。目录引用884源码单元，本次按需加载3单元，准入87配置、1份run-scoped观察接口材料，生成31资源记录。六类跨层适配器均接入；注册不等于完整推理可达。`workflow_complete=true`、`first_stage_complete=false`。

**Observed：** 完整CLI 230.51秒，内部组装/查询/读回218.84秒；峰值RSS 4,010,588 KiB，进程地址空间限制8 GiB。首个会话累计耗时：catalog 1.73秒、函数接口47.81秒、跨层接口85.50秒、局部状态/内容89.43秒、资源98.51秒。主要耗时在材料恢复及接入，尚未优化；这些是SCAR离线构建时间，不是LeWM性能或加速比。

顶层输出284,489字节，原正文和关系分片通过收据引用；此数字不含被引用原图及配置子目录。`gaps.json` 有89项（查询前沿80、过期接口拒绝5、旧catalog拒绝2、配置组合1、完整推理覆盖1）；这是有界入口查询和材料准入范围，不能与旧全目录51,298项比较为缺口减少。未复制正文，未展开循环迭代，资源未授实际placement/transfer。

旧入口3项回归通过；F4资源的单元邻接/typed codec检查通过；本轮完整CLI读回通过。未重跑LeWM推理。代码提交`322eb62e`已推送`origin/main`。统一入口和运行用法见README。

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

1. 以统一构建的主链断点报告按影响范围集中补齐配置/导入、callback捕获内容、调用/返回及相关deferred/resume；不再围绕单个callback连续增加验收层。保原类型、身份与依赖约束，不重跑全局FIFO。
2. 在同一图中补实际 I/O、设备放置/传输/同步到软件端口的证据；需求、候选与实际事件保持区分。不采Tensor数值、不展开OS内部。
3. 输入恢复后验正常推理主链：关键依赖、共享循环、资源边界及未知字段全部公开，无隐藏断边或预算截断后才标第一阶段完成。优化合法性证明、化简与代码生成留到后续阶段。

**环境复核（2026-11-10重启后）：** Conda `lewm`、Python 3.14.7、Torch 2.13.0+cu132/CUDA 13.2、RTX4090可用，实际CUDA计算及回传通过；SCAR和stable_worldmodel可导入。LeWM原仓库仍干净，源码、静态分片及配置启动trace保留。服务器13:33重启后原构建进程不存在，已用原材料重新完成上述构建。

**推理输入未恢复：** `/gpu1-share/data`不存在，历史`/gpu4-share/.../lewm_data`路径不存在，当前无NFS挂载；两个本地LeWM HF缓存只有refs，没有权重。可见未挂载的`data2-vg/lv-data`、`lv-nfs`、`lv-source`（850/850/200 GiB），尚未核实卷内内容，不能断言数据已删除或仍在其中。只读检查因`sudo`需要密码而未执行；需有权限者核查/恢复挂载或提供替代输入。未格式化、修复或挂载卷，未改变系统配置。当前继续离线建图，真实episode仍须输入。

实体和边见[MODEL](MODEL.md)，分层合同见[ARCHITECTURE](ARCHITECTURE.md)。
