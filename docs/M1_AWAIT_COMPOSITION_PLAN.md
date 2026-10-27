# Await完整组合：按原 A–H 清单持续验收

2026-10-19；基线 `e935082bb3626eae7e8b299e20e36441c7052c5f`，工作树已核干净。
上一目标轮为 **progress**：1393受影响定向、完整证据归档、提交及远端SHA核对。
它没有完成整个await单位、原16组或M0–M2。本轮不重复其测试来冒充进展。

## 1. 模型与范围沿用

沿用 [原D0计划](M1_AWAIT_ACQUISITION_PLAN.md) 与
[冻结D1合同](M1_AWAIT_ACQUISITION_CONTRACT.md)，不修改其原字节。五类实体仍为
Operation / Value / StateLocation / Region / Resource；输入、候选iterator、W/B
和异常是原Value/Use角色；控制使用原Region/CFG、发生使用原activation/segment。

Program23/Execution8不再扩型。本轮先把已定义的原端口关系放进完整供应程序与
执行记录，真实测试它们是否连接正确；具体错接才修公共resolver。禁止先添新
detector/backend或按LeWM/函数名选规则。不存Tensor逐轮数值，不再跑native12
探针、LeWM/GPU profiling或benchmark。

## 2. 完整分母与四路工作

| 原格 | 仍须实际核对；上一轮self首cut不能代替 |
| --- | --- |
| A | native/self、generator-coroutine/self、真正general parent/callee；普通generator的direct拒绝与general返回允许；不合格返回不能成功推进。 |
| B | lookup/call/qualification所有原N/R，早失败与合法TypeError消费；错当前值、packet、callee、state和slot。 |
| C | 零cut的首advance完成及准确最终提取/consumer，不制造父Suspend/Attach/Drive。 |
| D | 至少两cut、一持续B、逐准确slot恢复，中间handoff与最终结果分开。 |
| E | 同B direct/await两路径；多个相同body/code的Create不混；旧Resume/Drive/current-state错接。 |
| F | 独立W constructor→原getter W/B→准确Drive；W≠B、独立expectedB、同scope identity冲突、缺owner/缺采。 |
| G | 共享incoming/caller整组tuple，包含两臂传同一值的实际选择；删整stage/link后仍保source/consumer。 |
| H | 同shared budget贯穿静态与动态；budget1保原总数/未查项/cursor，reexecution/fresh identity与detach；不把空缺采强行报预算不足。 |

原F12–F24/X25–X27十六组、P5、M2原113构造/196字段全部保留。即使本轮
完整await单位通过，也不能跳过其他family原格和总验收。声明图、语言规则、
source/native/runtime/value身份及transform授权分别报告。

| 作者 | 独占新fixture/test | 首个交付与随后反例 |
| --- | --- | --- |
| C | `program_await_general_graphs` / `execution_await_general_graphs` / 对应general两个tests | 真GetAwaitable callee含lookup/call/qualification；A不是B；成功和合法失败。 |
| B | `program_await_wrapper_graphs` / `execution_await_wrapper_graphs` / 对应wrapper两个tests | 无假lookup的native构造W；getter自己的B结果及两级真实调用；W/B scoped身份。 |
| A | `program_await_resume_graphs` / `execution_await_resume_graphs` / 对应resume两个tests | 零cut/多cut的原控制与发生；同B direct/await和旧状态/来源。 |
| root | case四新fixture/test、公共产品修复、文档、串行执行及归档 | shared incoming/caller、预算、完整消费者；真实失败后准确修公共规则。 |

所有fixture以tests/fixtures现有图为基础，只import原构造器，不修改原文件。
先落最小完整路径→冻结作者→root实际运行，再按具体失败修复；不在写出首图前
做无限推演。subagents禁止Python/tests/probes/compile/commit；作者间不交叉编辑。

## 3. 自主关卡

1. **D2**：本计划冻结，逐原格登记预期观测与拒绝条件；已有D1优先，真字段阻断
   先记录原因，不能为了过测试自行造新producer/phase或缩掉不便表达的路线。
2. **P/X**：四路先用同一个canonical程序/执行组合；core合法性与原公开query
   分开检查。fixture/API失败原样保留；只有抵达产品接口的反例才叫产品缺口。
3. **I**：完整正反组合逐A–H核；原异常与当前state原端口守恒，删除附件仍有分母，
   一好caller/路径不能覆盖另一坏来源；不按测试数宣称完成度。
4. **V**：独立有限复审→所有作者冻结→root串行受影响定向，保上一1393项义务和
   已归档三个future参数ID迁移，不为单helper反复跑component/full。原16全齐才
   原组件与冻结全仓；当前历史5822 full仍只属于其原revision。
5. **A**：原失败、计划/合同、original fixtures/wire、保护目录、最终源码指纹及
   case身份核验，commit/push与远端SHA。未闭的原格继续OPEN，不叫阶段完成。

证据目录 `artifacts/experiments/b1_call_operands/model_await_composition/`。
保护 `/home/zyf/AAA/le-wm` 与 `/home/zyf/AAA/scar` 原HEAD/status；不reset、不覆盖
用户修改、不改环境。验收充分后停止可选复跑。整个第一阶段真正完成后再停下来
解释模型；本计划不是完成声明。
