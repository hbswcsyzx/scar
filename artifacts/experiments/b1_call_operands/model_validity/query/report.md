# V 查询与标签覆盖实施报告

状态：Implemented；owned focused 25 PASS / 2.34s（attempt007，exit0）。这是条件性图查询与准确几何验收，不是 native capture/完整 V/R3/M0–M2 或优化权限验收。

## 规范连接

- validity(ctx,read_id,budget=4096) 用全 P source candidates/write_associations，先扣 P budget_used，再共享 joins/formula/geometry/order/invalidator 预算。没有 caller contribution list；不依赖 P exact-whole current_production。
- known_fragment_coverage 只计准确 actual；conditional_fragment_coverage 包括准确匹配的 guarded pending requested 范围。actual、未来、source closure、stability 和 runtime applicability 分开。
- 每个准确 fragment 内 alternatives 作 OR，逐需求 portion 的 labels 做 AND。坏 alternative 不毒化 MATCHED，非必要旧版本也不毒化有效覆盖；它仍在每个 wanted fragment 的源/效果 threat 扫描中。
- 原 raw native-result 已存在但 actual join 被删：共享 source_result_barrier 阻止 pending/request fallback，不制造 Outcome。正常 pending fixture 的 raw 是 request/enqueue，完全没有 native-result。
- Completed、Ordered、partial FAILED/CANCELLED、SourceEdge/Raw 精确对应、domain/current-state/actual completion 由共享 helper 解析。目标内容不同的 fragment 不参与覆盖。
- labeled_storage_coverage 只在旧 G 上追加派生 labels/sweep；原旧函数与 geometry 规则保持。exact-ref symbolic intervals=None 不是空集合，holes 不填洞，labels 不跨片段挪用。
- 返回 detached 原事实、alternatives、覆盖公式、source ledger、interval/domain、invalidators/lifetime、未决条件和预算。source_runtime_verified/runtime_visibility_verified/transformation_authorized 均 False。

## 真实尝试，全部保留

| 尝试 | 实际终态 | 说明 |
| --- | --- | --- |
| attempt001 | labeled G 8 PASS / 0.41s | 两块labels、overlap OR、holes、huge symbolic、empty、共享budget、跨artifact、label碰撞。 |
| attempt002 | query 14 FAIL / 1.48s | 新fixture把unknown alias reference接到complete access；core正确拒incomplete_alias，query未执行。 |
| attempt003 | query 14 FAIL / 1.55s | 已正确声明buffer coarse whole domain，但漏刷ImplicitBinding内部support，core拒stale_state。 |
| attempt004 | mixed query 1 PASS / 0.61s | fixture两处准确补齐；默认budget4096不增大。 |
| attempt005 | 22 PASS / 1 FAIL / 2.04s | old-version额外candidate重复做wanted稳定性，耗尽budget。保留完整source threat扫描，只取消不适用版本的重复求值。 |
| attempt006 | 23 PASS / 1 FAIL / 2.11s | 新增删除Work用例误造中途empty QueuePrefix，constructor正确拒。删除对应prefix、后继保留Unresolved前缀，不虚构完整FIFO。 |
| attempt007 | 25 PASS / 2.34s | 最后五个owned文件hash对应此终态；包括raw已知短写删除Outcome防绕过。 |

每次目录有原命令/版本/environment、源码SHA、stdout/stderr、result。未更改旧tests/fixtures/goldens，未跑full/LeWM/GPU/安装/git。其它owner文件由各owner接线，后续统一组件和full由root执行。

## 有限验收内容

A actual left + B genuine-pending ordered right：conditional MATCHED/COVERED，但known actual INCOMPLETE；两份actual联合覆盖；missing B不借A证据；wait缺失不假顺序；COMPLETED短写及FAILED/CANCELLED只支持实际段；terminal None绕过拒；精确queue不匹配拒；同fragment missing+matched OR；unused旧版本不poison且仍被源扫描；实际alias覆盖阻断；删write/work源IDs不缩；删已知Outcome但raw结果仍在禁止future whole；共享预算截断；catalog改后重新校验与detached返回。

Endpoint 尚无已解释可见性协议：只有相同 FactRef、Q root 或 selector 不给 MATCHED。Capture闭合、完整 native write/alias/时钟/domain 适用和优化权限均未由这些夹具证明。

## Owned 源码冻结

- scar/ir/execution/coverage.py: `53da83b9cb3b67ae63a12163d74e58cf9d9d6d76511e2d4011a6918d43c59411`
- scar/ir/execution/validity_query.py: `29a5311cbf91aed6b4a399a2ec8faab1e7a662cb8f38267ba142add80121b810`
- tests/fixtures/execution_visibility_graphs.py: `478eb976dc8aef267bce1d5fbd50beacb6cdeef6797d7c6c417c0cc21895a5fe`
- tests/unit/test_execution_validity_query.py: `26c010a776a3158357e2f4ce2a700bcc4a8258a9aed571f1b27ebf3d9ecf0794`
- tests/unit/test_execution_labeled_coverage.py: `0a53b32778478e531ef9b5515850071e775ce56770da7d04c1a9126157ce8808`


