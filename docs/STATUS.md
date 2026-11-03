# 当前状态

当前唯一任务是整程序纯静态建模与建图。**第一阶段未完成**；不执行目标程序、import 初始化或用户回调，不做化简、detector/backend 或性能实验。唯一 checkout 为 `~/AAA/scar`，分支 `main`。LeWM 是外部 testcase，通用规则不按业务名称派发。

## 核心结构与真正的问题

主表示是层次化、有类型、有端口、带状态版本的程序依赖图。Operation、Value、StateLocation、Region、Resource 是实体主干，Use、绑定、状态地址、completion、控制和环境接口为强类型记录；不是五种互斥的源码标签。AST/CST 是输入，包含树只组织定义；数据、状态、调用和控制边可以跨层、共享和成环。

`ProgramDependencyGraph` 以原 namespace、typed ID 和静态 context 统一局部、call/env/G、class/provider、控制与资源导航。共享主体不复制，静态 context 不冒充 Invocation。值队列与区域 cut 已实际消费该接口。

**目前主要缺口是识别事实向规范接口的降低、关系覆盖和联合推理。** 全范围 calls 已发布，但大部分真实调用仍没有接通目标；module/class 主体后缀、receiver 来源、状态/alias/effects、Tensor 属性及 Python→native 仍不完整。不能用枚举完成或节点总数宣称整程序贯通。

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

同一批通用真实源码查询推得唯一不可变 tuple `(7,99,5)`；最新 15-root 机器记录为 135 points、281 edges、1,039 steps、2 branch proofs、5 binding proofs、6 route refutations。新增默认 factory 来源的开放前沿单列；未知/custom 区域没有污染独立已知字段。原 core 同步 region 的两层上下文、未知/循环/部分接口与预算边界已核验；**保存的 Python candidate frame 入口范围仍 open**，不能说全部跨函数控制已闭合。验证源码未执行。

当前 `queries/binding-knowledge/` 的源码、小模型与 proofs 收据一致。最新 schema4 仅重查询约 3.114 秒，context 显式保存 `unknown_prefix`，condition 保留 operands；原建模 1.96 秒未重测，单列旧测量。查询处理 2 graphs / 0 shards，输入计费 1,919,427 bytes；工作队列稳定与查询范围未闭合分别报告。源码、模型全部 14 个文件和主 current/static 均未改变。此目录只是通用规则核验，不是 LeWM 或另一份权威程序。

已有独立 binding state field、normal/raise slot0 隔离和原 TRUTH 合同推理继续保留；worklist 稳定与原查询覆盖完整分别报告。源码常量只来自静态 builtin literal/原编译常量表，不保存 Tensor 内容，不执行用户协议。

### 函数创建来源与条件身份

**Implemented / Verified（默认 Session 自动发现，尚未发布独立 origin 索引）**：`StaticFactoryEntryOrigin`、独立源码/编译重放与共同图 provider 现在由默认 Session 按需接入。不依赖已识别 caller CALL，也无需调用者提供 factory、SourceDefinitionReference 或 origin 列表，就可表示原 FUNCTION_OBJECT/G 捕获到原 body 环境端口。不映射 entry world、B、defaults 或 namespace 内容。

源码 hash、原 child slot/path/layout、词法 source 和两个原接口联合核对；捕获 G 还须等于原 module/class/nested ABI 的 G，不只信 role 标签。class 的 operand index1 与 module/nested 的 role index0 分别校验。已确定的编译槽对应进入 evidence，不挂成未知运行条件；入口来源、factory 正常完成和入口当前 code 匹配仍是条件。

审查还修复了条件键碰撞：`DependencyCondition.operands` 保留关系的其它 qualified 端点，entry callable 与不同 factory 不能共享同一个条件键。只懂一元签名的证明规则遇额外参数保持 open；empty origins 不能宣称完整，无关 literal 不产生假 factory 前沿。当前 walk/value/boundary 导出版本为 **3/4/3**，context 显式保存 `unknown_prefix`，原主图分片不改版本。

原显式 API 的两图核验仍保存在 `queries/factory-entry-origins.json`，仅为该组件较早的输入/读回记录，不能当作默认自动流程。

**Verified（真实 CEM 默认自动流程）**：默认 `session.graph()` 从 `solve` 的原 G formal 自动找到 class factory，并经 class suite→provider 的当前 G 读取→父级捕获 Use，连续 **6 条引用边**到达原 module G。没有手工构造 factory、定义引用、origin 列表或注入 provider。约 **32.76 秒**，9 个访问端点、8 条边、4 个 namespace/graph、4 个关系分片；只索引 **1 个 unit catalog、检查 1 个匹配 factory**，没有全局路由或扫描所有主体。输入计费 153,450,632 bytes；这是分析器成本，不是 LeWM 性能。

