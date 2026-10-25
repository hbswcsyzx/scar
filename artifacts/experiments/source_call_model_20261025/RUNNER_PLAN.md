# 最小 kwargs 原 body 门（尚未运行）

实现树固定为 `/home/zyf/AAA/scar-worktrees/source-call-model`；base754574ca 来自 root 提供，
未执行 Git。运行环境为 conda lewm，`PYTHONDONTWRITEBYTECODE=1`，PYTHONPATH 仅此新树。
main 全部原输入只读；这份计划不是已建 runner/freeze 或运行许可。

选择原 `exact-ast-frontiers.json` 中同时满足 Call、keyword.arg=None、无 Starred positional 的
rows，按准确 source span/fingerprint/SG Call/output 机械重核。应得到 sequence4/5/10/12，
两文件、四个原 body、原权重5 calls；同 span Expr/Call不重复。名单/函数名不进入生产规则。
当前 inventory 不同源或对应 SG/source 不唯一即停；已有相同 source/producer/capability 的
accepted body 先复用，已经成功的 tuple body不 lower。每个必要 body只尝试一次，失败不自动重试。

小输入根均取绝对 main URI：

- `.../artifacts/experiments/first_stage_source_frontend_automatic_20261023/exact-ast-frontiers.json`；
- `.../artifacts/analysis/kwargs_expansion_design_20261025/SOURCE_RECEIPTS.json` 中两份准确 UTF8；
- `.../artifacts/experiments/first_stage_source_revision_current_20261025/result/connections/source/report.json`，
  当前 inventory/coordinates严格取该报告的 inventory/coordinate_binding receipt，不能猜旧版本；
- 原 CodeWitnessStore：`.../artifacts/experiments/first_stage_partitioned_operand_routes_20261023/result/code-witnesses`；
- 原 source/context入口沿已运行 tuple 门的 `CompositionIndex` 与 `PreparedSource` 路径，原 compiler
  source composition为 `.../artifacts/experiments/first_stage_source_publication_current_20261023/result/composition/index.json.gz`。
  这里只允许打开两份所选 source/context及准确原 inventory 定义；须另核当前 inventory 中相同
  snapshot/definition/context资格。旧 compiler-origin不替代当前报告的inventory绑定。

正式入口应复用原 tuple attempt02 的小 runner 做法：根据原 SG/source构造 PreparedSource、
seal_for_lowering、SourceCodeEvidence(readonly store + 完整 captured descriptor/source link)，
然后直接对四个准确定义调用 session.lower。显式 capabilities=原3项+CALL_KWARGS_314_V1；
`expand_candidates=False`、STRUCTURED_ENV；不得调用全量 plan_source_frontend扫描所有定义。
新 runner 不照抄旧 recipe 的 git 命令，也不以当前目录/当前同名源文件补历史来源。

建议首次门独立上限：4 bodies、2 source files、每body4000 ops、总16000 emitted ops、每body180s、
总worker600s、外层660s；原 context/单record64MB、总输入256MB、总输出256MB。若实际所选
档头超过上限，先报告准确 descriptor 而非绕过预算。compile0/target0/prepare0，20-key原store
只读、不增加key；native/OS/raw/100k调用行均不读。GNU-time与SELF RSS分列、20s heartbeat，
逐body阶段/输入计费/原定位/返回metadata/失败保留。freeze参与源码/依赖/runner/准确实际roots并终检；
未完成的 freeze/未解析的两个context payload不假称已经核验。

每个返回图保存为独立新 source-program5，公共 read_structure往返；独立 exact AST/CodeWitness、
validate_call_protocols与原 structured/environment/language validators分别记录。正常入口的
SOURCE_REPLAY会从metadata.source.path重新读源码；若这不是准确归档同字节，不能冒称已做
该 replay，应用已供准确AST/options的原 validator路径并清楚报告模式。所有新图/记录只存本树
新 `artifacts/experiments/source_call_kwargs_bodies_20261025/attempt01`，不改main publication/旧史。

验收必须区分：原 kwargs frontier是否越过、图是否返回/结构合法、exact compiler/source是否
通过、call-owned pending是否通过、call/local-unwind及外层lifetime资格是否仍OPEN。当前协议
明确保留 CALL_EX_LOCAL_UNWIND_CONTRACT_UNVERIFIED 和 OUTER_PENDING_PREFIX_UNVERIFIED；
不是原CALL_EX所有路径已消费输入的证明。后继child/控制/效果若未恢复，保具体下一frontier。
_Unsupported返回与validator ValueError/异常失败分开，后者 FAILED_RETAINED，不能算UNSUPPORTED；
异常前未返回的 emitted cost不得填0。无新publication/current Run接线、无全程序PASS或新episode。
