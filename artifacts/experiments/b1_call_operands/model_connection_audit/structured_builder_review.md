# STRUCTURED_BODY builder：独立正确性审查

日期：2026-10-16。工作树 `/tmp/scar-structured-model-280qf4mi`。
范围：`analysis/structured_lowering.py`、`ir/program/structured.py` 及其 core binding
接口；只读实现，没有修改产品、测试或计划文档。未运行 pytest、全仓或 LeWM。
仅在自动清理的私有临时目录创建几段普通 Python 源码，用当前 lower_source 自动
建图并检查；额外执行三个小型 CPython finalizer fixture。

实施仍在并行修改。本报告保留初次失败证据，明确区分已复验修复和尚需处理项。
最后观察到的文件 SHA-256：

```text
structured_lowering.py c4a70c6c4be202a344978cad542db310d7496724ec90b500b67523d663c2c5f3
structured.py         80cf6163b14de463c2e5588ff134b6775fea16ca5b15446903fd212085b6fd92
binding_validation.py a2feffefaac34cda5a56d069120c65d9ef077682cd3c171938a5b7842adb5602
```

## 1. 尚需修正：LoopInterface 可以错误描述一个有效 core CFG

当前 `require_valid_structured_body` 已核对 loop source/kind 和记录存在，但约
633–648 行只检查列出来的端点/边是否存在、指向何处，没有重算必需集合。

从以下原始源码自动产生的有效图：

```python
def f(xs):
    for item in xs:
        if item:
            continue
        break
    return 1
```

对 model 单独作以下替换，再调用带独立 `semantic` 上下文的 validator，仍得到
ACCEPT：

```python
replace(loop, body_entry=loop.natural_exit, natural_exit=loop.body_entry)
replace(loop, bindings=())
replace(loop, backedges=(), breaks=(), continues=())
```

这不会改变 ProgramGraph 的规范控制边，但会让通过校验的 typed loop 索引错误
宣称 body/耗尽方向、丢失 carry 或没有 break/continue。后续若用该索引回答结构
覆盖、循环 carry 或化简边界，结果会错误。不能把它当成独立可信的循环合同。

建议最小修复：

- header/body/natural port 与该源 loop 的真实 truth 或 ADVANCE/MATCH 分支对应；
  for body 必须是 ADVANCE 的 NORMAL 入口，natural 必须是耗尽分支入口；while
  对应当前条件分支的 true/false。所有 block 都须属于声明的 loop.region。
- bindings 必须恰好等于 header 的全部 LocalBinding block arguments，保持 slot
  和顺序，不只验证已列出的元素。
- 重算所有真实回边及对应 source break/continue 集合；与索引精确相等。source
  replay 负责源码控制语义；结构 validator 不能允许删除现存边的索引就“通过”。
- 完成集合校验后，保留上述三个反例，外加 nested loop 转移归属和同 target 多边。

**边界：** 没有发现这能突破公共 SourceProgram 的源码重放。公开 replay 仍需
重建和比较完整结果；本项是 typed cross-validator 的实际缺口，不报告为已绕过
公共报告验证。

## 2. 已反馈并看到修复：for iterator lifetime 丢失

初版 `for_statement` 只让 iterator 成为 ADVANCE_ITERATOR 的输入；没有 hold、
正常耗尽/break 的 release，也没有将活动 iterator 加入 FRAME_EXIT。

三个自动源码图中，GET_ITERATOR 的 NORMAL result 的 consumer 均只有：

```text
['ADVANCE_ITERATOR']
```

原始函数分别为：

```python
def break_case():
    for item in make():
        break
    return observe()

def exhausted_case():
    for item in make():
        pass
    return observe()

def return_case():
    for item in make():
        return observe()
```

小型 `make()` 返回唯一 iterator，其 `__del__` 追加事件，`observe()` 记录并返回
当前事件副本。本机 CPython 3.14 的实际结果：

