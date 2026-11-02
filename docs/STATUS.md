# 当前状态

当前唯一任务是整程序纯静态建模与建图。**第一阶段未完成**；不执行目标程序、import 初始化或用户回调，不做化简、detector/backend 或性能实验。唯一 checkout 为 `~/AAA/scar`，分支 `main`。LeWM 是外部 testcase，通用规则不按业务名称派发。

## 核心结构与真正的问题

主表示是层次化、有类型、有端口、带状态版本的程序依赖图。Operation、Value、StateLocation、Region、Resource 是实体主干，Use、绑定、状态地址、completion、控制和环境接口为强类型记录；不是五种互斥的源码标签。AST/CST 是输入，包含树只组织定义；数据、状态、调用和控制边可以跨层、共享和成环。

`ProgramDependencyGraph` 以原 namespace、typed ID 和静态 context 统一局部、call/env/G、class/provider、控制与资源导航。共享主体不复制，静态 context 不冒充 Invocation。值队列与区域 cut 已实际消费该接口。

**目前主要缺口是关系覆盖和联合推理，而非图格式。** 全范围 calls 已发布，但大部分真实调用仍没有接通目标；module/class 主体后缀、receiver 来源、状态/alias/effects、Tensor 属性及 Python→native 仍不完整。不能用枚举完成或节点总数宣称整程序贯通。

## 当前唯一已发布图

`artifacts/current/static/manifest.json` SHA-256：
`18aab515266ee99b9293aa1d7eef72332236c07f97aceefaf79280a6787a97f1`。

| 项目 | 当前结果 |
|---|---:|
| 源码/声明单位 | 862 |
| 原始源码 | 12,447,536 bytes |
| AST occurrence / 词法入口及上下文 | 1,493,620 / 36,164 |
| 源码操作 / 关系 | 835,725 / 3,738,042 |
| CFG 节点 / 边 | 478,899 / 569,425 |
| 有限常量事实 | 124,535 |
| 有规范图的入口 / 所有主体产物 | 8,089 / 8,819 |
| 无主体产物声明 | 27,345 |
| 规范操作 | 1,262,346 |
| lowerer / shape 不支持 | 326 / 404 |
| 缺独立适配 / 新单位未派工入口 | 3,731 / 23,614 |
| 模块 / class suite 未展开后缀 | 107 / 45 |
| calls 分片 / 已枚举规范调用 | 6,697 / 35,747 |
| 有条件目标候选的调用 / 无目标候选调用 | 270 / 35,477 |
| class bindings / parent shards / 共享 provider | 1,065 / 400 / 15 |
| manifest / 全部压缩分片 | 58,749,856 / 2,438,917,125 bytes |
| 压缩分片数 | 21,625 |

源码/主体覆盖没有因发布 calls 而自动扩大。3,731 个适配项含父图已内联部分，不能全部当作缺独立 frame。当前 source-only Python 单位 264 个，stub 17 个；按需依赖闭包仍未完成。

### 调用发布已经结束，范围内枚举不等于目标解析完成

任务 `22e44842ba63409b97867674ac6da292` 于 2026-11-02 21:42:25 UTC 终态 **PUBLISHED**，约 6,446.07 秒。处理 862/862 units、8,819/8,819 主体条目，其中 8,089 有规范图、730 无图，剩余条目 0。producer/current 已解除本次发布冻结，没有遗留此任务的运行进程。

- 发布 317 条 argument port edges、412 条 argument value flows、343 条 return flows、676 条 completion routes。
- 193 条 cross-body namespace flows、184 条 import routes、8 条 module attribute flows；**module globals flows 为 0**。
- 596 份零 CALL 主体仍保存其它关系，不能只分析有 CALL 的主体。
- receiver 未连接 41,398 项，SOURCE_BINDING_OPEN 11,916 项；所有 35,747 个 CALL 的目标集闭合仍 open。计数覆盖多种关系，不应直接相加作为调用分母。
- **Observed**：CEM `solve` 已枚举 48 个 CALL，当前均无已连接目标候选；其它已检查 CEM 方法也未接通候选。因此尚不能沿实际规划/model 链获得完整依赖闭包。

