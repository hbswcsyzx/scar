# C1.3 INVOKE / 非 total 结构验收子批

2026-10-16。只新增授权的两个 fixture/test 文件；复用
`tests.fixtures.program_cleanup_graphs.resume_multistate_graph()` 与冻结 C1 合同。
没有修改产品、主 fixture、环境或 LeWM；没有提交、运行 full、GPU、capture。

## Implemented：手工规范图及实质反例

- `cleanup_invoke_graph()`：未知 INVOKE 同时携带 world 与 handled-context 两个输入域，
  NORMAL/RAISE 均产生两域新后态。原 pending/context 通过本地 Use 前递，不是 call
  arguments，也不伪装为新的 completion 结果。
- completion signature 的索引与目标参数位置刻意不同：NORMAL 的状态槽 0/1 接目标
  位置 1/3；RAISE 的 packet/world/context-domain 槽 0/1/2 接目标位置 0/2/4。
- 正常路径进入单独 Resume block；异常路径用本次私有 ExceptionPacket BlockArgument
  构造 fresh PendingRaise，再 route 到第一项操作为 Replace 的独立 block。两条退出均
  经真实 JUMP 到相同 parent post-pop Route，再接原 C0 dispatch。
- `cleanup_invoke_may_diverge_graph()`：cleanup 内 LOOP scope 的自边可无限重复，另有
  可达有限路径进入 INVOKE 并完成上述退出；每边携当前 state 与本次 anchors，循环不
  pop，固定点可证明 copies。未以 postdomination 或 total completion 拒绝合法结构。

反例分别必须拒绝：

1. Resume / Replace 使用 invoke 前 world：`stale_state`。
2. NORMAL / RAISE 少产生一个域、改传旧 ambient，仍保持类型/槽位一致：
   `completion_unknown_state`。
3. new Raise 路由到“恢复旧 token”的 Resume：`cleanup_route_next`。
4. 来源位于 cleanup entry 之前的 constructor 冒充 activation 内 fresh replacement：
   `cleanup_replacement_fresh`；没有仅靠 producer/port 相同放行。
5. 异常路径直接进入 post-pop corridor、跳过 Replace：
   `cleanup_stack_entry` / `cleanup_stack_merge`，删除无前驱残留避免只测死 CFG。

## Verified：唯一首轮终态

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_program_cleanup_invoke.py
```

实际 **10 passed in 0.47s；exit 0**。唯一首轮日志
[pytest.initial.log](pytest.initial.log)，没有失败或修改后重跑。正例同时检查 validate、
ProgramIndex 的 stack/anchor/action/route 查询及 v9 roundtrip，不把构造成功当验收。

```text
918c20f39feb72156f620ca6ecbe1f415c540711e52340971fcf07c4b919b3c3  tests/fixtures/program_cleanup_invoke_graphs.py
c80d8a3b804a12f5c126d60619af6cc78427666c8873985fa9c85336e261072f  tests/unit/test_program_cleanup_invoke.py
```

## 证据边界

这是手工 IR 的静态组合验收，未执行真实未知 callable 或 Python finally，不证明
implicit exception chaining、实际 handled context、引用释放/回调、totality 或 source
对应。协议 packet 仅传播引用，当前状态仍单独传递。本子批不关闭完整 C1/M1/M2，
不授 transform 权限，不提供 LeWM 优化或加速结论。
