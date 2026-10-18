# D1：从 Create 到本次 body outcome 的规范连接

2026-10-18；依赖 [D1连接合同](M1_DRIVER_CONTRACT_V2.md) 第1–3节；D2/D3仍开放。
本计划是下一批产品工作的顺序及自主验收分母，不是已经实现的 API。

## 1. 必须交付的完整路径

```text
已绑定参数/环境 → Create NORMAL instance
    → 当前 instance/raw request/state → final gate INVOKE
    → 私有 NORMAL landing 的唯一 BodyDrive(Start)
    → body 首 Suspend（不暴露 saved）

当前 instance/new delivered value/current state → 新的 final gate
    → BodyDrive(Resume: exact Suspend case)
    → body 首 Return/Raise/Suspend → 当前 driver 后态
```

同一 driver 支持多个 Create site 和外部 instance 接口声明。Create 之后即可返回
对象、永不驱动也是合法程序；不强迫每张含 Create 的图都有实际 BodyDrive。
全部关系仍是静态声明；真实 occurrence/guard/source 对应不在本门伪造。

## 2. 代码落实顺序

| 顺序 | 实际落点 | 交付和约束 |
| --- | --- | --- |
| 1 | `scar/ir/program/drivers.py`（拟新增）、`model.py`、`control.py`、`__init__.py` | exact records、RAW_DRIVER_REQUEST、typed drive terminator/result；ProgramGraph表与规范Use唯一归属。不是仅增加未接线enum。 |
| 2 | `validation.py`、`resumption_flow.py`、拟新增 `driver_validation.py` | 接原CFG successor、availability、state与typed projection；先普通结构有效，再检查driver合同；坏body不触发查询递归或崩溃。 |
| 3 | `codec.py`、`queries.py`、CLI现有program入口 | codec新capability完整检测；端口查询返回原UseSite，输入/输出关系只派生一次。旧版本无driver仍逐字节保留。 |
| 4 | `tests/fixtures/`、`tests/unit/`、原gate runner | 以下全部正反例及旧能力回归；冻结产品后单次完整回归、保留所有初次失败/修正、独立报告与版本推送。 |

基础设施直接复用，不新增通用 affine、request 历史状态机、Python 前端或 runtime
tracer。实现新term时 `first_body_outcome_operations` 继续沿它在所属body内的普通后继
走；它只在本body首次Suspend/Return/Raise停止，不能把嵌套drive认作本body终结。

## 3. 自主验收矩阵

| 范围 | 正例 | 必须拒绝/保留的反例 |
| --- | --- | --- |
| Create及normal结果 | 形参+完整环境Reference分区、原function_object source、真实normal handle；创建后不驱动。 | 缺/重capture、错误formal、state冒充Reference、normal/raise结果错接、未绑定默认值的捏造producer。 |
| raw/association/request创建 | 原参数有序Uses、四kind正确arity、显式None与omitted；request创建零body执行。 | THROW过早packet化、非Reference原参数、latent替代scheduler、凭code/site假定对象关联。 |
| gate→drive | 原owner/S/session沿独立edgeUses→formal→Drive；全域gate后态；同一个gate在循环里每次重新执行。 | 新结果冒充已输入owner、复用角色Use、旧state、normal landing插操作/多前驱、拒绝边假body、跳过gate的回边。 |
| Start接口 | 本地Create、两Create合流、外部instance声明同一body接口。 | 强制唯一Create、把Create时共享world作为启动时state、静态site当动态对象。 |
| Resume接口 | 明确Suspend/case和dynamic slots；私有SavedInput仍由body规范记录派生。 | 错body/case/slot/type、遗漏STATE/额外dynamic槽、复制saved/context到普通driver actual。 |
| body/current state | 按LocationID接本体子集，lifecycle可为driver域真子集，每个outcome显式转发driver额外域。 | 按位置交换域、缺当前域、仅覆盖lifecycle而漏gate其他域、为extra域捏造body producer；接口effects范围声明不授源码证明。 |
| source outcome | 首Suspend/Return/Raise各独占landing、真payload+handoff、空frontier、混合可终止/发散路径。 | 越过temporal边找远期Return、公开saved、错source/index/type、遗漏/重复source、多source先合流。 |
| 旧版与公开查询 | 新capability往返、规范UseSite identity、旧v1–v10及既有native/context/C1/C2B查询保持。 | 任一新table/type/term/result能塞进旧schema；解码吞字段、查询自授verified或transform。 |

索引、枚举、ID的exact类型与越界反例在各接口一起检查；不为每个同构字段机械堆
大量镜像测试。测试必须验证上述失效风险，组件数不等于自动建图/运行时证明。

## 4. Wire 与验证顺序的具体决定

- 新driver capability固定为 **schema v11**，不能仅以 `resumable_bodies` 是否非空决定。有Create
  无Drive、只有raw boundary、完整driver三类分别验；所有新标记都纳入旧版拒绝检测。
- 新 ProgramGraph 表名为 `resumable_creates`、`raw_driver_requests`、
  `async_request_creates`、`request_association_reads`、`driver_interfaces`、
  `final_body_gates`、`body_drives`。D2附加表不在本门冒称已冻结/发布。
- Create是已绑定后的抽象frame-create primitive，其invoke_arguments包含已产生的
  参数/环境References及当前state；它不是原Python CALL的显式参数表。源CALL的参数
  绑定、default/pack/环境producer仍分别建模，合成primitive不新增物理调用。
- 不再改变历史CALL/INVOKE的NORMAL/RAISE含义。BodyDrive专用projection的类型从
  successor.source的真实body Uses推导；不另存completion签名或调用参数表。
- records 和基础CFG检查先行，body/context/C1通过后复用共享frontier计算。不能在
  validate内部建立ProgramIndex（它会再次validate）；共享纯派生函数供双方使用。
- 固定入口角色copy沿真实edge actual→formal做有种子must分析；corridor内部是逐槽
  exact等式。原引用相同不证明内容相同，native guard条件仍需独立来源证据。
- 原full测试在产品改动前已通过，纯文档/设计探针不重跑。D1完整改动后先定向与
  组件检查；有实质剩余风险才扩测，最终冻结单次全仓，报告精确revision/source。

## 5. 明确后续门

D2接本门真实source边及端口，落实terminal commit/no-body/session/reference-drop；
D3核对完整Python family协议。M1还有资源instance/work/ready、location细化、
literal和occurrence/denotation等分母；不以D1通过宣布整个程序模型完成。
所有第一阶段项目满足后，按用户要求先停下来讲解，再进入自动全程序建图。
