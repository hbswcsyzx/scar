# C2D：创建、驱动与生命周期接口复审

2026-10-18，基线`012db08`。**Proposed：完整C2D字段未冻结、driver未实施。**
本文修订旧`model_resume_interfaces/review/driver-field-contract.md`的候选方案。
保留[C2B](M1_RESUMPTION_BODY_ACCEPTANCE.md)和完整C2.0/C2.4分母；不把一个新查询或
语言探针算作完整resumption。阶段顺序继续按[总计划](WHOLE_PROGRAM_MODEL_PLAN.md)。

## 1. 不变的核心类型与规范来源

不增加业务实体类别。Create、lookup、normalize、gate、body ingress、release仍是
Operation；参数/引用/协议载荷是Value，当前可变内容/生命周期是StateLocation，
body和driver是Region，物理承载/工作仍归Resource。Q/M不是新的计算节点。

实际值只由`Operation.uses/results`、entry/formal、completion/temporal参数定义。
附加合同只能引用这些端口，不能再存before/after world、capture值或可写verified位。
静态OperationID/RegionID不是对象、drive epoch或suspension generation。
版本化DriverRule也不能只凭方法名套语义：实际callable/receiver与实现版本的对应
仍须来源/guard证据。同名用户`throw`保留普通调用和实际effects，不能自动认作内置协议。

## 2. 必须分开的接口层

```text
Python外部调用/原始参数
   ↓ lookup / normalization / delegate / gate（实际CFG顺序，可回调/嵌套驱动）
实际body入口许可 + 当前状态 + 已交付值/packet
   ↓ 专用BodyDrive：Start(body)或Resume(Suspend,case)
body执行，止于本次第一个Suspend / Return / Raise
   ↓ 当前状态、body outcome、持久会话状态更新及真实引用释放
host outcome adapter → 外部返回/异常
```

接受外部请求、获得body入口许可、body实际执行、host正常返回、body完成、请求对象
完成、资源ready是不同事实。不能由名字、次数、相同type或一条正常边替代。

### 2.1 外部raw请求不等于body-delivered packet

修订候选为`RawRequestDefinition(value, kind, operands: tuple[UseID,...])`；操作只
用自己的规范Uses构造抽象请求。NEXT/CLOSE为0，SEND为1，THROW为1至3个Reference
端口，保留参数顺序、omitted和显式None。参数数量检查、警告、异常构造、traceback
校验是实际操作/失败，不因协议pack而消失。

