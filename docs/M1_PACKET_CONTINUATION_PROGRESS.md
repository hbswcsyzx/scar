# P4 packet continuation 实施与验收记录

2026-10-19，基线 `f2b4781a9afc399352a534517bc2e26a8b12b794`，依据
[冻结计划](M1_PACKET_CONTINUATION_PLAN.md)。本门限定结论 **PASS_WITH_SCOPE_WIP**。
原16组、P5/M2和完整第一阶段仍 OPEN；不声称自动恢复 LeWM 或加速。

## 1. Observed：实际缺连接和 core 保护

旧 `packet_frontiers` 明确只回答下一边界。旧 close 家族解析器也在 C1 action
后停止，但其局部 `DECLARED` 没有完整消费者清单，不能用于解除后续义务。
本轮复用既有合法图和既有 API，先检验这个缺连接，不以新 API 缺失充首红。

前两次新构图分别违反 C1 action/JUMP 邻接和 post-pop route-only corridor，
原 core 正确拒绝。它们是新 fixture 错误，不能写成产品错误或真实首红。
第三次把原 RAISE port 从 exact exit shim 改为合法 handler block landing，
保持原 PendingPayload、Detach 和最终 packet Use，在该 landing 插入未知操作。
core 和完整图均合法；旧 close 两条路线仍 `DECLARED`，测试真实失败。

| attempt | 真实结果 | 归属 |
| --- | --- | --- |
| red-after-c1-opaque | 1F | 新fixture把opaque插在action与必须紧邻JUMP之间 |
| red-valid-after-c1-opaque | 1F | 新fixture破坏post-pop route-only corridor |
| red-valid-handler-opaque | 1F | 合法图，既有家族API未核后续opaque边界；真正缺连接 |
| first-connected | 97P / 2F | 每receiver-case后继库存缺0/2；已知callee内部opaque被copy摘要掩盖 |
| repaired-connections | 14P / 0F | 修后新增两文件：两个失败与相关正反例统一复验 |
| final-focused | **1032P / 0F / 0E / 0skip** | 原1018项身份/义务保留，新增14项，同一冻结源 |

第三次720源前后固定指纹：
`4d05cbf3105d01f5a1a62a6ab5bc5998d103b168436dd24d4885e94025f6d207`。
所有attempt保命令、日志、JUnit和源码前后清单，不删除失败记录。

首组合721源前后固定指纹
`5243b2085611dc00d6671ef9ebee915bb0187930e7c58d25c46a97b44e02f6ef`，
pytest7.19s。opaque首红、两cut N/R真实host、已知/未知helper基本图、原相关
覆盖通过；这97P不覆盖两个失败义务，不能写成此门通过。新增逐case库存字段
缺失是本轮待实施接口，不冒旧产品语义错误；callee内opaque假完整确由实际
合法图重现。返回copy正确与内部后继/作用域已理解必须分别核。

## 2. 模型及已验证实现

实体仍是 Operation / Value / StateLocation / Region / Resource。pack、C1 action、
Route、Dispatch、SavedInput、投影和实际 terminal/parent Use 由原图连接，不造
第二份 producer/state/phase 图或新 schema。

完整解析器沿原 CFG 独立发现必须核的后继/消费者，再逐项对照独立 expected
source；旧 frontier 收据单列。selector/port 的 possibility 与 payload support
分离，不能用 expected source 的 support 删除错包分支。active pending 与死 pack
分开，首交付错包不能被“fresh Replace”洗掉。

C1原语依法保持 unknown callback effects 和全域 post-state；解释其声明后继
不等于证明 pure。Suspend 后继为条件恢复；declared path 完整不等于 P3 本次
activation/segment 已对应。真正opaque/handler/循环/截断须保精确边界和cursor。

