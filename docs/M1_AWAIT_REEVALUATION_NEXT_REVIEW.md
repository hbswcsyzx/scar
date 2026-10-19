# N4：获取结果发生与整条 pipeline 重求值

2026-10-19；N3 最终回归期间只读审查。下面为 **Inferred / Proposed**，没有
构造或运行新例，不将源码疑点写成已测缺陷，也不重开原G/F17/F21/F23结构格。

## 1. 既有证据应保留

E 的原 execution_await_resume 单元已有同代码两个 Create 不混来源、同 B
不借另一个 Drive、重复 root 不借 sibling activation 的准确 selectors。
但现 factory 的每个 instance 都有新 caller activation，每个只一次 Get。
G 的 copy loop 在 Get 之后、first Drive 之前，不能代替整 pipeline 重求值。
H 的预算、缺采、中间 join、detach/fresh catalog 也有既有准确测试，不能用
source/native 权限 False 把这些结构要求重新说成未实现。

## 2. 最小 public API 反例起点

同一个 caller activation 内只 Create B 一次，真实已知 callee 的自返回 Get
执行两次。Get0/Get1 各自 own NORMAL 结果都经原 callee Return 复制同一 B。
当前 iterator 明确经 Get1 的原结果 → zero-cut Drive → completion → 原 E/F
最终提取/consumer。可从原 native/self eligible 分支构造，不臆造 wrapper、
不存在的 RAISE 签名，或第二次 Start 已 Closed 的 B。

期望库存保两个 source occurrences，而该 advance 的 matched_sources 只取
Get1。Get0 不能因 B 相同被选，也不能使准确 Get1 被报歧义。这不是禁止对
两次获取提出复用；复用需要独立 effects/contract 证明，不能先抹掉执行来源。

**源码假设，尚未首测**：await_links 的候选过滤先按 body_value_roots、host
path 和静态 choices 合并来源；original known-call output recipes 又把两次
获取结果都追到同 B root。因此可能产生 await_source_occurrence_ambiguous，
虽实际 iterator 的 copy 路线明确经过 Get1 own result。

## 3. 复用已有关系，不另建来源图

从 actual iterator 沿现 body_original_copy_recipes 的准确 ValueOccurrence
predecessor/call support 追到本 source site 的准确 own-result/landing 边界。
先保当前获取结果发生，再参考共享 B 身份；不改 body_value_roots 的全局同 B
事实，不按“最新时间”选生产者。缺本次 Get1 的 Use/transfer 保未知与具体
gap，不借 Get0。遍历、原分母和截断共用预算，不新增 wire/SSA/producer 图。

## 4. 该反例不代替完整 E/H

真正整 pipeline 重求值仍需同 caller 的真实 backedge 带当前 state，回到
Create/Get；下一次新 Create 对应新 B activation，再经过真实完成、最终
consumer。不能重启已关闭 B，也不能用两个独立 caller 的顺序重复假装循环。
下一节点先冻结具体原图/端口/拒错标准，再作者冻结、root 首测，按原 E/H
矩阵逐项合账。当前不加 detector/backend，不跑 LeWM 或宣称新速度结果。
