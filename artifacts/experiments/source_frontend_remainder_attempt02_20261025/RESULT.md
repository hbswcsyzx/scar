# 65项未试普通函数：实际窗口结果

root确认session15780实际exit0，outer174.766063s、worker144.348859s，peak1110000KiB。
全部65项均有terminal：51 UNSUPPORTED（1501次保留调用权重）、12 SUCCEEDED（179次）、
2 FAILED（33次）；合计1713，未试0。完整plan保2217定义/817 groups/100438调用。

12图共1111 graph ops；原stored SHA已核，仍仅为本window产物，尚未正式ADD或重派runtime。
179 calls是潜在可接增量，不能加到现有6699次body-linked调用。正式source846/runtime843保持。

两个FAILED为seq15（fi133/bi42，32 calls）及seq61（fi124/bi2，1 call），均在
source_string_validation.py:135拒绝“string primitive does not own its ordered input hold suffix”。
完整CodeType已核，但lower未正常返回，emitted/graph size及construction cost均Unknown；
不能改分类为UNSUPPORTED或吞掉。原owner正在诊断；12成功图不重lower。

预算charge13132含失败预留，不能作为全部真实emitted；CodeWitness compile0/load13/
完整descriptor-match65，source-prepare0/target0。13份source各context/AST/session复用。
process rchar430228980为真实read syscall计数，不含解码；总stored+decoded的1GiB计费/验证
仍OPEN，不能冒称完整I/O通过。

原attempt01在selection tuple/list比较时exit1/0.698s、lower0保留；本次才真正完成前端window。
准确状态/成本/失败见terminal-receipt.json；12图完整原ref见successful-programs.json；
下表只按51个实际返回的最后typed frontier聚合，不把诊断当成功预测。

| 实际下一frontier | bodies | 保留calls |
| --- | ---: | ---: |
| GENERATOR_EXPRESSION_CREATION_DRIVE_INTERFACE_UNIMPLEMENTED | 2 | 904 |
| COMPREHENSION_SCOPE_INTERFACE_UNIMPLEMENTED | 10 | 197 |
| structured control/effect protocol still required for AugAssign | 4 | 137 |
| structured expression protocol still required for Call | 3 | 80 |
| UNPACK_FIXED requires fixed tuple/list ordinary-local leaves; starred/effectful targets remain unimplemented | 4 | 52 |
| COMBINED_SLICE_LIFETIME_UNRECOVERED | 5 | 32 |
| literal is outside exact scalar support | 1 | 30 |
| structured control/effect protocol still required for FunctionDef | 1 | 26 |
| structured expression protocol still required for Lambda | 3 | 23 |
| KWARGS_CALL_REQUIRES_FIXED_POSITIONALS_AND_DOUBLE_STAR | 6 | 7 |
| structured control/effect protocol still required for ImportFrom | 4 | 4 |
| structured control/effect protocol still required for With | 3 | 3 |
| structured control/effect protocol still required for Import | 1 | 2 |
| structured control/effect protocol still required for Try | 2 | 2 |
| structured control/effect protocol still required for Assign | 1 | 1 |
| structured expression protocol still required for Starred | 1 | 1 |

全源码分母、缺口及collector/source provenance、内容/state/ready/lifetime保持，第一阶段仍OPEN。
