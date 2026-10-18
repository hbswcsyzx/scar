# D1 codec / query / CLI 实施报告

2026-10-18；任务基线 `306a789`。本组件已实施、专属定向通过；不是完整 D1/M1 验收。
只改授权五文件；没有修改 model/validator/drivers/fixtures/其他测试/docs/gates，没有
git/commit、全仓、GPU、LeWM、安装、native capture 或新语言探针。

## 已实施

- `codec.py`：SCHEMA_VERSION=11，七张 driver 表能力检测；RAW 值及 exit/completion
  类型、BodyDriveTerminator 和 BodyDriveResult 均识别。raw-only 无 body、Create 后
  不驱动、完整 driver、request create/association 均可独立选择 v11。
- 新 term 使用 `kind=BODY_DRIVE`；新投影使用 `kind=BODY_DRIVE_RESULT`。后一 tag
  防止与同 shape 的旧 CompletionResult(index) 混读；旧 CompletionResult 仍无 tag。
  未修改共享 record_codec 或旧 wire variant。
- v1–v10 的 envelope 排除全部新表；typed decode 前在限定规范字段位置拒新 RAW/
  term/result marker，decode 后仍复核能力。v11 必须实际含新能力，不能仅靠空表升级。
  v2–v10 所有冻结 golden 字节保持；v1 保持既有迁移策略而非宣称重编码仍为 v1。
- `queries.py`：七表按真实 owner 查询；raw operands 为原序 canonical UseSite，
  已知零参数与未声明 recipe 分别返回 `()` / `None`。normal_result 按 owning INVOKE
  NORMAL projection index 找真实 landing Value，不以列表位置冒充 signature 槽。
- input bridge：Start state 按 LocationID；Reference 返回
  `InstanceCaptureInput(instance:UseSite,formal:ValueID)`，不猜某个 Create/site/对象。
  Resume saved 来源仍是原 Suspend UseSite，新 state/payload 是本 Drive 规范 UseSite，
  分别按 Location/slot 连接；不把 saved 复制进 driver actual。
- output bridge：outcomes 复用共享 body_outcome_uses；绑定从每条 source 的真实 public
  Uses 或 driver 的真实 forwarding Uses 派生。查询不改 producer；formals 仍是原
  BlockArgument，无新增实际值、运行时实例、物化、等价或权限结论。
- `cli.py` 仅 program summary：七表和 outcome counts，成功 validate 才给出
  driver_structure_validated。source/runtime/exclusivity/transform 标志继续 False，
  driver_lifecycle_verified=False。capability 判断复用 codec 同一检测函数。

## 实际定向命令与全部尝试

在 conda `lewm`，`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.`：

```text
python -m pytest -q tests/unit/test_program_driver_codec.py tests/unit/test_program_driver_queries.py
```

Python 3.14.7 conda-forge；精确 argv/version/exit/harness 时间各存对应 JSON。

| 尝试 | pytest 终态 | 原因/变化 |
| --- | --- | --- |
| initial | 46 PASS / 9 FAIL，1.39s，exit1 | 九项为同一诊断顺序：RAW completion type 注入旧非 INVOKE，record constructor 先报 only INVOKE，尚未到明确 historical capability 拒绝。没有错误接纳。 |
| corrected | 58 PASS，1.34s，exit0 | 新 RAW 早扫限定 values.protocol / exits.types / completions.types，旧 marker 在构造前拒绝；保留原断言。另补 Start/Resume input bridge 三正例。 |
| final | **64 PASS，1.51s，exit0** | 补 request create/association 正例、四种图 CLI counts/全部权限 False。无进一步产品修复。 |

全部日志保留：`initial.log/json`、`corrected.log/json`、`final.log/json`，未覆盖首败。
final harness wall-clock 2.1210711s；这是测试成本，不是任何 workload 性能或加速。

old schema 每版覆盖七空表拒绝、RAW value/exit/completion marker、term/result tag；
v11 覆盖 tag 缺失/错 tag/bool index、私有嵌套 mutation、空能力/缺表/自授证明拒绝。
输入/输出检查包含 canonical UseSite `is`、normal landing 物理顺序与 projection index
刻意不同、额外 driver state 直接 forwarding 和原 saved 不暴露为 public outcome。

v10 golden 由 root 从隔离 immutable `306a789c80ea7dd407b7fc88635056fa99fed1ad`
生成；本组件校验 proof generated_from_current_worktree=False 和 logical hash，
没有自己用当前 codec 生成 golden。

## 冻结文件指纹

```text
43e10faeaf8bb46728b03ae6b06760ddd4b816b5cd02817b83618b261d15eaa9  scar/ir/program/codec.py
2d31e31bdc9667bc52f632aa839301ed69ae3deaa2a10ba5b609deb3814379c2  scar/ir/program/queries.py
59467cd11d0f67bbaadc43c282395eebd76690b879d3a77c1d6aae7a2056eee8  scar/cli.py
adefc8f11bc18bfc869fbca6ab36507e3b1ab69f4e5d1516131dc2eb09b511c4  tests/unit/test_program_driver_codec.py
fedcb019438a32b49939e4689e45d2c9ed220da6429d8c201b8b7d6e65be277e  tests/unit/test_program_driver_queries.py
```

仍需 root 统一组件/独立审查/冻结回归与版本管理。public views 已在 queries.__all__，
按既有 API 习惯从 scar.ir.program.queries 导入，不把 records-only 包耦合整个 validator。
D2 commit/session/reference-release、D3 family/source/runtime、完整模型与自动全程序
建图仍未由这批 wire/query 实施完成；没有 detector/backend 或 LeWM 优化结论。