代码和机器证据：`queries/factory-entry-origins-automatic.json` 保存默认查询、规范化连续路径、原输入收据与后读校核；旁边 task 终态 COMPLETE/exit0。source/main manifest 前后不变。创建侧保留 `None` fallback 和已核 Open 两帧后缀，沿 provider 退为一帧，再回到 module 的未知外层；没有把未知补成 `()`。新增 class 捕获桥使用 `CURRENT_FUNCTION_GLOBALS_EQUALS_FACTORY_CAPTURE`，绑定原 bodyfn、捕获 G、读取 world 和 G 结果，仍为 MAY/REFERENCE。**48 个原 CALL 的目标仍为 0，入口 namespace 内容、IMPORT_FROM 及完整 CEM 未完成**。

通用静态案例同时覆盖无任何 call/class publication 的 module/nested/class 方法自动来源；增加 class publication 后才使用其原接口后缀追到 module G。原 canonical 分片 hash 不变；额外参数/开放前缀不授闭合证明，坏原定义引用拒绝，预算截断保已知边和具体原因。相关核验按修改范围运行，没有重跑长 fixture 或全范围 linker。

### 真实 IMPORT_FROM 接入同一依赖图

**Observed**：原端口早已存在，旧模块来源索引却只识别 `ast.Import`，因此 `ImportFrom`
没有进入模块来源/reaching-binding 分析。另一个独立问题是 `_namespace_sources()`
要求先有 CALL activation，`activate_target()` 又先要求目标，导致 G 绑定与调用解析互相等待。

**Implemented / Verified**：v9 新增原请求/读取的 typed records，复用原 module flow 表；
模块和函数中的绝对 FROM 经原 request → 返回模块 → namespace writer payload → FROM
normal result 连接。fromlist 来自原 `CodeConstantSource`，独立重编译核 CodeRef、常量槽、
成员 CFG 顺序及真实 receiver/key/world。非空 fromlist 返回完整模块；不伪造 Attribute，
不按名字跳定义。旧 v8 仍按旧契约读回，递归支持路径不能夹带新请求/读取/条件。
独立 reader、公共图 provider、v9 raw routing 和 producer 收据已接线；Attribute 与 FROM
的接口/处理计数分别保存。class import 的专用编译适配尚未实现，明确留前沿，原端口保留。

通用集成案例覆盖模块/函数、别名、多成员和完整包路径，约 19.02 秒；已有属性覆盖、
初始化 L/G 状态和双向调用路由三项回归通过，约 142.78 秒。未运行目标，没有扩大全量测试。

**Verified（真实源码）**：`cem.py:12` 的原 FROM 自动找到 `solver/utils.py` 的绑定及原
函数创建，成功推导/独立重放约 **5.01 秒**；索引 2 个主体，输入计费 72,331,914 bytes，
记录 6 个 FROM member，其中 2 个相对请求保留具体前沿。随后将这一条原关系保存成
**局部、明确不完整的 v9 关系分片**，由公共 `ProgramDependencySession` 独立读回，
得到 1 条 `STATE_VALUE/REFERENCE/MAY` 边，约 **7.18 秒**、2 graphs / 1 shard。
typed neighborhood 再编码/读回相等。没有手工构造函数目标或依赖边。

记录在 `queries/import-from/summary.json`、`relations.json`、`task.json`；后者 COMPLETE，
公共图核验为 true。它们只引用原规范主体，不是另一份程序模型；唯一 current 主发布仍为
v8、manifest SHA 不变，未重跑全范围 linker。查询脚本的行号/API 误用已纠正，以上成本
仅计成功分析和独立读回，不能当作目标运行性能。

**本节当时尚未完成**：入口时刻的 namespace projection 及调用求解器消费；本轮进展见下。
相对 package 来源、class import adapter、hook/fallback/跨主体覆盖仍有欠账。缓存/动态属性等保持条件，
`enumerated=false`。没有重新计算或发布 CEM CALL targets，原 48 个调用仍为 0 个目标。
这次接通绝对导入，不代表完整 CEM 或第一阶段完成。

### 入口状态和调用接口已由共同图实际消费

**Implemented / Verified**：默认 Session 增加不依赖 CALL activation 的
`EntryNamespaceProjection`。原 G 引用路径、函数 entry→read 的存活路径与模块
writer→normal snapshot 的 reaching binding 分开验证；snapshot/entry worlds 不合并。
L/G 只有独立的有条件 alias 分支，没有假定标准 import。函数内覆盖会 kill 旧 entry
来源；默认图同时保留新的同体 namespace writer→read，module/class 零 CALL 读也适用。
通用整例约 7.15 秒，含 codec、fresh 重放及原分片不变校核。

