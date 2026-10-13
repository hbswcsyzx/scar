# N1：程序类型与依赖核心

状态：开发中。起点：`e5b5548`。本门自行验收、保存报告并提交；随后继续 N2。

## 目标和范围

将 PROGRAM_TYPES 的结构、行为和连接类型落实为能验证完整小程序的图。
不新增 backend，不修改 LeWM，不把手工 IR 构造宣称为自动恢复源码。

N1 支持有限同步过程的显式基本块、分支、循环回边、普通调用、正常/异常出口。
状态通过区域/基本块参数显式传递；计算值按 SSA 定义与使用连接。使用基本块
作为 Region 内部控制记录，不增加第五种顶层实体。函数体可被多个 call 引用，
调用引用允许递归；结构 parent 包含不允许循环。

初期不支持异步 launch/ready 的完整合法性、autograd、隐式 Python dispatch、
动态位置创建/销毁和带异常 handler 的 invoke lowering。支持普通调用的区域
必须只有 normal 出口；带异常的程序可用显式分支/raise 出口表示。不能用缺失
关系当作纯性或优化授权。完成本门不代表 N2—N4 或整个 LeWM 建模通过。

## 文件与兼容

新增 `scar/ir/program/`，作为现有源码图和运行图待接入的规范程序核心。使用
独立 typed ID namespace，防止把旧 operation definition、slot 或动态值冒充
新节点。旧图继续工作，N2 明确适配；不直接改写旧 schema/报告。

- `ids.py` / `model.py`：强类型记录与局部不变量。
- `validation.py`：全图连接、路径可用性、状态传递、接口校验。
- `codec.py`：复用 record_codec 的严格 JSON，绑定 schema/version 并校验全图。
- `queries.py`：精确 producer/use、区域接口查询；不输出优化审批。
- 通用 fixtures 和反例位于 `tests/`，不放 LeWM 专用规则。
- `scar check-program graph.json --out report.json`：读取标准图 JSON 并验证，
  输出 WELL_FORMED/INVALID、实体计数和明确的范围；不执行输入、不审批变换。

## 固定接口（协作实现协议）

所有实体是 frozen dataclass。ProgramGraph 采用 tuple registry，解码不静默
覆盖重复 ID。ID 类复用 v2 Identifier：ValueID/LocationID/OperationID/RegionID/
BlockID/UseID，各用 `program_*` prefix。

```text
ValueKind = DATA | REFERENCE | STATE
ValueType(kind, data_type: str|None=None, location: LocationID|None=None)

LiteralOrigin(value: bool|int|float|str|None)
BlockArgument(block: BlockID, index: int)
OperationResult(operation: OperationID, index: int)
Origin = LiteralOrigin | BlockArgument | OperationResult

DataValue(id, region, origin, data_type: str)
ReferenceValue(id, region, origin, referent_identity: str|None=None,
               targets: tuple[LocationID,...]|None=None, selector=Footprint())
StateVersionValue(id, region, origin, location: LocationID)
Value = DataValue | ReferenceValue | StateVersionValue
value_type(value) -> ValueType

FootprintKind = WHOLE | INTERVAL | UNKNOWN
Footprint(kind=UNKNOWN, start: int|None=None, stop: int|None=None)
Stability = INTERNAL | EXTERNAL | UNKNOWN
StateLocation(id, label, extent: int|None=None, stability=UNKNOWN)

Behavior = COMPUTE | READ | WRITE | REPRESENT | MEMORY | TRANSFER | CONTROL | ORDER
UseRole = DATA | REFERENCE | STATE_CONTENT | STATE_ORDER
Use(id: UseID, value: ValueID, role=DATA)
AccessMode = READ | WRITE | READ_WRITE
StateAccess(location, before: UseID, mode, after: ValueID|None=None,
            footprint=Footprint(), full_overwrite: bool=False,
            reference: UseID|None=None)

ExitKind = NORMAL | RAISE
ExitPort(name: str, kind: ExitKind, types: tuple[ValueType,...])
TerminatorKind = JUMP | BRANCH | RETURN | RAISE
Successor(block: BlockID, arguments: tuple[UseID,...])
Terminator(kind, successors: tuple[Successor,...]=(), condition: UseID|None=None,
           exit: str|None=None, values: tuple[UseID,...]=())

Operation(id, label, behaviors: tuple[Behavior,...], uses: tuple[Use,...]=(),
          results: tuple[ValueID,...]=(), accesses: tuple[StateAccess,...]=(),
          effects_complete: bool=False, terminator: Terminator|None=None,
          callee: RegionID|None=None, call_arguments: tuple[UseID,...]=())
Block(id, arguments: tuple[ValueID,...], operations: tuple[OperationID,...])
Region(id, label, entry: BlockID, blocks: tuple[Block,...], exits: tuple[ExitPort,...],
       parent: RegionID|None=None)
OrderEdge(before: OperationID, after: OperationID)
ProgramGraph(root: RegionID, regions: tuple[Region,...], operations: tuple[Operation,...],
             values: tuple[Value,...], locations: tuple[StateLocation,...]=(),
             ordering: tuple[OrderEdge,...]=())
```

