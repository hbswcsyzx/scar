# Await acquisition 原端口合同：D1 审查稿

2026-10-19，实施基线 `0bbc623`；范围与 A–H 分母依
[D0冻结计划](M1_AWAIT_ACQUISITION_PLAN.md)。**DRAFT_FOR_REVIEW，产品尚未解冻。**
本文解决规则本体与连接，不增加优化backend，不把声明图当自动源恢复。

## 1. 主体、分母及兼容

Operation / Value / StateLocation / Region / Resource 不变。输入、未检查候选、
合格 iterator、异常 packet、W、held B 都是原 Value/Use 端口的不同角色。
无新 producer、state SSA、phase、activation或code registry。

旧 profiles、旧字段和 Program1–22 字节保留；新增 closed 能力使用 Program23。
Execution8 的 canonical records/schema 不变。新 tags、profile、嵌套variant以及
新合同出现在旧 enum 组合的情况，都必须被 capability 检测，不静默由旧reader接收。

新增两个 profile：

| Profile | 原 subject | 固定义务 |
| --- | --- | --- |
| AWAIT_ACQUISITION_V1 | OperationSiteSubject(parent region, 原GetAwaitable op) | AWAIT_ACQUISITION：该op全部原N/R；独立input来源；成功iterator与失败packet消费者 |
| AWAIT_METHOD_IMPLEMENTATION_V1 | OperationSiteSubject(真实callee region, 原lookup op) | AWAIT_LOOKUP、AWAIT_CALL、AWAIT_ITERATOR_QUALIFICATION；各原stage全部N/R或准确bool分支 |

旧 `AWAIT_SITE_V1` / `COROUTINE_AWAIT_WRAPPER_V1` 保留已有helper解释；不拿它们的
result-adapter要求给只负责获取的 helper 伪造最终 StopIteration 提取。
显式 native wrapper 仍使用原真实 lookup/call/result 记录，持有关系在§4薄桥中表达。

fixed scope/subject 先产生源与阶段义务，再查 rows/expansion/link；删除全部附件不删
原denominator。未知源类别保所有适用可能路线与具体分类gap，不任选一个好来源。
actual结果或实际Drive不能用于反选expected来源。

## 2. 局部 acquisition 与真实展开

新增局部 contract（字段顺序固定）：

```text
AwaitAcquisition(
    operand_use: UseID,
    expected: ExpectedSourcePort,
    result: ProtocolResultPort,
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...],
    expansion: ExpandedAwaitCallee | StaticProtocolGap)

ExpandedAwaitCallee(
    lookup: ProtocolOperationRef,
    call: ProtocolOperationRef | StaticProtocolGap,
    qualification: ProtocolOperationRef | StaticProtocolGap)
```

acquisition仅附原 GET_AWAITABLE 的 INVOKE；input必须为该 op真实Reference invoke
Use，result为自己准确NORMAL Reference或RAISE packet。原全部当前state经原N/R
传递；不假定NORMAL=edge0、handle=result0或landing formal0。expected不能等于
该consumer自己的OwnedUse；可以是独立原formal、准确上游result或已有expected源。

有 expansion 时，parent op **本身**必须有该实现Region作为callee。三个ref的原
owner须在这个准确callee内，child rows留其本地scope；原sameRegion约束不放宽。
更深helper必须经原准确CALL/INVOKE输入输出逐层连接；没有逐层桥就保gap，
不能扫另一个旁支Region充展开。无callee的opaque获取保原N/R和未展开条件。
parent不在原callee之外再执行一套虚假的aggregate步骤。

lookup/call/qualification ref分别锚该原stage；N/R全集从它们的原operation派生，
不是 refs tuple 长度。真实lookup失败不需要执行call；只有原CFG/selected leg证明
后stage不可达才N/A。缺ref不等于该阶段不存在。

从独立expected求值来源解释native/self、iterable-generator/self及general协议三路。
原input在本次call/incoming上的copy/current/available和来源类别一起核：

| 已声明原来源 | direct input | general方法返回 |
| --- | --- | --- |
| COROUTINE | self可适用 | 不合格，失败路径必须保留 |
| GENERATOR_COROUTINE | self可适用 | 不合格，失败路径必须保留 |
| GENERATOR | 不能直通await | 可作为iterator |
| 已知非iterator原literal | 不可直通 | 不合格 |
| 其他/外部/opaque | 保具体分类条件 | 保实际资格检查及条件 |

类别结论仅在所给原程序与规则的声明层成立；exact native type、loaded flags/
code关系、运行实例仍分开未证。self语义是固定native原语的条件投影，不把新的
Reference结果武断加入全局普通copy/identity union。

## 3. 资格检查与合法失败

```text
AwaitIteratorQualification(
    input_use: UseID,
    expected: ExpectedSourcePort,
    result: ProtocolResultPort,
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...],
    branch: OperationID | None,
    accepts_true: bool | None)
```

input和result属于该原qualification operation；expected独立选本次未经检查的
candidate来源，通常是准确AWAIT_CALL.NORMAL或原相关merge formal，不能自证。

- branch=None、accepts_true=None：原INVOKE，准确NORMAL Reference表示接受的
  原candidate，RAISE是自己的packet。实际N/R与完整当前state仍从core派生。