| 路径 | 实际事件顺序 |
| --- | --- |
| break | next → iterator-finalizer → observe |
| 立即耗尽 | next → iterator-finalizer → observe |
| body return | next → observe → iterator-finalizer |

这里是特定 CPython 的时点观察，不是物理 free 的通用保证。图至少必须表示相应
引用持有和清理可能产生的状态变化；不能以静态 SSA value 的存在代替生命周期。

根代理随后增加 FRAME_HOLD_TEMPORARY / FRAME_RELEASE_TEMPORARY，active temporaries
进入 FRAME_EXIT；耗尽异常还有 FRAME_DISCARD。最新自动图中的 iterator consumers：

```text
['FRAME_HOLD_TEMPORARY', 'ADVANCE_ITERATOR', 'FRAME_EXIT', 'FRAME_EXIT',
 'FRAME_RELEASE_TEMPORARY', 'FRAME_RELEASE_TEMPORARY']
```

方向已修正：continue 保留 iterator，break/natural 在离开循环前 release，return/
异常使用 FRAME_EXIT 持有活动引用。inner while 的 break 不应释放外层 for iterator；
inner for 完成后其 else 使用外层 loop 上下文。当前静态栈组织符合这两点。
本审查只复验了实际引用连接和有限控制案例，没有宣称完整 lifetime gate 已验收。

## 3. 已复验修复：确定 UNBOUND 的异常 producer 接口不兼容

初版最小输入：

```python
def f():
    return x
    x = 1
```

实际 `lower_source(..., profile=STRUCTURED_BODY)` 抛：

```text
ValueError: binding_read_exception ...
unbound local must raise one exception reference from a typed producer
```

原因是 MAKE_UNBOUND_LOCAL_ERROR 通过 INVOKE NORMAL CompletionResult 产生异常
reference，即 BlockArgument；当时 core 只接受 OperationResult。相同问题出现在
`return caller(x, must_not_run()); x = 1`，阻断公开源码构图。

最新短探针已得到 `CURRENT unbound GRAPH True`。异常来源必须由精确 normal
completion/slot 解释，不能改成接受任意 BlockArgument；实际异常种类仍由
MAKE_UNBOUND_LOCAL_ERROR 的 source profile 核验。确定 UNBOUND 的 final RAISE
额外 binding dependency 和不可能正常完成的规则按根代理与 core agent 当前
冻结合同处理，本报告不改写计划中的版本规则。

## 4. 已复验修复：protocol/loop 覆盖与 kind 缺失检查

初版独立 validator 对以下修改全部 ACCEPT：删除全部 protocols、删除全部 loops、
TRUTH 改成 GET_ITERATOR、WHILE 改成 FOR。

当前有必需 `semantic=` 验证上下文，源 atom 和 protocol coverage/shape 已加入。
最新结果：

```text
drop_protocols REJECT every synthetic source operation requires its exact typed protocol
drop_loops     REJECT structured loop interfaces must cover each emitted source loop control
wrong_kind     REJECT loop kind/source differs from its parsed language construct
```

TRUTH→GET_ITERATOR 也因 NORMAL payload type 不符被拒绝；public SourceProgram replay
删除 loops 已拒绝。报告第 1 节列出的是此修复后仍接受的三个不同问题。

MATCH_STOP_ITERATION 初版只用 exception reference 生成 bool、没有 state read。
根代理已增加 READ world access 并校验。此前没有获得实际 Python 类型可变导致
误分类的可运行反例，因此不将这一设计差异冒称已复现的目标运行错误。

## 5. 本次未发现错误的有限路径

以下均由小型原始 `.py` 调 lower_source，未手补 IR：

- while body 改写 x/flag，continue 回 header；break 绕过 else；core 校验通过。
- 两层 for，inner body continue/break，inner else 的 break 作用于 outer loop；
  loop 索引计数：inner back=1/break=1/continue=1，outer back=1/break=1/continue=0。
