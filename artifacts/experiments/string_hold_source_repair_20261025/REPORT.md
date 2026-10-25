Root确认本轮 session49716 **exit0**；launcher 50.081913222s，worker 49.358787247s（GNU0:50.04），最终source/input/runtime核对通过。freeze：`e78b0a1d30e710c7410b91a0dad520f76ef254e27c122baeadec6e31533b99b2`。

| 原FAILED主体 | 原调用权重 | 本轮结果 |
| --- | ---: | --- |
| seq15 / fi133-bi42 / body `5d3a0e23fb22…` | 32 | 148 emitted ops，RECOVERED_WITH_OPEN |
| seq61 / fi124-bi2 / body `094603d271aa…` | 1 | 131 emitted ops，RECOVERED_WITH_OPEN |

两图均通过public SourceProgram5结构roundtrip、准确retained AST/CodeWitness和字符串局部ordered-pending/两completion release检查。两图均明确保留 `FSTRING_CHILD_PRIMITIVE_CONSUMPTION_UNVERIFIED`，intermediate_consumption_verified=False；outer pending、runtime实例、完整lifetime/effects仍OPEN。没有以UNKNOWN掩盖ordered release错误：同一42-op fixture复现旧误拒后通过，缺raise release/normal乱release仍拒绝。

修复仅将字符串held-source选择从AST类型白名单改为原piece/value/conversion/spec角色，纳入原Call结果hold；不改lowerer、协议消费合同、IR或默认能力。validator SHA为 `2be18373563d4850c95f341e3c57fe33f7e0c31aa6de5fd35ac81c8baab44b2e`。main与iso已只读核同字节；root已在d2ec4d0e应用，状态为 **ALREADY_APPLIED_NO_REPLACE**，本次没有再次替换。

实际input131720165B（stored24000658 + decoded107719507），末FINISHED输出计数约55.66MB，SELF/GNU max RSS505996KiB。源码/tool两轮SHA核对另计102478508B。预算保持输入/输出各256MB、4000ops/body、180s/body；仅一个840 composition根与两context/session。门内target executable compile/target exec/prepare均0；CodeWitness compile0、module loads2、descriptor matches2。另有AST-only compile10、symtable4，不泛称全部compile0。

原65窗口两hardFAILED保留原路径/字节；未改其12/51/2总结。candidate01启动失败（root61807 exit1/4.172s，lower0）及原failure完整保留；准确原因是 `current.code_source_origin()` 读取843→842小parent metadata缺pins，840 CompositionIndex已成功，并非validator或大root错误。candidate02只补3个小pins后取得本次结果。

两新图仅保留本地、**未ADD、未接current runtime**；没有重放或重算已ADD的12图，也没有新episode。图的准确根URI、stored/decoded SHA和大小见RESULT_RECEIPT.json：第一图1861213B/decoded16484640B，第二图819307B/decoded7996534B。两者均不入Git；stage只保代码、metadata、原失败及必要fixture历史。没有新语法/class/v6/generator实现，没有Git操作。

Fixture历史说明：check01/candidate.json失败于沿用旧fixture的“JoinedStr必须无overlay”断言；本次普通return-string有原overlay，该断言不适用。check-call-value.py仅修正测试资格记录，candidate02.json的42-op检查通过；两个旧收据均保留。
