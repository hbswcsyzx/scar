# 第一阶段核心集成：2026-10-26

状态：Implemented / 局部真实验证；**整个LeWM模型仍OPEN**。

本提交集中保存已有主要功能，未增加detector/backend，未修改LeWM或环境。

- 静态入口自动选择flat With、独立generator创建等已实现规则；193/243外部入口
  已有source恢复结果，49未支持、1resumable适配缺口。193不是新运行绑定数。
- 轻量CALL计划接入公共trace和source-entry入口。小型Python+GPU+OS程序实际完成，
  26.494s插桩时间，1H2D/3kernel；81原材料成员/8,745,427 raw bytes完成coordinates
  读回。7calls/4handshake/2scoped gaps/0instruction，reader无issue。
- 可选V1 collector registration正常读回5份closed metadata，0.469s；没有请求
  process-image receipts，不声称对应process-image membership。最初relative路径
  调用错误已纠正为原绝对URI，无capture修改或重采。
- native provider/descriptor查询已能返回11个实际端口出现和11条原EvidenceEdge，
  主树11.845s；尚需分片adjacency避免全扫描。
- 原ReferenceValue/ObjectIdentity旁的独立符号payload投影已正常读回；仅Inferred、
  UNKNOWN provenance，未推断输入版本/alias/copy/ready，也未改原主bundle。
- 跨函数查询新接状态依赖：同一真实LeWM调用的caller world Use→callee入口，
  以及2个NORMAL/19个RAISE可能world出口→各自caller完成结果。它们是静态可能
  出口，不是19次实际异常；不推断纯性、状态不变或细粒度写范围。

验证仅使用对应真实路径正常生产/读取与一次CLI查询，未跑大套测试、未重复episode。
状态查询exit0/30.440s，stored24,151,415B/decoded182,372,465B（含旧大型composition），
body解码及索引各2次，同会话复用。当前旧查询仍偏重，不称全局轻量。

主树原记录：

- `artifacts/experiments/lean_joint_cli_main_20261026/verification.json`
- `artifacts/experiments/lean_capture_cli_main_20261026/verification.json`
- `artifacts/experiments/source_normal_return_main_20261026/lewm-query-with-state.json`
- `artifacts/analysis/native_port_sidecar_full_20261026/main-occurrences.json`
- `artifacts/analysis/symbolic_native_output_20261026/main-query.json`

下一轮只推进三项功能：剩余通用source结构、native引用流邻接、共享context的publisher。
全链缺口按`docs/FIRST_STAGE_IMPLEMENTATION_PLAN.md`继续，不推进性能优化。