- `return x; hidden(x)` 的 hidden Call 未生成 core operation，给出关闭路径 gap。
  不把此处语法调用统计成已执行 core coverage。
- invoke normal/raise 使用各自 completion state；next 的耗尽检查位于其异常私有
  后继，普通 body call 的异常直接退出，不走耗尽 else。
- 零次、循环局部 carry 和未知 boundness 使用 LocalBinding block arguments；
  未观察到 header value 不支配使用或 state 回到 pre-loop 的实例。

这些是有限审查结果，不替代 loop/state/source replay 正式门。没有扩展到本阶段
未支持的 try/with/generator/async，也没有运行 LeWM。

## 6. 可复现的短命令

所有探针使用以下环境；临时目录由 TemporaryDirectory 自动清理：

```bash
cd /tmp/scar-structured-model-280qf4mi
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
  /home/zyf/miniconda3/envs/lewm/bin/python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from scar.analysis.program_lowering import lower_source
from scar.analysis.structured_lowering import require_valid_structured_body
from scar.ir.program.functions import BodyLoweringProfile

with TemporaryDirectory(prefix='scar-loop-interface-review-') as tmp:
    path = Path(tmp) / 'raw.py'
    path.write_text('def f(xs):\n    for item in xs:\n'
                    '        if item:\n            continue\n'
                    '        break\n    return 1\n')
    result = lower_source(path, 'f', profile=BodyLoweringProfile.STRUCTURED_BODY)
    loop, = result.structured.loops
    changes = {
        'swap_body_natural': replace(loop, body_entry=loop.natural_exit,
                                    natural_exit=loop.body_entry),
        'drop_bindings': replace(loop, bindings=()),
        'drop_transfers': replace(loop, backedges=(), breaks=(), continues=()),
    }
    for name, changed in changes.items():
        model = replace(result.structured, loops=(changed,))
        try:
            require_valid_structured_body(model, result.graph, result.interface,
                                          result.metadata, semantic=result.semantic)
        except Exception as exc:
            print(name, 'REJECT', type(exc).__name__, str(exc))
        else:
            print(name, 'ACCEPT')
PY
```

此命令在上述 hash 版本耗时约 0.52 秒，三个反例均 ACCEPT。源码正在实施中，
后续版本应变为 REJECT；不得将本报告的旧失败当作已冻结最终状态。

## 7. LoopInterface 最小严格重算建议

根代理提出的 header 全部 binding ports、`header dominates source` 的全部入 header
边、source Continue 子集、WHILE 真/假与 FOR next/match 端点重算方案可用。边按
`(operation, successor_index)` 身份保留，不能按相同 target 合并。

**break/continue 的作用域不能只按最小包围 span 确定。** 内层 loop 的 else 中
可以 break/continue 外层。现有独立 `SourceControlFlowGraph` 已正确记录这一点：

- `control_flow_v2._compile_statement` 构造 loop body 时压入当前 loop；构造 else
  时使用旧 loop_stack。
- BREAK edge 的 source node.source 是 Break 的精确 SourceReference；target
  node.source 是被退出 For/While 的 SourceReference（其 after insertion）。
- CONTINUE edge 的 target source 同样是被继续的 loop，目标为其 statement node。

可按同一 function scope 和精确 SourceReference 找唯一 BREAK/CONTINUE 边，建立
`transfer atom -> owner loop atom`，再与当前 core 的实际 JUMP 端点核对。没有唯一
来源或该范围有控制 gap 时拒绝合同，不猜。control 必须来自同一封存 snapshot，
公开 replay 要独立验证它；不引入外部 `trusted=True`。调用 validator 时传已有
semantic+control 或 sealed context 即可，无需第二次完整 prepare。

after 也可从实际 core 重算，而不是用声明的 after 过滤后宣布成功：

