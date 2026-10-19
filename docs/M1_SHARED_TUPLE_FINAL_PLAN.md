# 原 G 整链：共享输入、真实回边与共享子实现

2026-10-19；基线 `635c9976120ef2120ce8c1e22a5437b04b03b696`，已核工作树干净。
上一轮为真实 progress：1747 affected focused 通过、原1716 identities守恒、
归档核验、commit/push及远端精确SHA完成。继续原完整目标，不重置原 A–H、
F12–F24/X25–X27 十六组、P5 和 M2 原113构造/196字段。

## 1. 回到原模型，而非再添一种节点

Operation / Value / StateLocation / Region / Resource 仍为五类规范实体。
一个静态 Region 可以被两个 Operation 调用；每次实际调用分别有自己的
CallActivation。循环是原 CFG 回边，phi 是原 BlockArgument，重复 visit 引用
同一静态块而有不同发生身份。输入 tuple、原状态 SSA、实际 control transfer
不得被相同对象身份或同 callee Region 合并。

现 G 的 case 图只走到首次 Suspend；既有 general/W/final/C1 图已验证的条件
结构不重写成“尚未实现”。真正残项是从共享 incoming/loop/caller 贯通现有
最终链。M1 的可表达/机器拒错与 M3/M4 的源码/运行自动恢复分账；authority
flags=False 保未证权限，不独自成为永远重开已核 M1 子义务的理由。

## 2. 完整供应程序与实际轨迹

以既有 general_final(zero_cut, depth=2) 为基础，保独立 A、helper lookup/call/
Create B/qualification、准确零或两 cut、whole completion、E/F 提取的原 N/R。

```text
A → Get/helper(Create B、qualification) → returned B
 → split → arm A / arm B（同 B，整组 live references/raw/state）
         → merge → retry decision
                    ├→ 当前 tuple / 合法状态更新 → 回 split
                    └→ 准确 first advance
 → 一持续 B（零 cut 或三个真实 segments、两次恢复）
 → completion constructor → 原 final advance RAISE packet
 → 原选择分支 → extractor callsite L / R（共享同一个 E/F Region）
 → 各自 own NORMAL / RAISE、完整 typed result slots
 → 准确当前 caller consumer / state
```

真实捕获至少包含先 A、回环、再 B 后才首次 Drive。另捕获无回环与相反最后
incoming；两实例选择不同 extractor site/child completion。循环发生在同步
caller 的 copy/control 层，绝不重复 Start/Resume 已终结 B，也不在同步 D 中
塞 Suspend。每个 B 仍保持一持续 activation；每个 E/F call 有独立准确关联。

同一 callee 的规范 Region 不复制；递归展开是 query-local frame 引用原定义。
缺某一 caller 的关联/slot/Use 不得借另一个 caller、旧 visit 或 sibling 实例。

## 3. 原 incoming 库存与声明分开

源码审查发现待实测问题：一个 guard=None 的 universal case 会绕过现
_guard_inventory，而 _input_case_inventory 直接使用该单 case；即使两条原
incoming 都真实存在，也可能把原 jobs/outcomes 分母合成一行并称完整。

universal expected tuple 可以是合法的全路径声明，不能为方便验收禁止它。
先按原 merge predecessor 枚举 incoming，再将该声明接到各原 input_guard。
显式 cases、universal、缺一 case、整个附件缺失都不能定义原控制分母。
case.guard 与 job.input_guard 各自保持含义；不另造规范 case/producer 记录。

预算不足时，未完成的来源/advance/Drive/控制锚和尚未核配对明确保留；关联
总数暂不能枚全就报告未知、pending/cursor，不能把 prefix 或原 FK 模板数
冒充完整实际 jobs 总数，也不为了低预算强行免费完成归属分析。

## 4. 连接与安全条件

1. 每个 incoming 核 receiver、ordered argument/raw trigger 和当前 state；
   不能把两个输入的独立成功拼成一个合法 whole tuple。
2. input_guard 约束当前最近一次 merge entry；旧 A 已发生不证明当前仍走 A。
   对 link.guard 的适用也不能从旧回环借边，普通 source/callee 路径条件与
   incoming 选择保持分工。不全局放开 locate 的重求值或 segment 边界。