body的`ResumeInput(THROWN_PACKET)`继续要求EXCEPTION_PACKET。原始throw参数的
规范化发生在哪条真实路径，就在那里用普通helper/INVOKE及最新后态构造packet。
不能统一前移：本机样例delegate.throw直接收到原始三个参数并产item，未构造该throw
请求的异常实例（三参数形式仍产生DeprecationWarning）；
普通fallback的异常类构造又能嵌套驱动同一generator。源码分支见
[genobject.c](https://github.com/python/cpython/blob/v3.14.7/Objects/genobject.c#L476)。
这两条是独立stdlib见证，未声称已实现SCAR adapter。

### 2.2 短命permit与持久session分开

短命body-ingress permit是当前driver协议执行中从指定gate正常边产生的私有Value。
它绑定实际owner、当时continuation目标及当前状态关系，只能沿规范本地端口转发；
不能普通escape、存入下一次host请求或冒充FRAME_CONTEXT。

**每个permit至多消费一次BodyDrive**；循环再次进入body必须重新取得许可或通过
另一个显式、已建模的续代操作产生新许可，不能复制旧claim。这个规则不是
“一次外部方法调用至多一个body ingress”：归一化/释放/lookup的用户回调可以
嵌套另一个driver epoch，嵌套操作及其返回后态必须留在图里。

异步request跨await保持的占用关系属于request/body对象的当前lifecycle state，
不是把旧permit保存起来。一个body的AWAIT handoff可以结束本次短步，但session
仍活动；同request继续、另一request被拒绝，以及ASYNC_YIELD后request完成而body
仍暂停，必须分别表示。占用更新通过真实owner/request引用和当前StateVersion/
StateAccess或native helper完成，不新建第二套持久token存储。

候选最小连接包括`RequestAssociationRead`：消费当前request实例及状态，正常结果
分别给出关联body引用与latent raw请求。driver entry本次scheduler/send请求与这个
latent asend/athrow/aclose请求是两个端口，不能按相同type或body code合并。

gate/许可字段仍须复审：request与body两层gate的parent关系、控制合流中的owner/
permit同步转发、状态写后许可是否仍有效，以及允许的helper使用位置。未冻结前
不实施新私有类型，不用一份gate标签替代这些规则。

## 3. Create、参数和同一实例的边界

Create在参数绑定/必要环境读取之后保存Reference，不执行body，也不保存旧world。
收敛后的候选保持简单：

```text
CreationCapture(formal: ValueID, source: UseID)
ResumableCreate(operation, body, function_object, captures, handle_result, lifecycle, rule)
BodyStart(body: RegionID)
BodyResume(suspend: OperationID, successor: int)
```

`formal`是非state body entry中的Reference端口，`source`必须是Create的真实owned
Reference input；该Python Create合同要求完整覆盖非state入口，不能拿协议值冒充形参。
默认值读取、tuple/dict pack和cell/environment lookup先有真实producer及可能失败；
没有这些actual时，自动绑定仍未完成，不能从source signature捏造值。现有
FunctionEntryLayout/EnvironmentInterface已经区分形参和各环境role，无需再用一个
CaptureOrigin/target union重复保存同一事实。函数对象及环境来源仍须准确连接；
同code不证明globals、defaults或cell引用相同。

旧`BodyStart(creation OperationID)`会强迫共享driver选一个静态Create，或为每个
site克隆driver。改以body选代码，每个Create仍保留自己的capture关系。不同site、
同site不同动态发生及同对象alias都不合并；实际instance选择哪个capture occurrence
依赖后续实例/来源证据，不能由候选集合或静态site推出。

普通CALL/INVOKE仍禁止直接callee=ResumableBody；专用BodyDrive不得改写旧
NORMAL/RAISE的语义。instance、permit和body动态输入各有独立owned Uses，唯一
actual列表引用原端口；不把已保存private frame/captures复制成driver的第二份参数。

## 4. 输入状态与本次outcome边界

本次输入按入口signature和LocationID连接，绝不把两个列表按偶然位置zip。
BodyStart接当前body state端口；Resume接指定case的真实inputs及保存槽关系。
callback/delegate已经写过的域须用其最新completion后态，不能回到Create/gate旧态。

现core的LocationID是规范静态状态域。body需要的域必须有明确current输入；缺失时
不能从instance名字伪造。driver多出的域则可通过每条outcome的独立Use保持转发，
不能冒充body producer。精确动态owner/selector或跨域映射仍属完整M1接口，普通
同Location不等于同实例，也不证明独占；不人为要求所有driver与body域数量相同。

### 4.1 当前可直接实施的派生frontier

对已验证body，选择entry或某个真实resume landing，从该root沿普通CFG走，首次
遇Suspend/RETURN/RAISE即收集并停止。**不跨Suspend的temporal successors。**
普通branch、INVOKE和cleanup路线均保守遍历，不按值猜分支。无可达outcome允许空；
有outcome不证明全部路径终止，也不证明实际运行会选它。

Suspend的结果签名只来自`exported,*handoff`，不公开saved frame/pending/context。
Return/Raise只来自真实terminal Uses；C1仅声明却被清理永久截留的exit不造结果。
结果集合按ID稳定排列只为查询，不是时间顺序。详见
[frontier组件](M1_BODY_OUTCOME_FRONTIER.md)。这是后续BodyDrive校验必须复用的
连接依据；不为候选driver另存第二份outcome图。

## 5. 引用释放、完成与观察边界

本机CPython3.14.7终结路径先标记closed/恢复caller context，再处理frame引用，
但body内覆盖/DEL也能在Attached时触发回调；Traceback又能保留已经结束的frame/
locals，使实际最终化延迟。这三种释放位置不能合并。
版本依据见[ceval.c](https://github.com/python/cpython/blob/v3.14.7/Python/ceval.c#L1835)；
八组本地断言及限制保留在新driver证据目录。

FrameRelease的合同只能是放弃/转移该owner的引用与全部当前效果，不保证对象已
free/finalize、无后续callback或GPU ready。普通finalizer异常的unraisable通道、
显式close失败与host adapter新异常分别保留；在所测终结frame清理路径中，完成
标记不能延到其可重入finalizer之后。这不使body内DEL提前关闭仍执行的body。
Created-close没有body入口但仍可能释放已绑定引用，不能捏造body Return。

若原native call作为opaque INVOKE，其completion已经包含内部释放和回调效果。
展开必须是同一调用的另一表示/关联，不能额外再执行一个release或把同一时间/
写入重复计量。现provider/native合同保持这条边界，未据本轮实现native expansion。

## 6. 有序实施与验收

1. **D0复审进行中：**修订以上已被反例推翻的假设；冻结gate/permit、request
   association/session阶段、生命周期提交的exact字段及关系固定点。旧提案不能
   直接实施，当前完整C2.0未关闭。
2. **Frontier依赖组件：**将§4.1接入已有ProgramIndex和唯一共享派生函数，正例/
   错入口/多cut/循环/cleanup/真实payload/private排除自验收；不变更wire或body规则。
   已通过517项组件及冻结`9f3d7e7`的3,549项全仓，C2D完整字段仍未因此通过。
3. **D1规范连接：**Create/raw request/association、专用BodyDrive与各输入/outcome，
   复用current SSA与helper INVOKE；旧schema拒绝新能力，不只交孤立records。
4. **D2阶段关系：**permit单次/owner同步转发、嵌套与无body路径、session保持/完成、
   lifecycle与release部分后态；反例优先，明确静态结构与runtime实例证明边界。
5. **D3全家族合同：**generator/coroutine/asyncgen/request及delegate/await/close/
   cancellation，用既有协议分册核对全部分母；公开接口、独立复核、冻结回归归档。

当前Observed是有界语言和已有IR探针，Inferred是它们约束的接口边界，Proposed是
新字段与实施顺序。完整driver不属于Implemented/Verified；没有新增LeWM规则、
detector、backend、Tensor快照或性能结论。完整第一阶段满足后才按用户要求停下讲解。
