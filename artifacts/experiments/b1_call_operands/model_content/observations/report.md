# Q observation 实施记录

状态：所属三文件实现完成、定向测试通过；可由 root 统一组件门验收。
这不是 R2.3 整体验收，也不是原生协议、可见性或 ready 的证明。

## 本次拥有的文件与最终 SHA256

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/execution/observations.py` | `8c8237c855680e78f6e1c256a30086105636c2af5ad6fb59958385840ed7d882` |
| `scar/ir/execution/observation_validation.py` | `eaae52e54664107ac7baa7aa5707fbf2a19be6e9b59346f0ce37040f563ff983` |
| `tests/unit/test_execution_observations.py` | `d48926e8d03302d564f83752073594ff2f52b97bcf39b9407b33be48317e288a` |

未编辑其他产品、测试或文档；没有 git、全仓测试、GPU 或 LeWM workload 操作。
本报告和尝试日志位于 ignored artifacts。

## 实现的关系

- 八种 records 均 frozen/slots，精确类型检查并重新核验嵌套 records；没有作者、
  已验证位、虚构 core operation 或 WorkTicket。
- 合同引用经共享 SemanticGraph snapshot resolver 核验 bytes/schema/hash/size。
  缺图是 gap；已供错误快照是 issue。RequiredOutput 必须准确属于合同 required_outputs。
- RequiredEndpoint 可使用任何明确 required=True 的 ContractFacet；不从 EXTERNAL、
  RNG 或其他 facet 名称推导端点。显式关系仍保留
  `contract_endpoint_protocol_unverified`。
- 已知 core endpoint 必须引用真实 RequirementBinding，并准确匹配 core requirement。
  无 core endpoint 使用 Unresolved requirement + ExternalEndpoint，不伪造 binding。
- ObservationRoot 复用 ProtocolInterval、原 ValueOccurrence、资源目标和 core 当前状态。
  已知 wrong run/process、旧 support、缺 FK、反向区间及错误 actual variant 拒绝。
  Unresolved anchor 只允许空 support；其 evidence point 不能冒充 canonical current 点。
- Region/operation-owned endpoint 可以在 owner 之后观察；不强制 sameop。
  跨 activation 的输出或绑定观察保留 pairing gap，不凭相同静态 ID 宣称对应。
- 协议/source 引用仅是条件声明；输出 slot denotation、native pairing、读取协议、
  内容稳定、可见性、ready 和 transformation authority 均未由本门证明。

## 实际验证

所有 Python 使用 `conda activate lewm`；每次仅运行所属文件：

```text
PYTHONPATH=. python -m pytest -q tests/unit/test_execution_observations.py
```

| 尝试 | 实际结果 | 说明 |
| --- | --- | --- |
| `attempt001` | 33 passed in 0.85s，exit 0 | 首次语法/导入/单元/组合运行，无先前隐藏失败。 |
| `attempt002` | 37 passed in 0.80s，exit 0 | 补准确 binding requirement、operation owner 较晚观察、缺 facet 和跨 run。 |

每个目录保留 command.txt、source.sha256、output.log、exit_code.txt。
第二次 37 项包含首次 33 项，不能相加为 70 个独立 case。
fixture 复用 `tests.fixtures.execution_resource_graphs.resource_execution_program`，
额外 operation-owned requirement 通过真实 ProgramGraph 元数据和新 snapshot 接入，
没有半套 CFG、假 ID 或手填 PROVEN 的正例。

正例包括无 work 的输出/端点/外部观察、required RNG/EXCEPTION facet、跨 activation
条件声明和 owner 之后的观察；负例包括精确 FK、错误 actual 类型、旧/非 state support、
反向区间、missing/nonrequired output、facet false/absent、跨 run/process 和变更快照。

## 上游接口及有界源审

按 root 审查修复了 ProcessTarget/ThreadTarget 同 run 但另 process 的 scope 检查；
对应真实外部端点负例进入首次测试。Unresolved anchor 非空 support 同样在首次运行前修复。
这些是源审发现后的修订，没有声称曾实测旧实现失败。

共享 helper 源审快照：

- `content_validation.py`：`9a262e278adb8ccbd642deb669ea79f6d527c9db425fd83f9633039bc4f9369f`
- `validation.py`：`49066eed09567850ae824fd8800b359be33f4c403d641e2fe117b0a786e63966`

`check_interval` 在已校验 exact records 下检查 FK、已知 scope/order，并为未知 native
区间保留 gap；`check_target` 仅校验目标 FK，Q 自行检查 observation/binding realm。
未发现这些 helper 在本次范围内新增的阻断；没有独立扩大 root content 源码审计。
曾向 root 报告早期 ContentEffect 注解/constructor 对 Unresolved 不一致，属于上游
content 文件，本次未自行修改，也不把该消息当成已验收的产品修复。
