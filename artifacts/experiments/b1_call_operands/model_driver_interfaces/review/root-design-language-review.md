# C2D / C2F 主稿事实与语言边界复审

2026-10-18。只读 `docs/M1_DRIVER_INTERFACES.md`（本次157行）、
`docs/M1_BODY_OUTCOME_FRONTIER.md`（本次48行），核对既有 lifecycle 八组 JSON/log、
另一 agent 的 claim-lifecycle 三组日志/报告和 root 已有 frontier 设计 probe。
本轮没有执行新程序/测试/采集，也没有修改产品、测试、文档或其他报告。

## 结论：本文事实层面没有 blocking；不是 C2D 完整签核

Observed/Inferred/Proposed 没有实质混用。driver 首段、§6（143–157行）明确字段
未冻结/未实施；frontier 首段及40–48行明确实施中、派生组件不等于 driver 完成。
未看到把3,542项旧回归、设计 probe 或本机小程序当新查询/完整C2D验收。

### 证据归属与结论范围

- **driver §2.1:40–45**：raw delegate 三参直传、fallback 异常构造可嵌套 next，
  与另一 agent `claim-lifecycle-probe.raw-throw.log` 第1/3组一致；不是本人的八组
  lifecycle probe。该报告合计3组，包含 async request lease；主稿没有合并计成
  本人八组或宣称所有 rawThrow 路径已测。
- **driver §2.2:49–70**：短命 permit 至多授权一个直接 BodyDrive，是 Proposed
  规范；一个外部方法中可嵌套另一 epoch 的语言观察不被否认。跨 await session
  的占用保留在 owner/request 当前状态，也没有被当作可存活旧 permit。
- **driver §5:126–139**：本人八组支持所测 terminal 清理 caller-context/CLOSED、
  body rebind/DEL 的 Attached 回调、traceback 延迟保留与 Created-close 无 body。
  opaque call 已包含内部释放效果时不再执行/计量一次，措辞正确。普通 finalizer
  unraisable、显式 close 失败和 host adapter 错误没有被合并。
- **frontier 8–22、31–38、42–48行**：止于首个 outcome、不过 temporal edge、普通
  CFG 保守遍历、空 frontier 不等于无效果/必发散，以及稳定顺序非时间顺序均自洽。
  root JSON 是8个入口/无完成设计情形加1个签名检查；主稿未称9个driver产品测试。

八组只能说明 CPython3.14.7 这个有界 harness。尤其 asyncgen await 暂停时的
AGEN_RUNNING、unraisablehook 的部分 context 是打印观察，并非每字段皆有独立
assert；主稿没有越界称全面断言。resurrection、周期GC、其他解释器/版本、线程/
并发、OOM、shutdown、trace/profile干预、任意callback或完整request×状态未覆盖。
这些限制继续以 `lifecycle-language-review.md` 与原始JSON为分母，不由本文签核。

## CreationCapture：表达能力与前端缺口必须分开

**driver §3:78–89 的修正合理。** `formal: ValueID` 可精确定位 FunctionEntryLayout
的形参 Reference，也可定位 EnvironmentInterface 的已有 Reference 端口；已有
分区承担 role/slot 信息。`source: UseID` 可以引用已读取 default、已pack tuple/dict、
已获取 cell/globals 等实际 producer 的结果。不需要再镜像 CaptureOrigin/target union
才能表达这些值。源与目标分属两Region的连接需要声明校验，不是第二份 producer。

旧 `bind_call()` 未自动 materialize default/pack/environment，缺的是相应前端产生
值与接线；它不等于 core 没有能力表示那些已绑定 References。主稿86行准确描述了
这一界限。BodyStart 改为 body 选代码而保留多Create来源（91–94行），也没有据此
证明实际 dynamic instance 来自哪一个 occurrence。

**字段冻结仍 OPEN：** captures 的准确完整不交覆盖、source ownedness/Reference
类型、function_object 与环境来源、Start 当前状态、permit/owner同步转发及消费/
session固定点仍待 exact API/validator。不能仅凭本文认可这种表示就算这些检查已实现。
§3:84“任一非state端口”在冻结时须与前文“保存Reference”一致：Python函数 entry 的
Reference 端口可完整覆盖；若通用 body entry 有其他 Data/Protocol 端口，应明确
profile/分区和各自来源，不能不检查种类地全部纳入 Reference captures。

## 两处可采用的最小措辞收紧（不构成产品/架构 blocking）

1. driver **第134行** 原句：
   `完成标记不能延到可重入finalizer之后。`
   建议：`终结frame清理的closed标记不能延到其可重入finalizer之后。`
   上下文已区分body内DEL，但加限定能防止读者把此句用到仍在运行的局部覆盖回调。
   本人第5组正好证明那时应保持 RUNNING，而非预先完成 body。
2. driver **第42行** 原句：
   `本机delegate.throw可直接收到原始三个参数并产item，未构造异常。`
   建议：`本机该delegate.throw样例可直接收到原始三个参数并产item，未构造该throw请求的异常实例。`
   这避免被误读为所有 delegate 实现均不构造，或连 DeprecationWarning/其他内部
   异常对象都未创建；三参 probe 实际记录了 DeprecationWarning。

除此未发现需修改的具体事实错误。此结论仅限两份稿件的事实和边界；C2D.0字段
仍未冻结，frontier本轮产品实现/验收不属于本次只读审查，完整C2D/M0–M2继续开放。

## 本轮并发改稿的限定复核

落盘报告后再次只读看到 driver 已增为159行：第84–85行明确了非state Reference
覆盖和 owned Reference input；§5也已将完成标记限定到所测终结frame清理，并明确
body DEL 不提前关闭 body。因此上面这两项表达范围已在新稿澄清，保留原审阅文字
作历史，不作为未关闭缺陷。raw delegate 的样例限定仍可作非blocking措辞收紧。

该次主稿 SHA-256 `42459a741f6c6ed393df2d674159711faa607b2ee891b93a409fdfd00fedf415`，
frontier SHA-256 `a6f1d50baac1193bd20ea4ae42820d7aa42c85a05a4acd11a530b664a3b4b934`。
没有新增实验；不因此改变 exact字段/产品/全模型尚未验收的结论。
