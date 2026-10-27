# 当前frame身份声明与历史F：实现计划

2026-10-20，基线`0bf37d2a422f51eec2955fb44611760ef75d868e`。
原M0–M2/P4/F19范围保持，依[M1_ASYNC_FINISHED_REQUESTS_NEXT_GATE.md](M1_ASYNC_FINISHED_REQUESTS_NEXT_GATE.md)
继续。**本批不关闭F19第1项、整族或第一阶段。** 不增加detector/backend/LeWM规则。

## G0实际证据与设计修正

上一检查点已复核。root在904稳定源码/ec1969…上运行一次有限公开查询诊断，
归档`model_async_request_body_history/baseline-diagnosis.json`。目标实例的Drive
ports、call chains及terminal→READ host route均完整；Drive owner→Create handle、
publication B→当前READ B普通copy未知，使post/expected均为None。兄弟实例另无host
route；4505/1048576预算未截断。不是缺时间预算或未观察到True分支。

三路只读审查确认：原RequestAssociation读的是**当前**request/state，现合同不保
Create后堆字段不变；StateAddress/ContentRead没有通用stored-Reference写入值→状态
版本→后续READ结果的关系。不能用host顺序或native no-reset偷代字段保持。

但是本问题可分成两个独立问题：

1. 当前predicate所见B是否就是已终结的同一个frame对象？
2. 这个B如何经过R的创建/堆字段写入/读取传来？

本批复用现有ValueDenotation(ObjectIdentity)补第1项的**显式条件身份分支**；
第2项自动stored-source恢复继续开放，不能把两者改名为同一个已完成任务。
旧无身份声明fixture的None断言保持正确，不为绿测发明字段不变或造READ身份。

## G1类型与公开合同

五类实体Operation / Value / StateLocation / Region / Resource不变。
身份比较是原ValueOccurrence与外部身份声明的派生关系，不是新核心节点或copy边。

新增`ExecutionIndex.object_identity(source, target, *, budget=4096)`，两参数为准确
ValueOccurrenceID。独立预算，fresh external context。内部复用同一shared预算供
body_state_history调用；没有新wire/schema或身份全局union。

返回最小合同：

- `inventory`始终保source/target两个原端点、原definition、denotation和resolved basis，
  缺/截断不减少分母；`match/status/gaps/cursor/budget`明确三值。
- 两Reference、准确当前occurrence、同实际process/run、两独立ObjectIdentity、
  相同`artifact_key=(sha256,schema,size_bytes)`、目录中均已注册且同ObjectID：
  `match=True`，`status=DECLARED_SAME_OBJECT`。不同artifact不推同一性。
- 同作用域不同ObjectID为本比较False，不将比较其它候选的正常不相等升级成整个
  模型错误。缺声明/目录、跨artifact、实际端点未解或预算不足为None。
- basis可能仍Unresolved；返回原basis和准确来源gap，不称runtime guard已验证。
  同ID仅是**所供声明成立条件下**的same-object。source/native/runtime/value身份与
  transformation权限均False。ObjectRef没有epoch字段，不能把裸id()/PID/URI当世代；
  世代必须由对象ID命名空间/原artifact明确区分。

原`pair`/copy_recipe/兼容校验保持原义。history在显式身份已知不同的候选上做局部
不相等比较；其它情况保ordinary True/False，只有ordinary None及充分身份声明才
新增`DECLARED_SCOPED_OBJECT_IDENTITY`依据。原copy冲突不被救回。返回identity receipt
与ordinary_binding分别列；普通copy仍可为None，不造“字段拷贝已证明”。

历史F仍独立要求真实BodyReturn/BodyRaise、commit全部当前state、准确Create/Drive
的原Uses/own results与call链、同native lifetime/no-reset scope及实际host顺序。
内容preservation未知不抹掉同frame历史F，但也不变成内容恒定/可cache证明。

## G2实施与所有权

- A：新`scar/ir/execution/reference_identity.py`及query.py一处公开薄委托；不改
  compatible/pair/codec/validator或其它查询默认语义。
- root：body_state_history.py集成独立identity依据，Create原port支持及完整原身份
  库存；计划/archive/串行执行/验收/Git。
- B：仅新增`tests/fixtures/execution_frame_identity_graphs.py`及
  `tests/unit/test_execution_frame_identity_history.py`，复用现有真terminal组合，不改
  旧fixture。每实例独立标识Create handle、Drive/publication owner、当前own READ；
  不能从期待结果或Create推造以后READ的身份。旧None case不迁移。
- C：独立只读复审，核三值/输入独立性/缺采/来源边界及剩余原单位。

所有作者FROZEN后root才运行任何Python/pytest/probe/compile。先在基线新增测试
复现缺失身份依据，再放行产品实现。作者不执行解释器或Git。

## G3有限验收

1. 原无denotation仍None；有独立身份声明的同实例历史条件性True、普通copy仍None；
   两实例各自产F，不能借完整兄弟，mutable preservation/native权限仍未知。
2. 同R的字段有真实WRITE，本次READ独立声明为B2时，旧B1 F不能用于它。不能从
   写入字段名、标签、Create/body或branch True猜本次READ值。
3. 缺当前READ身份/实际Use、缺Create/Drive原输入/当前state、不同artifact同名ID、
   同scope不同ID、目录删除刷新、budget1均有最小有区分力反例，不做全乘积。
4. 删RequestAssociation不等于删当前对象身份：R来源继续缺，但独立B身份可支持其
   F；删BodyStateCondition或其当前B支持才阻该历史结论。原源库存保持。
5. root一次直接受影响回归，独立复审、保存全部首败/源码/命令/JUnit与完整分母，
   自验报告后普通commit/push核远端SHA/clean/受保护仓库。通过后停止可选扩大测试。

## 后续原范围

通用stored-reference payload→版本→load关系、非finished native路径、graceful
AWAIT/HOLD两层close回复、illegal yield后的same/newR/finally/F/release仍须完成。
九族已接受/七族开放，P4 component/full、P5、M2原113/196及自动LeWM拆解不因本批
改变。第一阶段真正完成后再向用户讲解；这里没有可信自动变换或新加速比。
