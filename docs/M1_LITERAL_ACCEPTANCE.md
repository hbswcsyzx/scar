# M1 L：精确内容、来源与原求值接口验收

日期：2026-10-18。**限定门通过，完整第一阶段 M0–M2 未完成。**
按 [L0–L5 计划](M1_LITERAL_PLAN.md) 自主验收；
[接口说明](M1_LITERAL_INTERFACES.md) 定义三种关系、原端口与有限预算。

## 1. 实际证据

| 项目 | Observed / Verified |
| --- | --- |
| 冻结实现 | 干净 `4bc55ebcec2537adabfe3a40db7c3f1df17c4d48` |
| 最终组件 | 32 criteria，1,716 个独立 case，全部通过，49.349s |
| 唯一冻结全仓 | 5,294 passed，0 failed/error/skipped，5 warnings |
| 全仓成本 | 外部 wall 544.3679314125329s；pytest 542.19s；peak RSS 1,027,208 KiB |
| 源指纹 | 603 files，`7d3187f36f6cca07e0714a49ac20dbe1c0634601568f2986ef8f0c178431f7a9`，前后相同 |
| 守恒 | 原 5,144 case 身份和 74 fixtures 全部保留；新增 150 case，当前 78 fixtures |
| 旧源码 | 590 全保留，564 hash 不变，26 扩展，另新增 13 个登记文件 |
| 环境 | conda lewm；Python 3.14.7，pytest 9.1.1，Torch 2.13.0+cu132，NumPy 2.5.2 |
| 保护 | LeWM `f70fed8`、主 SCAR `84f165f` 均原 HEAD/干净；未修改环境 |

全仓只运行一次，2026-10-18 14:00:55–14:10:00 UTC。所有代理提前停止写入，
运行期间未修改源码、文档、报告或并行运行 SCAR 测试/profiler；仅轮询同一进程。
固定 full driver SHA 为
`9a28d3b043e12484e099d9794478399ceccaf24e42dd6643c535e7cee2de9b28`。
子进程终止后只移除了该 driver 独占的 basetemp。共享服务器外部负载未测量。
这里的时间与 RSS 是验收成本，不是 workload benchmark 或 LeWM 加速比。

## 2. 自主节点及审查结论

| 节点 | 交付及结论 |
| --- | --- |
| L0 | 三份设计审查、计划、旧 codec 改动前独立 v15 golden；区分内容、来源和原求值。 |
| L1 | 复用 PythonLiteral；精确 scalar/tuple、complex bits、surrogate codepoints、共同预检预算和 legacy family 门控；最终 25 定向通过。 |
| L2 | Exact Data origin、原 direct/INVOKE NORMAL 求值附件、v16 能力门控、静态原端口查询；65 定向通过。 |
| L3 | 原 execution/denotation/state-address/count 接入；loop/call/resume、多 state/forward、实际 N/R 及序列化接缝；最终 60 case 由统一组件一次覆盖。 |
| L4 | 独立有限复审 PASS_WITH_SCOPE；32 标准/1,716 组件通过；干净实现提交后唯一全仓 5,294 通过。 |
| L5 | 原失败、范围、保护、旧 case/fixture 守恒、逐文件指纹、归档 manifest 与只读 checker。 |

新增 150 case=25+65+60，不累计同一子集的重复 attempts。root 的 attempt006
运行 59 项，attempt007 只运行新增序列化接缝 1 项；最终组件才在同一快照上
覆盖完整 60 项。较早组件 1,710 PASS 保存在 component/attempt001，未被最终
1,716 PASS 覆盖，也未拿旧结果冒充后来新增的多 state/forward 组合。

独立报告逐项保留 I01–I10 与 C01–C20；两表有重叠，不是 30 个独立测试。
其中 C10 的真实 source/code-slot 重放、I09/C19 的不透明构造内部，以及 C14
部分 reference-only 旁路，只按各自声明/源码核对范围报告，没有改写为运行证明。

## 3. 原发现、首败与修正

原始 logs/JUnit/command/receipt 全部留存，不以成功终态覆盖失败。

- 独立复审发现：普通 escaped JSON 会将相邻 surrogate escapes 合并，不能区分
  D800/DC00 两个代码点与单一 U+10000。新 exact profile 使用 STR_CODEPOINTS，
  其实际正反例已通过。旧 raw STR 协议保留；相邻 surrogate 合并记录为
  **baseline defect**，未宣称修复所有旧 family/schema。
- 共享 tuple preflight 初版的 size 未初始化产生过真实构造 traceback，保存在
  core_literal/preflight.initial.log；修复后两作者的首个 pytest 均通过。
- root 源审发现超长 str 可能在廉价长度拒绝前扫描 surrogate、节点预算可能在
  入队之后才计量。现分别提前长度拒绝、预留全部 scheduled nodes；三个树入口
  的实际回归保留。源审另发现 nested generic tags 只剥根标签的问题，改为逐层
  严格且有界的 decoder。没有虚构这些源发现的修复前 pytest 失败。
