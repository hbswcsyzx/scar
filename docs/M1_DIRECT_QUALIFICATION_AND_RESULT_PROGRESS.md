# F15：资格与另一Drive结果的实施记录

2026-10-19，基线7aee713c1b700f504ba3ebb8606fa2a4456c4e1c。上一门为verified
progress：1845同源定向、原1807 identities及旧字节保留；原E/G/H与F17/F21/F23
条件结构验收；提交前后checkpoint及远端精确SHA核验。本轮起点实际重新
运行前轮checkpoint，通过后才准备新设计基线。

[冻结计划](M1_DIRECT_QUALIFICATION_AND_RESULT_PLAN.md) SHA
10c6d970c8b60509af4f7d23282c6d0f60309b27219e175c086541067f6534b6。
证据目录artifacts/experiments/b1_call_operands/model_direct_qualification_and_foreign_result/。
prepare实际完成；两个作者分别只写新unit文件，root独占所有解释器/产品/
文档/归档/Git。旧tests/fixtures/contracts/codecs及上一门归档全部冻结。

## 两个原义务的准确含义

1. **Observed（源码）**：used_source已按DIRECT_INPUT的已知kind检查await
   资格。**Proposed**：保完整Get→advance→body→final的原图，把GENCORO
   改为普通GENERATOR并迁移其准确已有profile/clause；core应合法，full应
   报acquisition_kind。普通generator的NEXT仍合法。还未把源码判断当实测。
2. **Proposed**：原图中两个真实Create/B，foreign Get→独立Drive→原完成
   conversion→foreign final OutcomeAdapter，取其own NORMAL Ref并沿真实
   CFG forward到current final RETURN。只替换current payload Use；两Ref
   同型、支配合法、state仍为current。foreign最终adapter的原input须准确
   追到foreignDrive，不拿错O关联/helper/终端packet冒充另一Drive结果。

M1定义/发生/身份/权限仍分离；不增加LeWM业务规则、detector或backend。
F12/F13同步只读按原条款核selectors，不提前关账、不扩大组合分母。
本轮实际运行与最终结果将逐attempt登记；完整M0–M2和自动整程序建图仍未完成。

## 首轮实际结果

- `direct-qualification-first`：3P/0F，pytest1.22秒，854份源码前后SHA
  cbeaf92a39be93d41381694523febd31640e227a8fe4cb443fa17fde6a9184df。
  完整GENCORO self图、ordinary GENERATOR合法NEXT及精准误资格拒绝均通过。
  full负例仅报protocol_await_acquisition_kind；产品无需修改。
- `foreign-drive-first`：2P/0F，pytest3.35秒，855份源码前后SHA
  2c066dad88cef7b75acd544d65d24eec60ceb01baba4f026be3f4794e7f00db6。
  两真实Create/B/Drive分别接准确conversion与final OutcomeAdapter ownN/R；
  foreign ownNRef支配current final。只替换payload的negative保core合法，
  foreign binding=True、current binding=False、准确final_copy拒绝。无产品改动。

## 有限F12补充

B只读逐原条款核出：B/C/D/F及F13已有准确正反与缺采/预算入口，最终同源
JUnit后可直接验收，不再扩cleanup/每source/cut矩阵。A/F12真正余native
self无W、knownCOROUTINE/精确builtin bad return三项；ordinaryGEN误资格
已由本轮首测满足。为避免每个极小残项再全跑，冻结F12补充与literal澄清，
原计划/设计/selection保字节，新增design-amendment及amended selection。
`record-f12-amendment`实际exit0，源码855/SHA仍2c066dad...，没有启动测试。

LiteralEvaluation在原NORMAL Ref端口合法声明精确builtin内容；不是新producer
或对象身份。已有classifier能识别该内容，legacy资格筛选却可能跳过无Create/
无callee结果，这是源码疑点，尚未实测。第三文件保native正链、general
COROUTINE负例及builtin的literal-attachment/knowncallee-return两参数格；真
首红后才窄修。UninterpretedConstant不能被宣称known noniterator。

## F12首红与通用修复

`native-and-general-first`实际3P/1F，856源SHA
71bd021ac7acc944b5e0d4e4aace8401732ed2a11ee8e7b145a02044ac4e907b。
三个完整对照通过，own-normal-literal在_classified已完整NON_ITERATOR/
current True、core合法后，full validate却返回零issue；这是产品漏检，不是
供图/作者API错误。真实失败日志与四个原节点保留，未删负例求绿。

root只改protocol_await._legacy_qualification原fast筛选：查询现有共享
source indexes的精确row.contract.result，仅PythonLiteral保留到原检查链。
Unknown payload仍未知，knowncallee原所有kind/slot/Return路径不变，不作
新copy/identity/效果或变换许可。B独立只读复核无新增阻断。

`native-and-general-literal-fixed`实际4P/0F，2.00秒，856源前后SHA
fd1069cea62d96ed451b0cedc8ae8c644add212e5ec8f31a6982a8eac86bfed6。
opaque节点中的UninterpretedConstant分类未知/full合法控制也通过。
`record-extra-source-spec`实际exit0、0新测试，同856/SHA；用于原A/F12准确
selectors的证据映射。root随后全冻结，启动原1845+新增9的verified-final。
没有修改三个已交付测试文件、任何旧fixture或冻结合同来让产品通过。

## 最终同源回归、原范围合账与下一门

**Verified**：verified-final实际1854P、0失败/错误/跳过；pytest713.98秒，
命令包装715.0721124866977秒，856份源码前后SHA均为
fd1069cea62d96ed451b0cedc8ae8c644add212e5ec8f31a6982a8eac86bfed6。
全部原1845准确JUnit identities和旧字节由checkpoint另核；新增9仅来自三个
新文件。受影响定向不是新组件/全仓，实际充分验证后停止可选复跑。

original-structural-accepted实际exit0、0.2592569589614868秒、0新测试，同源
SHA不变；逐原A/B/C/D/F和F12/F13/F15匹配精确selectors及实际参数节点，
保原E/G/H与F17/F21/F23。原await A–H条件结构范围及F12/F13/F15正式关闭，
完整报告见M1_AWAIT_SOURCE_FAMILY_ACCEPTANCE.md。原旧remaining描述保留在
ledger的previous_remaining，未悄悄删原义务或用authority False重开结构门。

剩余十家族、P4组件/冻结全仓、P5、M2原113构造/196字段仍为原范围。
F14/F16只读审查见M1_COROUTINE_REQUEST_NEXT_REVIEW.md：已实现三次真实
同R/B stepping应计入，确切欠项为native phase/reentry/reuse/throw-close与
request COMPLETE再用/竞争/initialASEND/后续scheduler packet。这些是下一
门真正关系，不再重新铺四种来源的基础矩阵。当前整个目标保持active。
没有新增LeWM自动建图、TRANSFORM、GPU profiling或加速结论。
