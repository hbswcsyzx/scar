# D4产品的有限独立复核

2026-10-19；root单独串行执行，A/C/B仅在约定新test/fixture范围写入，所有
执行期间作者冻结。独立源码审查未执行Python/tests/probe/compile或提交。
本复核不代表完整A–H/16组或自动Python/LeWM恢复全图完成。

## B发现的具体风险与收敛

B `/root/value_resource_review` 指出的原helper parent edge不一致由独立2项
真实反例复现：callee NORMAL→parent NORMAL与parent RAISE选择冲突，以及同端口
快路绕过选择，均在首轮错误返回True。root先排准确edge冲突，再保完整caller/
descendant choices作局部流与各kind/slot原出口投影。

临时实现的必要source前缀与输入choices冲突又抛ValueError，新增2反例在
boundary-outcomes真实失败。现known conflict返回False；may流是带显式
await_source_choice_conflict的空可行库存。预算/未证仍None，不伪装已知冲突。

其余有限审查并修正：

- 必需前缀由原入口移除一条边后的可达性建立，不从实际Drive/metadata反选。
  may候选按每个原position的membership访问复用Use索引；跨callee保原actual
  与pending，不能把本region库存冒作所有内部消费者。
- HANDOFF/BodyRaise原payload需要到准确parent kind/slot的delivery桥。False
  不能作本outcome消费成功；None连子consumer也PARTIAL。N/R原leg仍保留。
- False/None必须参与terminal→path、own leg→consumer→outcome的状态与gap汇总。
  family全局issue不能掩盖局部DECLARED。最后两处advance-leg/state-None汇总
  在第一1477P之后才修，旧绿测不归给这次新源码。
- 原INVOKE可通过独立edge-owned Use转发current state，不能只数signature产出。
  新core合法图在red-forwarded-state实际复现2项支持变0；现保slot=None、原
  position、landing formal及原Use，没有伪造CompletionResult或新state版本。
- converter按准确own output匹配附件；缺NORMAL row保原NORMAL腿和缺口，不能
  借同op另一RAISE row补语义或补requires_final_extraction=True。

## C的有限复核

C `/root/reuse_capture` 独立指出failure terminal/path的False/None状态上卷缺口。
修复后只读确认：原stage prefix及own parent RAISE保持；source own失败与展开
失败沿各自正确方向核packet/state；按Location及真实signature slot匹配，转发
Use保原port而非伪造post；缺source row/consumer receipt不删除原义务。packet
要求原EXCEPTION_PACKET角色，不靠TypeError标签认证异常类别。

## 最终有界确认与SHA

B最终有限复核对上述范围无新增阻断；C对failure方向/slot/status修复无新增
阻断。运行结果由root的最终accepted-focused独立给出，源码意见不代替测试。

- protocol_await.py：82ef32fd488260ed8dbd749dde14f94ab797e263d055401b02ae7003c8c2e30f
- await_outcome_flow.py：b7d63442ec97024576539d878c3718bc91f4eadfe0b2ae8a1b19651a4ba77f29
- await_outcomes.py：c8f3243c5e8f3057c1448b7ea3e01c23df490be857a4c9ee0acfe1b27e6557bc
- await_failures.py：a9cabec1228724b7727735686df1bd4901f82508f2806812cfe6d61336993e21

原三路source、W/B、多caller/current/mixed/C1、实际捕获完整投影、跨callee
consumer展开和原A–H组合没有因这份有限复核关闭。native/source/runtime/value
验证与变换授权继续False；没有新backend或LeWM加速结论。
