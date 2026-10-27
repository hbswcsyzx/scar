# 真实 BodyRaise 的来源、清理与调用方连接

2026-10-19；基线 `753104593c67c0d0d1190288843eb0420ebcc072`，当前工作树干净。
上一轮是真实 progress：1693 affected focused、原1671 identities 守恒、归档核验、
提交/推送及远端精确 SHA 已确认。本轮延续原 A–H 与 F12–F24/X25–X27；P5、
M2 原113构造/196字段及完整 M0–M2 保持原目标，不能用新增小门替代。

## 1. 审查结论与本轮单位

五类实体仍为 Operation / Value / StateLocation / Region / Resource。BodyRaise
是原主体的实际 RAISE 完成；获取失败、构造器 RAISE、提取 child 的 RAISE 是
另外的原事件，不能靠相同 packet 类型替代。没有新 wire、第二 SSA 或 backend。

三路独立只读审查与 root 源码核对确认：

- program/await_outcomes.py 的 structured 接入只覆盖转换器自己的结果；没有
  producer_ids 的真实 BodyRaise 仍直接比较旧 payload→parent result，False 就
  NOT_APPLICABLE 并清空消费者，没有当前终点/state 收据。
- protocol_validation.py 的 BodyRaise 检查仍要求原包/adapter 直接传播，尚未
  复用 adapter 分支已有的 typed C1 continuation 关系。
- 动态 port_value/_result 尚不解 DriveResult；不能冒充转换器 result，必须沿
  本次实际 Drive transfer 的 BodyDriveResult.index→原 landing formal 解值。
- 获取/lookup/资格失败另有同类旧假设。其 own acquisition RAISE 仍是 RAISE，
  caller finally 的 Return 不会把它改写成 acquisition NORMAL；资格拒绝控制
  来源也不是现成 whole packet。这些原欠账保留，不拿本轮 BodyRaise 关闭 B。

本轮完整单位：

```text
原独立来源 / acquisition / Create 或 W-held-B
 → 准确 B 的实际 RAISE（零 cut 或真实两 cut）
 → 本次同步 D 的原 DriveResult whole packet
 → 同步 C1 保留 / ReplaceRaise / ReplaceReturn
 → 当前终点与当前 state
 → 准确 parent completion kind/fullslot（W 另有真实中间调用）
 → 当前消费者；无原最终提取义务
```

## 2. 收据合同：扩展既有查询，不造新事实

1. 原 EXCEPTION outcome key、DriveOutcomeRef 和 payload 不变。新增可选
   `continuations`、`terminals`；`conversion_legs` 保空，不制造 StopIteration。
2. 复用 continuation_rows/structured_completion。每个终点保原 root_source、
   当前 current_source/role、准确 choices/context、current 与 root binding。
   原包保留与合法替换分别证明；current=False 拒绝，unknown 不洗成覆盖成功。
3. 按当前真实 RETURN/RAISE 接 parent 自己的同 kind/full result slot；保原
   advance_legs 分母。已完整核到不适用才 NOT_APPLICABLE，opaque/预算/缺桥
   不得因无终点而排除消费者义务。所有 BodyRaise 分支 requires_final_extraction=False。
4. 继续核当前 terminal State Use→parent 当前 state result，各 location 分开；
   清理前 state 仅作来源/失效关系，不以“旧版本必须不变”判断合法清理。
5. 动态从准确 body outcome/DriveExecution 与 actual transfer 解 DriveResult，
   核本次 D CallActivation 完成，再接 parent。W 的中间调用不是 B 的 activation；
   缺一实例 Use/关联/dispatch 不能借另一实例。source/runtime/value/transform
   authority flags 继续 False。
6. 默认直接传播仍用既有视图形状/关系；新连接启用的字段/计费引用唯一原图。
   修订仅限明确 C1 的 BodyRaise 终点规则，不取消错误原包、错当前 state、错
   adapter 或非法 native profile 的检查。旧冻结合同字节不改，以本文件记录细化。

## 3. 作者职责与接口

root 独占产品、文档、所有 Python/pytest/probe/compile、归档与版本管理。
作者不执行解释器/git、不改旧 tests/fixtures/合同/codec，各自完成后报告 SHA 冻结。

- A：新 `tests/fixtures/program_await_raise_cleanup_graphs.py` 与 execution 对应
  文件。提供 `add_driver_raise_cleanup(program, details, mode='preserve')`，仅将
  准确最后 D 的 BodyRaise landing 接到同步 C1；保留其他原 outcome/正常 CFG。
  modes：preserve/replace_raise/replace_return/opaque/wrong_terminal。self 完整
  factory 使用旧真实两-cut BodyRaise 基础；动态须重建所有改变 region 的采集，
  不能只换 snapshot。静态 helper 对 general/W preserve/replace_raise 也可组合；
  Return 至少 self 有完整新 parent NORMAL 与实际 consumer，不能伪造 R 提取。
- C：新 `tests/fixtures/program_await_raise_sources_graphs.py` 与 execution 对应。
  提供 general/W 的真实 BodyRaise 原图与采集。`source_kind='general'|'wrapper'`，
  `zero_cut=True|False`；零 cut 真 packet RAISE，无假 Suspend；两 cut 真 C1
  Replace 到 B RAISE。通过 A helper 组合 preserve/replace_raise，保来源图、
  Create/capture/held-W 与调用层次。旧 child_raised 绝非 B raise。直接 native/self
  的其他来源组合仍属原 A/E 待闭，不把 general/W 两路算作全三路已齐。
- B：新 `tests/unit/test_program_await_raise_continuations.py` 与 execution 对应。
  独立完整整链断言与有限错包/opaque、缺采、预算/分母反例；先原API真实首红。
  不按 root 实现镜像测试，不伪造身份来消除合法 PARTIAL。

共同 metadata 保旧 keys：caller/caller_path、body/body_terminal、drivers（各自
driver_region/drive/path/host_terminal/caller_call）、source/get/acquisition_scope、
drive_outcome；新 `raise_cleanup` 指准确 root payload、C1 actions/dispatch/current
source、真实 terminal、准确 terminal payload/state Uses。执行 examples 保 advance、
body_activation/segments/drives/outcome、D scopes/call associations、driver terminal、
final，以及缺采切换。细节需三作者先同步，不能按 label 寻找关系。

## 4. 自验与原剩余范围

先冻结字段/接口→独立新图/断言→root 首红（作者错误与产品缺口分列）→修公共
关系→有限反对审查→作者/源码冻结→原1693精确 case identities 守恒的受影响
回归→归档核验→commit/push/远端 SHA。每次执行独立 command/log/JUnit/source
前后注册表，不覆盖旧失败或拿旧 SHA 的绿测作新源码证明。

原 A–H 八格和十六组仍按原清单逐格核；本轮不能关闭获取失败、共享 incoming、
重执行/刷新、native/self direct-vs-await 的全部组合。原十六组真齐后才组件/full、
P5 和 M2 总核，完整 M0–M2 完成后按用户要求先停下来解释模型。无新 profiler、
detector/backend、LeWM-specific 规则或性能结论。
