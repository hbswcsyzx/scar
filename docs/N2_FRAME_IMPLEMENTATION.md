# C0 实施：自动返回引用与 frame 生命周期

状态：C0 的 F0–F4 有限范围已自主验收，见[N2_FRAME_ACCEPTANCE.md](N2_FRAME_ACCEPTANCE.md)；
完整跨调用门仍未通过。
本文件对应 [Frame 生命周期计划](N2_FRAME_LIFETIME_PLAN.md) 的实现。
不添加 detector/backend，不使用外部 testcase 函数名称规则。

## 模型怎样落实到代码

核心实体仍是 Operation、Value、StateLocation、Region。
FrameModel 是源码规则与核心图的类型化对应，不是另一份数据依赖图。
每个 transition 都引用真实 Operation/Use；状态前后值来自核心 StateAccess。

原始 Python：

```python
def identity(unused, x):
    y = x
    return y
```

新 profile 自动得到的连接可概括为：

```text
unused, x, world S0
    -> ENTER(全部形参持有) -> S1
    -> BIND(y <- x)       -> S2
    -> EXIT(held x)       -> S3
    -> RETURN(x, S3)
```

RETURN 使用原 x 的 ValueID，不经过产生未知新引用的 opaque return。
unused 仍通过 ENTER 和 world 状态链影响退出；引用传递不删除生命周期效果。
首次绑定、覆盖、自绑定与表达式结果丢弃各自有状态操作。分支仅一侧的局部即使
不进入 env 交集，其持有关系仍由逐前驱 world 保留。表达式失败先携带异常及
求值后状态进入一次 EXIT，再保留原异常引用完成 RAISE，不回到调用前状态。

FrameRules 固定保留：NO_FRAME_INTERPOSITION 未证、effects UNKNOWN、可能
不完成、finalizer 错误 unraisable、释放不保证。无 RAISE 边不等于纯或必然完成。
返回对象内容可被 finalizer 修改，frame/traceback 也可保留局部对象。

## 自动入口、范围与版本

```bash
python -m scar.cli model-program /path/to/program.py --entry Class.method \
  --out body.json.gz
python -m scar.cli check-source-program body.json.gz
python -m scar.cli query-frame-refs body.json.gz
python -m scar.cli inventory-program /path/to/main.py \
  --project-root /path/to/project --out inventory.json.gz
```

这些命令读取源码，不 import 或执行目标。输入是入口、范围与预算，不是参数
类型、纯函数名单、业务模型或手写图。model-program 默认使用 BOUND_FRAME_V1；
该单体报告只 lower 所选 body，候选调用仍是接口。inventory 从入口自动发现并
调度多个 body，各 body 为 root-only，不能把这理解为已经组合了跨调用依赖。

SourceProgram v2 持久化 profile/interface/frame。`--body-profile legacy` 仍可
生成原 v1；Python `lower_source` API 默认仍 LEGACY，显式 profile 可选择新版。
旧 v1 SourceProgram 及 inventory v1–v4 按历史路径重放，不补造 frame。
新 inventory 默认 v5，顶层 profile/frames 对应全部成功 body；原 body wire 不变。
绑定计划不证明 callable、default、receiver 或真实 actual→formal 来源。

范围为已有同步表达式、普通局部 Name 绑定、Expr、Pass、If、return/fallthrough。
try/finally、with、del、显式 raise、循环、closure/nonlocal、generator/async
仍输出具体 UNSUPPORTED；关闭路径后的上述生命周期/控制语法也不假装支持。
领先的函数 docstring 属于定义元数据，不生成每次调用的 DISCARD。

CLI 对 source report 复用有限额、拒绝重复字段和非有限数的 JSON 解码。
`--max-report-bytes` 对解压输入/原始输出独立计费；输出超限保持已有文件。
`query-frame-refs --max-reference-steps N` 显式限制引用路径展开。

## 查询能回答什么

每个正常/异常完成分别报告 payload 与 post-world，并沿精确核心端口逐前驱
追踪引用。来源可到 formal、literal，或停止在 opaque completion result。
不沿 opaque producer 的所有输入推定输出别名，也不把两条分支来源无条件合并。
预算耗尽输出 QUERY_BUDGET。该查询不证明路径可行、对象内容、纯性或变换许可。

FrameModel 结构检查与源码重放不同：同时删掉 BIND core/overlay 并缝回 world，
或者同时篡改 EXIT 与 RETURN payload，可能仍结构一致；公共源码重建必须拒绝。
形参顺序由原始 signature/source replay 核对；旧 source graph 的 input_slots
次序对 varargs/keyword-only 并不等于 Python canonical signature，不能据集合
覆盖宣称已证明位置绑定。

## 本轮必须留下的证据

1. F0：strict records、core/frame/state/payload/context 篡改与独立审查。
2. F1/F2：原始源码自动图、路径引用查询、所有 formal/branch/异常/丢弃；
   CPython 小程序实际展示 finalizer 改内容、unraisable、frame/traceback 保留。
3. F3：真实历史包分别生成 v1–v4 inventory 后严格重放；新 v2/v5 与独立预算、
   回滚、上下文和公共 CLI；旧/new 调用证据路径都不能回归。
4. 冻结代码 mapped gate 与必要全仓回归，记录源码哈希和实际失败后修复。
5. F4：不改 LeWM，从同一原入口和归档真实证据自动生成/重放并比较覆盖及成本。

各门尚未完成的部分如实保留。完整 N2.call-edges E4、实际 callee/环境、跨调用
state/结果、循环、细状态/provenance 与观察根闭包仍未满足。
没有新 LeWM transformation、clean A/B 或已验证加速比。