本次读入按 stored+decoded 计费 19,793,911,750 bytes；module 派生索引 8,203 builds、624,606 hits、8,203 metadata reuses，0 oversize rejects。前次 64 MB 缓存反复淘汰 65,027,047-byte 主体的错误已修；前次取消原因和本次终态可由当前 task/result 记录核对。这里的时间是分析器成本，不是 LeWM 性能。

`complete=true` 只表示保存的 canonical 分母已枚举；`whole_program_model_complete=false`、target resolution/source attribute scope 未闭合。manifest 根 `worker_errors` 当前为空，源码记录中仍保留 37 条早期 BrokenProcessPool 文本，不能说历史记录已消除或当成本轮新失败。

## 本轮已实现并核验

### 共同查询不再因全局重放漏掉已知接口

**Observed / Implemented / Verified**：原默认 outgoing 为查一个 actual Use，会重放全部 typed call shards，耗尽预算后漏掉已有参数边。现改为有界、核收据的 raw namespace→原 shard 路由，仅对命中 shard 严格重放；先投影已知本地关系，后续预算不能抹掉它们。raw 路由完整只证明保存记录的检索范围，不证明 target、alias 或效果闭合。

真实 `cli.py:179`→`data/utils.py` 的原 actual/formal 已双向核对，静态 frame 深度 1，保留 `ALIAS_TARGETS_OPEN`。原 outgoing 73.39 秒返回 0 参数边；修复后 agent 冷查约 29.01 秒，raw 路由 6,697 shards / 7,123 references，仅 typed 1 shard / 2 graphs。机器记录为 `queries/lewm-call-interface-outgoing.json` 和 `queries/lewm-call-interface-incoming.json`；这是接口查询，不是 CEM 闭包或目标加速。

Root 独立双向读回 29.93 秒，1 条参数边、2 个 namespace，raw 路由完整，双向合计 typed 2 shards / 2 graphs、387,120,180 bytes 输入；目标未执行。针对调用路由、原值分析和字面 If 的合并检查通过；区域旧检查把所有证据边误要求为空，已改为核对结构边不传递值/身份，并独立通过。没有扩成全量长测试。

### 控制必要性接入同一值队列

**Implemented / Verified**：从原 Use owner、result producer 或 block argument 追踪原入口 edge-dominance 必要条件，沿最近 controller 递归；与 MAY postdom 控制影响分开。稳定的分支/绑定证明可反证值路由，并从原 seeds 重算，原图与异常/效果边保留。报告新增 occurrence、infeasibility 和 route_refutations，不把结构证据当作值相等。

同一批通用真实源码查询推得唯一不可变 tuple `(7,99,5)`；刷新后的 15-root 机器记录为 128 points、268 edges、999 steps、2 branch proofs、5 binding proofs、6 route refutations。未知/custom 区域没有污染独立已知字段。原 core 同步 region 的两层上下文、未知/循环/部分接口与预算边界已核验；**保存的 Python candidate frame 入口范围仍 open**，不能说全部跨函数控制已闭合。验证源码未执行。

当前 `queries/binding-knowledge/` 的源码、小模型与 proofs 收据一致，静态建模约 1.96 秒、查询 2.13 秒；主 current/static 未改变。此目录只是通用规则核验，不是 LeWM 或另一份权威程序。

已有独立 binding state field、normal/raise slot0 隔离和原 TRUTH 合同推理继续保留；worklist 稳定与原查询覆盖完整分别报告。源码常量只来自静态 builtin literal/原编译常量表，不保存 Tensor 内容，不执行用户协议。

### 源码覆盖：编译器已消去的字面 bool If

**Implemented / Verified，尚未重建 current 主体**：模块 `if True/False` 通过原源码与独立重编译 CFG 见证展开；保留两臂源码，仅为选中臂建立执行结构，不制造 TRUTH/BRANCH。死分支仍影响的 compiler annotation factory/cell/prelude/global scope 不丢弃。旧保守 wire 独立读回，不静默升级覆盖。

