# C1 补充：cleanup 不完整效果与多域状态

状态：**Proposed；补充已冻结合同，不修改原文。** 本轮未运行测试或语言探针。
本补充限制 `NEXT_CLEANUP_IMPLEMENTATION.md` §3 的后态解释，不扩大到 source lowering。

## 1. 必须纠正的推理边界

Enter/Resume/Replace 写 context_domain 且 effects_complete=False，**不能**推出其余已声明
state 域无效果或内容未变。保存/解除引用保持、恢复上下文和释放旧 pending 可能触发
finalizer/weakref 回调及其他可重入执行；回调可改 global、文件、RNG、对象或资源状态。
`NO_FRAME_INTERPOSITION` 的未证条件不排除普通 finalizer 对对象/外部状态的写。
没有 StateAccess、没有观察到写、静态声明为空、同一旧 StateVersion 被转发，都不是 NONE 证据。
当前 validator 允许某种结构不等于它已经证明该普通操作的完整效果摘要。

## 2. C1 的默认落地合同

- 单 coarse-world 域：动作读取当前 world 并产生未知 READ_WRITE 后态，可覆盖这些未知
  effects；pending/context 保持规则只约束协议载荷，不冻结 world 中对象内容。
- 多域：每个 Enter/Resume/Replace 默认对 **Region 已携带的所有 state 域**各建一条
  READ_WRITE、full_overwrite=False 的 StateAccess，逐域产新 StateVersionValue。
  context_domain 已包含在其中，不可再重复增加同 location 的 access。
- 所有 before Uses 都是各域当前 STATE_CONTENT；所有 after 都是该动作自己的 canonical
  results。后继传完整的新向量，不能仅更新 context 而把别域旧值当作未变证明。
- effects_complete 仍为 False：全域保守后态是依赖闭包措施，不是已知具体写集合或纯性。
  若模型没有覆盖回调可触达的外部状态，应保留 coarse fallback 域/显式边界，不称全效果封闭。
- LocationID 不同不证明不相交。已有共享/重叠域同时保守推进；不能把同一真实状态的
  coarse 与 refined 表示任意挑一套更新。若模型无法保持覆盖/别名约束，拒绝把这个
  多域实例作为精确状态模型，保持 coarse 表示或显式报告覆盖冲突。
- 修改当前 C1 validator 时需显式检查上述全域后态，不依赖 effects_complete=False 自动
  实现；普通 StateAccess 路径与 INVOKE 的未知效果全出口约束目前不是同一个检查。

## 3. 何时可保留某个域原版本

只有适用且已建立的 intrinsic 摘要，或明确附带未证适用条件的条件模型，才可缩小域集；
后者不能在公开查询中变成无条件“域未变”。摘要必须包含引用释放/回调/重入的效果，
明确每域完整性、状态覆盖与潜在别名，并给出来源和适用条件的证据链接。
静态 `DECLARE`、操作名、C0 合法图、未见回调、reference 相同均不能充当该证据。
仅排除 tracing/interposition 仍不能排除最后一次引用释放触发的普通 finalizer。
不要新增可写 `verified=true`；checker 核验摘要的结构/适用条件，source/runtime 对应另证。

## 4. 必需的正反例（本补充只列合同，不声称已实跑）

**引用丢弃引发跨域写：** `try: return make_payload(); finally: return replacement`。
若旧 payload 因 Replace 失去最后保持，`__del__`/回调修改 global counter 和文件状态：
应保留旧 pending Use，推进 context/global/file 各域，返回 replacement 引用。
只更新 context、退出仍携带旧 global/file StateVersion 的图必须被 C1 契约拒绝。
不保证实际立即析构：存在其他引用/逃逸时可无此写，保守后态仍正确。

**回调修改返回对象内容：** 正常 Resume 释放其他保存对象，其 finalizer 修改 pending
Return 引用的对象。正确图保持原 token/引用，却使用更新后的对象域；把“原 token”
解释成“原内容版本”或因 reference 相同复用旧结果，必须拒绝这种查询/变换结论。

**真正的新清理异常：** finalbody 的用户调用先修改 RNG/文件，再抛异常。
INVOKE RAISE 边携其实际保守后态，新 Raise 替换旧 pending；随后 Replace 自身的
释放回调还可能再次跨域写。不能跳过其中一段后态，也不能用调用输入状态覆盖它。

**finalizer 自身报错：** 按现有受限 frame 规则，普通 `__del__` 的异常为 unraisable，
不自动成为替换 pending 的语言 Raise；unraisable reporting/hook 仍可能有可观测效果。
不能因“异常未传播”就删 state 写；也不能凭空增加一个普通 replacement Raise 出口。

## 5. 权限与验收范围

Typed primitive contract 规定若该动作按合同完成，应怎样保持载荷、恢复 context 并
传递状态；它不证明源码操作确实被如此恢复、运行时没有 hook 或最终释放发生。
多域反例与最小解码篡改检查应进入 C1 gate；此前19组语言观测未覆盖这些所有回调组合。
此补充不提升 source/runtime/extraction/transformation 权限，也不关闭完整 M1/M2。
