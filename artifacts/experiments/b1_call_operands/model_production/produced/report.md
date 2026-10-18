# Write / produced validator 实施记录

所属三文件已经冻结，单文件最终 **41 passed in 1.53s**。
这是声明连接和固定前缀 profile 的定向结果，不是整个 P、V 或 M0–M2 验收。

## 最终所属源码

| 文件 | SHA256 |
| --- | --- |
| `scar/ir/execution/production_validation.py` | `c824c947a3ecf745b95096cdd6b69a529c2563ed02f6b951e261783ce4bb8c1e` |
| `tests/fixtures/execution_produced_graphs.py` | `751b40a5c3e5190c5bf08341dc7c68c4fafe76aed3cdae7fb50fba9546c79aa6` |
| `tests/unit/test_execution_produced.py` | `24733d0e3d0eea29438bb371ee13573a3b60c200dcc46088af1f583002a3b546` |

未修改其它产品、旧 fixture、文档或测试；没有 git/full/gate/GPU/LeWM workload。
所有 Python 使用 conda lewm。

## 实现

- `write_errors(ctx)` / `produced_errors(ctx)` 使用原 occurrence/Use/state/actual
  completion/placement 和 root source helpers，不调用 ProgramIndex/validate 递归。
- Work/Host/External writer 分开；Host INVOKE 用局部纯 resolver 检查原 state input、
  实际 successor/CompletionResult/formal/location，无须伪造 WorkTicket。
- StateProduction 拒 READ-only，核原 effect/current state/owner/run；ValueProduction
  保留原 Data/Reference output。State 的 frontier 为准确 index 或 explicit unresolved，
  Value 的 frontier 必须 None/NotApplicable，不造 state frontier。
- SourceEdgeRef 原 FK/关系及 same-bundle 原 version/materialization 与 placement
  相连；换同 bundle 另一原 mat/version 拒绝。Cross-artifact 不比裸 ID，仍保留
  source/native join 和 physical content/version 未证 gap。
- 固定 `scar.native.byte-prefix-write` + schema_version=1，只有 stage/requested_bytes/
  written_bytes；闭合字段、exact 非 bool 非负计数，written≤requested。
  最初口头草案字符串含 `/v1`，实施已按 root 冻结计划统一为无 `/v1`，未保留双解释。
- Prefix 只解释同 exact VG/allocation、rank1 uint8/stride1/同起点的原 selectors，
  比较原 shape 与解析 count，并复用 G 核实际区域在原 mat 内；未知布局不猜 bytes。
- 原 Outcome/ticket/frontier/effect 精确匹配；ProviderFact result 必须指原 raw artifact
  的 `#L{line}/metadata/scar_native_result`。Data Literal exact int 可与 written 核对；
  非 literal/bool 等保留结果未解析 gap，FactRef 从不单独证明 native success。
- COMPLETED 不升级 whole；FAILED/CANCELLED 保留准确部分，不授 quiescence/ready。
  解析结果保存在 ctx.resolved_writes/resolved_produced，返回原对象及各条件/gaps。

## 全部定向尝试（原样保留）

命令和所属/上游依赖 SHA 逐次保存在 attemptNNN。所有运行只含
`tests/unit/test_execution_produced.py`；attempt002 起另存 JUnit 属性。

| 尝试 | 结果 | 原因/变化 |
| --- | --- | --- |
| attempt001 | 33P/1F，1.39s，exit1 | 本模块在已诊断 missing HostWrite FK 后继续 activation lookup 导致 KeyError；已修为不继续使用该缺失 operation。 |
| attempt002 | 35P，1.41s，exit0 | 修前项；加真实 OS positional write 见证。 |
| attempt003 | 38P/1F，1.42s，exit1 | 新测试把 LiteralOrigin(True) 错标 builtins.int，core constructor 正确拒绝；fixture 改准确 builtins.bool，非产品漏检。 |
| attempt004 | 39P，1.37s，exit0 | ValueProduction Work output/None frontier、literal4/5/bool 已验证。 |
| attempt005 | 41P，1.53s，exit0 | root 同意补 same-bundle source version/mat 核对及两项真实 source-bundle 组合。 |

这些是递增/重复子集，不能把通过数相加为独立建模覆盖率。

## 真实 CPU/OS witness 的精确界限

在测试独占 tmp_path 的 8-byte 文件上，实际 `os.pwrite` 请求4、返回4，之后 wrapper
受控 raise；最终 bytes 为 `abcd....`。原 descriptor 在 finally 关闭，未动外部文件。
JUnit 保存：desired_output_bytes=8、native_requested_bytes=4、native_returned_bytes=4、
actual_file_hex=616263642e2e2e2e、host_completion=RAISE、native_outcome=COMPLETED。

同一测试把实际计数接入 canonical INVOKE 的 RAISE traversal +独立 COMPLETED work
Outcome+raw inventory+原4-byte selectors。它证明这条受控路径的 native write 完成
不会被后续 host raise 抹去；**不是 syscall 8→4 short write，也不是 OS 原生 FAILED
partial write 的普遍证明**。原 ProgramGraph/source/native 关联仍是条件声明，authority false。

## 当前证据边界

没有增加 producer/SSA/state/materialization 或新 backend/detector。由来源枚举完整
writer universe、stage 去重/invalidators、整读区间有效性和 visibility 由 root 及后续
P/V 对账；本模块始终保留 native/source applicability、state→content、capture 权威缺口。
后续 cross-author review 单独保存，不把本代理自己的 validator 当独立自审通过。
