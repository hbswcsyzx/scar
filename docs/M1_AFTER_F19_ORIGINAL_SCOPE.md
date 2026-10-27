# F19之后：原剩余分母的准确落点

2026-10-20独立只读审计。当前F19仍在实施；本表没有提前关闭F19或其他族。
原入口为[M1_REMAINING_PROTOCOL_PLAN.md](M1_REMAINING_PROTOCOL_PLAN.md)第68–75行，
历史[M1_PROTOCOL_SCOPE_RECONCILIATION.md](M1_PROTOCOL_SCOPE_RECONCILIATION.md)须
扣除后来已验的F23/await重求值等结果，不能照抄当时OPEN清单为新失败。

| 原行 | 复用的准确证据 | 真正剩余组合 |
| --- | --- | --- |
| F20 | continuation_connections的iterator/item/exhaustion/failure；method_lookup_connections独立iterator/bound method | 同一父YieldFrom：求值/GetIterator失败、无效iterator、首次exhaustion→父表达式结果/零Suspend。delegate-only无父Drive不能替代 |
| F22 | method_lookup_connections保THROW1–3原ordinal；lookup_fallback保E0/lookup/matcher三包；packet_continuation_edges到真终点 | 本次THROW与同一父实例：item再挂起、exhaustion最终值、missing-method原包传播及父应/不应恢复联合发生，不重造lookup helper |
| F24 | async_connections区分request/delivery/handler/status及删除分母，waiter forwarding正确Unknown | CURRENT_AWAITED转发/回调→准确目标；抑制后再AWAIT；C1新包Replace及normal/raise/cancel终态分开，不实现整个Task框架 |
| X25 | pending_cleanup两cut/saved角色、resumption的local binding/loop/合流、delegate-close动态 | active C1＋local binding＋重复visit/合流的同图连接及旧值/Replace反例；不能重报“两cut未实现” |
| X26 | lifecycle_body/cleanup_composition partialstate、callback/F/post与重建；protocol_release宽helper杀post但保F | F19的async终结/release可在真通过后合账；另将cancel终结→当前state/session/helper后态→同一release实际接通 |
| X27 | execution_resumable_links持续实例/缺Resume/原库存；delegate-close三Drive整链及缺采已接受 | F20初始/零cut、F22父续路、F24取消各自的实际tuple；其余await/async复用；noDrive不造segment，不借兄弟 |

## 后续整门

1. 补F20/F22完整委托链、F24完整取消链，同时消费这些组合补原X25–X27。
   delegate-close与已验await不重开，不另开来源工具箱。
2. P4原16行全合账后做组件与一次冻结full（原计划95–112行）。历史focused
   不是当前P4组件/full；旧coverage ledger全部OPEN是当时状态，不是新增失败。
3. P5/X28按[M1_PROTOCOL_FAMILY_PLAN.md](M1_PROTOCOL_FAMILY_PLAN.md)76–95行，
   完整F01–F24/X25–X28 ledger、公共wire/query/CLI、兼容、budget/cursor、独审
   和冻结归档。复用protocol_ledger、protocol_codec、lifecycle_scope_cli现有
   tests，不重造协议图以代统一验收。
4. M2原113构造/196字段：既有`model_stage1_audit/field_coverage.json`及closure
   审查已处理G1–G6文字缺口，不能重报历史12 GAP。仍须逐构造的phase、依赖、
   effects、完成/失败和边界映射到现canonical接口并核组合；见
   [FIRST_STAGE_COMPLETION_MATRIX.md](FIRST_STAGE_COMPLETION_MATRIX.md)相应原分母。
   这不是M3自动前端恢复。整个M0–M2完成后先向用户解释，再进入自动建图。

以上均是原范围定位，尚未实施或验收；状态仍由各门实际证据决定。没有新
detector/backend/LeWM规则或加速结论。
