# P3：持续 body 的运行发生与原端口关联

2026-10-18。基线 `a740661`，上一门为[完整P2声明矩阵](M1_GENERATOR_MATRIX_ACCEPTANCE.md)：
修复原预算不稳定缺陷后，冻结`bd673cd`的5,676回归通过。上一目标回合有产品修改、
真实失败定位、修复与验收归档，属于有实质进展。原失败不覆盖，整体目标仍未完成。

本门落实[已冻结联合合同§3–4](M1_PROTOCOL_CONTRACT.md)，不重新发明程序图或
缩小为record形状检查。完成P3后仍有P4/P5、原113构造/196字段与完整M0–M2总验收。

## 1. 模型中补哪条关系

```text
ResumableCreate的实际NORMAL handle（或明确外部/缺采来源）
          ↓ 原ValueOccurrence与原Use路线
同一持续RegionActivation ← 多次BodyDrive的原instance Use
          ↓ 每次分别选择
原InitialEntry / 精确旧Suspend occurrence→ResumeIngress
          ↓ 本次ExecutionSegment及实际ControlTransfer
本次entry→首Suspend/Return/Raise
          ↓ 原BodyDrive source/selected edge与原landing
当前host消费者
```

核心五类实体和原SSA不变。运行发生仅增加两个自然键关系：
`BodyDriveExecution(drive, activation, entry, outcome, source)`，
`BodyActivationOrigin(activation, creation, source)`；字段严格依联合合同。
不新增association ID、phase变量、captured value表或第二套world identity。

同步CallActivation每次关联一个新callee frame；持续body则一次activation可以
被多次Drive。不同片段可换线程，但本次Drive与其已知entry/outcome必须同线程。
因此不能将CallActivation的全activation线程检查或activation DAG直接照搬。

## 2. 原事实和复用接口

| 已有事实/接口 | 本门职责 |
| --- | --- |
| ProgramGraph BodyDrive/BodyStart/BodyResume、原ordered Uses/state | 精确解析本次静态目标和原输入，不按名字/类型猜。 |
| ProgramIndex.drive_input_bindings/drive_bindings、原first-outcome frontier | 每个context准备一次；Start capture、Resume saved/current、输出/forward均保原recipe。 |
| ExecutionModel occurrence/visit/segment/transfer和derive_flow | 复用实际路径与当前定义检查，不再造动态SSA。 |
| CallActivation及原host order | 保原同步规则；新增body的两条conditional桥，再联合检查实际occurrence因果环。 |
| ValueDenotation、ObjectRef、VersionRef、ExternalSnapshots | 每个binding检查已知矛盾；query刷新外部证据，不信构造时可变catalog。 |
| 原strict执行codec与独立旧golden | 新能力选Execution8，旧1–7范围/bytes保留；无新关系保持旧family。 |

## 3. 必须验收的完整分母

| 编号 | 所需正例和错误/缺采反例 |
| --- | --- |
| O01 | 原drive/activation自然键、strict nested records；非法kind/FK/重复键拒绝。 |
| O02 | 同一持续activation先Start再Resume；多body实例与同code不同activation不混。 |
| O03 | Start是准确InitialEntry及entry block；旧loop回访/CaptureIngress不冒准确入口。 |
| O04 | Resume选原BodyResume landing、精确旧Suspend occurrence/代次、同activation、新segment及实际temporal transfer。 |
| O05 | entry/outcome分别核已知FK/region/run/process/thread；未知一端不豁免另一端已知矛盾。 |
| O06 | 本次segment中的实际首出口、原frontier及选中的BodyDrive source一致；多个首出口/更早出口/捕获相反路径拒绝；断采保gap。 |
| O07 | entry、segment和outcome不能被两次Drive同时认领；不同片段分次换线程合法。 |
| O08 | Create是准确ResumableCreate occurrence的NORMAL handle；RAISE来源/别的body/多实例误接拒绝；外部/未知origin保recipe。 |
| O09 | 每个capture/saved/delivered/current-state/output/forward按原Use/ValueOccurrence映射；缺binding不删原端口，旧state/错slot/错来源拒绝。 |
| O10 | 同artifact scope的不同ObjectID拒绝；相同ID只相容。Data同scoped VersionRef只声明相同版本，不同version不直接推数值不等；跨artifact/缺身份保逐bindinggap。 |
| O11 | 同activation多次Drive的owner与Create NORMAL handle之间逐pair相容；不能仅核每次drive内部连线。 |
| O12 | 两端都缺仍保静态input/frontier分母；缺relation仍保每个已捕获BodyDrive项；空frontier不造completion。 |
| O13 | Drive BEFORE→实际entry首op BEFORE；实际outcome AFTER→Drive实际EDGE两桥分别核本端证据，缺一桥不抹另一桥；partial completion support明确缺路径。 |
| O14 | 原CALL/body桥与实际局部CFG联合occurrence因果环拒绝；正常持续恢复合法；有限endpoint/local-chain压缩，不能activation DAG、逐drive全图扫描或allpairs。 |
| O15 | 公开两query detached、共享预算/cursor、每次fresh外部快照；缺采/截断不记VERIFIED，准备/校验成本独立报告。 |
| O16 | Execution8与v1–v7独立golden；旧case/fixture守恒、CLI及受影响资源/content/host order组合，保留所有原失败。 |

## 4. 自主关卡与分工

| 关卡 | 完成条件 |
| --- | --- |
| P3-A 接口与建模复核 | 三路实际源码审查；确认复用接口、字段/自然键/边界；发现实质冲突先修合同并说明，不为了已有代码掩盖。 |
| P3-B records/原连接实施 | records/codec、canonical组合fixture、共享resolver/validator/query、逐bindingfresh identity和host桥/因果环全部落实O01–O16；不能只通过表结构。 |
| P3-C 定向与独立审查 | 每条分母有真实原图正反例与具体code/gap；修前失败、命令/输出/hash保留；解决审查阻断，不重复无意义测试。 |
| P3-D 组件与冻结 | 统一最终focused→组件所有标准→干净提交→一次完整pytest；所有作者停写、无并行SCAR测试/工作负载。失败留证再审，不自动重试。 |
| P3-E 守恒与发布 | 只读manifest/source/case/fixture/保护目录核验；报告原范围，commit/push；P4/P5及完整第一阶段仍保原分母。 |

A负责records/model/codec及其测试；B负责canonical组合fixture/语义反例；C只读
审查模型与实际连接；root负责共享resolver、validator/query、host顺序集成和统一
验收。只修改独立worktree，继续使用lewm conda；不升级环境、不动原LeWM/SCAR。

## 5. 明确边界

本门是运行关联的强类型接口与supplied-model校验，不是自动runtime adapter。
不以同code、同ValueID、同类型或重复node推instance相同/结果可复用。不新增
backend/detector/LeWM业务规则，不运行重型LeWM profiling，不报告新的加速比。
整个模型完成前不以测试计数代替覆盖率。完整M0–M2完成后先向用户讲解的停止点保留。
