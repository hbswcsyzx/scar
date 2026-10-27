# D2.4 C1/body/lifecycle 组合预审与定向交付

## 范围与结论

- 起点由 root 指定 clean `fdf9d0d`；本代理未执行 git。
- 先只读预审，随后 root 明确授权新增两份 fixture/test 文件；未改产品、旧 fixture、文档或冻结字段。
- **Observed：**本次两个真实组合及必要负例共 13 项定向通过；不以此宣称 D2.4 全门、D3 或 source/runtime 已完成。
- **Bounded conclusion：**现 core→C0→C1→C2B→D1→publication→session/release→E/F/P 接线自然支持这两种组合，没有发现需产品放宽的阻断。
- `validation.py:650–705` 先检真实 CFG/状态和私有协议，再派生 lifecycle；没有第二套 producer、world 或许可。

## 冻结依据与复用点

- `docs/M1_DRIVER_LIFECYCLE.md:91–103`：D2.4 要求真实 C1/context 组合，不能只跑旧 case。
- 冻结 `docs/M1_DRIVER_LIFECYCLE_CONTRACT.md` SHA256：
  `94e0e84e918129875ae0f913095015ecef42ee9c25bb8305d96135ce9b8ef699`。
- 原 body：`tests/fixtures/program_resumption_graphs.py:690` 的 `resumption_cleanup_invoke_program()`；从 `finally.suspend` 恢复至 `finally.landing`，Attach 后真实 `finally.invoke` NORMAL→Resume、RAISE→fresh pack→Replace。
- 实际 terminal source：`finally.return`、`finally.raise-exit.op`；它们各自先 Detach，公开结果不包含私有 frame/caller/saved-context。
- `driver_program(target="value", body_graph=...)` 在 `program_driver_graphs.py:146–176` 选 `BodyResume(finally.suspend, 0)`，直接派生首 terminal frontier。
- `publication_program` / `with_publications` 位于 `program_publication_graphs.py:13/20`，保留每个 actual source 私有 landing 的首 `publication.0/1`。
- `resume_multistate_graph()` / `cleanup_return_resume_graph()` 位于 `program_cleanup_graphs.py:38/356`；参考其 `shared.cleanup.enter/resume` 和 `shared.cleanup.resume.to-route→shared.cleanup.route→shared.dispatch`，不直接合并第二份旧图。

## A：body 内 C1+C2B → D1 → session/release

`body_cleanup_session_release_program(helper=False|True)`，新 fixture 第 27 行。

```text
finally.suspend → resume landing Attach → finally.invoke
  NORMAL → CleanupResume → route/dispatch → Detach → finally.return
  RAISE  → fresh pending → CleanupReplace → route/dispatch → Detach → finally.raise-exit.op
driver.drive → 每个实际 source 的私有首 publication.N
  → SessionUpdate(ordinary 或真实 helper NORMAL) → TerminalFrameRelease → 原 host exit
  helper RAISE → 原始真实 packet + 当前 D → host Raise
```

- 用现 `_Tail.metadata(name=唯一名)` / `_Tail.invoke(唯一名, post)` / `release(不同 index)`；`extra_domain=True` 确认 release 还覆盖 driver-only 当前域。
- 此处两个 source 分支都实际追加 session/release；不拿旧 D2.1 的两条 commit 测试冒充完整组合。
- helper 的真实 RAISE 保留，不对该边声明 NORMAL post。本小工厂不承诺每个 helper-failure 边也执行 release；root 的 A 专门组合另覆盖其所需路径，本代理不重复扩大。
- **fixture 限制：**旧 `_Tail.finish():138–140` 给本 region 每个 scope 补全所有缺块，只适用于这里单 driver function scope；B 不能直接套它，否则重复 lexical owner。这不是产品漏洞。

## B：driver 自身 active C1 cleanup 中 release/helper

`driver_cleanup_release_program(helper=False|True)`，新 fixture 第 42 行。

```text
driver.gate NORMAL → 唯一 driver.drive（corridor 原样）
  Return/Raise actual source → 私有首 commit → 独立 source-post(HOLD)
  → pack 相应 pending → CleanupRoute → 共享 composition.entry
  → CleanupEnter → composition.post(HOLD)
    简单路径：Release → CleanupResume → JUMP → parent route-only → dispatch-only → 真 exit shim
    helper：真实 INVOKE(R,B,D)，pending/context 仅作为独立 CFG-forward Uses
      NORMAL(D') → Release → CleanupResume → 同一 post-pop corridor
      RAISE(packet,D'') → fresh Raise pack → Release → JUMP
        → 私有 Replace+JUMP block → 同一 post-pop corridor
```