- branch非空、accepts_true为exact bool：普通原READ/计算产生自己的bool，准确
  原BRANCH消费该bool；true/false哪条接受按accepts_true解释，其他边为失败。
  不造新bool，不把普通bool当iterator返回值；成功candidate仍是原input引用。

一般方法NORMAL返回不合格对象是合法事实。其后真实资格失败→本次TypeError/
构造失败packet→host/handler的图同样合法，不能全图拒绝这种正常异常行为。
已知矛盾是把错误候选/失败腿当成功iterator继续advance/body，或把别次正常值/
packet冒本次结果。单有Reference类型和方法NORMAL绝不授资格。

资格只在其原检查/选择点成立；callback后state变化、别次检查和旧求值不能充
当前检查。具体未理解的异常分类/外部行为保准确gap，不以UNKNOWN吞已知错接。

## 4. 非普通copy的 W→B 及实际驱动桥

在现有 `protocol_bindings` closed union 新增一类，不新增表：

```text
AwaitBodyLink(
    source: ProtocolOperationRef,
    advance: ProtocolOperationRef,
    drive: OperationID,
    projection: WrapperHeldBody | StaticProtocolGap | None,
    guard: ControlEdgeReference | None)

WrapperHeldBody(
    constructor: ProtocolOperationRef,
    expected_body: ExpectedSourcePort,
    body: OwnedUse,
    wrapper_read: OwnedUse,
    body_result: ProtocolResultPort,
    state_sites: tuple[ExistingAccess | InvokeStateOperand, ...])
```

`AwaitBodyLink.scope`是由source.scope派生的只读property，不在wire重复存scope。
自然键(source,advance,drive,guard)唯一；projection不是第二个producer或target身份。

source须是准确成功acquisition/accepted iterator端口或原native wrapper构造
NORMAL引用；advance是消费该iterator的原NEXT/SEND等真实协议步骤；Drive必须
经advance原callee链可达且保同caller/guard。actual B只从该Drive.instance Use
读取。不能先从actual B选一个恰好可达Create来自证。

projection=None只适用于有原直接/self/合格返回来源可解释的B：expected owner
由source producer及其独立expected来源派生，不表示UNKNOWN或普遍可copy。
外部普通iterator不必须有B；无原body路径不得伪造Drive或需终结的frame。

WrapperHeldBody仅描述native coroutine await wrapper持有关系：

1. constructor锚真实wrapper构造自己的NORMAL结果W，绝非B。body可在真实
   lookup.receiver，或准确native构造自己的body Use；expected_body独立绑定该B。
   必须核lookup/call真实关联，不能给零用户参数call伪加B实参。
2. wrapper_read为原getter/held-body操作的真实W input Use；constructor.W沿
   原call/CFG进入它，body_result为这个getter自己的准确body Reference结果。
   无原getter/ABI端口就是gap，不发明执行事件、硬编码访问地址或按唯一B补齐。
3. 再核body_result到实际Drive.instance的原路径/current state。expected_body与
   body_result之间是此固定native关系的条件投影，不是W/B普通copy或身份合并。
4. getter的当前state/N-R/可能失败仍从core与state_sites派生；state变化、错误
   constructor W、另一Create B、另一Drive/旧发生都不能补当前关系。

source/advance/候选body path库存先派生，再查link。删link保原missing job；泛型
iterator无可见body时保边界，不能为满足分母创造B或强迫所有iterator有B。
精确native解释仍为条件，不因FactRef相同就证明W/B或版本适用。

## 5. 统一求值来源与动态证据

内部派生resolver拟为：

```text
evaluated_sources(ctx, expected, actual: OwnedUse, choices=())
→ binding, cases, inventory_complete, gaps, cursor
```

每case保原recipe/caller/CFG、origin/Create/body/kind/current，全部case参与判断。
两个不同Create均产生普通generator时类别可一致，不能要求某一个Create对整体
must-copy为True；GEN/GENCORO混合不能一个好臂覆盖坏臂。
CALL结果只打开其准确kind/slot对应callee原exit Uses；多caller、循环/递归、
重执行、缺出口或opaque保具体缺口，不猜唯一可见来源。缓存仅本ctx，键含准确
expected/consumer/caller/guard及DIRECT_INPUT/GENERAL_RETURN角色，共用原预算。

动态视图是同一静态库存到原occurrences/selected transfers的投影；逐准确
CallActivation进入真实callee，逐BodyDriveExecution连持续B/segment。不按名字、
类型或单个可见candidate制造发生。缺采仍保source/leg/jobcount与cursor。
新的必要identity/copy端点复用原祖先索引与fresh外部context，不保存Tensor逐轮值。

所有 source_runtime / runtime_identity / value_identity / transformation 权限
保持独立，未证不授。准备/FK/snapshot/外部刷新/detach成本另列。

## 6. 冻结与实施纪律

D1独立复审核上述字段、三种原角色、早失败/资格失败、多来源和W/B关系；有真实
字段阻断先修本文，不在产品中悄悄选一种不同语义。精确冻稿SHA另存审查记录。
R须是旧公开接口真实缺口，失败夹具/API错误保原证据。N语言例不能冒SCAR测试。
之后分record/codec、静态resolver、完整同图fixture和P3桥独立拥有文件，root串行
执行；A–H任一必需格未过都不称本完整单位完成。原16组、P5/M2不随局部绿删除。
