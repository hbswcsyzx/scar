# P3：actual branch prefix 的首出口 cut

2026-10-18。只新增 owned `execution_body_prefix_graphs.py` / `test_execution_body_prefix.py`；不改原已冻结33项或产品。复用原 `_branching_body` / `_first_driver` 和 `_model`，不是另造 producer/SSA 图。

## 精确构造

同一个 body 的 Resume ingress 进入真实 `close.body.choose` bool/BRANCH：A 是 `close.body.return.exit`，B 是 `resume.raise` 的实际 ignored-close YIELD。两者都是同一原 BodyDrive 的合法 first frontier source。normalizer、gate、每次选中的 Drive source、私有 N/R landing、当前状态、原 Attach/Detach 及 payload 都沿原图保留。native close/source 适用仍未证明。

反例实际捕获 choose-A transfer 和 A block/Detach，但故意漏掉 A terminal occurrence；同一 selected segment 另有无 incoming 的 B visit/outcome。Drive 实际所选 source 和声明 outcome 都是合法 B，所以不能用 source shape、FK 或 multiple-outcome 误拒掩盖问题。剥两张新 O 关联表后原 canonical validation 必须仍 valid。新 validator 精确报 `body_outcome_path`：实际前缀走入 A first-outcome cut，不能用断开的 B 补造路径。

对照缺采例没有实际 branch transfer；原静态 suffix 包含合法 B，保留 B 原 output Uses 和 `body_path_unobserved`，不能误拒或宣称完整路径。

## 验收

`prefix/attempt001`：**4 passed / 1.36s**，包括完整A、完整B、已知choose-A但漏A terminal/断开B负例、真实缺transfer的gap对照。命令、stdout/stderr、JUnit与完整源码清单均保留。before/after registered fingerprint 相同 `2d53d280d2d750e69231a60c7dec67cc57bf711b2cd32a60a767fbfc8b94e3bf`。没有失败重试、组件/full、运行capture或GPU。

冻结 SHA256：fixture `1167c421cab7672c3ca5fb764b35a9a22cbae5e026f1708a24dc4fa954a27b41`；unit `087b04c7516ec689194b9eb5a147fd73e91456823a422dbd16c3c31ce75ee8ae`；受测 root `resumable_validation.py` 为 `670750af064b5f865979edf59819a19045bedadbc341830a2b45df8c19b1f318`。本 owner 两源码从此停止写入。

结论限于 supplied-model 的这项 source/path 规则。查询 source/runtime/transformation flags 为 False，不将 hand-authored IR 当自动恢复或实际 native 行为证明。此4项与原33项是不同的强反例分母，不代替其余 O01–O16 或完整P3统一验收。
