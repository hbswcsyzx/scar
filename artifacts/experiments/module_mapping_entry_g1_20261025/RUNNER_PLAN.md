Root 审阅入口：`candidate02/run_gate.py`，freeze `adabc18cd062f92383541a8d3672bb8ae54d85126d051c5c1b0ce01cce7d62ea`，状态 FROZEN_NOT_RUN。

本门自动从真实 G1 原 composition `module_roots` 选唯一 source unit，复用正常 CompositionIndex/source-layer reader 与已有 readonly SourceCodeEvidence。输入原 586B UTF8、1455B marshal；7 个准确原 URI 的 stored 总计 101394B，声明 decoded 总计 994990B（包括未压缩记录的逻辑长度，不能当实际 I/O）。准备只读 232655B 小 metadata（逻辑规范化计数）及 source/runtime SHA；没有打开 840089B source-layer 正文、marshal、目标源，也没有 lower/compile/target/raw。

本模型是 `ENTRY_GRAPH_WITH_UNEXPANDED_BODY`：原 MODULE initializer + mapping frame locals/globals/builtins/world → 原 core callee/invoke → 同一 child Region 的 whole-world opaque body → 独立 NORMAL/RAISE worlds。child 不是额外 Python frame。ModuleUnitSource + 完整 SourceContextDigest 固定到原 95 atoms/92 semantic operations/45 CFG nodes/56 edges；required_expansion 固定 REQUIRED，未恢复语句运算数 0，不剥 import/try、不伪造 module AST atom/FunctionObject。ModuleObject/sys.modules/actual alias/actual activation binding 未证；原 0 function/class、9 groups/271 calls/其中 module1 的分母保留，本门不重扫或重分类这些动态事实。三处 producer/source/schema6 分支及 child/entry 连接由独立 validator 检查；普通 read_structure 重读同一完整两 Region core，无删图投影。严格负例限 unknown field、缺 retained source、伪装历史 version、把 required expansion 改 COMPLETE，均在 Root 实际门执行，不先填 PASS。

预算：1 source unit、1 entry construction、最多 4000 ops；retained 输入 stored+gzip-decoded（包括重复）32MB；单 record/context/root4MB；source1MB；output+owned readback16MB；worker180s/outer240s；20s heartbeat、GNU time、SELF RSS。358 scar sources/141 runtime files、7 input stat，源码/runtime/runner 每次 SHA guard 14788956B，单次 guard 上限32MB，两次分别记账，不藏进 retained I/O。freeze 自身明确列为 internal check input，路径是最终 candidate02/freeze.json；attempt 固定 candidate02/attempt01，失败留原不重试。

待 Root 审阅后运行（本 agent 未运行）：

```bash
cd /home/zyf/AAA/scar-worktrees/source-call-model
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/zyf/AAA/scar-worktrees/source-call-model /home/zyf/miniconda3/envs/lewm/bin/python -B artifacts/experiments/module_mapping_entry_g1_20261025/candidate02/run_gate.py --read-inputs --approved-freeze-sha256 adabc18cd062f92383541a8d3672bb8ae54d85126d051c5c1b0ce01cce7d62ea
```

源码只改批准的6文件，准确 SHA 见 IMPLEMENTATION_RECEIPT.json/freeze.json。PRODUCTION.patch 对隔离 HEAD 的准确增量包含3新增；应用 main 时 worklist 只追加 module_entry_catalog，不能整文件复制覆盖 main 的 eligible_body_keys 或默认策略。v1–5/默认3–4/core28不变；schema6 不进入 CP2/SourceProgram5 publisher。candidate01 原 scripts/freeze 保留 NOT_RUN；本轮无真实 gate 结果、无发布。