**Implemented:** 原 `packet_frontiers` 合同保留。共享 `packet_continuations` 在原
close 和 fallback 家族中实际调用，并纳入 issues/gaps。close 的
`first_frontier` 保首交付证据，完整 `targets` 列真正 terminal/parent Use；
`actions/projections/suspensions/helpers/boundaries` 保原图见证。

fallback 每腿保独立 `continuation_cases`：原 receiver case、它自己的完整
choices 与该来源的后继报告；聚合按所有 case 核，不用任意一个成功代替覆盖。
pending constructor recipes 的原 CFG choices 先与当前 case 相关，再查当前
token 与 payload；未证 token 不触发硬错包/合法覆盖授权，来源分母不删。
不同 active port 随后继保关联，同 port 多来源仍分别核，不能互相冒充。

known helper 的准确输入→输出 copy 摘要与其内部可达作用域分别核。
新 `_callee_scope` 使用同预算、原 CFG/guard、嵌套 callee、独立 port possibility
和查询内缓存；不扫不可达整张表来推测 effects。内部 opaque 即使返回 copy
为 True，也保准确原操作边界并令外层 PARTIAL。typed C1/条件恢复各保原条件。

上述14项修后验证在721源固定指纹
`4da7929e56cb8ab4629d12249972f1f3401d716f578c9f55edd5d75da2e732a4`
通过，pytest2.41s。未知/周期/截断与源码/native/本次动态发生仍不是完成证明。

## 3. 旧验收义务迁移

既有 case ID
`test_close_normal_and_raise_merge_into_one_real_fresh_pending_and_current_cleanup_replace`
保留。其旧 `DECLARED` 和 active pending/packet 断言移到 `first_frontier`，不删除
原义务；新完整路线在旧不完整作用域 JUMP 处必须 PARTIAL。原 fixture 字节不改。
这不是用弱断言覆盖旧失败，是明确局部交付和完整后继的不同分母。

## 4. 最终验收

**Verified:** root串行运行，conda lewm / Python3.14.7。最终统一 affected focused
为 **1032 passed**，零失败/错误/跳过，pytest43.31s、runner44.15971277654171s。
721源前后指纹均为
`4da7929e56cb8ab4629d12249972f1f3401d716f578c9f55edd5d75da2e732a4`。
原1018用例ID保留，新增14项；这些计数是验收成本，不是workload加速。

B/root在最终统一运行前完成限定源码复审；C的同源只读closure随后也确认
callee内部边界与copy摘要分离，没有发现本范围剩余假完整阻断。所有作者停止
写入，子代理不执行测试，最终运行期间源码稳定。完整源/fixture/失败记录和
保护目录另由checkpoint只读核验；不会在归档阶段启动新测试。

Program1–22/Execution8不变，原model/codec和全部旧fixture字节保留。唯一旧测试
断言迁移详见第3节与归档JSON；未删除用例。没有新backend/detector、LeWM规则、
环境升级、重型profiling、自动LeWM变换或新加速比。本轮不是component/full。
历史5822 full仍只属于8138986，不能归给当前源。

**Rejected / Unproved:** 确定错包按准确上下文拒绝；未证token、opaque、未知调用、
循环与预算保持相应缺口。declared-route完整不授source/native/runtime/transform
权限。callee内部截断保incomplete，但精确内部resume cursor尚无；外层cursor回到
该原call，这是报告精度限制，不是成功。合法覆盖仍保独立新来源及适用条件，
不能把旧包未继续视为任意删除该义务的许可。

## 5. 后续保原范围

原F12–F24/X25–X27的16组全部继续OPEN。本门连接了C1后的真正消费者，不等于
完整家族/source语义或P3本次activation/segment已经对应。接下来把这些共用
路径证明纳入原家族组合清单，补剩余normalization/handler、async生命周期和
发生关联；原分母齐备后才统一component与一次干净frozen full。然后继续P5、
M2原113构造/196字段和完整M0–M2验收，完成第一阶段后按用户要求停止并讲解。

证据：`artifacts/experiments/b1_call_operands/model_packet_continuations/`。