1. 取该 loop source 的合成 JUMP 中目标不为 header 的边（自然/else 正常退出）。
2. 加上按上述独立控制来源确定 owner 为本 loop 的所有 Break JUMP 目标。
3. 目标集合为空时 after 必须 None；恰好一个时 after 必须为该 block；多于一个
   拒绝。继续核对这些边在合法 region 内，不能用任意外部 block 充当 after。

若选择不复用 legacy control graph，可传 PreparedSource 的 AST，做有作用域的
loop-stack 遍历：body 压当前、else 不压当前；nested def/class/lambda 的独立范围
重置。它给出同样的 transfer-owner 映射。纯 AST containment 或声明的 loop.after
本身都不能作为这个证明。

## 8. 冻结版本定向复验：已知 LoopInterface 缺口关闭

2026-10-16，按根代理限定只复验第 1 节三个 mutants 和一个 nested loop-else
break-owner 场景，未扩展审查、未运行 pytest/全仓/LeWM。

冻结提交：`dcd498699e0cd1331cf496158b29575c3fc2c536`。开始时工作树 clean。
`structured_lowering.py` SHA-256：
`2e15e5c3586523507d164152f367e39ae6db9436c312273f3943bc1438688969`。

命令环境：

```bash
cd /tmp/scar-structured-model-280qf4mi
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 \
  /home/zyf/miniconda3/envs/lewm/bin/python - <<'PY'
# TemporaryDirectory 内写原始源码；lower_source(..., STRUCTURED_BODY) 自动构图。
# 每次使用以下实际校验调用；没有调用 SourceProgram.from_dict：
require_valid_structured_body(model, program.graph, program.interface,
                             program.metadata,
                             semantic=program.semantic,
                             control=program.control)
PY
```

原三个修改仍为第 1 节的交换端口、清空 bindings、清空全部 transfer indexes。
新增 nested 源码的确切行号：

```python
def f(xs, ys):                   # 1
    for x in xs:                # 2
        for y in ys:            # 3
            if y:               # 4
                continue        # 5
            break               # 6: inner
        else:                   # 7
            break               # 8: outer
    else:                       # 9
        return 1                # 10
    return 2                    # 11
```

正图明确断言 outer(line 2).breaks 对应 line 8，inner(line 3).breaks 对应 line 6。
反例将 outer.breaks 清空，并将原 outer break 加入 inner.breaks；core CFG 和
独立生成的 semantic/control 均保持不变。

| 检查 | 实际结果 |
| --- | --- |
| 原始单层 for 图 | VALID |
| 交换 body_entry / natural_exit | REJECT：`for loop control ports differ from its item/exhaustion edges` |
| bindings=() | REJECT：`loop binding interface must cover every ordered header binding` |
| backedges=breaks=continues=() | REJECT：`loop backedge interface must cover each actual backedge` |
| nested loop-else 的原始 break 归属 | VALID：outer→line 8，inner→line 6 |
| 将 else break 错归 inner | REJECT：`loop break interface must cover each actual break` |

实际运行 exit 0；探针主体 wall 0.229263 秒（不含前后源码指纹计算），shell 工具
记录总时长约 0.745 秒。共 2 个原始图正例校验、4 个有针对性的篡改拒绝检查，
不是新增 pytest/gate 数量。

前后都调用 `scripts/run_gate.py::fingerprint()` 的同一实现，均得到：

```text
bf7ccd18b51b843c53b6b49f290c5f7368c397f394209991eb1f13a1f313bf05
```

**结论：** 第 1 节剩余的三个 typed-validator 反例及此次 nested owner 反例在
该冻结版本均已关闭，历史 ACCEPT 记录仅描述修复前版本。本次验证的是“原始
源码自动生成上下文 + 局部 typed cross-validator”的拒绝能力；没有重新执行
公共 SourceProgram 报告重放，也不以它代替完整源码语义、生命周期或全程序门。
报告到此冻结，未修改产品、测试、gates 或计划文档。
