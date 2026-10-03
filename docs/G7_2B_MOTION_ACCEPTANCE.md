# G7.2b 窄源码上移自行验收

状态：**Verified，限于精确直线 suite alias 上移的条件合法性**。
这不是完整 G7.2b、REUSE、循环 hoist、G7 总门或 LeWM 优化验收。

实现：`1cf69657b3022bca8037ee4f4518bb6983483a5d`；旧格式夹具修正后的实际
验收 revision：`750639f91c812f096f360f0c0b4ee761e5d2a7ae`。
专项 **179 项通过**，整仓 **1,064 项通过**，两项既有警告，无失败或跳过。
两份正式报告绑定同一源码摘要：
`9f829755b8908fae9f9ecc1649eb81595ba89dd7250e5f5896ee3658a685d80c`。
测试期间和归档核对时均未变化。gate 37.088 秒，回归 wrapper 97.372 秒。
两项测试并发；下述分析在它们结束后逐次运行。

## 本次补上的模型连接

| 实体/规则 | 连接 | 当前范围 |
| --- | --- | --- |
| SourceFragment | 完整 statement → RHS/READ/BIND 操作成员 → scope/suite/source version/text digest | 单目标 Name Assign，不接受孤立 RHS 当作整语句 |
| StaticSourceMove | fragment → SourceControlFlowGraph 的精确 insertion anchor | 独立静态 delta，禁止与其他差量混合 |
| LocalStatementSemantics | 完整函数体 → first local bindings、逐 use 的 exact reads、builtin 内容/类型、return slot | 有限封闭同步函数；完整语句总性/效果不由常量结果替代 |
| 固定 MOTION 账本 | SG/source overlay/CFG/region/Q/delta → 六项重算义务 | `ALL_PATHS`、原始 MAY_RAISE、显式观察条件 |
| OIR schema 4 | static_moves 与既有差量严格序列化 | 1/2/3 迁移补空字段，不补许可或证明 |

ControlFlow IDs 与 SourceVersion 下移到 v2 核心并在旧入口重导出**同一类型**，
避免 optimization 依赖 overlay 的循环；不是创建两套可互换名字。
Object identity 沿 exact alias binding 保留，不由相等常量内容推定。

## 外部通用样例：实际保存并重放的结果

`testcases/source_motion/program.py` 不导入 SCAR。查询指定第 4 行完整赋值向上
移到第 2 行之后。该 query 由调用方给定，不能称为新 detector 自动发现的机会。
没有执行或修改样例，更没有修改 LeWM。

| 项目 | 默认空 Q | synthetic fixture 的显式 Q |
| --- | ---: | ---: |
| scoped declared assumptions | 0 | 26 |
| 六项义务 | UNKNOWN | 全部 PROVEN，条件保持 DECLARED |
| 账本结论 | NEEDS_CONTRACT | CONDITIONALLY_LEGAL |
| selected / applied | 0 / 0 | 0 / 0 |
| cost | PENDING | PENDING |
| SCAR 分析时间 | 0.881 秒 | 0.875 秒 |
| 分析及压缩写出 | 0.900 秒 | 0.897 秒 |
| 当前 executable VmHWM | 30,776 KiB | 30,796 KiB |
| gzip report | 17,246 bytes | 18,161 bytes |

Q 声明来自外部样例 README 的明确 observation policy：runtime 匹配，以及
resource/async/frame/trace/refcount/finalizer 等行为不在观察范围。它不是自动证明
这些观察不存在，也不是可以套到 LeWM 的普通默认。实际 primitive/绑定/路径/
消费关系必须从源码重新推导，不能由 Q 提供。

样例原始 source SHA256：
`84b6c519e953fc3f818aa3a444c3319109e310ee84d0ba372e0474e535ed4d35`。
默认/带 Q 两报告 SHA256 分别为
`6d0850e57ae0826b461f1b4aed5f7d0e0b16ac25384781dfd6e2d6913598cba6`、
`d37b70ad21247c72ee3bb5d873be24f1759070d55d454d001a1a427003e2e3bc`。
Q 文件 SHA256：`c0526f7f8c90dad65f195e8d42ec11cb34c178f67a20eb531d6361af165a36dd`。
固定源码与账本重放全部通过，报告/input/Q 哈希一致，LeWM 工作区干净。

这些时间是 SCAR 分析成本，不是目标程序 baseline、A/B 或 LeWM 加速比。
没有复制 Tensor 值或创建 GPU context 来为静态证明填充证据。

## 反例与失败记录

三名 Luna max 子代理分别完成完整 fragment、整语句证书及独立 ledger/codec
反例审查；主代理集成并执行冻结 revision 的 gate、回归和归档重放。
被拒/不支持的情形包括：输入在插入点不可用、opaque call、binding rebind、
mutable allocation、branch、loop zero-trip、try/finally、同位置/跨 suite 插入、
查询超预算、source/CFG/fragment/Q/delta 篡改和动态/静态 move 混合。
浮点算术因缺少 floating-environment Q 路径不获支持；frame/getrefcount 等观察
调用不能被“纯”声明洗掉。删去 runtime、resource、async、frame、trace、refcount
或源前提之一，正例不再成立。

第一轮 implementation 的专项 109 项通过，但整仓 **3 失败、1,061 通过**：
旧 port 测试仍断言 schema 3，且构造 schema 1 夹具时未去掉 schema 4 的
`static_moves`。已修正夹具和精确版本断言，保留 strict reader 对夹带字段的
拒绝；把该 port suite 纳入 gate 后重新通过。首次 JSON/JUnit 报告没有覆盖，
以 `g7-2b-motion-initial-*` 保留。这是 SCAR 测试迁移修复，不是 baseline defect。

公开报告的初始集成测试还发现 replay 调用省略了生成时显式传入的
source_texts，source hash 因而不同。重放现在传入同样的已核对源码快照；严格
账本比较没有放松。错误 query line 的断言也改为真实不存在的行。

## 复现与范围

```bash
cd ~/AAA/scar
conda activate lewm
PYTHONPATH=. python scripts/run_gate.py gates/g7_2b_motion.json
python -m pytest -q
PYTHONPATH=. python scripts/measure_static_motion_v2.py \
  testcases/source_motion/program.py --statement-line 4 --after-line 2 \
  --q artifacts/reports/gates/g7-2b-motion-example-q.json \
  --out artifacts/reports/gates/g7-2b-motion-example.json.gz
```

保存的 Q 绑定当前源码路径、版本、规则和 Python 环境；换 checkout/runtime 后
必须重新建立调用方合同，不能自动接受旧文件。artifact 中的 report、精确 Q、
measurement、replay audit、gate 和完整回归分别可检查。
Guard、失效和 NO-OP 见 [STATIC_MOTION.md](STATIC_MOTION.md)。

## 下一节点

继续 G7.2b 的真实 object-only identity / bool singleton materialization、精确
operand-site/event 连接和窄 REUSE 正反例；当前 REUSE 仍 NOT_YET_SUPPORTED。
之后 G7.3 桥接 import provenance → CONSTANT ledger，并把值替换和 import 删除
拆成独立、可组合的修改计划。当前没有循环上移证明、选中 LeWM 变换或已验证
workload 加速。完整 G7.2b 和父 G7 不随此子节点标为完成。