3. 最终 child own N/R、full slot 与逐 parent result 一直保留。共享 E/F 的
   caller frame 必须来自准确 Operation/CallActivation，不能按结果内容选择。
4. 错另一 Create/原包/当前 state/caller 均应由适当层拒绝或保持明确不匹配。
   如果过期状态已被 core SSA 拒绝，记 core 反例，不伪称新查询缺陷。
5. 删 case/整附件、link、final adapter 或可合法缺省的语义 stage 时，保原
   source/advance/Drive/输出/consumer 锚。已删 stage 的原引用用准确 StaticGap
   处理，不能保悬空非法图；没有配对证据时不凭唯一 callee 重建关联。
6. 不存 Tensor 数值、不新增 wire、第二 producer/state 图、detector/backend。
   所有派生查询共享预算，原静态/动态/身份/变换权限继续分别报告。

## 5. 作者职责与冻结

root 独占产品、文档、所有 Python/pytest/probe/compile、证据与 Git。作者只写
各自 NEW 文件，不改旧 tests/fixtures、冻结合同、codec 或旧归档；完成报 SHA
冻结。root 执行前所有作者停止写入，执行串行；不运行新的 native/GPU/LeWM。

- A：tests/fixtures/program_await_shared_final_graphs.py。
  await_shared_final_program(zero_cut=False, depth=2, case_mode='explicit')。
  case_mode=explicit/universal/partial/missing；保完整正常/异常 CFG。
  shared_final metadata 明确 split/arms/jumps/merge/guards/backedge/condition、
  当前完整 tuples、精确 first advance、两个 extractor sites/各 adapter/原 own
  results/终端 Uses 与共享实现 records；提供可按 arm 序列、extractor site、
  child kind 生成完整有限 caller_path 的 helper，禁止按 label 猜端口。
- C：tests/fixtures/execution_await_shared_final_graphs.py；调用 A 原图。
  await_shared_final_execution(zero_cut=False, depth=2, case_mode='explicit',
  instances=2, arms=(0,1), extractor=0, child_raised=False, ...)；可对两实例
  指定不同 arms/site/kind。按 visit 切片索引所有重复 occurrence，不用 site→
  occurrence 字典覆盖旧访问。重建全部改变 caller 的采集与 CallActivation/
  BodyOrigin endpoints；保真实 helper、1/3 B segments、D 与 E/F 采集。缺采只
  选一个实例的明确 Use/call/transfer，core-invalid 删除要如实另列。
- B：tests/unit/test_program_await_shared_final.py 与 execution 对应；独立核
  全链、原分母与反例。先最小真实 API 首红，作者错误与产品缺口分列。冻结
  合同后先与 A/C 同步 metadata，不镜像 root 产品，不用删除正常 CFG 过测。

## 6. 原 G 自验分母

| 必须核对 | 证据范围 |
| --- | --- |
| incoming 与循环 | 两臂同 B、零/多次真实回环、最后 incoming 选择；整 tuple/current state。 |
| 最终链 | 零/两 cut 各到实际 constructor、E/F own N/R/full slots 与 consumer，非只首 cut。 |
| 多 caller | L/R 两个准确调用点共享 E/F；两实例、错 caller/旧包与单实例缺采。 |
| 独立分母 | explicit/universal/partial/missing；删 link、adapter/stage 后保原锚或明确未知配对。 |
| 有界与失效 | budget1、真实中段、全缺采、返回 detach 和 fresh external context；不把 prefix 叫总数。 |

先三路只读审查→冻结计划→新完整图/断言冻结→实际首红→公共关系修复→有限
反对复核→全冻结→原1747 identities 加新增的 affected focused→归档核验→
commit/push/远端SHA。每次保独立命令、全日志、JUnit 和源码前后清单。整 G
是否满足由原要求逐项审计，不按测试数或 flags 结论代替。

F17/F21/F23 等已有结构证据另做合账，缺什么写什么，不重开已核子义务。
原 E/H 的 whole-pipeline 重执行、同 B 重复获取来源与其余家族仍是下一工作，
不能由当前 copy-loop 冒充。原16组真齐才组件/full、P5及M2总核；M0–M2 完成
后先向用户讲解模型。自动 whole-LeWM 恢复、变换与加速比仍未证。

证据目录：artifacts/experiments/b1_call_operands/model_shared_tuple_final/。
