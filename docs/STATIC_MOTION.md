# 精确源码上移：当前证明范围

状态：实现已接入，独立验收见 `G7_2B_MOTION_ACCEPTANCE.md`（归档后创建）。
这是 G7.2b 的窄 MOTION 能力，不是 REUSE、循环 hoist、backend 或 LeWM 优化。

## 模型先于规则

移动对象是 `SourceFragment`：一个完整的单目标局部赋值语句，包含顶层语句、
RHS、读取及写绑定操作；它不是一条孤立的 profiler event 或 RHS 值。
fragment 绑定原始 scope、suite、SourceReference、SourceVersion、操作成员和
文本摘要。`StaticSourceMove` 连接该 fragment 与源码控制图的精确插入点。
这些实体进入 OIR schema 4；旧 schema 1/2/3 严格迁移，只补空的 `static_moves`。

独立 source replay 重建 SG、source semantics 和 CFG；固定的整语句规则再
核对完整函数体、精确 local bindings、全部 read sites 和返回 slot。常量求值
只提供 builtin 类型/内容证据，不证明赋值、分配、异常或引用计数没有可见效果。

## 固定六项义务

`scar.proof-ledger.v2.2` 对一项完整 alias 赋值上移重新推导：

1. 全部输入绑定在目标插入点前可用，并有 `ALL_PATHS` dominance；
2. 插入点支配原语句，完整 suite 无分支、循环、suspension 或 handler；
3. 每条跨越的完整语句具有受支持的固定 builtin 语义，绑定无冲突，异常/观察条件明确；
4. 保留原有精确 object identity，闭合 immutable builtin 来源、first binding 与新 live range；
5. 所有实际消费者是该作用域内已认证的后续 read，不把 trace 缺边解释为没有 callback；
6. source fragment 和目标 anchor 可重新生成，且确实越过至少一条语句向上移动。

原 CFG 的 `MAY_RAISE` 边保留，查询不降为 `NORMAL`。运行环境、资源失败、
异步中断、frame/locals/trace 顺序、refcount/finalizer 观察边界是精确 scoped Q，
在账本中保持 **DECLARED**。没有这些声明时正例返回 `NEEDS_CONTRACT`；它们
不能为 unsupported CALL、loop、mutable value、rebinding 或输入不可用生成事实。

当前函数体子集只接受一次写入的局部 immutable literal、封闭有限 builtin
常量表达式、直接局部 alias、`pass` 和唯一终末 return。普通调用、Tensor、
参数值、闭包、属性、索引、重复写、循环、分支、handler、异步等继续有明确缺口。
浮点算术需要尚未连接的 floating-environment 条件，因此不放行。

## 公开 API 与可复现查询

API 依次使用 `derive_source_fragment`、`RegionInventory.region`、
`StaticSourceMove`、`ProofContext` 和 `derive_proof_ledger`；读取保存的账本必须
提供当前模型和同样的 source snapshot context 并重新验证。若生成账本时显式
传入 source_texts，重放时也从当前已核对的源文件读取并传入相同快照；省略该
context 会导致 source hash 不同，而不会默默接受。OIR serde 的结构正确不等于移动合法。

测量入口接受调用方指定的 query，不发现新候选，也不接受隐式 Q：

```bash
cd ~/AAA/scar
conda activate lewm
PYTHONPATH=. python scripts/measure_static_motion_v2.py \
  testcases/source_motion/program.py --statement-line 4 --after-line 2 \
  --out artifacts/reports/gates/g7-2b-motion-no-q.json.gz
```

默认 Q 为空。`--q` 只接受 strict `ProofQ` JSON；scope、条件 subject、源码路径/
版本、规则和 Python runtime 必须匹配。这些声明须来自调用方的观察合同，不能
由 candidate 或 saved PROVEN 自动生成。归档的正例 Q 只是外部 synthetic fixture
的明确语义边界，不适用于 LeWM，也不等于实测没有这些观察者。

报告保留 source graph、source overlay、CFG、region、Q、精确 delta 和 ledger，
可以独立重算。即使六项义务成立，仍为 `CONDITIONALLY_LEGAL`、`NOT_SELECTED`、
成本 `PENDING`、`applied=false`。成本模型和计划生成是后续独立阶段。

## Guard、失效与 fallback

调用方必须在使用指导前重新验证源码快照、完整模型、Q、scope、规则、运行
环境和 delta；源码、绑定、目标 suite、观察合同或验证预算不匹配时不能复用旧账本。
没有动态 runtime region guard 的结论不得升级成跨运行 Tensor reuse。
合法性、成本或验证尚未通过时 fallback 为原始程序/NO-OP；本阶段不写目标源码。