OrderEdge 在 N1 仅表示同步控制范围内额外的 must-before，不覆盖 GPU ready。
effects_complete 是输入图的显式声明，不由标签推定，也不是一个 proof。
full_overwrite 区分旧内容依赖与顺序依赖；声明必须与 WHOLE footprint 及 WRITE
模式一致。不依赖旧内容的写入用 STATE_ORDER，其余读取/更新用 STATE_CONTENT。
已知 footprint/selector 是同一位置坐标中的精确范围，interval 是半开区间，
允许空区间；UNKNOWN 不提供覆盖证明。引用经参数端口传递时不能缩小可能
target 集合或改变已知 selector/identity；无法验证的 call 引用返回摘要在 N1
必须保持未知，防止只有 REFERENCE 类型一致却把返回对象指向别的位置。

## 全图校验要求

1. ID/UseID 唯一；每个 op 恰在一个 block；每个 value origin 与 producer 或
   参数位置一致；Literal 只用于精确 builtin scalar DataValue。定义结果不重复。
2. 一个普通值只能在定义所在区域使用；跨区域必须走 call/参数端口。块内定义
   先于 use；跨块定义必须支配 use；分支合流逐 predecessor 传参。入口不可有
   incoming edge；循环使用独立 header 参数和回边，不展开无限动态实例。
3. 每块恰有一个末尾 terminator；jump/branch successor 数、bool 条件、exit
   kind/result type 正确。每个 block 均可从 entry 到达。
4. 每个 Region 的状态域由 entry 的 StateVersionValue 参数给出；其所有块都
   显式携带相同位置集合的状态参数。跟踪块内当前位置版本：READ 必须读当前
   版本，WRITE 后建立新版本。后续 access、successor 参数和退出状态不得倒退。
   所有出口必须传出这些位置的当前状态，不能丢失文件/日志等效果。
5. StateAccess 的 before use/after result 类型和 location 匹配；READ 没有 after；
   写入结果有新的 StateVersionValue。引用选择器/footprint 不可跨已知不相交
   目标；未知 alias 不能被当作已知无依赖。WHOLE/INTERVAL/UNKNOWN 分开。
6. 不同调用共享 body，但各有独立 use/results。call_arguments 与 entry 类型
   匹配，results 与 normal exit 匹配；状态调用结果推进 caller 当前版本。
   具有 raise 出口的 callee 在 N1 普通 call 中拒绝，等待 N2 invoke 接口扩展。
   普通 call 的每个 use 都须绑定一个实际参数。call/control 状态端口必须
   使用 STATE_CONTENT；只有被明确建模的全覆盖写可使用 STATE_ORDER。
7. parent 必须存在且包含无环；额外 order 端点存在、同区域且遵循必经控制顺序，
   不能用跨互斥路径的顺序边伪造依赖。
8. 校验不以名字认定操作纯净；未知效果可以入图，不能因此获得优化授权。

`validate(graph) -> tuple[ValidationIssue,...]`；issue 有 `code/path/message`。
`require_valid(graph) -> None`，错误抛 ValueError。`dumps(graph) -> str`、
`loads(payload) -> ProgramGraph` 均全图校验，JSON 使用固定 schema/version。
`ProgramIndex(graph)` 校验后提供 `producer(value_id)`（Origin）、
`consumers(value_id)`（tuple[UseSite(operation,use),...]）、`entry_arguments(region_id)`。
返回精确 use，`f(x,x)` 保留两个 occurrence。

## 验收节点

- **N1.a 结构与连接**：强类型、严格 JSON、重复 ID、错误 origin/ownership。
- **N1.b 完整程序**：输入 → 分支 → 读取/计算/写入 → 正常/异常出口，含跨区域
  调用、循环携带状态；图中所有使用和要求保留的状态可追踪。
- **N1.c 反例**：错位置、旧版本、未定义 use、跨分支不可用值、丢出口、错误
  alias、错误 call binding、伪造 order 都必须拒绝。
- **N1.d 类型与载荷无关**：业务标签不同、基础图结构相同的编码/写入 fixture
  进入同一类型/校验/查询路径，不假装真实视频库/torch.save 已被解析。
- **N1.e 集成**：`gates/n1.json` 映射上述测试；冻结 implementation commit 后
  重跑 gate，做一次整仓回归，归档哈希/失败与修复记录，再报告提交并 push。

根据反例允许调整字段，但必须同步本协议、测试与报告，不保留两套冲突事实。
