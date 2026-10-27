# Slice/INDEX 地址建模：body26-only 验收

2026-10-23。**Verified / PASS_WITH_OPEN，实际exit0。**session92295，Python PID625373。
独立 `/usr/bin/time -v`：38.21s wall、37.57s user、0.56s system、RSS478140KiB；
内部37.153s。无目标、forward、GPU、采集、prepare、新compile、全suite执行。

三模块适配候选patch SHA70551c0114a28b00a5989f7c3db0637eab118b14d26fd8192af281d34407f9ca
在原SHA全核后应用，随后删除函数内重复OperationKind导入。原first gate/attempt02
两次exit1、各自freeze/输入/traceback完全保留。本轮实际 `freeze.json` SHA
1abfd7969f3ad2eddc5c3d79bb077cf1319139567cec395ed558fada39b3a2dc，12源码AST PASS；
`producer.json` SHA7ac5191a5ef7e4faa56b17b47cbf686ac659a3db8ce58239e550b063c4987871。

输入是旧272038 immutable composition的file140、body26原definition/source link与namespace，
以及owned只读20-key CodeWitness archive；旧Run只供静态source witness，不产生当前Run事实。
从原source archive读取一次三图，当前source文本hash核同，只AST/symtable解析，
PreparedSource直接引用原三图，source prepare0。CodeWitness实际compile0、load1、
完整descriptor匹配1、source bytes read0；不exec code。

本轮仅body26新构造65 operations，≤4000固定预算：

- 1 READ_CODE_CONSTANT：函数co_consts直接path[1]，CodeWitness/full descriptor、原source
  LOAD_CONST位置/constant path独立核；不授运行中CodeType/constant object实例身份。
- 1 BUILD_SLICE：存在bounds左到右与明确None、省略step、原正常/异常world端口；
  tuple-key与INDEX沿原source producer/Use连接。
- INDEX的原receiver/key/world Uses、READ/PARTIAL状态地址，在env与language validator
  分别核；保留完整地址集合等式。不声明自定义getitem纯读、实际storage read或无副作用。
- 4 compiler-local mappings引用原词法slots；没有comprehension本体adapter，仍OPEN。

`body-26-checks.json` 保存每项检查：v5公共结构读取/canonical roundtrip PASS，结构模式的
source_shape_verified/code_constant_provenance_verified均false；独立exact AST + owned
CodeWitness来源检查另PASS。旧v4 producer/parser拒新协议，v5无独立options拒source proof。
未执行v5默认SOURCE_REPLAY的再次构造，不能将结构读取称为source replay。

原body11只从原gzip读取并核canonical与STRUCTURE，`body11-previous-structure.json`
明确source/code proof flags=false、body_reconstructed=false；原gate118ops/UNPACK6与
旧独立source/code核验保原producer含义，不以本轮报告冒充重跑。

`summary.json`、progress/time、producer、原图、逐项checks均保留；输出manifest的storedSHA
与namespace参考由归档脚本生成，不是另一套可变producer。完整程序建模仍OPEN。
下一步是显式checkpoint2/inventory后继版本与CompositionIndex正规reader接入，复用原source
archive/其它body receipts、保artifact+representation+root namespace，再按现Run完整raw
绑定新的source body端口。本轮没有集成新body到当前Run，也没有优化或LeWM加速结论。