**Implemented / Verified（真实源码定点重建，未替换 current）**：module 的简单名称 AnnAssign 已接默认 lazy registration 与 future 字符串模式，保留原 RHS→store→lookup→set/subscript 更新、world 和正常/异常清理；注解表达式不执行。整数索引/字符串来自原编译器槽，不按已展开语句重编号；隐式操作仍引用原 AnnAssign，不伪造 AST。只接精确 BUILD_MAP0 空 dict RHS，其它 Dict/复杂目标维持原边界。

真实 `envs/utils.py` 前缀 7→15/15、语句残留 8→0（321 ops）；`callbacks/registry.py` 前缀 6→15/15、残留 9→0（425 ops）。构建与独立读回约 16.28/10.51 秒，原图与模块接口逐对象相等。唯一扩展短验通过 13.00 秒，Root 原 class/compiler/import 回归通过 7.47 秒。旧 wire 没有新见证时仍重放旧覆盖，没有静默升级。

原 source/producer 收据、两个压缩样本及未闭合项在 `queries/module-annotation/summary.json`。两模块仍 PARTIAL：生成的延迟注解子主体和 namespace/alias/effects 未闭合。current 主体尚未替换，107/45 后缀分母不变；class annotation 协议仍待补。这项覆盖修复不解决 CEM 的 G-origin/IMPORT_FROM 断边。

### 库/原生材料：输入层完成一部分，整程序连接未完成

**Implemented / Verified**：隔离复用 torchgen schema parser，6 个实际 ATen overload 构造现有 NativeBoundary 接口，共 18 ops；版本/文件/工具收据、正常/异常与 opaque world 保留。原 schema alias/write/dispatch 不冒充 must-alias、物理 copy 或已选 kernel。

C++ source 前端复用 Tree-sitter，实际 53,705-byte template 中机械枚举 79 个显式方法项、83 个函数、563 个调用、5,661 个相关 occurrence / 12,576 条 SOURCE/STRUCTURE 边；保留 4 个模板孔、6 个 ERROR。原 ID 表规范化保存约 2.98 MB JSON / 0.383 MB gzip，读回相等。私有工具环境约 19 MiB，未修改 LeWM 环境。

这些材料和验证在 `queries/native-static-model/`；**尚未发布进 current canonical 整程序，Python callable→参数转换→native overload 与具体 runtime/kernel/resource 连接未完成**。CST 是源码输入层，不冒充 C++ 类型/ABI 证明。

## 下一步，按实际依赖缺口推进

1. 盘点真实未解析 CALL 的第一处断边，优先修 module/class 初始化、receiver 与字段来源；先证明通用关系，再在原 LeWM 端点核对。保留候选和明确条件，不按名称猜目标。
   已定位 CEM 的两个独立实现缺口：①函数 G 入口来源只在 CALL target 激活后建立，缺少原 factory→body 的条件捕获关系；②IMPORT_FROM 原端口未参与模块来源求解。相关两份模块实际已完整展开，不能把这两个问题归因于模块后缀。一般 self/descriptor 来源是另一项欠账。先接引用，再分析 entry 状态内容；不制造 CALL，也不复用创建 world 冒充 entry world。
2. module AnnAssign 首个范围已定点核验；继续 class annotation、deferred child 及实际主体阻断，保留 lazy/future、namespace/world 和异常语义。发布主图时才更新其覆盖分母。
3. 将原调用、逐地址 reaching writes、alias/effects、binding/容器与 Tensor 属性在共同固定点中反馈；把源码可推而缺规则与真正未绑定字段分开。
4. 完成按需依赖材料和 Python/native 绑定、资源契约，覆盖加载→规划/推理→保存路径。CPU/GPU/DRAM/HBM/storage/stream 建模到可控制边界，不展开 OS FD 表或指令。
5. 有关主体/关系改动再原子重建并公开读回完整范围。唯一主图仍为 `artifacts/current/static/`，queries 是带原收据的派生核验，不是第二份程序。

验收看实体、关系、推理和覆盖四项同时成立。未达成则继续第一阶段，不以小样例或队列收敛替代整程序完成。完整计划见 [STATIC_ANALYSIS_PLAN](STATIC_ANALYSIS_PLAN.md)。
