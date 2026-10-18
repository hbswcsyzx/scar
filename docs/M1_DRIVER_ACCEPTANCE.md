# D1：规范 driver 连接组件

2026-10-18；设计基线 `306a789`。**已实施，671项组件检查通过；冻结全仓待完成。**
依据[连接合同](M1_DRIVER_CONTRACT_V2.md)第1–3节及[实施矩阵](M1_DRIVER_IMPLEMENTATION.md)。
这不是自动 Python/LeWM 建图、runtime adapter 或优化发布。

## 1. 实际模型与实现

五类核心实体保持。新 records 是 Operation/Value/State/Region 的接口关系，不是另一张
可修改的图。`drivers.py` 的七张 ProgramGraph 表记录 raw 请求、已绑定的 Create、
request 创建/关联、driver 入口角色、final gate 与 BodyDrive。

- Create 是已绑定后的抽象 frame 创建步骤：形参/环境引用已各有 producer，结果来自
  INVOKE 的真实 NORMAL 槽。它不是源 Python CALL 的原参数列表，不执行 body。
- gate 使用原 INVOKE。NORMAL 产生全部 driver 域后态，并经独立 edge Uses 转发原
  owner、scheduler、session、delivery；其私有 landing 只含配对 BodyDrive。
- BodyDrive 是专用控制 terminator，显式区分 Start(body) 与 Resume(Suspend,case)。
  没有可保存/复制的 permit；body 仍不能被普通 CALL/INVOKE 直接调用。
- 输入按 LocationID/ResumeSlot 连接当前状态与本次 payload。Start 的非state输入是
  当前 instance 的 capture 接口；Resume saved 仍由原 Suspend.saved 派生。
- 每条 driver outcome 指向本次 first frontier 的具体源操作。签名从源 Uses 派生，
  Suspend 只公开 exported+handoff。各 source 独占 landing；不越过下一次 Suspend。
- lifecycle L 可以是 driver 全域 D 的真子集，但 gate 两条 completion 必须给出全部
  D 后态。body 只消费自己所需域，driver 额外域逐条显式转发。

`driver_flow.py` 是共享纯派生函数；core validator、driver validator 和查询复用它，
没有在 validate 中构造 ProgramIndex 或另存 producer/actual/outcome 签名表。

## 2. Wire 与公开接口

新能力使用 schema v11。原 v1–v10 没有新能力的 wire 保持原字节；新表、raw value/
exit/completion type、BODY_DRIVE terminator 和结果投影不能塞进旧版。
BodyDriveResult 的 wire 显式标记 BODY_DRIVE_RESULT，避免其 `index` 字段被旧
CompletionResult 的同形记录悄悄接纳。旧 CompletionResult wire 不变。

v10 golden 独立取自冻结 `306a789c80ea7dd407b7fc88635056fa99fed1ad` 的 git archive，
隔离 cwd/PYTHONPATH 生成，确认导入的 codec 是历史 v10。原始文件为34,717 bytes，
不是从本次可变 codec 生成“期望值”；命令与源/hash证明一起归档。

```python
from scar.ir.program.codec import loads
from scar.ir.program.queries import ProgramIndex, InstanceCaptureInput

index = ProgramIndex(loads(payload))  # 完整校验声明图
index.creation_bindings(create_operation)
index.drive_input_bindings(drive_operation)
index.drive_outcomes(drive_operation)
index.drive_bindings(drive_operation, source_operation)
```

这些方法返回原 UseSite 或 instance-frame 来源 recipe。外部 instance/多个 Create
不猜唯一 creation occurrence；Resume 不把 saved 私有槽复制成 driver actual。
查询 views 从 `program.queries` 导入，保持基础 records 独立导入的原有边界。

`python -m scar.cli check-program graph.json` 检查 wire/结构，不执行目标程序；
driver_structure_validated 只指本门的声明连接。driver_lifecycle、body_source、
body_runtime、body_exclusivity、body_driver_verified、transformation_authorized
仍为 False。

## 3. 自主验收与发现的问题

组件门：`gates/m1_driver_interfaces.json`。覆盖 records、完整声明路径、正/反接线、
v11/旧版拒绝、输入/输出查询、CLI及原C0/C1/C2B/frontier/native回归。

主要正例包括：Create无后续drive、external/local Start、两Create合流、Resume值与
packet、request创建/关联、L真子集和额外driver域、多source、C1/INVOKE、混合及完全
发散。负例覆盖缺捕获、错normal口、latent替换scheduler、伪造owner、旧state、插入
操作、错target/slot/source、state位置交换、漏outcome和旧wire偷带新能力。

原始尝试在 `artifacts/experiments/b1_call_operands/model_driver_implementation/`：

- records首败是测试把正确的ValueError误写为TypeError；修正测试预期，不放松构造器。
- wire首败是旧record构造错误先于historical能力诊断；改为限定字段位置提前识别新能力，
  保留旧版严格拒绝，未弱化断言。
- 独立审查发现raw pack可同时声称WRITE/MEMORY/TRANSFER而仍作为纯constructor通过。
  已限制其非空行为集合为COMPUTE/CONTROL/REPRESENT的子集；真实读内容/分配/搬运/
  写入/同步在外部操作表达，仍允许该抽象操作具有多个合适标签。修前/修后复现均保留。

本门综合组件13项标准全部PASS，671个唯一test case；415源文件指纹前后一致：
`4d1b28511b8005829d87349fd81a859ef4225af81c810f1641068fa3272066a4`。
最终组件耗时9.142s，报告为 `component/final.json`；首个671项通过记录也保留，最终
只规范化一个测试文件的末尾空行后重验，以绑定准确源指纹。独立审查终态没有剩余的有界实现
阻断；报告哈希只标识修后的源码，不能拿来绑定修前进程早已加载的模块。原始修前/
修后结果均保留。冻结全仓结果待归档后在此更新，
不沿用旧3,549项回归替代本次新代码验收。

## 4. 没有因此证明什么

typed rule/有哈希provider位置不是运行时guard已执行。静态Create site、Reference
端口、同Location或候选来源集合不等于实际对象/activation/generation，更不等于
Tensor内容版本相同。有限frontier不证明branch可满足、must-return、无effects或dead。

D2终结commit、no-body finish、session更新、frame引用放弃及相位组合未在本门实现。
D3全family协议、source恢复和实际native/运行证据仍各自需要验收。完整C2D、M0–M2
与第一阶段仍未完成；不授reuse/hoist/delete或任何变换，没有新的LeWM加速比。
