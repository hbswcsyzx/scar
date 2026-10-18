# P3 持续执行关联接口与图的连接

2026-10-18。依据[执行计划](M1_BODY_OCCURRENCE_PLAN.md)和原
[联合合同](M1_PROTOCOL_CONTRACT.md)。此文说明实现接口；完整验收另行记录，
不因文档存在就算P3或整个建模阶段完成。

## 1. 定义、发生和物理执行分别是什么

Operation是原代码中的操作定义；OperationOccurrence是一次实际或声明的运行
发生。RegionActivation是一份执行实例，ExecutionSegment是其中一段连续运行。
generator一次创建后可多次进入，同一个activation具有多个segment。每次驱动
是不同的原BodyDrive occurrence，不把同一个静态site当作同一次调用。

五类规范实体不变，数据流仍为producer→Value→有序Use→consumer。新增关系
只连接原事实，不复制SSA或资源图：

```python
BodyDriveExecution(drive, activation, entry, outcome, source)
BodyActivationOrigin(activation, creation, source)
```

drive/activation分别是自然键；entry/outcome/creation可为带run/process和明确
原因的Unresolved。缺一端仍检查另一端的已知矛盾。已捕获canonical BodyDrive和
body activation独立形成分母，删关系不使义务消失。

## 2. 从原图解析本次输入和出口

- Start：原InitialEntry及body.entry；capture从准确Create NORMAL handle的
  原CreationCapture Uses派生。未知origin保InstanceCaptureInput recipe。
- Resume：原BodyResume指定的landing和精确旧Suspend occurrence、ResumeIngress、
  新segment、真实temporal transfer。saved取旧发生的原Uses；current state和
  sent/packet取本次Drive的原Uses。
- 输出：本次segment的第一个Suspend/Return/Raise，与Drive实际selected source
  一致；原BodyDriveResult映射到实际driver landing。driver自带forward另列。
- 已捕获分支前缀约束剩余路径。静态A/B都可能发生，不代表已走向A的实际前缀
  还能选择断开的B；真正缺transfer、B仍可达时保gap。

每个原端口保留Use/ValueOccurrence、原binding recipe和source/formal定义。
状态比较原Location/当前SSA/实际路线，不比较跨activation的ValueOccurrence ID
来声称内容相同。没有记录outcome不表示实际发散，也不生成假NORMAL。

## 3. 身份与中间传递链

在原CFG/call/body copy recipes上准备一个派生predecessor索引。只取被声明body
关系使用的source/formal/owner/Create handle的ancestor closure，每条中间边检查
一次；保原ControlTransfer、UseOccurrence及关联记录作support。不为每次Drive
重扫全模型或枚举两两组合，不打开或保存Tensor数值。

只比较两端是不够的：Create H(A)→formal X(B)→owner Y(A)的中间边已经矛盾。
因此每条相关中间copy和每个body输入/输出/forward/owner都核已知声明：

- Reference在同精确artifact `(sha256,schema,size)` 中的不同ObjectID是冲突；
  相同ID只记声明相容，跨artifact或缺身份保gap。URI只是locator。
- Data同scoped VersionRef只记同逻辑版本；不同revision不直接推数值不等。
- 直接原copy指向另一个准确Create NORMAL handle时，即使没有ObjectID也可拒绝
  接错来源。该索引来自所有已捕获Create的实际NORMAL出口/原handle落点，
  不要求它另有origin关联；失败、缺transfer或缺handle不进入索引。
  任意不同producer root则不能直接推对象或数值不同。
- 同持续activation跨次的owner要核相容；创建缺采、换线程不能豁免已知冲突。

每次public query用原ExternalSnapshots刷新外部可变catalog，重建denotation及
copy compatibility；不把Index构造时的旧快照当永久身份。结果仍不证明native
source/value identity或变换合法性。

## 4. host顺序是另一种连接

合法端点分别形成Drive BEFORE→本次entry首op BEFORE、实际outcome AFTER→
Drive实际EDGE两条conditional桥。缺entry/path时可保有明确缺口的completion
配对桥，不能称完整捕获路径；缺首op、线程或实际edge则不造该桥。host返回
与GPU完成/visibility仍分开。

原CALL桥、body桥与实际local chains联合核因果环。实现只收有限桥端点、按
原visit-chain顺序排序并连接相邻点，再做Kahn；不对activation强制DAG，也不
枚举全部endpoint pair。循环恢复重复关联同一body是合法结构。

## 5. 公开query与预算

```python
index = ExecutionIndex(model, program, evidence_graphs=..., value_graphs=...)
view = index.drive_execution(drive_occurrence_id, budget=4096)
origin = index.body_activation_origin(body_activation_id, budget=4096)
```

view包含原drive/operation/association、activation/entry/outcome/segment/target、
inputs/outputs/forwards、instance、原outcome_candidates和带原证据的copy_support。
origin包含准确creation/handle/captures及关联drives。所有返回均detached。

有限query预算共享于binding投影、copy support遍历、instance及host-cycle摘要。
截断保完整inputs/outputs/forwards及count，未检查项compatibility=None、
check_status=NOT_CHECKED，cursor指明位置；host摘要不能在截断后称已检查。
准备/record/FK/原路径校验、fresh外部快照与detach成本独立报告，不混为预算内
遍历或工作负载加速。status只为DECLARED/MISSING/PARTIAL/CONFLICT等有限声明；
所有source/runtime/value_identity/transformation标记仍False。
`gaps`描述本条关联的局部缺口；`validation_gaps`保留fresh context的整体诊断，
包括缺外部artifact及未证native/source，不能因局部声明相容而隐藏这些限制。

## 6. wire、CLI和验收边界

两表自动选择Execution8；没有新表仍按既有能力选择1–7。显式新版空能力视图
沿旧规则允许。独立v7 golden来自旧`a740661`的真实call模型，不由新版encoder
伪造；旧case中原future8现验证支持，新增future9拒绝，原case身份保留。

只读命令接口：

```text
scar query-body-execution PROGRAM_JSON EXECUTION_JSON --drive CANONICAL_WIRE_ID
scar query-body-execution PROGRAM_JSON EXECUTION_JSON --activation CANONICAL_WIRE_ID
```

命令使用原strict codecs及上述query，不import或执行目标程序。不提供外部catalog
时如实保source/artifact缺口；报告不授native/runtime/优化权限。输出不得覆盖输入。
本门不增加detector/backend，不运行新的LeWM重型profile。O01–O16以独立标准验收；
P4/P5、原M2构造分母和完整第一阶段仍需完成。
