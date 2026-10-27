# 下一门：返回原F19，不扩展来源工具箱

本门范围见[冻结计划](M1_VALUE_SOURCE_CONSUMERS_PLAN.md)，实际结果见
[限定验收](M1_VALUE_SOURCE_CONSUMERS_ACCEPTANCE.md)。完整顺序仍是
[WHOLE_PROGRAM_MODEL_PLAN.md](WHOLE_PROGRAM_MODEL_PLAN.md)。

## 1. 合并原有证据，而非追加相似手工图

先用原finished-request图及准确occurrence复核当前READ主体、历史Drive主体、
Create handle、terminal/F、host顺序和state区间分别卡在哪里。新来源查询只补
有原store/load声明和完整区间支持的边。缺少的native内部不能从Create.body
或observed True猜出，不把原primitive自己的own新R伪造为pre-owned输入。

若原实现可展开，则用现有Region/CallEffectExpansion/CallActivation和raw store /
load表达allocate→own R→init→return/fullstates，schema无需先扩展。若原实现
确实opaque，保准确接口及native适用义务；不能把“类型能表达”记成“已自动恢复”。
Drive owner→Create handle与opaque/RW区间仍须独立成立，不能仅将目标READ接通
便把F19第1项、F历史或whole-stage翻成True。

## 2. 原F19组合保持原分母

继续原[M1_ASYNC_CLOSE_CONTINUATIONS_PLAN.md](M1_ASYNC_CLOSE_CONTINUATIONS_PLAN.md)
的graceful close：GE→finally AWAIT/HOLD→同R/当前S恢复→真实terminal→两层reply。
随后illegal close-yield：R完成而B仍挂起、sameR拒绝、新R无Drive、同B后续finally
与真实终结。R完成、active session、ag_closed、F和physical release分别建模。

复用旧接口、原source/native观察和既有反例；只针对具体剩余连接补有限证据。
没有实质连接问题时不再扩大来源helper、codec迁移或测试排列。每门先明确原
覆盖单位，再冻结、串行自验、独立审查、写报告和普通commit/push。

## 3. 整阶段顺序不变

九族限定接受，F19/F20/F22/F24/X25/X26/X27七族及P4 component/full、P5、
M2原113构造/196字段继续开放。原2304目录是已知focused test义务，不是阶段
分母，也不是全仓当前通过数。完整M0–M2真正验收后先向用户解释类型、连接、
覆盖和边界；再进M3入口自动Python shell / FX/Export子Region建图。

本门封存后known focused目录2325＝原2304＋21新增；271个旧身份在本门复验，
2033个只保义务，未在本门重跑。下一门继承整个2325目录，不以本门292替换它。

不增加detector/backend/LeWM规则，不将单元模型证明或测试耗时当成自动LeWM
建图、可变tensor内容保持、可信TRANSFORM或wall-clock加速。