真实 `solve` 的原全局 read 已自动得到 **1 个投影 / 1 条公共 STATE_VALUE 边**，
owner 路径 6 边；21 个条件、7 份证据，仍为 MAY。None/Open 上下文与初始化/入口
world 分开。推导、typed 读回与公共边独立再对齐约 **79.85 秒**，4 graphs / 4 shards，
输入 153,450,632 bytes。记录在 `queries/entry-namespace/`，任务 COMPLETE/exit0，
原源码及 manifest SHA 不变；不代表所有 entry binding 已闭合。

新的 contextual 调用消费者沿共同图的引用/绑定字段边到真实 factory，生成独立的
`StaticCallInterface` 与 `ContextualCallTarget`。caller 与 factory context 各自保留，
真实 CALL push/pop 生成参数和正常 reference 返回边；所有来源条件继承，未知外层
保留 Open，不进入旧闭合 activation。共享 facade 的 graph/index/document 与 owner
原对象相同；不读旧 CALL publication，module 索引另列保留预算。无匹配 caller 的
formal/return 保留开放前沿，递归已知后缀受深度预算限制。通用闭环、篡改拒绝及原
CALL 路由兼容两项合并核验约 18.74 秒通过，没有重跑全量测试。

**Verified（实际通用 CLI）**：`scar static-calls` 对 `cem.py:134` 原 CALL，自动经
entry read→模块导入写入→工具模块 factory 找到 **1 个条件目标**，建立 **6 条
ARGUMENT / 5 条正常 reference COMPLETION 边**，约 **45.74 秒**。源路径 5 边、
38 个条件全部继承到接口边，caller/factory 均保留未知前缀，callee 为 Open context。
结果 typed 解码、接口边重算精确相等，所有边为 MAY。输入计费 241,802,513 bytes，
共享 4 个主体，只读 1 个 class 关系分片。任务 `COMPLETED_WITH_FRONTIERS`，记录在
`queries/contextual-call/`；没有执行目标、重算其它 47 个 CALL 或更新主发布。

**边界**：这是选中 CALL 的条件源码关系，当前字典内容、函数可变字段、其它目标和
effects 仍未闭合。旧全量 v8 索引的 48/0 统计保持历史发布原值；新查询不能直接覆盖
它。legacy 全范围队列尚未迁移到 contextual 域，完整 SCC/receiver/descriptor/defaults
与 shape/资源连接继续欠账，第一阶段仍未完成。

派生调用记录现为规范化 v2：复用原 namespace/context/point/condition/evidence/edge
表，每条仍引用原 ID，不复制 ProgramGraph。已用上述真实结果离线转换并强类型读回，
resolution 与 11 条派生边逐对象相等；decoded **17,560,258→128,382 bytes**，gzip
**664,538→23,264 bytes**。v1 raw 兼容读回，bool 索引与错误 node type 拒绝；这只是
记录完整性，不替代基于原输入的 fresh 来源验证。转换没有重跑 LeWM 或分析查询，
原报告与 chunk 收据已同步，唯一当前记录保留 v2。

### 先定位再改：Attribute 前端分层审计

按用户最新要求暂停新增规则，先核对识别、降低、连接、推理的具体职责。保存的 48
CALL 形式分类中，local/produced-object attribute 有 22 个、global/builtin 10 个、
imported-module attribute 7 个；这只是导航分类，不能据此声称同组全部缺同一规则。

**Observed / Verified**：在原 `solve` 图上只读审查 144/145/166/210 四个点，AST/SG
及 `derive_attribute_accesses` 都已识别 field/receiver，typed access 的 result 与原 callee
Value 4/4 一致。原 producer 为 EXPRESSION，protocol/refinement 均为空、effects 未闭合，
只保 coarse world 和 normal/raise。第一处已证缺口在降低后的 lookup/state 接口，
不属于 AST 未识别；也不能直接归咎动态 Tensor 类型。原 graph/source/Use/world 收据
与阶段归属存 `queries/attribute-front-end-audit.json`，约 20.10 秒，未运行 resolver/目标、
未修改源码或图。结论不扩大到未查的其它点。

receiver 审计也已完成，见 `queries/receiver-source-audit.json`：mean/var 经原 binding→
同一个 UNPACK_FIXED 的 component0/1→144 CALL NORMAL0；v_batch 经 slice、binding、
unpack、iterator item→162 items CALL NORMAL0，并能追到原 info_dict formal。相关端口
和本地绑定已经存在，普通 operand/result 依赖不能当对象身份。此处欠的是 product/
iterator/slice 抽象事实转移与真实 caller 输入条件；self/info_dict 的未知来源不能靠
词法类名或注解补成确定对象。该审计无 resolver/目标/建图/代码改动。

下一项先定义准确 lookup 接口，再改负责 lowerer：保留已知 selector/receiver/world，
不把属性访问无条件当作直接读取 `__dict__` 或存储字段。descriptor/MRO/native 与未知
副作用继续分层处理。暂不凭候选数添加规则或优化。

