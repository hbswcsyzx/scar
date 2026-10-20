# 原存储值关系：实际进展

2026-10-20。基线5fd5a7f；完整原范围见[计划](M1_STORED_VALUE_PLAN.md)，
审查修正见[设计补充](M1_STORED_VALUE_DESIGN.md)。第一阶段仍未完成。

## G0 实际诊断

root在所有作者FROZEN时运行`baseline_probe.py`：907源文件/b7a6ad…前后稳定。
原公开state_preservation结果True、budget60/65536、无blocker；但StateAccess、
StateAddressRefinement、ContentRead原字段确无store-payload/load-result角色，
stored_value_sources入口不存在。native target执行0。保存原字段、预算及完整
源指纹，不把正确Unknown叫作已有模型的错误推导。

## G1 实施与审查

A实施两原访问附件、校验与Program27，B只加通用fixture/test，root写执行查询与
薄入口；C只读独立审查。作者不执行解释器/Git，root在全部源作者FROZEN后串行运行。

设计审查先阻止同一完成同最终槽P/Q双post事实，要求唯一read result和静态冲突
拒绝，未知alias多post仍不能任取来源。查询沿原copy祖先或独立对象声明比较owner，
不同候选不写全局copy冲突；state_preservation原任意写阻断语义保持。

执行源码审查又发现合法Reference key可能在literal fallback访问DataValue专属
字段而崩溃。root在首测前加准确DataValue guard，B补独立Reference key反例；
原地址validator继续允许Reference selector，不为绿测强改原IR。

新wire独立复用InvokeLiteralResult tag；旧字段排除新表。新增独立Program26
encoder以冻结git源在隔离子进程产生oracle，不拿当前codec反证自己的字节正确。
最大/未来版本断言迁移仍须单列首败、原case和保留义务，不修改旧fixture。

## G3 实际首测、修复与最终选集

`first-exact-store-read`：913/38f767…稳定，1 PASS，0.90秒。
`first-joint-stored-values`：同源106节点，94 PASS/12 FAIL，20.10秒；8个fixture
在canonical构造阶段失败（opaque state未连接、控制Use复用、产出Ref带未证精度），
另4个旧codec最高/未来版本断言需既定迁移，未包装为成功拒绝。

保全首败源码后，B将opaque建为真实world RW/context READ，后续消费新world；
N/R分别用独立原forward Use，普通产出Reference精度保持未知。root仅迁移16份
旧codec的15行最高版本、7行未来参数、6行旧字段集合；原wire与旧encoder不改。
A修同原Data key多post静态冲突，并增加1节点，原11记录节点保留。

`corrected-original-ports`：913/469d8d…稳定，100 PASS/7 FAIL，21.93秒；剩余
7例是exception packet缺原Region lexical scope，未到来源查询。B仅补每原region
全部原blocks的FUNCTION scope，不造packet constructor；25个执行测试逐字节未改。
`corrected-packet-scopes`：913/51ff19…稳定，原7节点PASS，1.14秒。

最终作者FROZEN后`verified-current`一次47模块相关选集：961 PASS，379.59秒pytest
/380.5244640568271秒wrapper，913/51ff19…前后稳定。新增40节点，原fixture和非
codec旧tests字节保持；独立Program26字节oracle通过，旧未来case迁移单列。
C最终只读审查无未决阻塞，完整SHA和边界见归档review；不代表native/source恢复。
后续只做账本核验、普通commit/push及远端SHA/clean检查，不扩大可选测试。
