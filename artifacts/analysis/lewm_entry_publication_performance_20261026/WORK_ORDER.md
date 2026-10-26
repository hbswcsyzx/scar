本工单准备诊断，未执行profile或修改生产。目标是在原全部26个SP5、8GB/8GiB、1200/1260s预算内完成schema3出版、独立normal factory和all-body query，不能靠加wall或缩名单通过。

实际基线：resume02 Root64946主动止损actualexit1，215.60s建立817groups，689.66s完成第9个CP2，最近每条约37.73s；完整manifest/factory/query未完成。plain858原index decoded77,635,618B。`SourceEntryCatalog.require_unchanged → _inputs → project.source_inputs`每次canonical完整document；但目前各函数耗时占比NOT_MEASURED。最后中断栈在`SourceProgram.read_structure → from_dict`，不能把所有37秒归于fingerprint。

下一步只做一个有界cProfile诊断，Root持执行入口；保持当前代码和原输入SHA，原失败现场不改。fresh进程正常构造同plain858 CompositionIndex、原continuation+三archive的catalog，机械取26成功列表中原顺序第一个SP5，正常resolve/prepare原definition/text。不恢复失效owner、不lower/compile/target，不新增成功资格。setup时间/I/O与被profile阶段单列；沿原8GB总输入、AS8GiB，建议诊断whole480s/outer540s、report16MB，source/control hash独立64MB。准备入口时如normal setup所需量不符，先给准确预算，不盲目运行。

依次测量，均只一次：

1. 对同一genuine project的一次`source_inputs()`单独cProfile，保全canonical/sha/ancestor调用，记录wall、CPU、total/cumulative和调用数；输出仍须等于原普通结果。不能只profile一个假造dict或把setup构造器时间算成该函数成本。
2. 正常读取同一原SP5一次，核原physical/decoded SHA与字节；以genuine catalog.prepare取得原archived text。单独cProfile原`SourceProgram.read_structure(document, source_texts=..., max_operations=10000)`，不删source/language/ABI/graph验证；报告codec、source/control/language与record validation的实际cumulative分布。读取/AST准备和指纹阶段不混入此时间。

结果只解释一个条目和单次fingerprint成本，不假装全26耗时占比。导出小JSON统计、profile本体与入口/输入/源码freeze；不额外矩阵、不再全capture/worker跑一次。

根据实测选最小修复：若canonical主导，优先可靠的受控mutation epoch或transitive immutable snapshot，绑定原完整canonical bytes、源artifact/watch和确切document身份；必须拒绝nested mutation、陈旧parent/CAS、换sourceInputs。普通mutable对象仍走原完整检查。不得以裸id、callertrusted/verified布尔或文件stat代替内存文档完整性，不改原namespace/representation/parent/ABI。

若structure验证主导，先定位实际重复的原validator/codec工作，再考虑绑定精确source/program/archive的不可变prepared结果；变化候选仍须独立语义验证。不会在测量前凭猜测给这条链加缓存。候选范围先从`program_composition.py`、`source_entry_catalog.py`、`source_program_publication.py`选择；若热点需要`program_lowering.py`或更外源，提交准确第四源授权，不悄悄扩大。保默认API、schema1/2/3、source/artifact guards、ADD/REVISE/CAS、原全部26与独立factory/query。修复后只安排一次相同26全门，旧失败不追认。