- source outcome blocks 才属于新 protected BLOCK；gate/reject 留在 driver FUNCTION。拒绝路径不被凭空加 cleanup 义务。
- `composition.protected` 与 `composition.cleanup` 是 sibling；direct block partition 明确，保留 body 的所有 C1/C2B records。
- owner/R/pending/全部 D 同步 actual→formal；两条 Return/Raise source 的 owner 合流后仍有 F，T 精确包含两个 commit。
- 两个 source-post 在 Enter 前建立当前 HOLD；查询验证入口 `(Rphi,Bphi)` HOLD，Enter 后失效，内部 post 再建立。
- saved context 是当前 Enter 的独立 token；helper 两边只作 CFG 转发，NORMAL/RAISE 状态均为各自 CompletionResult 新后态。恢复 context 不得回滚旧 StateVersion。
- helper RAISE 的新 pending 原 payload 精确来自 `composition.helper.raise.0`；`composition.failed.jump.1` 转发该 fresh pack。
- Replace block 只有 `composition.replace` 与 `composition.replace.jump`；fresh pack/release 不塞进此 corridor。
- 本 driver 不是 ResumableBody；其 C1 handled-context domain 复用已存在 context Location，不新增 Python formal 或 driver Attach/Detach。body 的 Attach/Detach 保持原位置。

## 当前实现会检查什么

- `cleanup_validation.py:215–242` 固定 Resume/Replace→JUMP→parent route；`:246–351` 对全部真实边（含 INVOKE）作 LIFO/覆盖；`:363–413` 检 pending/context must-copy、freshness 和 private escape。
- `control_validation.py:271–287`：pending 不能作 opaque call/invoke argument；`:319–338` 最终 pending dispatch 只能精确出口 shim，不能在其后插 release。
- `resumption_validation.py:251–288`：Detach 紧邻 body Suspend/Return/Raise，caller/frame 私有协议不能泄露。
- `driver_flow.py:68–75` 只公开 source terminal/handoff Uses，排除 private saved slots。
- `session_release_validation.py:50–74,107–114`：窄 release 只有 owner+D，全部当前 D WHOLE RW，不加 pending/context Uses；宽 raising helper 仍是真 INVOKE。
- `lifecycle_flow.py:150–180`：只有实际 terminal commit/no-body 种 F；后续 release/C1/helper 不消耗历史 F。
- `session_flow.py:100–121`：C1 unknown RW、release/helper 使 P 失效；NORMAL SessionUpdate 只在实际 NORMAL edge 重种，RAISE 不授后置。
- C1 copies/freshness 沿原逻辑边；E/F/P 都在每边同步改名后合流，未修改规则来适配组合。

## 定向验收与反例

- attempt-001：初始四个 factory×helper 正例，**4 passed / 0.53s**。
- attempt-002：扩充分支/关系与六个负例，**13 passed / 1.08s**。
- attempt-003：补入站 HOLD→Enter kill 与 canonical fresh packet 链，**13 passed / 1.08s**。
- 最终是 **13 个 owned cases**；首轮 4 项是其子集，attempt-002/003 也是同一组增量修订，不能相加为 30 项独立覆盖。
- root 单独 A 的首轮 4P/3F 为其报告的测试 API 拼写错误，未算作本批产品失败；本代理未重跑或独立复核该批日志。
- 所有 Python 均经 `source /home/zyf/miniconda3/etc/profile.d/conda.sh; conda activate lewm`；未运行 component/full/LeWM/GPU。
- 命令与原输出在 `model_lifecycle_composition/cleanup/attempt-00N/`；三次没有产品/测试失败，未覆盖首跑记录。
- 实际负例：release owner 换成 request；一条 owner phi arm 换成未 finished 的 Reference payload；Resume 回退 Enter 旧 state；pending/context 独立 Use 泄漏给 helper；真正 gate 前 release 冒借未来 terminal 历史。分别确认 `terminal_release_unfinished`、`stale_state`、`pending_escape`、`cleanup_context_escape`。
- 正例检查两个实际 terminal source、两份 C1 Enter、当前 pending/context copy、全部最新 release 后态、helper NORMAL/RAISE P 差异、F/T 多来源、同一图 wire roundtrip。

## 冻结与边界

- fixture SHA256：`2c50833ec7571796d9c500e7a43a8daf46ada860676f4bf6203e3662cc841238`。
- tests SHA256：`aae51c755e934eeaa43c88a57d4f6af16ab2c5ff779c0b37ca67dd58c7bbf5c5`。
- 这是 hand-authored、条件化声明图验收。HOLD/COMPLETE 的真实 family 适用性、native context/field 对应、动态 owner/activation 身份、callback 是否满足 fixed no-reset profile 均未证。
- F 不证明还持引用、已释放/free/ready；P 失效不等于运行时 post 为假。窄 release 没有 raising edge，也不以它吞掉真实 helper RAISE。
- 本次未进行独立 full/component 回放，未对 root 自写 A 的最终测试作独立通过声明；交 root 统一验收与公开面审查。
- root 后续报告组件 1015 cases / 32 criteria / 18.022s、451 文件 fingerprint `e0683fad9eae6a34b0dd781a9823921aac3d969372246498ff1a236e9605ed5d`；此为 root 执行结果，本代理未重复运行。两份 owned 文件自 attempt-003 后冻结未改。
