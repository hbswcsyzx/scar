# P2-B：真实外层 body 重入连接

2026-10-18。仅 supplied static IR 的连接验收；不宣称真实实例同一性、自动 native 恢复或完整 P2/M0–M2 完成。

## 交付 / 冻结

- 新 fixture `tests/fixtures/program_generator_reentry_graphs.py`：`088f4ed3e8f217ee3f9f4e993dbdbd346fc264a52b2583fd8e739adb7b812115`
- 新 tests `tests/unit/test_program_generator_reentry.py`：`bb3e916851356b47ca399db6e2acf3657fd072cb88bc17ff0113eb86345e4136`
- API `generator_reentry_program(kind=RawRequestKind.NEXT) -> (ProgramGraph, details)`；支持四个有效 RawRequestKind，复用原 matrix/driver/body builder，不改其冻结文件。
- 原 57 文件 hashes 仍为 fixture `91a188b4...82e8e0` / tests `dbe6a447...b54474`，没有重新运行它们。

## 实际原图路径

一个 canonical resumable body；外层专用 Start driver 与 inner Running driver 均指向它。root 的真实 Create 捕获 holder Reference；其 NORMAL handle 原 Use 写入 holder，WRITE.after 是 outer call 的当前 world actual。body 初入 Initial → Attach → 原 holder READ（捕获 holder + 当前 world）→ 本次 raw pack → 原 INVOKE（callee 为专用 inner driver）→ N/R 私有 completion 的当前 world/context。

RAISE landing 是 body 内真实原 block：本次 packet → caught-context READ_WRITE → 新 context after → 数据 handler 消费本次 packet产新的 continued Reference → 原 JUMP 把 caller token、当前 states、holder、continued 送入 YIELD block → 原 Detach → 真正 Suspend.exported。export 精确引用 continued formal，并非仅在 root 多放一个 Compute。private caller token 只走 CFG edge，不进入 opaque callee actual。C2、state SSA、typed address 和原 protocol/lifecycle 检查均正常执行。

NEXT 的 inner phase read 在 entry；SEND/THROW/CLOSE 保留其真实规范化 helper N/R 后各自 phase read，所以 THROW 构造 callback / failure 不被提前重入检查抹去。合法的其它 phase 分支仍有原 BodyDrive/outcomes；没有虚增不存在的 NORMAL，也没有将整个 body 当普通 callee。静态递归依赖并不声明该过近似路径能在 native 条件下实际发生或终止。

holder 精确 read-from 与 same-runtime-body identity 的边界见 `../design/reentry-reference-coherence.md`：原 value Use、typed owner/selector、coarse state 和 actual/formal 依赖可表达；不能据此声称 READ 必然取到写入对象。没有伪造 DataIdentity、物化 pointer tensor 或新增 execution/P3 记录。

## 实际验收

最终 attempt004：**8 passed / 1.30s**。命令与所有原输出、JUnit、before/after source 清单位于本目录；registered source fingerprint 前后均为 `1d5505a62d5e26c875b473de41eb64ff6c4ec66cf6a96c792f9a7e499a83f700`。只运行新 owned unit 文件，无组件/full/GPU/LeWM。

分母：四请求分别 require_valid 后核 body实际INVOKE/本次raw/currentpacket/continued→真实YIELD；一项核 successful Create handle实际存储、capture 与 typed READ/WRITE/current state；两项将 callback actual/handler outgoing state 替换为 pre-Attach context或pre-callback world，精确要求 `stale_state`；一项将 private forward Use 同时放入 invoke actual，精确要求原 `control_binding` 拒绝。查询 source/transform 为 False，address_interpretation_verified 为 False。

attempt001：8F，owned READ 构造沿 _Builder 缺 READ Behavior，原 core 正确拒绝；只补该原 behavior。attempt002：7P1F，私有 token 反例实际被正确的 `control_binding` 阻断，原断言用了别的 guard 名；修断言为准确 code。attempt003：8P/1.25s，运行时仅共享的 `test_program_protocol_reachability.py` 被 root 改动，source_unchanged=False 已保留，未冒称全局冻结。随后按 root 要求显式补 caught-context state effect，最终 attempt004 8P；不是新增 8 个独立 case，不能累加为 16。所有原失败未覆盖。

## 限定结论

PASS_WITH_SCOPE：source/coherence 条件下的静态嵌套体调用、当前完成、frame/context/state 和真实 YIELD 连接。native except/context安装、异常类识别、holder heap coherence、动态 body activation 与实际源覆盖仍未证。此处不是新的 phase、entered/finished flag 或第二套状态/producer 图。完整 P2 仍由 root 统一消费者分母/组件/冻结全回归决定。
