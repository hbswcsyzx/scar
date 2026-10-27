# D2.2 最终有限只读复审

2026-10-18；任务基线 `e86563a`。**结论：本轮 bounded source review 通过，未发现剩余实质阻断。**
范围为 no-body 声明接线、此前两处修正、最终 fixture 及 codec/query/CLI 的有限源码核对。
本轮没有新增独立测试、probe、pytest、component/full、LeWM 模型、GPU、git 或 tracked edits。
只在 conda lewm Python 3.14.7 调用既有 `scripts.run_gate.fingerprint()` 读取并保存源快照；未调用 gate main。

## 1. 全 source 绑定

`scripts/run_gate.py` SHA256：`8e7a1c3b0ea192592d03d30b3b5aa3d59a62972ec7d8c1b48f3b962f1ea87fd2`。
其 fingerprint 覆盖 scar/tests/scripts Python、gates JSON、pyproject 及存在的 sitecustomize，共 **430** 文件。
本次 source digest：

`48c08626b5921f0adf08f57298738097c6d0ed0349f8efc08274813e63c93ebc`

全部 per-file SHA、实际解释器及 scope 写于 `final_fingerprint.json`；精确命令、脚本和输出分别保存为
`final_fingerprint.command.txt/.py/.log`。JSON SHA256：
`615673b7066f8abdc535a384341844d7e852d1e58f9b8d819ed21617c80d03fb`。
该指纹是审查快照，不声称该全体 source 均经本审查逐文件阅读或执行测试。
合同 `docs/M1_DRIVER_LIFECYCLE_CONTRACT.md` 另读 SHA：
`94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699`。

## 2. 前次两项修正闭合

R1：`no_body_validation.py:149–152` 对普通 BRANCH forward actual 采用 `isinstance(UseID)`，保留现有旧 ID 子类。
`test_program_no_body_graph.py:163–178` 已有 `test_ordinary_true_edge_preserves_legacy_use_id_subclass_copy`，
同时替换真实 owned Use 与 edge actual，再 require_valid；没有修改新 typed BodyDriveSuccessor 的 exact 约束。

R2：`:117–120` 要求配对 BRANCH complete、behaviors 恰 CONTROL、无 result/access/call/completion。
`test_program_no_body_graph.py:209–215` 已有两参数 `test_guard_branch_itself_cannot_hide_unknown_effects`，
分别以 effects_complete=False 与 MEMORY 行为破坏 corridor，要求 `no_body_branch_shape`。
此前缺口及源审/未复现的界限仍保留在 `implementation-source.md`，不改写为独立实测记录。

当前 validator SHA：`22669aec4d7c608b1b60c7d161908452f1135e4a1b434b7b80fccccca12607ea`。
graph unit SHA：`6619910f48bf05edd64a1bfcc66b8d72d1b0d381aa1845d43c7bdfa3db859c1a`。

## 3. 最终 fixture 的实际结构

`tests/fixtures/program_no_body_graphs.py` 现为一份约 420 行工厂，无旧同名覆盖草稿；SHA：
`6d41be9a1bbe6992eba8571f871ebdec436b29ae52cbe964433017b8659b5b67`。

- `:252–274`：predicate 自己产生 bool，condition 以 DATA Use 读取它；Test 读取各 L 当前状态。
- `:295–309,363–368`：true/false 各有独立实际 Uses；真实 edge0 去 mark landing，edge1 去 `driver.close.fallback`；
  BRANCH 为 complete CONTROL-only。不是用虚构 NORMAL helper 来替代 bool guard。
- `:238–250,375–384`：原 gate 移到 false fallback，uses 重映射到其真实 formals，最终 operation map 保留 moved gate。
  `driver_validation.py:307–311` 仍要求 gate NORMAL 私有 landing 仅含唯一 Drive，没有为 fixture 宽化 corridor。
- `:317–350`：true 首 mark 由真实 StateAccess 产生非空 W⊆L 的 after；`:352–359` host Return 使用更新后的 current。
  `predicate_only` 分支省略 mark 与 Finish metadata，直接保留当前状态；不会由 predicate 的 true 值自动授完成事实。
- `:75–159`：可选 AssociationRead 是真实 INVOKE，NORMAL 的 B/E 为 CompletionResult(0/1)，S/R/delivery 为原独立 Uses 转发，
  NORMAL 与 RAISE 都产生全部真实 D 后态；RAISE packet 到真实 host Raise。没有把读取出的新 B 当旧 B must-copy。
  `:214–223` false gate 使用这次 NORMAL B、S、R、delivery、current states。无独立 read 的 ASYNC 外部 B/E 仍可声明。

先前草稿中的重复关键字、bool role、region/operation map 问题在最终读取版本已清除。
BOOL/predicate/mark 的 source/runtime 意义仍是声明；真实 false/true 可行性未被 fixture 执行验证。

## 4. 公开面和证据界限

no-body validator 仍在 core/D1/publication 通过后运行；scope/角色/真实 edge0/私有首 mark/精确 owner/current state 均有门。
只遍历 Finish 表施加 mark 义务，predicate-only 允许；ASYNC 固定 R/S，B/E 的实际关联由当前 typed predicate 的 true 合同表达，
不强制独立 AssociationRead/RequestGate，不把错误 association 造为类型错误或 Python RAISE。

`queries.py:334–357` 引原 UseSite、bool、真实两条 Successor、真实 READ before 与实际 RW after；无新 producer 或 body outcome。
codec 仅两表真实 capability 选 v13，旧版本字段集不偷带声明；predicate-only 亦有合法 capability。
CLI 的 no-body structure scope 明说 optional Finish；runtime/lifecycle/source/transform 权限没有因此改为 true。
本轮对这些公开面的结论来自有限源码核对，不替 codec agent 的 focused gate 或后续统一 component。

已只读查看 root `graph/attempt-001/command.json/result.json/stdout.log`：43 passed in 0.82s、returncode 0，
其中 command 记录的 fixture hash 与本报告一致。它是 **root 既有执行证据**，不是本审查新增独立运行；
wrapper wall duration 1.429s 与 pytest 自报 0.82s 不混写，不把 43 当语义建模覆盖率。

最终结论仅为 D2.2 已实现声明接口的 bounded review。后续统一 component/full 由 root 执行。
没有证明 native guard、真实 current association/对象身份、无 callback 实现、body 实际字段更新、
F/P/T 产品算法、session/drop、runtime/source 对应或完整 D2/D3；手写 IR 不是自动导入与运行时证明。
