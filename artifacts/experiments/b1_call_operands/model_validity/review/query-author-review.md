# Query 作者对 C/effects/ranges 的有限交叉审查

状态：只读、无新增实验/pytest；不是自己query/G的独立验收。基于当前代码审读，并区分owned25P执行证据。完整组件/full由root统一。

## 已核对的实际连接

- effects.resolve_canonical_effect解析原AccessRef或真实INVOKE输入、CompletionResult/formal、实际successor和activation；不要求work存在。work membership和read/write政策仍留调用者，未制造state或producer。
- production_ranges复用固定byte-prefix原payload、准确line+SHA及原protocol-result locator，requested/actual offset/count逐项核。FAILED/CANCELLED没有被COMPLETED扩范围。
- C resolve_support每次用query共享budget重新求路径，不拿validation缓存order当免费证据。精确domain、原动作锚、ConsumerStart和whole-work区间分别核对；未知OrderAssociation保持ASSUMPTION，不能凭FactRef匹配。
- Endpoint visibility明确unsupported；Q/target/相同FactRef身份不构成解释后的flush/read/persistence规则。
- C source_result_barrier支持exact RawRecordRef和fixed-normalizer同bundle SourceEdge原instance metadata.raw_reference+raw_sha256（含return_boundary），不按host/parent猜，不选首native行。源结果/未知映射阻止pending，不凭该检测伪造WorkOutcome。
- C生产保护范围从conservative start扫描至整段读取；只有晚于conservative production end的确切重叠写才可作definite conflict，生产内部潜在阶段不能未经phase/kill就判冲突或丢弃。
- 请求范围overlap但实际Produced disjoint：源mapped phase用actual，独立broad core effect仍保留potential；不以请求bbox产生definite冲突。精确own-stage/effect只排该项，不清掉同call其它未知phase。
- 先前指出的_spatial exactRef在未知dtype/layout前返回OVERLAP已在当前代码改为共享G resolve/describe先验，word/rank预算也经共享adapter；未知描述为UNRESOLVED，不当definite。

## 一项通用范围守卫需root判定/关闭（R1）

已读production_ranges.resolve_actual_range：actual-vs-Mat scope/allocation/subset检查目前放在BytePrefixWrite分支。rule=Unresolved时只有actual Region FK，未普遍拒已知physical placement矛盾。

最小静态反例：同VG里wanted Version V有MatA/allocA(read)及MatB/allocB(write)，WriteAssociation placement=MatB；OutcomeProduction.actual却选allocA且rule=Unresolved。query版本匹配来自MatB的V、coverage来自actual allocA，有机会组合成conditional覆盖，虽然原physical placement已知冲突。未执行该反例，未更改产品。

建议通用解析先核已知同scope actual与write Mat的allocation、必要的selector subset；unknown/crossscope correspondence保留gap，已知同scope不同allocation为issue。BytePrefix分支另解offset/count/返回数。此为已冻结准确placement不变量，不是新backend/新协议。已发root，后续决定/修改可追加限定closure；本报告不将该项写成已验证通过。

## 证据边界

owned25P覆盖canonical mixed/partial/source删除/actualalias，不是所有C helper分支或所有Python/native代码的自动恢复证明。Endpoint规则未实现，跨process/native clock、捕获闭合及free/retirement真实性均有条件。无新GPU/LeWM或source重采。

## 审读指纹

- scar/ir/execution/validity_validation.py: `b347ece5df59c8a6aeeb0e7421a533f1decb1c21eacd6cbaf755c3254c6a161e`
- scar/ir/execution/validity_order.py: `8e0c0afcf8ada6cfddbc217c6de733868406921ed85f709f7979f70951b55ad4`
- scar/ir/execution/validity_stability.py: `c394f306fe4ff318ee80badf112881f5c2b8c310b881b74253eeca66afe9aadd`
- scar/ir/execution/effects.py: `fd3d756ea382af33916ae6076b17e71a7bc3bc59a45db30c2b7974b573534e6d`
- scar/ir/execution/production_ranges.py: `e657ea85c609c8e6f975b7bcfa9d0787f6ce00bc1cd704362a4de69c01f69f81`


## R1与两个重开点的限定closure

状态：**PASS_WITH_SCOPE**（代码审读 + owned27P；不是完整V/native/runtime验收）。原R1发现/旧源码hash/未执行反例说明原样保留。

root已将 `_actual_placement` 放在result profile分支之前：所有已解析Region actual均先核原StorageContent的准确VG scope、原Mat region、allocation incarnation，并用既有G核actual是原Mat的subset；已知crossscope/alloc/outside为issue，缺图/Endpoint/无法解释或预算不足为None+gap。BytePrefixWrite另核请求/实际计数、offset及原返回payload。Unresolved rule不能跳过通用physical placement守卫。

P `resolved_produced` 显式保留placement_match，Host `resolved_establishments` 通过原ranges展开保留同字段。V实际贡献消费这同一字段，只有True进入wanted覆盖；不再从Mat的version与任意actualRegion独立拼成tuple。新合法unbacked Endpoint案例将此None路径实测到fragment/global MISSING。root报告其独立actual_placement/旧produced/query focused为71P/3.57s；本agent未重复运行root测试，只审读当前实现与其测试。

必要coverage冲突已按good+blocked标签的同需求portion判断，新增canonical两wanted左半+缺右回归通过；旧实际previous-version clobber依旧CONTRADICTED。两个被重开点限定关闭，不将未解释Endpoint协议、capture completeness、物理写入/时钟/domain适用或runtime/transform权限升格。

最终owned两文件focused：attempt010 **27 PASS / 2.50s**（具体命令、conda/Python版本、SHA、stdout/stderr/result均已保存）。本次不修改任何C/root产品文件，也不执行新probe/full/GPU/workload。

### 当前closure指纹

- scar/ir/execution/coverage.py: `53da83b9cb3b67ae63a12163d74e58cf9d9d6d76511e2d4011a6918d43c59411`
- scar/ir/execution/validity_query.py: `de6313dc979859a7c92d79a67e36b49c6f29d6bb0ce4bc34a1bbfef52d6113b9`
- tests/fixtures/execution_visibility_graphs.py: `478eb976dc8aef267bce1d5fbd50beacb6cdeef6797d7c6c417c0cc21895a5fe`
- tests/unit/test_execution_validity_query.py: `a516f2dda8cba9f6aa805c923c789c593a6139706e6b9f2c8969ac39419b2f37`
- tests/unit/test_execution_labeled_coverage.py: `0a53b32778478e531ef9b5515850071e775ce56770da7d04c1a9126157ce8808`
- scar/ir/execution/production_ranges.py: `b271aec4114679468269101f870f208fd933d06dc103eeed98b03b5ec0bbaabf`
- scar/ir/execution/production_validation.py: `4610410f2d367d99a6abdc355ee55b628184a78ea48882b10bd6ae4bacbaa734`
- scar/ir/execution/validity_validation.py: `b347ece5df59c8a6aeeb0e7421a533f1decb1c21eacd6cbaf755c3254c6a161e`
- tests/unit/test_execution_actual_placement.py: `4b33baa8ab69a64e84a4d35c6bf2b9b90b7b5e515f00243fc0e56dd861402737`