- dynamic attempt001 为 48P/1F：测试错期待 stale_incarnation，原校验器已在
  use_activation 更早拒绝。只修期待；attempt002 为 49P。
- attempt003 为 51P/3F：新恢复 fixture 把工作放在 Initial/Attach 之前。只把
  新 fixture 操作移入正确 Attached 窗口，原 context 守卫保持；attempt004 为 54P。
- C07/C08 新组合 attempt005 为 54P/5F：同一 Use 被当作 actual 和 forwarded
  两种端口，原 control_binding 正确拒绝。新建独立 owned forward Use 后
  attempt006 为 59P；第二 state、NORMAL/RAISE 和原 produced 逻辑槽均保留。
- 两作者各有一次 metadata 命令误用不可用的未激活 python，得到 command not
  found；没有 Python 执行或文件变化。所有实际 Python 测试均激活 lewm。

七处旧测试仅机械更新当前最高 schema 为 16；历史 v14/v15、旧 golden 和
语义断言分别保留。独立 v15 fixture 为 15,511 bytes，SHA
`0bd50636fb4f18c85239917b2895f71b9a0cfff0b0c1fdf77cb715068851dd8e`，
proof 绑定旧 `13201ad` 和原 codec，不从新 codec 重造旧期望。

归档 staged whitespace 检查的48条提示全部来自 attempt003/005 的原始 pytest
stdout/JUnit（共4文件）；保留其原字节和hash。维护的源码、文档、测试和gate
单独检查通过，没有为消除原失败日志的空白而改写证据或重跑测试。

## 4. 本门落实了什么

**Implemented / Verified：** 精确 builtin 内容、来源声明、原求值端口分别建模。
ExactLiteralOrigin 只定义抽象 Data 内容；LiteralEvaluation 只能附着原 direct
Data/Reference 或 INVOKE NORMAL produced slot，不增加 producer、Uses 或状态链。
它不消除原操作的分配、回调、异常和其他效果。相同内容不替代对象身份。

静态查询保留原操作、按顺序的 Uses、准确 completion/landing formal 及各项条件；
动态查询绑定准确 occurrence/visit/activation 和实际 transfer。RAISE、缺 transfer、
缺捕获/denotation 不借另一次同内容结果；保存引用仍受 suspension cut 约束。
两次求值的同/异 ObjectIdentity 通过已有声明测试，未冒充运行采集。

payload 固定上限为 root depth0/max64、16,384 展开节点、1,048,576 scalar bytes、
4,096 decimal digits。共享子树按每次展开计，cycle 拒绝，整数分块转换不改全局
digit limit。查询预算只覆盖动态 joins；准备、校验、索引、外部快照及 detached
copy 成本另列，不宣称同一个严格 CPU 总预算。

v16 仅由新 origin/附件能力选择；旧 SourceSemantics/OIR profiles 不静默扩大，
Execution wire 继续复用原版。容器/格式化示例保留明确的 opaque 构造与效果边界，
未将几个 label 当成全部内部协议已实现。

## 5. 未完成范围及下一步

**Inferred / Proposed，尚未 Verified：** SourceExpression 是否对应实际 AST 求值、
CodeConstant 所指 code/container/slot 与实际运行对象是否匹配、真实 native
返回槽/写入/alias 与完整捕获；本门没有重放 artifact 或执行 locator。
source_runtime_verified、value_identity_verified、transformation_authorized
保持 False。DECLARED 不证明 pure、ready、可删除或可复用。

按原顺序继续：

1. 核对完整 C2.0/C2.4 与 D3 家族分母，对 generator/coroutine/asyncgen/request、
   delegate/await/close/cancellation 逐项连接现有原端口、状态和完成规则；先审计
   已有 D1/D2 与语言见证，避免再造一套生命周期表。
2. 完成 M2 Python 构造/字段的依赖、顺序、隐式调用、失败与效果规则；不透明
   内部仍未理解，不拿旧测试数关闭全部构造。
3. 逐项核对 M0–M2 完整矩阵，满足后按用户要求先停下来讲解，再进入自动建图。

没有新增 detector/backend、source lowerer、LeWM 特殊规则、重型 profiling 或
新的性能数据。完整第一阶段、自动 LeWM 全过程建图和化简仍 OPEN。

## 6. 机器记录与只读核验

目录：`artifacts/experiments/b1_call_operands/model_literals/`。
包含 design、三实现方全部 attempts/receipts、独立 review、两次有限 component、
唯一 full 的 command/environment/logs/JUnit/cases/time-v/source/manifest、
protected.before/after、preservation、closure 和总 manifest。

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_literals/check_archive.py
```

checker 启动零测试/工作负载，检查归档字节、当前源/fixture/docs、旧 case 与冻结
实现祖先关系。组件原入口为 scripts/run_gate.py gates/m1_literals.json；完整
测试的唯一命令和环境保存在 full/command.json，无需为读取验收而重跑全仓。