### 源码覆盖：编译器已消去的字面 bool If

**Implemented / Verified，尚未重建 current 主体**：模块 `if True/False` 通过原源码与独立重编译 CFG 见证展开；保留两臂源码，仅为选中臂建立执行结构，不制造 TRUTH/BRANCH。死分支仍影响的 compiler annotation factory/cell/prelude/global scope 不丢弃。旧保守 wire 独立读回，不静默升级覆盖。

**Implemented / Verified（真实源码定点重建，未替换 current）**：module 的简单名称 AnnAssign 已接默认 lazy registration 与 future 字符串模式，保留原 RHS→store→lookup→set/subscript 更新、world 和正常/异常清理；注解表达式不执行。整数索引/字符串来自原编译器槽，不按已展开语句重编号；隐式操作仍引用原 AnnAssign，不伪造 AST。只接精确 BUILD_MAP0 空 dict RHS，其它 Dict/复杂目标维持原边界。

真实 `envs/utils.py` 前缀 7→15/15、语句残留 8→0（321 ops）；`callbacks/registry.py` 前缀 6→15/15、残留 9→0（425 ops）。构建与独立读回约 16.28/10.51 秒，原图与模块接口逐对象相等。唯一扩展短验通过 13.00 秒，Root 原 class/compiler/import 回归通过 7.47 秒。旧 wire 没有新见证时仍重放旧覆盖，没有静默升级。

原 source/producer 收据、两个压缩样本及未闭合项在 `queries/module-annotation/summary.json`。两模块仍 PARTIAL：生成的延迟注解子主体和 namespace/alias/effects 未闭合。current 主体尚未替换，107/45 后缀分母不变；class annotation 协议仍待补。这项覆盖修复不解决 CEM 的入口 namespace 状态与调用解析问题。

### 库/原生材料：输入层完成一部分，整程序连接未完成

**Implemented / Verified**：隔离复用 torchgen schema parser，6 个实际 ATen overload 构造现有 NativeBoundary 接口，共 18 ops；版本/文件/工具收据、正常/异常与 opaque world 保留。原 schema alias/write/dispatch 不冒充 must-alias、物理 copy 或已选 kernel。

C++ source 前端复用 Tree-sitter，实际 53,705-byte template 中机械枚举 79 个显式方法项、83 个函数、563 个调用、5,661 个相关 occurrence / 12,576 条 SOURCE/STRUCTURE 边；保留 4 个模板孔、6 个 ERROR。原 ID 表规范化保存约 2.98 MB JSON / 0.383 MB gzip，读回相等。私有工具环境约 19 MiB，未修改 LeWM 环境。

这些材料和验证在 `queries/native-static-model/`；**尚未发布进 current canonical 整程序，Python callable→参数转换→native overload 与具体 runtime/kernel/resource 连接未完成**。CST 是源码输入层，不冒充 C++ 类型/ABI 证明。

## 下一步，按实际依赖缺口推进

1. 默认 factory-origin、入口状态投影和 contextual 调用接口已在选中真实 CALL 接通；下一步按 **原 48 个 CALL 的断边分类**扩展共同求解，补 receiver/descriptor、相对 package/class import、函数字段/defaults、循环与递归摘要，保留条件/未知前缀，不能退回名字提示填目标。origin 和 contextual 关系的全范围发布仍待完成；派生记录需规范化读回，旧发布计数不能冒充最新闭包。
   CEM 模块与工具模块均已完整展开；不能误归因为主体后缀。创建 G 的引用不证明入口内容；不制造 CALL，不复用 creation world，不由局部 1 个目标推定全部 48 个已经解决。原分类与收据在 `queries/lewm-call-gaps.json`。
2. module AnnAssign 首个范围已定点核验；继续 class annotation、deferred child 及实际主体阻断，保留 lazy/future、namespace/world 和异常语义。发布主图时才更新其覆盖分母。
3. 将原调用、逐地址 reaching writes、alias/effects、binding/容器与 Tensor 属性在共同固定点中反馈；把源码可推而缺规则与真正未绑定字段分开。
4. 完成按需依赖材料和 Python/native 绑定、资源契约，覆盖加载→规划/推理→保存路径。CPU/GPU/DRAM/HBM/storage/stream 建模到可控制边界，不展开 OS FD 表或指令。
5. 有关主体/关系改动再原子重建并公开读回完整范围。唯一主图仍为 `artifacts/current/static/`，queries 是带原收据的派生核验，不是第二份程序。

验收看实体、关系、推理和覆盖四项同时成立。未达成则继续第一阶段，不以小样例或队列收敛替代整程序完成。完整计划见 [STATIC_ANALYSIS_PLAN](STATIC_ANALYSIS_PLAN.md)。