## 两项具体复审后的有限关闭（attempt008–010）

状态：Implemented / owned focused **27 PASS / 2.50s**，attempt010 exit0。原attempt007及全部旧结论/指纹保留为历史，当前以下指纹才是重新冻结版本。没有追加全仓、GPU、LeWM、重采或优化backend。

1. 必要区段冲突：不再将任意历史冲突leaf作全局OR。仅在conditional尚未覆盖需求时，将good和blocked标签交给同一个既有labeled G分区；需求portion无good但有blocked标签才列入 `conditional_support.blocked_portions` 并可作全局CONTRADICTED。其余真实缺段保持MISSING，历史冲突仍保留在原fragment及invalidators里。
2. 精确物化位置：actual贡献只有原解析 `placement_match is True` 才进入known/conditional offers。None保留原actual、相同内容version及可见性诊断，但fragment为MISSING，并明确actual-to-write物化位置尚未核定。pending请求路径保持原有语义，不能借source result删除降级为pending。
3. 新Q1 canonical回归：两个实际wanted左半写入，P1旧leaf被r1新left覆盖，r1有独立actual及consumer-start路径，需求右半无贡献。旧leaf仍CONTRADICTED、新leaf MATCHED，global MISSING、blocked_portions为空。原已有alias负例中clobber写的是previous版本且需求仅left，仍正确CONTRADICTED，两者未混淆。
4. 新endpoint回归：独立region=None的Endpoint Mat与Storage Mat共享准确scoped version；actual Region恰等于read byte selector，但Endpoint selector到Storage placement无已解释桥。placement_match=None，known和conditional均不COVERED，fragment/global MISSING。没有把storage Mat改名为endpoint来逃避现有content_endpoint_storage守卫。

| 尝试 | 实际终态 | 保留和最小修正 |
| --- | --- | --- |
| attempt008 | 25 PASS / 2 FAIL / 2.56s | 新三writer例默认4096触共享预算；Endpoint测试误传MissingEvidence而非FactRef。产品严格构造没有放松。 |
| attempt009 | 25 PASS / 2 FAIL / 2.64s | 两overlap wanted保护扫描仍在4096截断；Endpoint同storage Mat被原content_endpoint_storage正确拒。 |
| attempt010 | 27 PASS / 2.50s | Q1单新case按root指示显式8192并断言未截断/used<=8192；产品默认4096、原mixed/default全部不变。Endpoint创建真实unbacked Mat。 |

Q1实际used数值未在成功pytest输出单独持久化，不编造；有源码断言未截断且used<=8192的实际通过证据。遵root收束指令，未为抽取数值额外运行诊断。默认4096对该更密集图的TRUNCATED是真实有界结果，不是模型拒绝。预算未按fragment重置，所有扫描保留。

构造编辑时另有一次未激活conda的shell `python: command not found`，未执行产品/测试；随后编辑和全部pytest均实际激活lewm。

### 最终读入/owned指纹

- scar/ir/execution/coverage.py: `53da83b9cb3b67ae63a12163d74e58cf9d9d6d76511e2d4011a6918d43c59411`
- scar/ir/execution/validity_query.py: `de6313dc979859a7c92d79a67e36b49c6f29d6bb0ce4bc34a1bbfef52d6113b9`
- tests/fixtures/execution_visibility_graphs.py: `478eb976dc8aef267bce1d5fbd50beacb6cdeef6797d7c6c417c0cc21895a5fe`
- tests/unit/test_execution_validity_query.py: `a516f2dda8cba9f6aa805c923c789c593a6139706e6b9f2c8969ac39419b2f37`
- tests/unit/test_execution_labeled_coverage.py: `0a53b32778478e531ef9b5515850071e775ce56770da7d04c1a9126157ce8808`
- scar/ir/execution/production_ranges.py: `b271aec4114679468269101f870f208fd933d06dc103eeed98b03b5ec0bbaabf`
- scar/ir/execution/production_validation.py: `4610410f2d367d99a6abdc355ee55b628184a78ea48882b10bd6ae4bacbaa734`
- scar/ir/execution/validity_validation.py: `b347ece5df59c8a6aeeb0e7421a533f1decb1c21eacd6cbaf755c3254c6a161e`
- tests/unit/test_execution_actual_placement.py: `4b33baa8ab69a64e84a4d35c6bf2b9b90b7b5e515f00243fc0e56dd861402737`
